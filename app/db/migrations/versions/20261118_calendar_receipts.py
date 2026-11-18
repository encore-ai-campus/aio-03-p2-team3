"""일정 등록 멱영수증 표(계획 2절). 같은 승인의 재실행을 같은 결과로 끝낸다."""
from alembic import op
from sqlalchemy import text

revision = "20261118_calendar_receipts"
down_revision = "20261118_query_indexes"
branch_labels = None
depends_on = None


def upgrade():
    from app.db.models import CalendarEventReceipt
    connection = op.get_bind()
    CalendarEventReceipt.__table__.create(connection, checkfirst=True)
    if connection.dialect.name == "postgresql":
        table = CalendarEventReceipt.__tablename__
        connection.exec_driver_sql(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        connection.exec_driver_sql(f"REVOKE ALL ON public.{table} FROM PUBLIC")
        for role in ("anon", "authenticated"):
            if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar():
                connection.exec_driver_sql(f"REVOKE ALL ON public.{table} FROM {role}")


def downgrade():
    raise RuntimeError("등록 영수증 보존을 위해 전진 갱신만 지원합니다.")
