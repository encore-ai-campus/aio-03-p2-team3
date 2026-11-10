"""견적서 확인 화면에서만 호출하는 승인·첨부 발송(계획 11절).

9절의 일반 후보 승인·send_email 구현은 별도다. 여기서는 등록된 도구만 호출한다.
"""

from base64 import b64encode
from email.utils import parseaddr
from threading import RLock

from sqlalchemy import select

from app.db.models import Approval, ProcessedMessage, Quote, ReplyCandidate, Run, ThreadMessage, User, utcnow
from app.quote.pdf import render_quote_pdf
from app.runlog.logger import log_event, recording
from app.services.auth import GoogleAccess, get_access_token
from app.tools.base import ToolResult
from app.tools.registry import TOOLS

# SQLite는 SELECT FOR UPDATE를 지원하지 않는다. Postgres에서는 사용자·견적서 행 잠금도 쓴다.
_quote_approval_lock = RLock()


def _result(status, *, ok=False, message="", sent_message_id=None):
    return {"ok": ok, "status": status, "message": message, "sent_message_id": sent_message_id}


def _log(database, run_id, user_id, event, detail):
    with database.session() as session:
        exists = session.scalar(select(Run.run_id).where(Run.run_id == run_id, Run.user_id == user_id))
    if exists:
        log_event(run_id, event, tool="send_email", detail=detail, database=database)


def send_approved_quote(access: GoogleAccess, user_id: int, quote_id: int, candidate_id: int) -> dict:
    """DB에 sending을 먼저 확정한다. 재클릭·다른 후보 승인·불확실한 실패는 재발송하지 않는다."""
    database = access.database
    with _quote_approval_lock, database.session() as session:
        session.scalar(select(User).where(User.id == user_id).with_for_update())
        quote = session.scalar(select(Quote).where(Quote.id == quote_id, Quote.user_id == user_id)
                               .with_for_update())
        candidate = session.scalar(select(ReplyCandidate).where(
            ReplyCandidate.id == candidate_id, ReplyCandidate.user_id == user_id,
        ))
        if quote is None or candidate is None or candidate.quote_id != quote.id or candidate.kind != "quote":
            return _result("not_found", message="견적서와 답장 후보를 찾을 수 없습니다")
        if candidate.run_id != quote.run_id or candidate.thread_id != quote.thread_id:
            return _result("not_found", message="견적서와 답장 후보가 일치하지 않습니다")
        # 같은 원문에서 고른 다른 후보도 하나의 승인으로 묶는다.
        source = session.scalar(select(ThreadMessage).where(
            ThreadMessage.user_id == user_id, ThreadMessage.thread_id == candidate.thread_id,
            ThreadMessage.gmail_message_id == candidate.source_message_id, ThreadMessage.direction == "in",
        ))
        if source is None:
            return _result("not_found", message="답장할 원문을 찾을 수 없습니다")
        session.scalar(select(ProcessedMessage).where(
            ProcessedMessage.user_id == user_id,
            ProcessedMessage.gmail_message_id == candidate.source_message_id,
        ).with_for_update())
        prior = session.scalar(select(Approval).join(ReplyCandidate).where(
            Approval.user_id == user_id, ReplyCandidate.user_id == user_id,
            ReplyCandidate.thread_id == candidate.thread_id,
            ReplyCandidate.source_message_id == candidate.source_message_id,
        ))
        if prior is not None:
            return _result(prior.send_status, ok=prior.send_status == "sent",
                           message="이미 보냈거나 발송 결과를 확인해야 하는 승인입니다",
                           sent_message_id=prior.sent_message_id)
        if quote.status != "ready" or quote.draft["missing_prices"]:
            return _result("needs_price", message="빠진 단가를 입력한 뒤 승인해 주세요")
        if candidate.status != "pending":
            return _result("unavailable", message="승인 대기 중인 후보가 아닙니다")
        snapshot = dict(quote.draft)
        payload = {"user_id": user_id, "thread_id": candidate.thread_id,
                   "subject": candidate.subject, "body": candidate.body}
        source_message_id, run_id = candidate.source_message_id, candidate.run_id
        approval = Approval(user_id=user_id, candidate_id=candidate.id, send_status="sending")
        session.add(approval)
        candidate.status = "approved"
        for sibling in session.scalars(select(ReplyCandidate).where(
            ReplyCandidate.user_id == user_id, ReplyCandidate.thread_id == candidate.thread_id,
            ReplyCandidate.source_message_id == source_message_id, ReplyCandidate.id != candidate.id,
            ReplyCandidate.status == "pending",
        )):
            sibling.status = "superseded"
    _log(database, run_id, user_id, "approval", {"ok": True, "quote_id": quote_id, "candidate_id": candidate_id})
    try:
        # Gmail 원문의 RFC 헤더를 읽는다. DB에 없는 Message-ID를 임의로 만들지 않는다.
        token = get_access_token(access, user_id)
        raw = access.google.get_message(access.google.gmail(token), source_message_id)
        if raw["id"] != source_message_id or raw["threadId"] != payload["thread_id"]:
            raise ValueError("source_mismatch")
        headers = {h["name"].lower(): h["value"] for h in raw["payload"].get("headers", [])}
        recipient = parseaddr(headers.get("reply-to") or headers.get("from", ""))[1]
        if not recipient:
            raise ValueError("missing_recipient")
        reply_to = headers.get("message-id")
        references = headers.get("references", "").split()
        if reply_to and reply_to not in references:
            references.append(reply_to)
        payload.update(to_addrs=[recipient], in_reply_to=reply_to, references=references,
                       attachments=[{"filename": f"견적서_{snapshot['quote_no']}.pdf",
                                     "mime_type": "application/pdf",
                                     "content_b64": b64encode(render_quote_pdf(snapshot)).decode("ascii")}])
        with recording(database, run_id):
            sent = TOOLS["send_email"].invoke(payload)
        if sent.ok and not (isinstance(sent.value, dict) and sent.value.get("sent_message_id")):
            raise ValueError("missing_send_result")
    except Exception as error:
        sent = ToolResult(ok=False, error_kind="internal", source="code",
                          error_message=f"견적서 발송 실패 ({type(error).__name__})")
    with _quote_approval_lock, database.session() as session:
        approval = session.scalar(select(Approval).where(Approval.user_id == user_id,
                                                         Approval.candidate_id == candidate_id))
        approval.send_status = "sent" if sent.ok else "failed"
        approval.sent_message_id = sent.value["sent_message_id"] if sent.ok else None
        approval.error = None if sent.ok else sent.error_kind or "internal"
        candidate = session.scalar(select(ReplyCandidate).where(ReplyCandidate.id == candidate_id,
                                                                 ReplyCandidate.user_id == user_id))
        candidate.status = "sent" if sent.ok else "send_failed"
        if sent.ok:
            quote = session.scalar(select(Quote).where(Quote.id == quote_id, Quote.user_id == user_id))
            quote.status, quote.sent_at = "sent", utcnow()
            quote.draft = {**quote.draft, "status": "sent"}
        processed = session.scalar(select(ProcessedMessage).where(
            ProcessedMessage.user_id == user_id, ProcessedMessage.gmail_message_id == source_message_id,
        ))
        if processed:
            processed.status = "sent" if sent.ok else "error"
    _log(database, run_id, user_id, "send", {"ok": sent.ok, "error_kind": sent.error_kind,
                                            "quote_id": quote_id, "candidate_id": candidate_id})
    return _result("sent" if sent.ok else "failed", ok=sent.ok,
                   sent_message_id=sent.value["sent_message_id"] if sent.ok else None,
                   message="견적서를 첨부해 보냈습니다" if sent.ok else
                   "발송에 실패했습니다. 보낸편지함에서 결과를 확인해 주세요. 자동으로 재발송하지 않습니다")
