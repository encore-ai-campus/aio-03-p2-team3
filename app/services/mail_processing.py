"""원문 저장 뒤 제외 판정. 나머지는 기존 그래프를 그대로 실행한다."""
from datetime import datetime, UTC
import logging

from app.llm import mail_gate
from app.services.openai_keys import UserKeyAccess

log = logging.getLogger(__name__)


def process_saved(access, store, owner, message_id, *, graph=None, force=False,
                  should_continue=lambda: True):
    """호출자는 기존 사용자별 mailbox lock을 보유한다."""
    row = store.get(owner, message_id)
    if not row or not row["email"] or row["status"] in {"sent", "awaiting_approval"}:
        return
    if row["status"] != "processing" and not force:
        return
    if not store.connected(owner) or not should_continue():
        return
    stamp = store.stamp(owner)
    current = lambda: should_continue() and store.connected(owner) and store.stamp(owner) == stamp
    triage = dict(row["triage"] or {})
    if store.candidates_exist(owner, message_id):
        store.mark(owner, message_id, "awaiting_approval", {**triage, "phase": "done"})
        return
    if not force and triage.get("phase") == "graph_started":
        store.mark(owner, message_id, "needs_review", triage, "processing_interrupted")
        return
    try:
        if force:
            triage.update(phase="passed", manual=True)
        elif triage.get("phase") != "passed":
            store.mark(owner, message_id, "processing", {**triage, "phase": "deciding"})
            key = UserKeyAccess(access.database, owner, access.cipher,
                                access.settings) if access.settings else UserKeyAccess(access.database, owner, access.cipher)
            result = mail_gate.classify_email(key, row["email"], store.context(owner))
            triage.update(phase="excluded" if result.exclude else "passed", confidence=result.confidence,
                          choice=result.choice,
                          model=mail_gate.MODEL, policy_version=mail_gate.POLICY_VERSION,
                          decided_at=datetime.now(UTC).isoformat())
            if not current():
                store.mark(owner, message_id, "needs_review", triage, "connection_changed")
                return
            if result.exclude:
                store.mark(owner, message_id, "ignored", triage, "mail_excluded")
                return
        if not current():
            return
        store.mark(owner, message_id, "processing", {**triage, "phase": "graph_started"})
        # 기존 general/deal/ignore 판단·기억·성찰·초안 경로는 변경하지 않는다.
        from app.services.gmail_push import _run_message
        _run_message(access, owner, row["email"], graph)
        result = store.get(owner, message_id)
        if result:
            store.mark(owner, message_id, result["status"], {**triage, "phase": "done"},
                       result["notice"])
    except Exception as error:
        # 실패를 무관 판정으로 숨기거나 그래프에 우회 전달하지 않는다.
        store.mark(owner, message_id, "needs_review", {**triage, "phase": "failed"},
                   (getattr(error, "code", None) or "classification_failed").lower())
        log.warning("사용자 %s: 메일 처리 보류 (%s)", owner, type(error).__name__)


def resume_pending(access, store, *, graph=None):
    from app.services.gmail_push import _mailbox_lock
    # ponytail: 단일 앱 프로세스의 기존 사용자 잠금을 재사용한다. 다중 수집 프로세스는 별도 DB 임대 필요.
    for owner, message_id in store.pending():
        lock = _mailbox_lock(access.database, owner)
        if not lock.acquire(blocking=False):
            continue
        try:
            process_saved(access, store, owner, message_id, graph=graph)
        finally:
            lock.release()
