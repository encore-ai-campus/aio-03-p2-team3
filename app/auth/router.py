"""`GET /api/me` — React 로그인·새로고침 복구가 시작하는 Bearer 전용 JSON 진입점(CONTRACT 9.1절)."""
from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.auth.gmail import gmail_status
from app.auth.supabase import bearer_user_id
from app.db.models import User
from app.services.watch import renew_watch_if_due

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me")
def me(request: Request, background: BackgroundTasks, user_id: int = Depends(bearer_user_id)):
    # React 화면 요청의 감시 갱신(계획 7절): legacy HTML 방문에만 의존하지 않게 API 경로에도 건다.
    background.add_task(renew_watch_if_due, request.app.state.google_access, user_id)
    with request.app.state.database.session() as session:
        user = session.get(User, user_id)
    return {
        "user_id": user_id,
        "email": user.email,
        "display_name": user.display_name,
        "gmail": gmail_status(request, user_id),
    }
