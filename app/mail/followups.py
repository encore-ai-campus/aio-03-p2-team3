"""발송된 메일 이후의 수신 기록으로 앱 알림 상태를 갱신한다."""
from datetime import timedelta
from email.utils import parseaddr

from sqlalchemy import exists, or_, select

from app.db.models import MailFollowup, ThreadMessage, utcnow
from app.mail.errors import MailError


def _result(row, anchor):
    return {"id": row.id, "thread_id": row.thread_id, "subject": anchor.subject,
            "anchor_at": row.anchor_at.isoformat(), "due_at": row.due_at.isoformat(),
            "status": row.status}


def register(database, actor_id, thread_id, due_at, *, now=None):
    now = now or utcnow()
    with database.session() as session:
        anchor = session.scalar(select(ThreadMessage).where(
            ThreadMessage.user_id == actor_id, ThreadMessage.thread_id == thread_id,
            ThreadMessage.direction == "out",
        ).order_by(ThreadMessage.sent_at.desc(), ThreadMessage.id.desc()).limit(1).with_for_update())
        if anchor is None:
            raise MailError(409, "followup_requires_sent_mail", "수집된 발송 기록이 있는 메일을 골라 주세요.")
        where = (MailFollowup.user_id == actor_id, MailFollowup.anchor_id == anchor.id,
                 MailFollowup.due_at == due_at)
        row = session.scalar(select(MailFollowup).where(*where))
        if row is None:
            if not now < due_at <= now + timedelta(days=365):
                raise MailError(422, "followup_invalid_due", "현재부터 1년 이내의 미래 시각을 지정해 주세요.")
            row = MailFollowup(user_id=actor_id, thread_id=thread_id, anchor_id=anchor.id,
                               anchor_at=anchor.sent_at, due_at=due_at)
            session.add(row)
            session.flush()
        return _result(row, anchor)


def list_items(database, actor_id, *, due_only=False, cursor=None):
    query = (select(MailFollowup, ThreadMessage).join(ThreadMessage, ThreadMessage.id == MailFollowup.anchor_id)
             .where(MailFollowup.user_id == actor_id, ThreadMessage.user_id == actor_id))
    if due_only:
        query = query.where(MailFollowup.status == "due")
    if cursor is not None:
        query = query.where(MailFollowup.id < cursor)
    with database.session() as session:
        rows = session.execute(query.order_by(MailFollowup.id.desc()).limit(21)).all()
        return {"followups": [_result(row, anchor) for row, anchor in rows[:20]],
                "next_cursor": rows[19][0].id if len(rows) > 20 else None}


def cancel(database, actor_id, item_id):
    with database.session() as session:
        row = session.scalar(select(MailFollowup).where(MailFollowup.id == item_id,
                             MailFollowup.user_id == actor_id).with_for_update())
        if row is None:
            raise MailError(404, "followup_not_found", "후속 알림을 찾을 수 없습니다.")
        if row.status in {"pending", "due"}:
            row.status = "cancelled"
        return _result(row, session.get(ThreadMessage, row.anchor_id))


def _reply_window():
    return (
        ThreadMessage.user_id == MailFollowup.user_id,
        ThreadMessage.thread_id == MailFollowup.thread_id,
        ThreadMessage.direction == "in",
        or_(ThreadMessage.sent_at > MailFollowup.anchor_at,
            (ThreadMessage.sent_at == MailFollowup.anchor_at) & (ThreadMessage.id > MailFollowup.anchor_id)),
        ThreadMessage.sent_at <= MailFollowup.due_at,
    )


def refresh_due(database, *, now=None):
    now = now or utcnow()
    cursor = 0
    while True:
        with database.session() as session:
            rows = session.scalars(select(MailFollowup).where(
                MailFollowup.id > cursor,
                MailFollowup.status.in_(("pending", "due")),
                or_((MailFollowup.status == "pending") & (MailFollowup.due_at <= now),
                    exists(select(ThreadMessage.id).where(*_reply_window(), ThreadMessage.sent_at <= now))),
            ).order_by(MailFollowup.id).limit(100).with_for_update(skip_locked=True)).all()
            if not rows:
                return
            for row in rows:
                anchor = session.get(ThreadMessage, row.anchor_id)
                recipients = {parseaddr(value)[1].casefold() for value in anchor.to_addrs}
                senders = session.scalars(select(ThreadMessage.from_addr).where(
                    ThreadMessage.user_id == row.user_id, ThreadMessage.thread_id == row.thread_id,
                    ThreadMessage.direction == "in",
                    or_(ThreadMessage.sent_at > row.anchor_at,
                        (ThreadMessage.sent_at == row.anchor_at) & (ThreadMessage.id > row.anchor_id)),
                    ThreadMessage.sent_at <= min(now, row.due_at),
                ))
                if any(parseaddr(sender)[1].casefold() in recipients for sender in senders):
                    row.status = "replied"
                elif row.due_at <= now:
                    row.status = "due"
            cursor = rows[-1].id
