"""개인 PC 수집기. watch/stop·공개 수신 포트 없이 본인 Gmail history만 읽는다."""

import asyncio
import json
import logging
from threading import Event

from sqlalchemy import or_, select, update

from app.clients.gmail import GoogleError, HistoryExpired, TokenExpired
from app.config import validate_runtime
from app.db.models import GmailWatch, User
from app.services.auth import get_access_token, mark_reauth_required, utcnow
from app.services.gmail_push import _mailbox_lock, collect_history

log = logging.getLogger(__name__)
LOCAL_TOPIC = "local:history"
POLL_SECONDS = 30
TERMINAL_ERRORS = {"token_expired", "history_expired"}


def connect_local(access, user_id, now=None):
    """명시적 로그인마다 현재 위치로 시작한다. 연결 전 메일은 조회하지 않는다."""
    with _mailbox_lock(access.database, user_id):
        return _connect(access, user_id, now or utcnow())


def _connect(access, user_id, now, *, expected_generation=None):
    with access.database.session() as session:
        if expected_generation is not None:
            # 일시적 첫 조회 실패를 재시도하는 동안 로그아웃했으면 다시 켜지 않는다.
            changed = session.execute(_current_watch(user_id, expected_generation).where(
                GmailWatch.history_id.is_(None),
            ).values(last_renewed_at=now, last_error="local_connect"))
            if not changed.rowcount:
                return "stopped"
        watch = session.get(GmailWatch, user_id)
        if watch is None:
            watch = GmailWatch(user_id=user_id)
            session.add(watch)
        watch.topic = LOCAL_TOPIC
        watch.history_id = None
        watch.expiration = None
        watch.last_renewed_at = now  # 연결 세대. 중지·재연결 전 수집 결과는 적용하지 않는다.
        watch.status = "error"
        watch.last_error = "local_connect"
    try:
        history_id = access.google.get_history_id(get_access_token(access, user_id))
    except TokenExpired:
        return "error"
    except GoogleError as error:
        if _auth_failed(error):
            mark_reauth_required(access, user_id)
            return "error"
        history_id = None
        label = f"local_connect: {error.code}"
    with access.database.session() as session:
        session.execute(_current_watch(user_id, now).values(
            history_id=history_id, status="active" if history_id else "error",
            last_error=None if history_id else label,
        ))
        return session.get(GmailWatch, user_id).status


def _current_watch(user_id, generation):
    return update(GmailWatch).where(
        GmailWatch.user_id == user_id, GmailWatch.topic == LOCAL_TOPIC,
        GmailWatch.last_renewed_at == generation, GmailWatch.status != "stopped",
        or_(GmailWatch.last_error.is_(None), GmailWatch.last_error.not_in(TERMINAL_ERRORS)),
    )


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
    def __init__(self, access, *, interval=POLL_SECONDS):
        self.access = access
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
            owner = access.settings.local_owner_google_sub.strip()
            if not owner:
                return
            with access.database.session() as session:
                user = session.scalar(select(User).where(
                    User.google_sub == owner, User.last_login_at.is_not(None),
                ))
            if user is None:
                return
            with _mailbox_lock(access.database, user.id):
                self._poll_user(user)
        except Exception as error:
            # 계정·토큰·메일·예외 원문을 기록하지 않으며 다음 주기에 재시도한다.
            log.warning("로컬 Gmail 수집 실패 (%s)", type(error).__name__)

    def _poll_user(self, user):
        access = self.access
        with access.database.session() as session:
            watch = session.get(GmailWatch, user.id)
            if (watch is None or watch.topic != LOCAL_TOPIC or watch.status == "stopped"
                    or watch.last_error in TERMINAL_ERRORS or self.stopping.is_set()):
                return
            generation = watch.last_renewed_at
            cursor = watch.history_id
        if cursor is None:
            _connect(access, user.id, utcnow(), expected_generation=generation)
            return

        def active():
            if self.stopping.is_set():
                return False
            with access.database.session() as session:
                current = session.get(GmailWatch, user.id)
                owner = session.get(User, user.id)
                return (current is not None and current.topic == LOCAL_TOPIC
                        and current.last_renewed_at == generation and current.status != "stopped"
                        and current.last_error not in TERMINAL_ERRORS and owner is not None
                        and owner.google_sub == access.settings.local_owner_google_sub.strip()
                        and owner.last_login_at is not None)

        try:
            gmail = access.google.gmail(get_access_token(access, user.id))
            latest = collect_history(access, user, gmail, cursor, should_continue=active)
        except Exception as error:
            if not active():
                return
            if isinstance(error, TokenExpired) or _auth_failed(error):
                mark_reauth_required(access, user.id)
                return
            label = "history_expired" if isinstance(error, HistoryExpired) else (
                f"local_poll: {error.code if isinstance(error, GoogleError) else type(error).__name__}"
            )
            with access.database.session() as session:
                session.execute(_current_watch(user.id, generation).values(status="error", last_error=label))
            log.warning("사용자 %s: 로컬 Gmail 수집 중단/실패 (%s)", user.id, label)
            return
        if latest is not None and active():
            with access.database.session() as session:
                session.execute(_current_watch(user.id, generation).values(
                    history_id=str(latest), status="active", last_error=None,
                ))
