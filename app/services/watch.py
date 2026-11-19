"""Gmail 감시 등록·갱신·중지(CONTRACT 7·10절, 계획 6절).

- 로그인할 때 `register_watch()`로 등록한다.
- 로그인·알림·화면 요청과 앱 lifespan 주기 작업에서 `renew_watch_if_due()`를 부른다. 마지막 갱신이
  `WATCH_RENEW_AFTER_HOURS`(24시간)를 넘었거나 지난번 등록이 실패했으면 다시 등록한다
  (Gmail은 최소 7일마다 다시 호출해야 하고 하루 1번을 권장한다).
- 연결 해제하면 `stop_watch()`로 멈춘다. 멈춘(`stopped`) 사용자와 다시 연결이 필요한
  (`token_expired`) 사용자는 갱신하지 않는다.
- `history_id`: 처음 등록하거나 멈췄다가 다시 등록할 때만 watch 응답 값으로 정한다. 켜져 있는 감시를
  갱신할 때는 알림 처리(7)가 이어서 읽을 수 있게 그대로 둔다. 앱 로그아웃은 수집을 멈추지 않는다.
"""

from datetime import datetime, timedelta
import logging

from app.clients.gmail import GoogleError, TokenExpired, _error_label
from app.config import LIMITS
from sqlalchemy import select
from app.db.models import GmailWatch, GoogleToken
from app.services.auth import GoogleAccess, get_access_token, utcnow

log = logging.getLogger(__name__)


def watch_is_due(watch: GmailWatch | None, now: datetime) -> bool:
    if watch is None or watch.status == "stopped":
        return False
    if watch.status == "error" and watch.last_error == TokenExpired.code:
        return False
    if watch.status == "error" or watch.last_renewed_at is None:
        return True
    return now - watch.last_renewed_at >= timedelta(hours=LIMITS["WATCH_RENEW_AFTER_HOURS"])


def register_watch(access: GoogleAccess, user_id: int, now: datetime | None = None) -> str:
    """감시를 등록(또는 갱신)하고 결과 상태(`active`/`error`)를 돌려준다. 실패는 표에 남기고 예외를 내지 않는다."""
    now = now or utcnow()
    if access.polling:
        from app.services.local_gmail import connect_local
        from app.db.local_gmail import SqlMailboxStore

        return connect_local(access, user_id, SqlMailboxStore(access.database), now)
    def stamp(session):
        watch, token = session.get(GmailWatch, user_id), session.get(GoogleToken, user_id)
        return (watch.status, watch.last_renewed_at) if watch else None, token.refresh_token_enc if token else None

    with access.database.session() as session:
        started = stamp(session)
    try:
        token = get_access_token(access, user_id, now)
        response = access.google.watch(token, access.topic)
    except TokenExpired:
        return "error"  # get_access_token이 이미 token_expired로 남겼다
    except GoogleError as error:
        label = _error_label(error.__cause__ or error, include_reason=True)
        log.warning("사용자 %s: Gmail 감시 등록 실패 (%s)", user_id, label)
        with access.database.session() as session:
            session.get(GmailWatch, user_id, with_for_update=True)
            if stamp(session) != started:
                return "stopped"  # 요청 중 연결 해제/재연결된 상태를 덮지 않는다.
            watch = _watch_row(session, user_id, access.topic)
            watch.status = "error"
            watch.last_error = f"watch_failed: {label}"[:200]
        return "error"
    with access.database.session() as session:
        session.get(GmailWatch, user_id, with_for_update=True)
        if stamp(session) != started:
            return "stopped"
        watch = _watch_row(session, user_id, access.topic)
        if watch.history_id is None or watch.status == "stopped":
            watch.history_id = response.history_id
        watch.topic = access.topic
        watch.expiration = response.expiration
        watch.last_renewed_at = now
        watch.status = "active"
        watch.last_error = None
    return "active"


def renew_watch_if_due(access: GoogleAccess, user_id: int, now: datetime | None = None) -> bool:
    """갱신할 때가 됐으면 다시 등록한다. 다시 등록을 시도했으면 True."""
    if access.polling:
        return False  # 폴링 수집은 수집기가 주기적으로 확인하므로 화면 방문 갱신이 없다
    now = now or utcnow()
    with access.database.session() as session:
        due = watch_is_due(session.get(GmailWatch, user_id), now)
    if due:
        register_watch(access, user_id, now)
    return due


def renew_connected_watches(access: GoogleAccess) -> None:
    """화면 방문 없이 연결된 서버 계정만 갱신한다. 중지 계정은 켜지 않는다."""
    if access.polling:
        return  # 폴링 수집은 수집기가 주기적으로 확인하므로 배경 갱신이 없다
    with access.database.session() as session:
        owners = list(session.scalars(select(GmailWatch.user_id).join(
            GoogleToken, GoogleToken.user_id == GmailWatch.user_id,
        ).where(GmailWatch.topic == access.topic, GmailWatch.status != "stopped",
                GoogleToken.refresh_token_enc.is_not(None), GoogleToken.refresh_token_enc != "")))
    for owner in owners:
        renew_watch_if_due(access, owner)


def stop_watch(access: GoogleAccess, user_id: int) -> None:
    """감시를 멈춘다. Google 호출이 실패해도 표는 `stopped`로 바꾼다(남은 알림은 7이 무시)."""
    if access.polling:
        with access.database.session() as session:
            watch = session.get(GmailWatch, user_id)
            if watch is not None:
                watch.status = "stopped"
                watch.last_error = None
        return
    try:
        access.google.stop(get_access_token(access, user_id))
    except GoogleError as error:
        label = _error_label(error.__cause__ or error, include_reason=True)
        log.warning("사용자 %s: Gmail 감시 중지 호출 실패 (%s)", user_id, label)
    with access.database.session() as session:
        watch = session.get(GmailWatch, user_id)
        if watch is not None:
            watch.status = "stopped"
            watch.last_error = None


def _watch_row(session, user_id: int, topic: str) -> GmailWatch:
    watch = session.get(GmailWatch, user_id)
    if watch is None:
        watch = GmailWatch(user_id=user_id, topic=topic, status="stopped")
        session.add(watch)
    return watch
