"""메일 사전 제외 결과. 기존 메일은 재분류하지 않는다."""
from alembic import op
import sqlalchemy as sa

revision = "20261116_mail_triage"
down_revision = "20261116_calendar_oauth"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("processed_messages")}
    if "triage" not in columns:
        op.add_column("processed_messages", sa.Column("triage", sa.JSON(), nullable=True))


def downgrade():
    raise RuntimeError("메일 분류 결과 보존을 위해 전진 갱신만 지원합니다.")
