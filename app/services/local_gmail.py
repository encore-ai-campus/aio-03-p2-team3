"""연결된 사용자별 로컬 Gmail 수집. SQL·ORM은 주입한 Store가 담당한다."""
import asyncio
from dataclasses import dataclass
from datetime import datetime
import json
import logging
from threading import Event
from typing import Protocol

from app.clients.gmail import GoogleError, HistoryExpired, TokenExpired
from app.config import validate_runtime
from app.services.auth import get_access_token, utcnow
from app.services.gmail_push import _mailbox_lock, collect_history

log = logging.getLogger(__name__)
LOCAL_TOPIC = "local:history"
POLL_SECONDS = 30
TERMINAL_ERRORS = {"token_expired", "history_expired"}


@dataclass(frozen=True)
class Mailbox:
    id: int
    email: str
    cursor: str | None
    generation: datetime | None


class MailboxStore(Protocol):
    def list(self) -> list[Mailbox]: ...
    def current(self, user_id: int) -> Mailbox | None: ...
    def begin(self, user_id: int, now: datetime, *, expected: Mailbox | None = None) -> Mailbox | None: ...
    def advance(self, mailbox: Mailbox, cursor: str) -> bool: ...
    def fail(self, mailbox: Mailbox, label: str, *, reauth: bool = False) -> bool: ...


def connect_local(access, user_id, store: MailboxStore, now=None):
    """명시적인 연결마다 현재 위치로 시작한다. 연결 전 메일은 조회하지 않는다."""
    with _mailbox_lock(access.database, user_id):
        return _connect(access, user_id, store, now or utcnow())


def _connect(access, user_id, store, now, *, expected=None):
    mailbox = store.begin(user_id, now, expected=expected)
    if mailbox is None:
        return "stopped"
    try:
        history_id = access.google.get_history_id(get_access_token(access, user_id))
    except TokenExpired:
        return "error"
    except GoogleError as error:
        reauth = _auth_failed(error)
        store.fail(mailbox, "token_expired" if reauth else f"local_connect: {error.code}", reauth=reauth)
        return "error"
    if history_id:
        return "active" if store.advance(mailbox, history_id) else "stopped"
    store.fail(mailbox, "local_connect")
    return "error"


def _auth_failed(error):
    cause = error.__cause__
    status = getattr(getattr(cause, "resp", None), "status", None)
    if status == 403:
        # Gmail은 일시적 사용량 제한도 403으로 돌려준다. 그때 토큰을 폐기하지 않는다.
        try:
            reasons = json.loads(cause.content)["error"]["errors"]
            if any(isinstance(entry, dict) and entry.get("reason") in {
                "rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded", "quotaExceeded",
            } for entry in reasons):
                return False
        except (AttributeError, ValueError, TypeError, KeyError):
            pass
    return status in {401, 403}


class LocalGmailCollector:
    def __init__(self, access, store: MailboxStore, *, interval=POLL_SECONDS):
        self.access, self.store = access, store
        self.interval = interval
        self.stopping = Event()
        self.wakeup = asyncio.Event()

    def stop(self):
        self.stopping.set()
        self.wakeup.set()

    async def run(self):
        # to_thread는 전용 실행기의 실제 리스너 ContextVar도 이어받는다.
        while not self.stopping.is_set():
            await asyncio.to_thread(self.poll_once)
            if self.stopping.is_set():
                break
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=self.interval)
            except TimeoutError:
                pass

    def poll_once(self):
        access = self.access
        if not access.local_mode or self.stopping.is_set():
            return
        try:
            validate_runtime(access.settings)
            mailboxes = self.store.list()
        except Exception as error:
            log.warning("로컬 Gmail 대상 조회 실패 (%s)", type(error).__name__)
            return
        # ponytail: 한 프로세스에서 순차 수집한다. 여러 PC 수집이 필요해지면 DB 임대를 추가한다.
        for mailbox in mailboxes:
            if self.stopping.is_set():
                break
            try:
                with _mailbox_lock(access.database, mailbox.id):
                    current = self.store.current(mailbox.id)
                    if current is not None:
                        self._poll_user(current)
            except Exception as error:
                # 한 계정의 실패가 다음 계정 수집을 막지 않는다. 예외 원문은 기록하지 않는다.
                log.warning("사용자 %s: 로컬 Gmail 수집 실패 (%s)", mailbox.id, type(error).__name__)

    def _poll_user(self, mailbox):
        access = self.access
        if self.stopping.is_set():
            return
        if mailbox.cursor is None:
            _connect(access, mailbox.id, self.store, utcnow(), expected=mailbox)
            return

        def active():
            return not self.stopping.is_set() and self.store.current(mailbox.id) == mailbox

        try:
            if not active():
                return
            gmail = access.google.gmail(get_access_token(access, mailbox.id))
            latest = collect_history(access, mailbox, gmail, mailbox.cursor, should_continue=active)
        except Exception as error:
            if not active():
                return
            reauth = isinstance(error, TokenExpired) or _auth_failed(error)
            label = "token_expired" if reauth else "history_expired" if isinstance(error, HistoryExpired) else (
                f"local_poll: {error.code if isinstance(error, GoogleError) else type(error).__name__}"
            )
            self.store.fail(mailbox, label, reauth=reauth)
            log.warning("사용자 %s: 로컬 Gmail 수집 중단/실패 (%s)", mailbox.id, label)
            return
        if latest is not None and active():
            self.store.advance(mailbox, str(latest))
