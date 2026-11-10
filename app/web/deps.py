"""여러 화면이 함께 쓰는 FastAPI 의존성."""
from fastapi import HTTPException, Request


class LoginRequired(HTTPException):
    """로그인하지 않은 요청. `app/main.py`가 `/login`으로 보낸다."""

    def __init__(self):
        super().__init__(status_code=401, detail="로그인이 필요합니다")


def current_user_id(request: Request) -> int:
    """로그인한 사용자 id. 로그인(계획 6)이 세션에 `user_id`를 넣는다.

    세션 미들웨어가 아직 없어도 오류 없이 '로그인 안 함'으로 본다. 테스트는
    `app.dependency_overrides[current_user_id]`로 바꿔 끼운다.
    """
    user_id = request.scope.get("session", {}).get("user_id")
    if user_id is None:
        raise LoginRequired()
    return int(user_id)
