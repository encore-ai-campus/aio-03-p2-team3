"""새 발신 초안의 입력과 소유자별 저장 규칙."""
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db.models import MailComposeDraft
from app.mail.schemas import ComposeInput, EditComposeInput
from app.mail.errors import MailError


def _view(row: MailComposeDraft) -> dict:
    return {field: getattr(row, field) for field in ("id", "recipients", "subject", "body", "revision")}


def _owned(session, owner, draft_id, *, lock=False):
    query = select(MailComposeDraft).where(MailComposeDraft.id == draft_id, MailComposeDraft.user_id == owner)
    row = session.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise MailError(404, "compose_not_found", "새 메일 초안을 찾을 수 없습니다.")
    return row


def save_draft(database, owner, draft_id, inputs: ComposeInput):
    with database.session() as session:
        session.execute(insert(MailComposeDraft).values(
            id=draft_id, user_id=owner, **inputs.model_dump(),
        ).on_conflict_do_nothing(index_elements=["id"]))
        return _view(_owned(session, owner, draft_id))


def read_draft(database, owner, draft_id):
    with database.session() as session:
        return _view(_owned(session, owner, draft_id))


def revise_draft(database, owner, draft_id, inputs: EditComposeInput):
    with database.session() as session:
        row = _owned(session, owner, draft_id, lock=True)
        if row.revision != inputs.revision:
            raise MailError(409, "compose_changed", "다른 화면에서 초안을 수정했습니다. 최신 초안을 다시 읽어 주세요.")
        for key, value in inputs.model_dump(exclude={"revision"}).items():
            setattr(row, key, value)
        row.revision += 1
        return _view(row)
