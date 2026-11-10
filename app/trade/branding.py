"""사용자별 직인 조회(원본의 개인 Supabase 버킷 대신 이 서비스의 DB 사용).

원본: reference/kekorea/Quotation_KEKOREA/agent/branding.py
원본: reference/kekorea/Quotation_KEKOREA/agent/seal_storage.py (폐기 — Supabase 접근을
      app/db/models.py의 company_branding 표 조회로 바꿨다, docs/CONTRACT.md 15.4·15.7절)
원본 동작 보존: 직인 bytes의 PNG 매직 검사와 SHA-256 대조로 업로드 뒤 변조·저장 오류를 감지한다.
원본의 고정 상수 비교를 사용자별 저장값(company_branding.seal_sha256) 기준으로 일반화했다.
직인 bytes와 대조값은 Git·로그에 넣지 않는다(PRESERVED_BEHAVIOR '직인·비밀정보').
"""
import hashlib

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


# 원본: reference/kekorea/Quotation_KEKOREA/agent/branding.py resolve_company_seal(반환 형식은 계약 15.4절)
def resolve_company_seal(user_id, *, database=None):
    """company_branding 표에서 사용자별 직인 PNG bytes를 꺼낸다.

    반환: (직인 bytes | None, 오류 문구 | None). 오류 문구는 화면 안내용이고 비밀값을 담지 않는다.
    database를 주지 않으면 앱 기본 DB(app.db.engine.get_database)를 쓴다.
    """
    from app.db.engine import get_database
    from app.db.models import CompanyBranding

    db = database or get_database()
    with db.session() as session:
        row = session.get(CompanyBranding, user_id)
        seal = row.seal if row is not None else None
        expected = row.seal_sha256 if row is not None else None
    if not seal:
        return None, "회사 직인이 업로드되지 않았습니다. 설정에서 직인을 업로드해 주세요."
    if not seal.startswith(PNG_MAGIC):
        return None, "저장된 회사 직인이 PNG 이미지가 아닙니다. 직인을 다시 업로드해 주세요."
    if not expected:
        return None, "직인 대조값(SHA-256)이 저장되어 있지 않습니다. 직인을 다시 업로드해 주세요."
    if hashlib.sha256(seal).hexdigest() != expected:
        return None, "저장된 직인이 업로드할 때의 값(SHA-256)과 다릅니다. 직인을 다시 업로드해 주세요."
    return seal, None
