"""Gmail 연결도 일회성 OAuth 대기 행을 쓴다(쿠키 없는 콜백 지원)."""
from alembic import op
from sqlalchemy import Column, String, inspect, text

revision = "20261119_oauth_attempt_service"
down_revision = "20261119_inbound_context"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        existing = {column["name"] for column in inspect(connection).get_columns("calendar_oauth_attempts")}
    else:
        existing = set(connection.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'calendar_oauth_attempts'"
        )).scalars())
    if "service" not in existing:
        op.add_column("calendar_oauth_attempts",
                      Column("service", String(16), nullable=False, server_default="calendar"))


def downgrade():
    op.drop_column("calendar_oauth_attempts", "service")
