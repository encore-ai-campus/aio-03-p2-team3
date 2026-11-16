"""Calendar 토큰과 일회성 OAuth state를 Gmail과 분리한다."""
from alembic import op
from sqlalchemy import text

revision = "20261116_calendar_oauth"
down_revision = "20261113_knowledge_ingestion"
branch_labels = None
depends_on = None


def upgrade():
    from app.db.models import CalendarOAuthAttempt, CalendarToken
    connection = op.get_bind()
    for model in (CalendarToken, CalendarOAuthAttempt):
        model.__table__.create(connection, checkfirst=True)
        if connection.dialect.name == "postgresql":
            table = model.__tablename__
            connection.exec_driver_sql(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
            connection.exec_driver_sql(f"REVOKE ALL ON public.{table} FROM PUBLIC")
            for role in ("anon", "authenticated"):
                if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar():
                    connection.exec_driver_sql(f"REVOKE ALL ON public.{table} FROM {role}")


def downgrade():
    raise RuntimeError("암호화 토큰 보존을 위해 전진 갱신만 지원합니다. 백업으로 복구하세요.")
