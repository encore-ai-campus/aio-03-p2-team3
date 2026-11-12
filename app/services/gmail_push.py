"""푸시 응답 뒤 새 메일을 저장·실행한다(CONTRACT 1·2·4.3·7·10절, 계획 7절)."""

from datetime import datetime
import logging
from threading import Lock
from weakref import WeakKeyDictionary

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.clients.gmail import GoogleError, TokenExpired, decode_message
from app.db.models import GmailWatch, ProcessedMessage, ThreadMessage, User
from app.graph.run import start_run
from app.services.auth import GoogleAccess, get_access_token
from app.services.watch import renew_watch_if_due

log = logging.getLogger(__name__)
_locks_guard = Lock()
_locks = WeakKeyDictionary()


def _mailbox_lock(database, user_id):
    # 계약의 단일 프로세스 안에서 같은 사용자의 기록 조회·커서 갱신을 직렬화한다.
    # 실제 중복 삽입은 DB 유일 제약으로도 막는다.
    with _locks_guard:
        return _locks.setdefault(database, {}).setdefault(user_id, Lock())


def process_notification(access: GoogleAccess, email_address: str, history_id: str, *, graph=None):
    if access.local_mode:
        return  # 로컬 수집은 검증된 소유자만 조회하며 Pub/Sub로 시작하지 않는다.
    with access.database.session() as session:
        user = session.scalar(select(User).where(func.lower(User.email) == email_address.lower()))
    if user is None:
        return
    with _mailbox_lock(access.database, user.id):
        try:
            _process_mailbox(access, user, history_id, graph)
        except Exception as error:
            # Gmail 응답·예외 원문에는 토큰이나 메일 내용이 있을 수 있다.
            label = error.code if isinstance(error, GoogleError) else type(error).__name__
            log.warning("사용자 %s: Gmail 알림 처리 실패 (%s)", user.id, label)
            with access.database.session() as session:
                watch = session.get(GmailWatch, user.id)
                if watch is not None and watch.status != "stopped" and watch.last_error != TokenExpired.code:
                    watch.status = "error"
                    watch.last_error = f"gmail_push: {label}"


def _process_mailbox(access, user, notification_id, graph):
    with access.database.session() as session:
        watch = session.get(GmailWatch, user.id)
        if watch is None or watch.status == "stopped" or watch.last_error == TokenExpired.code:
            return
    renew_watch_if_due(access, user.id)
    with access.database.session() as session:
        watch = session.get(GmailWatch, user.id)
        if watch.status == "stopped" or watch.last_error == TokenExpired.code:
            return
        cursor = watch.history_id
    if cursor is None:
        # watch의 최초 커서는 등록 경로만 정한다. 알림으로 추측해 건너뛰지 않는다.
        raise ValueError("Gmail 기록 시작 위치가 없습니다")
    if int(notification_id) <= int(cursor):
        return
    gmail = access.google.gmail(get_access_token(access, user.id))
    latest = collect_history(access, user, gmail, cursor, graph=graph)
    # 모든 페이지와 메일 읽기가 성공한 뒤에만 커서를 옮긴다. 중간 실패 때 저장된 메일은
    # 다음 알림에서 유일 키로 건너뛰고 아직 못 읽은 메일부터 이어서 처리한다.
    with access.database.session() as session:
        watch = session.get(GmailWatch, user.id)
        if watch.status != "stopped" and watch.last_error != TokenExpired.code:
            watch.history_id = str(max(int(watch.history_id), latest))
            if watch.last_error and watch.last_error.startswith("gmail_push:"):
                watch.status = "active"
                watch.last_error = None


def collect_history(access, user, gmail, cursor, *, graph=None, should_continue=lambda: True):
    """공용 푸시와 로컬 조회의 MIME·필터·중복·실행 경계. 중단되면 커서를 반환하지 않는다."""
    page_token = None
    latest = int(cursor)
    seen = set()
    while True:
        if not should_continue():
            return None
        page = access.google.list_history(gmail, cursor, page_token)
        latest = max(latest, int(page["historyId"]))
        for history in page.get("history", []):
            for added in history.get("messagesAdded", []):
                message_id = added["message"]["id"]
                if message_id in seen or _processed(access, user.id, message_id):
                    continue
                if not should_continue():
                    return None
                seen.add(message_id)
                raw = access.google.get_message(gmail, message_id)
                if not should_continue():
                    return None
                email = decode_message(raw, user.email, lambda attachment_id: access.google.get_attachment(
                    gmail, message_id, attachment_id,
                ))
                reason = _skip_reason(email, raw.get("labelIds", []))
                if not should_continue():
                    return None
                if _claim_message(access, user.id, email, history["id"], reason):
                    _run_message(access, user.id, email, graph)
        page_token = page.get("nextPageToken")
        if not page_token:
            break
    return latest if should_continue() else None


def _processed(access, user_id, message_id):
    with access.database.session() as session:
        return session.scalar(select(ProcessedMessage.id).where(
            ProcessedMessage.user_id == user_id, ProcessedMessage.gmail_message_id == message_id,
        )) is not None


def _skip_reason(email, labels):
    if email["direction"] == "out":
        return "self"
    local = email["from_addr"].partition("@")[0].casefold().replace("-", "").replace("_", "")
    if "noreply" in local or "donotreply" in local:
        return "no_reply"
    if "CATEGORY_PROMOTIONS" in labels:
        return "promotion"
    if "CATEGORY_SOCIAL" in labels:
        return "social"
    if "INBOX" not in labels or "TRASH" in labels or "SPAM" in labels:
        return "not_inbox"
    return None


def _claim_message(access, user_id, email, history_id, reason):
    try:
        with access.database.session() as session:
            session.add(ProcessedMessage(
                user_id=user_id, gmail_message_id=email["gmail_message_id"], thread_id=email["thread_id"],
                history_id=str(history_id), received_at=datetime.fromisoformat(email["received_at"]),
                status="ignored" if reason else "processing", skip_reason=reason,
            ))
            session.flush()  # 메일 ID 유일 제약을 통과한 처리자만 스레드·그래프를 만든다.
            if not reason:
                session.add(ThreadMessage(
                    user_id=user_id, thread_id=email["thread_id"], gmail_message_id=email["gmail_message_id"],
                    direction=email["direction"], from_addr=email["from_addr"], to_addrs=email["to_addrs"],
                    subject=email["subject"], body_text=email["body_text"],
                    sent_at=datetime.fromisoformat(email["received_at"]),
                ))
    except IntegrityError:
        if not _processed(access, user_id, email["gmail_message_id"]):
            raise
        return False
    return reason is None


def _run_message(access, user_id, email, graph):
    result = start_run(user_id=user_id, email=email, mode="live", database=access.database, graph=graph,
                       key_cipher=access.cipher)
    with access.database.session() as session:
        message = session.scalar(select(ProcessedMessage).where(
            ProcessedMessage.user_id == user_id,
            ProcessedMessage.gmail_message_id == email["gmail_message_id"],
        ))
        message.run_id = result["run_id"]
        message.notice = result["notice"]
        message.status = {
            "awaiting_approval": "awaiting_approval", "followup_question": "awaiting_approval",
            "ignored": "ignored", "failed": "error",
        }[result["end_reason"]]
        if result["end_reason"] == "ignored":
            message.skip_reason = "intent_ignore"
