"""문서 JSON API가 공유하는 인증·CSRF·확정 파일 전송."""
import hmac
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.trade.review.repository import SQLReviews
from app.trade.review.operations import download_file as load_file
from app.auth.deps import current_user_id

router = APIRouter(prefix="/api", tags=["trade-session"])


def require_write(request: Request, user_id: int = Depends(current_user_id)) -> int:
    if request.headers.get("authorization"):
        return user_id  # Bearer 인증은 헤더 자격증명이라 브라우저가 몰래 실어 보내지 않는다(CSRF 검사 생략).
    expected = request.session.get("trade_csrf")
    supplied = request.headers.get("X-CSRF-Token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(403, detail="유효한 X-CSRF-Token이 필요합니다")
    return user_id


@router.get("/session")
def session_info(request: Request, user_id: int = Depends(current_user_id)):
    request.session.setdefault("trade_csrf", secrets.token_urlsafe(32))
    return {"user_id": user_id, "csrf_token": request.session["trade_csrf"]}


@router.get("/trade/files/{file_id}")
def download_file(file_id: str, request: Request, user_id: int = Depends(current_user_id)):
    file = load_file(file_id, repository=SQLReviews(request.app.state.database, user_id, "PI",
                                                    storage=request.app.state.storage))
    return Response(content=file["content"], media_type=file["media_type"], headers={
        "Content-Disposition": f'attachment; filename="{file["filename"]}"',
        "Cache-Control": "private, no-store", "ETag": f'"{file["content_hash"]}"',
        "X-Content-Type-Options": "nosniff",
    })
