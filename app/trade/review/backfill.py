"""기존 trade_artifacts.content 바이너리를 Storage 객체로 옮기는 일회성 backfill·검증
명령(계획 10절). 실제 content 열 DROP은 하지 않는다(22절로 분리).

사용:
    uv run python -m app.trade.review.backfill        # 계획만 출력(dry-run)
    uv run python -m app.trade.review.backfill --yes   # 실행 + 저장 객체 해시 대조 검증

- object_key는 승인 절차와 같은 결정적 key({user_id}/issued/{proposal_id}/{format}/{sha256})
  이다. 이미 그 key에 같은 bytes가 있으면 새로 올리지 않고 재사용한다.
- 이미 object_key가 있는 행은 옮기지 않고, --yes 때는 Storage bytes 해시 대조로 검증만 한다
  (반복 실행이 곧 검증 실행이다).
- bytes의 SHA-256이 기록된 content_hash와 다른 행, 같은 key에 다른 bytes가 있는 행은 옮기지
  않고 보고한다(조용히 고치지 않는다).
- 기존 파일 ID·형식·해시·승인 관계는 바꾸지 않는다. 업로드 뒤 SQL이 실패하면 그 객체는
  미참조로 남고 cleanup 명령이 정리한다.
"""
from argparse import ArgumentParser
from collections.abc import Sequence
from hashlib import sha256

from sqlalchemy import select, update

from app.config import get_settings
from app.db.engine import get_database
from app.db.models import TradeArtifact
from app.files.storage import StorageClient, StorageError
from app.files.locks import lock_object
from app.trade.review.repository import issued_object_key


def _download(storage, object_key) -> bytes | None:
    """객체를 읽는다. 없는 객체(404)는 None, 그 외 실패는 StorageError로 나간다."""
    try:
        return storage.download(object_key)
    except StorageError as error:
        if error.code == "object_not_found":
            return None
        raise


def _link(database, storage, row, *, confirmed: bool) -> tuple[str, bool]:
    """한 행을 object_key로 옮긴다. `(결정적 key, 새 업로드 여부)`를 돌려준다(검증 포함)."""
    digest = sha256(row.content).hexdigest()
    key = issued_object_key(row.user_id, row.proposal_id, row.file_format, digest)
    uploaded = False
    if confirmed:
        with database.session() as session:
            lock_object(session, key)
            existing = _download(storage, key)
            if existing is None:
                storage.upload(key, row.content, row.media_type)
                uploaded = True
            elif sha256(existing).hexdigest() != digest:
                raise ValueError("같은 key에 다른 bytes가 있습니다")
            stored = _download(storage, key)
            if stored is None or sha256(stored).hexdigest() != digest:
                raise ValueError("저장한 객체를 다시 읽었을 때 해시가 다릅니다")
            matched = session.execute(update(TradeArtifact).where(
                TradeArtifact.id == row.id, TradeArtifact.object_key.is_(None),
            ).values(object_key=key, size_bytes=len(row.content))).rowcount
            if matched != 1:
                raise ValueError("동시 실행으로 이미 옮겨졌습니다")
    return key, uploaded


def backfill(database, storage, *, confirmed: bool = False) -> dict:
    """바이너리를 해시 대조하며 object_key로 옮긴다. 보고: {linked, uploaded, verified, skipped, confirmed}."""
    linked, uploaded, verified, skipped = 0, 0, 0, []
    with database.session() as session:
        rows = list(session.scalars(select(TradeArtifact).order_by(TradeArtifact.id)))
    for row in rows:
        if row.object_key is not None:
            if confirmed:  # 이미 옮긴 행은 검증만 한다(반복 실행 = 검증 실행).
                stored = _download(storage, row.object_key)
                if stored is None or sha256(stored).hexdigest() != row.content_hash:
                    skipped.append(f"TradeArtifact {row.id}: 저장 객체 해시 불일치")
                else:
                    verified += 1
            continue
        if not row.content:
            continue
        if sha256(row.content).hexdigest() != row.content_hash:
            skipped.append(f"TradeArtifact {row.id}: bytes 해시가 기록과 다릅니다")
            continue
        try:
            _, new_upload = _link(database, storage, row, confirmed=confirmed)
        except ValueError as error:
            skipped.append(f"TradeArtifact {row.id}: {error}")
            continue
        if confirmed:
            uploaded += int(new_upload)
            verified += 1
        linked += 1
    return {"linked": linked, "uploaded": uploaded, "verified": verified,
            "skipped": skipped, "confirmed": confirmed}


def main(argv: Sequence[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true",
                        help="계획을 실제로 실행하고 저장 객체를 해시 대조로 검증한다")
    args = parser.parse_args(argv)
    settings = get_settings()
    if not settings.supabase_url.strip() or not settings.supabase_secret_key.strip():
        print("SUPABASE_URL·SUPABASE_SECRET_KEY가 설정되지 않았습니다.")
        return 2
    database = get_database(settings)
    storage = StorageClient(settings.supabase_url, settings.supabase_secret_key,
                            settings.supabase_storage_bucket.strip() or "trade-files")
    try:
        report = backfill(database, storage, confirmed=args.yes)
    except StorageError as error:
        print(f"저장소 오류로 중단합니다: {error.message}")
        return 1
    mode = "실행" if args.yes else "dry-run"
    print(f"backfill {mode}: object_key 연결 {report['linked']}행(새 업로드 {report['uploaded']}개), "
          f"해시 대조 검증 {report['verified']}행.")
    for reason in report["skipped"]:
        print(f"건너뜀: {reason}")
    if not args.yes:
        print("dry-run입니다. 실제로 옮기려면 --yes를 붙여 다시 실행해 주세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
