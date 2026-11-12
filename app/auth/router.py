"""`GET /api/me` — React 로그인·새로고침 복구가 시작하는 Bearer 전용 JSON 진입점(CONTRACT 9.1절)."""
from fastapi import APIRouter, Depends, Request

from app.auth.supabase import bearer_user_id
from app.db.models import GmailWatch, GoogleToken, User

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me")
def me(request: Request, user_id: int = Depends(bearer_user_id)):
    with request.app.state.database.session() as session:
        user = session.get(User, user_id)
        token = session.get(GoogleToken, user_id)
        watch = session.get(GmailWatch, user_id)
    return {
        "user_id": user_id,
        "email": user.email,
        "display_name": user.display_name,
        "gmail": {
            # 갱신 토큰이 저장돼 있으면 Gmail 연결로 본다. 연결 시작·해제 API는 계획 7절이 만든다.
            "connected": bool(token and token.refresh_token_enc),
            "watch": watch.status if watch else "stopped",
        },
    }
