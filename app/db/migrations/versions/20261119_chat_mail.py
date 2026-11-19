"""비공개 채팅의 새 메일 초안과 후속 업무 저장."""
from alembic import op
from sqlalchemy import text

revision = "20261119_chat_mail"
down_revision = "20261118_calendar_receipts"
branch_labels = None
depends_on = None


def upgrade():
    from app.db.models import MailComposeDraft, MailFollowup

    connection = op.get_bind()
    for model in (MailComposeDraft, MailFollowup):
        model.__table__.create(connection, checkfirst=True)
        if connection.dialect.name != "postgresql":
            continue
        table = model.__tablename__
        connection.exec_driver_sql(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        connection.exec_driver_sql(f"REVOKE ALL ON public.{table} FROM PUBLIC")
        for role in ("anon", "authenticated"):
            if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar():
                connection.exec_driver_sql(f"REVOKE ALL ON public.{table} FROM {role}")


def downgrade():
    raise RuntimeError("사용자 초안의 보존을 위해 전진 갱신만 지원합니다.")
