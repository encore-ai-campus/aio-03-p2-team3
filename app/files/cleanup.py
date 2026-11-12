"""미참조 Storage 객체 목록·수동 정리 명령(CONTRACT 16.3절, 계획 8절).

사용:
    uv run python -m app.files.cleanup                                  # 목록만
    uv run python -m app.files.cleanup --older-than-hours 24            # 오래된 미참조 객체만
    uv run python -m app.files.cleanup --older-than-hours 24 --delete --yes  # 재확인 뒤 삭제

- 미참조 = 버킷에 있지만 `file_assets.object_key`·`trade_artifacts.object_key`가 가리키지 않는
  객체(업로드 성공 뒤 SQL 실패로 남은 것). 참조 중인 객체는 절대 지우지 않는다.
- 나이를 알 수 없는 객체는 지우지 않는다(보수적으로 남긴다).
- 크론·자동 큐 없이 사람이 목록을 확인하고 실행한다.
- 회사 이미지(계획 9절)는 file_assets 행을 거쳐 객체를 가리키고, 발급 파일(계획 10절)은
  trade_artifacts가 object_key를 직접 가리킨다. 둘 다 이 참조 집합에 들어 있다.
"""
from argparse import ArgumentParser
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select

from app.config import get_settings
from app.db.engine import get_database
from app.db.models import FileAsset, TradeArtifact
from app.files.storage import StorageClient, StorageError

DEFAULT_OLDER_THAN_HOURS = 24


def _age_hours(entry: dict, now: datetime) -> float | None:
    created = entry.get("created_at")
    if not isinstance(created, str) or not created:
        return None
    try:
        parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (now - parsed).total_seconds() / 3600


def unreferenced_objects(database, storage) -> list[dict]:
    """버킷 객체 중 DB가 참조하지 않는 것을 `{key, size_bytes, age_hours}`로 돌려준다."""
    with database.session() as session:
        referenced = set(session.scalars(select(FileAsset.object_key)))
        referenced.update(session.scalars(select(TradeArtifact.object_key).where(
            TradeArtifact.object_key.is_not(None))))
    now = datetime.now(UTC)
    rows = []
    for entry in storage.list_objects():
        key = entry["name"]
        if key in referenced:
            continue
        metadata = entry.get("metadata") or {}
        rows.append({"key": key, "size_bytes": metadata.get("size"),
                     "age_hours": _age_hours(entry, now)})
    return rows


def execute(database, storage, *, older_than_hours: float = DEFAULT_OLDER_THAN_HOURS,
            delete: bool = False, confirmed: bool = False) -> tuple[list[dict], list[str]]:
    """미참조 객체를 목록화하고, 조건이 모두 맞을 때만 지운다. `(나열한 객체, 지운 key)`를 돌려준다."""
    rows = unreferenced_objects(database, storage)
    stale = [row for row in rows
             if row["age_hours"] is not None and row["age_hours"] >= older_than_hours]
    deleted: list[str] = []
    if delete:
        if not confirmed:
            raise SystemExit("삭제에는 --yes가 필요합니다. 먼저 --delete 없이 실행해 목록을 확인해 주세요.")
        for row in stale:
            storage.delete(row["key"])
            deleted.append(row["key"])
    return rows, deleted


def main(argv: Sequence[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--older-than-hours", type=float, default=DEFAULT_OLDER_THAN_HOURS,
                        help=f"이 시간(기본 {DEFAULT_OLDER_THAN_HOURS})보다 오래된 미참조 객체만 다룬다")
    parser.add_argument("--delete", action="store_true", help="목록화한 객체를 지운다(--yes 필요)")
    parser.add_argument("--yes", action="store_true", help="삭제 재확인")
    args = parser.parse_args(argv)
    settings = get_settings()
    if not settings.supabase_url.strip() or not settings.supabase_secret_key.strip():
        print("SUPABASE_URL·SUPABASE_SECRET_KEY가 설정되지 않았습니다.")
        return 2
    database = get_database(settings)
    storage = StorageClient(settings.supabase_url, settings.supabase_secret_key,
                            settings.supabase_storage_bucket.strip() or "trade-files")
    try:
        rows, deleted = execute(database, storage, older_than_hours=args.older_than_hours,
                                delete=args.delete, confirmed=args.yes)
    except StorageError as error:
        print(f"저장소 오류로 중단합니다: {error.message}")
        return 1
    for row in rows:
        age = "알 수 없음" if row["age_hours"] is None else f"{row['age_hours']:.1f}시간"
        size = "?" if row["size_bytes"] is None else row["size_bytes"]
        print(f"{row['key']}\t{size}\t{age}")
    stale_count = sum(1 for row in rows
                      if row["age_hours"] is not None and row["age_hours"] >= args.older_than_hours)
    print(f"미참조 객체 {len(rows)}개(이 중 {args.older_than_hours}시간 이상 {stale_count}개).")
    if deleted:
        print(f"삭제 {len(deleted)}개.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
