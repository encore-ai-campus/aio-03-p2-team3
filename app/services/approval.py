"""승인 뒤 보내기 경로 — 그래프 밖(CONTRACT 3.1·4.4·7절, 계획 9절).

화면의 승인 요청이 `send_approved_candidate()`를 부르고, 그 안에서만 `send_email` 도구를 부른다.
- 두 번 눌러도 한 번만 보낸다: 후보 상태를 `pending`/`send_failed` → `approved`로 바꾸는 조건부 UPDATE를
  통과한 요청만 보낸다(DB가 한 요청만 통과시킴). 같은 원본 메일의 다른 후보를 동시에 승인하는 경우는
  계약의 단일 프로세스 안에서 사용자별 잠금으로 막는다.
- Gmail 발송은 자동 재시도하지 않는다. 실패하면 후보를 `send_failed`로 두어 같은 후보로 다시 승인할 수 있다.
- 보내면 같은 원본 메일의 나머지 대기 후보는 `superseded`, 처리한 메일은 `sent`가 된다.
- `kind=quote` 후보는 여기서 보내지 않는다(견적서 확인 화면의 `send_approved_quote()`, 계획 11).
- 승인·발송은 후보를 만든 실행의 `run_id`로 `approval`·`send` 기록을 남긴다(CONTRACT 8.1절).
"""

from dataclasses import dataclass
from email.utils import getaddresses
import logging
from threading import Lock
from time import perf_counter
from weakref import WeakKeyDictionary

from sqlalchemy import select, update

from app.clients.gmail import GoogleError
from app.db.models import Approval, ProcessedMessage, ReplyCandidate, utcnow
from app.runlog.logger import log_event
from app.services.auth import GoogleAccess, get_access_token, get_owned
from app.tools.base import ToolResult
from app.tools.registry import TOOLS
from app.tools.send_email import google_error_kind, use_google

log = logging.getLogger(__name__)
_locks_guard = Lock()
_locks = WeakKeyDictionary()

RESENDABLE = ("pending", "send_failed")
TAKEN = ("approved", "sent")  # 보내는 중이거나 보낸 후보


@dataclass(frozen=True)
class ApprovalResult:
    """`outcome`은 화면 안내 키(`app/web/routes/candidates.py`의 `APPROVAL_NOTICES`)."""

    outcome: str
    thread_id: str | None = None


def _user_lock(database, user_id: int) -> Lock:
    with _locks_guard:
        return _locks.setdefault(database, {}).setdefault(user_id, Lock())


def send_approved_candidate(user_id: int, candidate_id: int, *, access: GoogleAccess) -> ApprovalResult:
    """로그인한 사용자가 고른 후보 하나를 같은 스레드로 보낸다. 다른 사용자 후보면 `not_found`."""
    with access.database.session() as session:
        candidate = get_owned(session, ReplyCandidate, candidate_id, user_id)
        if candidate is None:
            return ApprovalResult("not_found")
        thread_id = candidate.thread_id
    with _user_lock(access.database, user_id):
        claimed = _claim(access, user_id, candidate_id)
        if isinstance(claimed, str):
            return ApprovalResult(claimed, thread_id)
        _record(access, claimed, "approval", ok=True)
        started = perf_counter()
        result, stage = _send(access, user_id, claimed)
        _finish(access, user_id, claimed, result)
        _record(access, claimed, "send", ok=result.ok, error_kind=result.error_kind,
                duration_ms=int((perf_counter() - started) * 1000))
    if result.ok:
        return ApprovalResult("sent", thread_id)
    if result.error_kind == "auth":
        return ApprovalResult("failed_auth", thread_id)
    if result.error_kind == "network" and stage == "send":
        return ApprovalResult("failed_unknown", thread_id)  # 시간 초과 등: 실제로 나갔을 수 있음
    return ApprovalResult("failed", thread_id)


def _claim(access, user_id, candidate_id):
    """보낼 권리를 얻으면 보낼 값(dict), 못 얻으면 화면 안내 키(str)."""
    with access.database.session() as session:
        candidate = get_owned(session, ReplyCandidate, candidate_id, user_id)
        if candidate.kind == "quote":
            return "quote_only"
        if candidate.status in TAKEN:
            return "already_sent"
        if candidate.status == "superseded" or session.scalar(select(ReplyCandidate.id).where(
            ReplyCandidate.user_id == user_id,
            ReplyCandidate.source_message_id == candidate.source_message_id,
            ReplyCandidate.id != candidate.id, ReplyCandidate.status.in_(TAKEN),
        )) is not None:
            return "already_replied"
        claimed = session.execute(
            update(ReplyCandidate)
            .where(ReplyCandidate.id == candidate_id, ReplyCandidate.user_id == user_id,
                   ReplyCandidate.status.in_(RESENDABLE))
            .values(status="approved")
            .execution_options(synchronize_session=False)
        ).rowcount
        if claimed != 1:
            return "already_sent"
        # candidate_id는 유일하다. 실패 뒤 다시 승인하면 같은 승인 기록을 '보내는 중'으로 되돌린다.
        approval = session.scalar(select(Approval).where(Approval.candidate_id == candidate_id))
        if approval is None:
            approval = Approval(user_id=user_id, candidate_id=candidate_id)
            session.add(approval)
        approval.approved_at = utcnow()
        approval.send_status = "sending"
        approval.sent_message_id = None
        approval.error = None
        return {
            "candidate_id": candidate.id, "run_id": candidate.run_id, "thread_id": candidate.thread_id,
            "source_message_id": candidate.source_message_id, "subject": candidate.subject,
            "body": candidate.body, "quote_id": candidate.quote_id,
        }


def _send(access, user_id, claimed) -> tuple[ToolResult, str]:
    """(결과, 실패한 단계). 원본 머리글을 읽은 뒤 `send_email` 도구를 한 번만 부른다."""
    try:
        gmail = access.google.gmail(get_access_token(access, user_id))
        headers = access.google.get_reply_headers(gmail, claimed["source_message_id"])
    except GoogleError as error:
        return ToolResult(ok=False, error_kind=google_error_kind(error), error_message=error.code,
                          source="gmail"), "prepare"
    to_addrs = [addr for _, addr in getaddresses([headers.get("reply-to") or headers.get("from", "")]) if addr]
    if not to_addrs:
        return ToolResult(ok=False, error_kind="invalid_input", error_message="받는 사람 없음",
                          source="code", attempts=0), "prepare"
    message_id = headers.get("message-id")
    references = headers.get("references", "").split()
    if message_id and message_id not in references:
        references.append(message_id)
    with use_google(access):
        result = TOOLS["send_email"].invoke({
            "user_id": user_id, "thread_id": claimed["thread_id"], "to_addrs": to_addrs,
            "subject": claimed["subject"], "body": claimed["body"],
            "in_reply_to": message_id, "references": references,
        })
    return result, "send"


def _finish(access, user_id, claimed, result: ToolResult) -> None:
    with access.database.session() as session:
        approval = session.scalar(select(Approval).where(Approval.candidate_id == claimed["candidate_id"]))
        candidate = session.get(ReplyCandidate, claimed["candidate_id"])
        if not result.ok:
            approval.send_status = "failed"
            approval.error = f"{result.error_kind}: {result.error_message}"
            candidate.status = "send_failed"
            return
        approval.send_status = "sent"
        approval.sent_message_id = result.value["sent_message_id"]
        candidate.status = "sent"
        session.execute(
            update(ReplyCandidate)
            .where(ReplyCandidate.user_id == user_id,
                   ReplyCandidate.source_message_id == claimed["source_message_id"],
                   ReplyCandidate.id != claimed["candidate_id"], ReplyCandidate.status.in_(RESENDABLE))
            .values(status="superseded")
            .execution_options(synchronize_session=False)
        )
        session.execute(
            update(ProcessedMessage)
            .where(ProcessedMessage.user_id == user_id,
                   ProcessedMessage.gmail_message_id == claimed["source_message_id"])
            .values(status="sent")
            .execution_options(synchronize_session=False)
        )


def _record(access, claimed, event, *, ok, error_kind=None, duration_ms=None) -> None:
    try:
        log_event(claimed["run_id"], event, tool="send_email", duration_ms=duration_ms, database=access.database,
                  detail={"candidate_id": claimed["candidate_id"], "quote_id": claimed["quote_id"],
                          "ok": ok, "error_kind": error_kind})
    except Exception as error:  # 기록 실패로 발송 결과 저장을 막지 않는다
        log.warning("승인 기록 저장 실패 (%s)", type(error).__name__)
