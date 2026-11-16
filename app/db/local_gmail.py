"""로컬 Gmail 대상 조회와 연결 세대별 조건부 갱신. ORM은 이 경계 안에 둔다."""
from sqlalchemy import or_, select, update

from app.db.models import GmailWatch, GoogleToken, User
from app.services.local_gmail import LOCAL_TOPIC, TERMINAL_ERRORS, Mailbox


def _connected():
    return select(User.id, User.email).join(GoogleToken, GoogleToken.user_id == User.id).where(
        GoogleToken.refresh_token_enc.is_not(None), GoogleToken.refresh_token_enc != "",
    )


def _eligible():
    return _connected().add_columns(GmailWatch.history_id, GmailWatch.last_renewed_at).join(
        GmailWatch, GmailWatch.user_id == User.id,
    ).where(GmailWatch.topic == LOCAL_TOPIC, GmailWatch.status.in_({"active", "error"}),
            or_(GmailWatch.last_error.is_(None), GmailWatch.last_error.not_in(TERMINAL_ERRORS)))


def _current(mailbox):
    return update(GmailWatch).where(
        GmailWatch.user_id == mailbox.id, GmailWatch.last_renewed_at == mailbox.generation,
        GmailWatch.user_id.in_(_eligible().with_only_columns(User.id)),
    )


class SqlMailboxStore:
    def __init__(self, database):
        self.database = database

    def list(self) -> list[Mailbox]:
        with self.database.session() as session:
            return [Mailbox(*row) for row in session.execute(_eligible().order_by(User.id))]

    def current(self, user_id: int) -> Mailbox | None:
        with self.database.session() as session:
            row = session.execute(_eligible().where(User.id == user_id)).first()
            return Mailbox(*row) if row else None

    def begin(self, user_id, now, *, expected=None):
        with self.database.session() as session:
            if expected is not None:
                changed = session.execute(_current(expected).where(GmailWatch.history_id.is_(None)).values(
                    last_renewed_at=now, status="error", last_error="local_connect",
                ))
                return Mailbox(user_id, expected.email, None, now) if changed.rowcount else None
            user = session.execute(_connected().where(User.id == user_id)).first()
            if user is None:
                return None
            watch = session.get(GmailWatch, user_id)
            if watch is None:
                watch = GmailWatch(user_id=user_id)
                session.add(watch)
            watch.topic, watch.history_id, watch.expiration = LOCAL_TOPIC, None, None
            watch.last_renewed_at, watch.status, watch.last_error = now, "error", "local_connect"
            return Mailbox(user_id, user.email, None, now)

    def advance(self, mailbox, cursor):
        with self.database.session() as session:
            return bool(session.execute(_current(mailbox).values(
                history_id=str(cursor), status="active", last_error=None,
            )).rowcount)

    def fail(self, mailbox, label, *, reauth=False):
        with self.database.session() as session:
            changed = session.execute(_current(mailbox).values(status="error", last_error=label))
            if changed.rowcount and reauth:
                token = session.get(GoogleToken, mailbox.id)
                token.access_token_enc = token.refresh_token_enc = token.expires_at = None
            return bool(changed.rowcount)
