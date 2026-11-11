"""스레드·후보 고르기 화면과 승인(CONTRACT 3.1·7·9절, 계획 9절).

승인 버튼만 `send_approved_candidate()`를 부른다. 결과는 안내 키로 스레드 화면에 돌려보내(303)
새로 고침해도 다시 보내지 않는다. `kind=quote` 후보는 견적서 확인 화면에서만 승인한다(11).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.config import LIMITS
from app.db.models import Approval, ProcessedMessage, ReplyCandidate, ThreadMessage, User
from app.services.approval import RESENDABLE, TAKEN, send_approved_candidate
from app.tools.fallback import NOTICE_MESSAGES
from app.web.routes.auth import require_user
from app.web.routes.inbox import kst

router = APIRouter()

APPROVAL_NOTICES = {
    "sent": ("답장을 보냈습니다. 같은 메일의 다른 후보는 보내지 않습니다.", "done"),
    "failed": ("답장을 보내지 못했습니다. 잠시 뒤 같은 후보를 다시 승인해 주세요.", "warn"),
    "failed_unknown": ("Gmail 응답을 받지 못했습니다. 실제로는 보내졌을 수 있으니 Gmail 보낸편지함을 확인한 뒤, "
                       "보내지 않았으면 같은 후보를 다시 승인해 주세요.", "warn"),
    "failed_auth": ("Google 연결이 만료돼 보내지 못했습니다. 다시 로그인한 뒤 같은 후보를 다시 승인해 주세요.", "warn"),
    "already_sent": ("이미 보냈거나 보내는 중인 답장입니다. 다시 보내지 않았습니다.", "muted"),
    "already_replied": ("이 메일에는 이미 다른 답장을 보냈습니다. 다시 보내지 않았습니다.", "muted"),
    "quote_only": ("견적서 답장은 견적서를 확인한 뒤 견적서 화면에서 승인합니다.", "muted"),
}
CANDIDATE_STATUS = {
    "pending": ("승인 대기", "accent"),
    "approved": ("보내는 중", "muted"),
    "sent": ("보냄", "done"),
    "send_failed": ("보내기 실패", "warn"),
    "superseded": ("다른 답장을 보냄", "muted"),
}
KIND_LABELS = {"general": "일반 답장", "followup": "추가 질문", "quote": "견적서 답장"}


def thread_view(database, user_id: int, thread_id: str) -> list[dict] | None:
    """스레드의 메일·처리 상태·후보. 본인 것이 하나도 없으면 None."""
    with database.session() as session:
        messages = list(session.scalars(
            select(ThreadMessage).where(ThreadMessage.user_id == user_id, ThreadMessage.thread_id == thread_id)
            .order_by(ThreadMessage.sent_at, ThreadMessage.id)
        ))
        processed = list(session.scalars(
            select(ProcessedMessage).where(ProcessedMessage.user_id == user_id, ProcessedMessage.thread_id == thread_id)
            .order_by(ProcessedMessage.id)
        ))
        candidates = list(session.scalars(
            select(ReplyCandidate).where(ReplyCandidate.user_id == user_id, ReplyCandidate.thread_id == thread_id)
            .order_by(ReplyCandidate.id)
        ))
        approvals = {a.candidate_id: a for a in session.scalars(
            select(Approval).where(Approval.user_id == user_id,
                                   Approval.candidate_id.in_([c.id for c in candidates]))
        )}
    if not messages and not candidates and not processed:
        return None
    taken = {c.source_message_id for c in candidates if c.status in TAKEN}
    by_source = {p.gmail_message_id: {"status": p.status, "run_id": p.run_id, "candidates": []} for p in processed}
    for c in candidates:
        label, tone = CANDIDATE_STATUS.get(c.status, (c.status, "muted"))
        approval = approvals.get(c.id)
        source = by_source.setdefault(c.source_message_id, {"status": None, "run_id": None, "candidates": []})
        source["candidates"].append({
            "id": c.id, "label": c.label, "subject": c.subject, "body": c.body,
            "kind_label": KIND_LABELS.get(c.kind, c.kind), "quote_waiting": c.kind == "quote" and c.status in RESENDABLE,
            "status_label": label, "tone": tone, "needs_review": c.needs_review,
            "notice": NOTICE_MESSAGES.get(c.notice or ""),
            "quote_id": c.quote_id if c.kind == "quote" else None,
            "approved_at": kst(approval.approved_at) if approval else None,
            "can_approve": c.kind != "quote" and c.status in RESENDABLE and c.source_message_id not in taken,
        })
    entries = [{
        "from_addr": m.from_addr, "subject": m.subject, "body": m.body_text, "sent": kst(m.sent_at),
        "outgoing": m.direction == "out",
        **by_source.pop(m.gmail_message_id, {"status": None, "run_id": None, "candidates": []}),
    } for m in messages]
    for leftover in by_source.values():  # 원본 메일 줄이 없는 처리 상태·후보도 숨기지 않는다
        entries.append({"from_addr": None, "subject": None, "body": None, "sent": None,
                        "outgoing": False, **leftover})
    return entries


@router.get("/threads/{thread_id}", include_in_schema=False)
def thread_page(request: Request, thread_id: str, notice: str | None = None, user: User = Depends(require_user)):
    entries = thread_view(request.app.state.database, user.id, thread_id)
    if entries is None:
        raise HTTPException(404, detail="스레드를 찾을 수 없습니다")
    message, tone = APPROVAL_NOTICES.get(notice or "", (None, None))
    return request.app.state.templates.TemplateResponse(request=request, name="pages/thread.html", context={
        "entries": entries, "notice": message, "notice_tone": tone,
        "thread_id": thread_id, "processing": any(entry["status"] == "processing" for entry in entries),
        "poll_seconds": LIMITS["INBOX_POLL_SECONDS"],
    })


@router.post("/candidates/{candidate_id}/approve", include_in_schema=False)
def approve(request: Request, candidate_id: int, user: User = Depends(require_user)):
    result = send_approved_candidate(user.id, candidate_id, access=request.app.state.google_access)
    if result.outcome == "not_found":
        raise HTTPException(404, detail="후보를 찾을 수 없습니다")
    return RedirectResponse(f"/threads/{result.thread_id}?notice={result.outcome}", status_code=303)
