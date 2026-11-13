"""도메인 라우터가 공유하는 사용자 인증과 세션 폼 CSRF 검사."""
import hmac

from fastapi import HTTPException, Request

from app.auth.supabase import bearer_user_id


class LoginRequired(HTTPException):
    """로그인하지 않은 요청. `app/main.py`가 `/login`으로 보낸다."""

    def __init__(self):
        super().__init__(status_code=401, detail="로그인이 필요합니다")


def current_user_id(request: Request) -> int:
    """로그인한 사용자 id. `Authorization` 헤더가 있으면 Supabase Bearer 토큰으로만 인증하고
    잘못된 토큰일 때 쿠키 세션으로 우회하지 않는다(CONTRACT 9.1). 헤더가 없을 때만 legacy
    `gq_session` 쿠키 세션(계획 6절)을 읽는다. 테스트는 `app.dependency_overrides`로 바꿔 끼운다.
    """
    if request.headers.get("authorization"):
        return bearer_user_id(request)
    user_id = request.scope.get("session", {}).get("user_id")
    if user_id is None:
        raise LoginRequired()
    return int(user_id)


def check_session_csrf(request: Request, supplied: str):
    """개인 키·PC 연결 승인 폼의 세션 토큰을 검사한다."""
    expected = request.session.get("trade_csrf", "")
    if not expected or not supplied or not hmac.compare_digest(expected.encode(), supplied.encode()):
        raise HTTPException(403, "유효한 CSRF 토큰이 필요합니다")
