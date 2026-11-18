"""대화 소유권·화면 상태. 그래프 체크포인트는 공식 saver가 관리한다."""
from alembic import op
from sqlalchemy import text

revision = "20261118_master_agent"
down_revision = "20261116_mail_triage"
branch_labels = None
depends_on = None


def upgrade():
    from app.db.agent import AgentConversation
    connection = op.get_bind()
    AgentConversation.__table__.create(connection, checkfirst=True)
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("ALTER TABLE public.agent_conversations ENABLE ROW LEVEL SECURITY")
        connection.exec_driver_sql("REVOKE ALL ON public.agent_conversations FROM PUBLIC")
        for role in ("anon", "authenticated"):
            if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar():
                connection.exec_driver_sql(f"REVOKE ALL ON public.agent_conversations FROM {role}")


def downgrade():
    raise RuntimeError("대화 보존을 위해 전진 갱신만 지원합니다.")
