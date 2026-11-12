"""기존 company_branding·trade_proposals 바이너리를 Storage 객체+file_assets로 옮기는
일회성 backfill 명령(계획 9절). 실제 바이너리 열 DROP은 하지 않는다(22절로 분리).

사용:
    uv run python -m app.trade.settings.backfill        # 계획만 출력(dry-run)
    uv run python -m app.trade.settings.backfill --yes   # 실행

- 이미 파일 ID를 가진 행은 건너뛴다. 같은 사용자의 같은 bytes(SHA-256)는 기존 file_assets 행을
  재사용해 중복 객체를 만들지 않는다. 반복 실행해도 값이 바뀌지 않는다.
- 해시 대조: company_branding.seal_sha256, 제안 payload의 seal_sha256/logo_sha256과 바이너리
  해시가 다른 행은 옮기지 않고 보고한다(조용히 고치지 않는다).
- 행 단위로 커밋한다. 업로드 뒤 SQL이 실패하면 그 객체는 미참조로 남고 cleanup 명령이 정리한다.
"""
from argparse import ArgumentParser
from collections.abc import Sequence
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select

from app.config import get_settings
from app.db.engine import get_database
from app.db.models import CompanyBranding, FileAsset, TradeProposal
from app.files.storage import StorageClient, StorageError


def _expected_hash(row, kind):
    """행이 스스로 기록한 이미지 해시(없으면 None). 제안은 payload에, 설정은 seal_sha256 열에 둔다."""
    if isinstance(row, TradeProposal):
        return (row.payload or {}).get(f"{kind}_sha256")
    return row.seal_sha256 if kind == "seal" else None


def _link(database, storage, row, kind, data, digest, known, confirmed) -> bool:
    """한 행의 한 이미지를 file_assets 파일 ID로 옮긴다. 새 자산을 만들었으면(만들 예정이면) True."""
    user_id, create = row.user_id, (row.user_id, digest) not in known
    if confirmed:
        with database.session() as session:
            session.add(row)
            if create:
                object_key = f"{user_id}/branding/{uuid4().hex}"
                storage.upload(object_key, data, "image/png")
                asset = FileAsset(user_id=user_id, original_filename=f"{kind}.png", content_type="image/png",
                                  size_bytes=len(data), sha256=digest, object_key=object_key)
                session.add(asset)
                session.flush()
            else:
                asset = session.scalar(select(FileAsset).where(
                    FileAsset.user_id == user_id, FileAsset.sha256 == digest))
            if kind == "logo":
                row.logo_file_id = asset.id
            else:
                row.seal_file_id = asset.id
    known.add((user_id, digest))
    return create


def backfill(database, storage, *, confirmed: bool = False) -> dict:
    """바이너리를 해시 대조하며 파일 ID로 옮긴다. 보고: {linked, uploaded, skipped, confirmed}."""
    linked, uploaded, skipped = 0, 0, []
    with database.session() as session:
        rows = (list(session.scalars(select(CompanyBranding)))
                + list(session.scalars(select(TradeProposal))))
        known = {(asset.user_id, asset.sha256) for asset in session.scalars(select(FileAsset))}
    for row in rows:
        for kind in ("logo", "seal"):
            current = row.logo_file_id if kind == "logo" else row.seal_file_id
            if current is not None:
                continue  # 이미 옮겼다(반복 실행 안전)
            data = row.logo if kind == "logo" else row.seal
            if not data:
                continue
            digest = sha256(data).hexdigest()
            expected = _expected_hash(row, kind) or None
            if expected is not None and expected != digest:
                skipped.append(f"{type(row).__name__}(user_id={row.user_id}) {kind}: 해시 불일치")
                continue
            if _link(database, storage, row, kind, data, digest, known, confirmed):
                uploaded += 1
            linked += 1
    return {"linked": linked, "uploaded": uploaded, "skipped": skipped, "confirmed": confirmed}


def main(argv: Sequence[str] | None = None) -> int:
    parser = ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="계획을 실제로 실행한다")
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
    print(f"backfill {mode}: 파일 ID 연결 {report['linked']}행, 새 업로드 {report['uploaded']}개.")
    for reason in report["skipped"]:
        print(f"건너뜀: {reason}")
    if not args.yes:
        print("dry-run입니다. 실제로 옮기려면 --yes를 붙여 다시 실행해 주세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
