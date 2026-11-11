"""kekorea-port 4절: 원본 test_branding.py 이식 — 직인 조회는 개인 Supabase 대신 DB 표에서.

원본: reference/kekorea/Quotation_KEKOREA/tests/test_branding.py
바꾼 점: 원본의 로컬 파일/클라우드 시크릿/Supabase 업로드 경로를 company_branding 표 조회로 바꿨다.
PNG 매직 검사와 SHA-256 대조(오래된 직인이 조용히 쓰이지 않음)는 원본 동작을 유지한다.
"""

import hashlib

from app.db.models import CompanyBranding, User
from app.trade.settings.repository import resolve_company_seal

SEAL = b"\x89PNG\r\n\x1a\n" + b"seal-image-bytes-for-test"


def put_branding(database, user_id, *, seal=SEAL, sha=None):
    with database.session() as session:
        session.add(CompanyBranding(
            user_id=user_id, seal=seal,
            seal_sha256=sha if sha is not None else hashlib.sha256(seal).hexdigest()))
    return database


def test_stored_seal_is_returned_when_png_magic_and_sha256_match(database):
    put_branding(database, 1)
    seal, error = resolve_company_seal(1, database=database)
    assert seal == SEAL and error is None


def test_missing_seal_reports_setup_error(database):
    seal, error = resolve_company_seal(1, database=database)
    assert seal is None and "업로드" in error


def test_non_png_seal_is_rejected(database):
    put_branding(database, 1, seal=b"not-a-png" + SEAL[8:])
    seal, error = resolve_company_seal(1, database=database)
    assert seal is None and "PNG" in error


def test_seal_must_match_its_stored_sha256(database):
    # 원본 test_cloud_secret_must_match_requested_image: 대조값이 다르면 옛 직인을 조용히 쓰지 않는다.
    put_branding(database, 1, sha="0" * 64)
    seal, error = resolve_company_seal(1, database=database)
    assert seal is None and "SHA-256" in error


def test_missing_sha256_reference_is_rejected(database):
    with database.session() as session:
        session.add(CompanyBranding(user_id=1, seal=SEAL, seal_sha256=None))
    seal, error = resolve_company_seal(1, database=database)
    assert seal is None and "대조값" in error


def test_users_only_see_their_own_seal(database):
    with database.session() as session:
        session.add(User(id=2, google_sub="fake-sub-2", email="demo2@example.invalid"))
    put_branding(database, 2)
    assert resolve_company_seal(1, database=database)[0] is None
    assert resolve_company_seal(2, database=database)[0] == SEAL
