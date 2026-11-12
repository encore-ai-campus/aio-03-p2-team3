"""`GET /api/me` — React 로그인·새로고침 복구가 시작하는 Bearer 전용 JSON 진입점(CONTRACT 9.1절)."""
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import JSONResponse

from app.auth.gmail import gmail_status
from app.auth.supabase import bearer_user_id
from app.db.models import User
from app.services.watch import renew_watch_if_due
from app.llm.client import OpenAIKeyError
from app.services.openai_keys import delete_key, save_key

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


@router.put("/openai-key")
def put_openai_key(request: Request, api_key: Annotated[str, Form()] = "",
                   user_id: int = Depends(bearer_user_id)):
    # 길이/공백 검사는 기존 서비스가 수행한다. 검증 오류에 입력한 비밀값을 되돌려주지 않는다.
    try:
        save_key(request.app.state.database, user_id, api_key, request.app.state.google_access.cipher,
                 settings=request.app.state.settings)
    except OpenAIKeyError as error:
        return JSONResponse({"error": {"code": error.code, "message": error.message}},
                            status_code=error.status_code, headers={"Cache-Control": "private, no-store"})
    return JSONResponse({"registered": True}, headers={"Cache-Control": "private, no-store"})


@router.delete("/openai-key")
def remove_openai_key(request: Request, user_id: int = Depends(bearer_user_id)):
    try:
        delete_key(request.app.state.database, user_id, settings=request.app.state.settings)
    except OpenAIKeyError as error:
        return JSONResponse({"error": {"code": error.code, "message": error.message}},
                            status_code=error.status_code, headers={"Cache-Control": "private, no-store"})
    return JSONResponse({"registered": False}, headers={"Cache-Control": "private, no-store"})
