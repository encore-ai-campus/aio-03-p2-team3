"""kekorea-port 4절: 원본 test_branding.py 이식 — 직인 조회는 DB 바이너리 대신 Storage 이미지에서.

원본: reference/kekorea/Quotation_KEKOREA/tests/test_branding.py
바꾼 점: 원본의 로컬 파일/클라우드 시크릿/Supabase 업로드 경로를 company_branding → file_assets →
비공개 Storage 조회로 바꿨다(계획 9절). PNG 매직 검사와 SHA-256 대조(오래된 직인이 조용히 쓰이지
않음)는 원본 동작을 유지하고, Storage 장애·손상은 성공으로 돌려주지 않는다.
"""

import hashlib

import pytest

from app.db.models import CompanyBranding, FileAsset, User
from app.files.storage import StorageError
from app.trade.settings.repository import resolve_company_seal
from tests.fakes.storage import FakeStorage
from tests.test_trade_flow import seal_png

SEAL = seal_png()


def put_branding(database, storage, user_id=1, *, data=SEAL):
    """직인을 file_assets + 가짜 Storage 객체로 심는다(9절 저장 경로와 같은 상태)."""
    with database.session() as session:
        asset = FileAsset(user_id=user_id, original_filename="seal.png", content_type="image/png",
                          size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                          object_key=f"{user_id}/branding/seed")
        session.add(asset)
        session.flush()
        session.add(CompanyBranding(user_id=user_id, seal_file_id=asset.id))
    storage.objects[asset.object_key] = data
    return asset


def test_stored_seal_is_returned_when_png_magic_and_sha256_match(database):
    storage = FakeStorage()
    put_branding(database, storage)
    seal, error = resolve_company_seal(1, database=database, storage=storage)
    assert seal == SEAL and error is None


def test_missing_seal_reports_setup_error(database):
    seal, error = resolve_company_seal(1, database=database, storage=FakeStorage())
    assert seal is None and "업로드" in error


def test_non_png_seal_is_rejected(database):
    storage = FakeStorage()
    put_branding(database, storage, data=b"not-a-png" + SEAL[8:])
    seal, error = resolve_company_seal(1, database=database, storage=storage)
    assert seal is None and "PNG" in error


def test_corrupted_seal_bytes_fail_instead_of_returning_stale_image(database):
    # 원본 test_cloud_secret_must_match_requested_image: 기록(SHA-256)과 다르면 조용히 쓰지 않는다.
    storage = FakeStorage()
    put_branding(database, storage)
    storage.objects["1/branding/seed"] = b"tampered"  # Storage 객체가 기록과 달라졌다
    with pytest.raises(StorageError):
        resolve_company_seal(1, database=database, storage=storage)


def test_storage_failure_is_not_success(database):
    storage = FakeStorage()
    put_branding(database, storage)
    storage.download_error = StorageError("storage_unavailable", "저장소 오류")
    with pytest.raises(StorageError):
        resolve_company_seal(1, database=database, storage=storage)
    with pytest.raises(StorageError):  # Storage 미설정도 실패다
        resolve_company_seal(1, database=database, storage=None)


def test_users_only_see_their_own_seal(database):
    with database.session() as session:
        session.add(User(id=2, google_sub="fake-sub-2", email="demo2@example.invalid"))
    storage = FakeStorage()
    put_branding(database, storage, user_id=2)
    assert resolve_company_seal(1, database=database, storage=storage)[0] is None
    assert resolve_company_seal(2, database=database, storage=storage)[0] == SEAL
