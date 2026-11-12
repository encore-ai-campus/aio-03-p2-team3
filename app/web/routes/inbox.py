"""받은 메일·후보 목록 화면(CONTRACT 7·9절, 계획 9절).

본인 메일만 보인다(`user_id`로 거름). `GET /inbox/list`는 화면이 열려 있는 동안 `INBOX_POLL_SECONDS`마다
HTMX로 새로 읽는 가벼운 조각이다(새 후보를 바로 보여 주고, Render 무료 서버가 잠들지 않게 함).
"""

from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import and_, func, select

from app.config import LIMITS
from app.db.models import ProcessedMessage, ReplyCandidate, ThreadMessage, User
from app.web.routes.auth import connection_status, current_user, require_user
from app.services.openai_keys import key_registered

router = APIRouter()
KST = timezone(timedelta(hours=9), "KST")
INBOX_LIMIT = 50

# 처리 상태와 화면 표시(CONTRACT 7절). ignored는 목록에 보이지 않는다.
MESSAGE_STATUS = {
    "processing": ("처리 중", "muted"),
    "awaiting_approval": ("승인 대기", "accent"),
    "sent": ("보냄", "done"),
    "error": ("오류", "warn"),
}


def kst(value) -> str:
    return value.astimezone(KST).strftime("%m-%d %H:%M") if value else "—"


def inbox_items(database, user_id: int) -> list[dict]:
    with database.session() as session:
        rows = session.execute(
            select(ProcessedMessage, ThreadMessage.subject, ThreadMessage.from_addr)
            .outerjoin(ThreadMessage, and_(
                ThreadMessage.user_id == ProcessedMessage.user_id,
                ThreadMessage.gmail_message_id == ProcessedMessage.gmail_message_id,
            ))
            .where(ProcessedMessage.user_id == user_id, ProcessedMessage.status != "ignored")
            .order_by(ProcessedMessage.id.desc())
            .limit(INBOX_LIMIT)
        ).all()
        pending = dict(session.execute(
            select(ReplyCandidate.source_message_id, func.count())
            .where(ReplyCandidate.user_id == user_id, ReplyCandidate.status.in_(["pending", "send_failed"]))
            .group_by(ReplyCandidate.source_message_id)
        ).all())
    items = []
    for message, subject, sender in rows:
        label, tone = MESSAGE_STATUS.get(message.status, (message.status, "muted"))
        items.append({
            "thread_id": message.thread_id, "subject": subject or "(제목 없음)", "from_addr": sender or "—",
            "received": kst(message.received_at or message.created_at),
            "status_label": label, "tone": tone,
            "rate_limited": message.notice == "rate_limit",
            "key_required": message.notice == "openai_key_required",
            "worker_notice": worker_notice(message.notice),
            "pending": pending.get(message.gmail_message_id, 0) if message.status == "awaiting_approval" else 0,
        })
    return items


def worker_notice(code):
    from app.worker.adapter import ERRORS
    return next((message for name, message, _ in ERRORS.values() if name.lower() == code), None)


def _context(request: Request, user: User) -> dict:
    return {
        "user": user, "items": inbox_items(request.app.state.database, user.id),
        "poll_seconds": LIMITS["INBOX_POLL_SECONDS"],
        "local_mode": request.app.state.settings.ai_runtime == "local",
        "openai_registered": key_registered(request.app.state.database, user.id, settings=request.app.state.settings),
    }


@router.get("/inbox", include_in_schema=False)
def inbox(request: Request, user: User | None = Depends(current_user)):
    context = {"user": None, "status": None}
    if user is not None:
        context = {**_context(request, user), "status": connection_status(request, user)}
    return request.app.state.templates.TemplateResponse(request=request, name="pages/inbox.html", context=context)


@router.get("/inbox/list", include_in_schema=False)
def inbox_list(request: Request, user: User = Depends(require_user)):
    return request.app.state.templates.TemplateResponse(
        request=request, name="pages/inbox_list.html", context=_context(request, user),
    )
