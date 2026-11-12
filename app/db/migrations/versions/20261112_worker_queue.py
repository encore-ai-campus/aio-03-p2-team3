"""개인 실행 장치와 사용자별 큐. 기존 사용자/메일/키 데이터는 보존한다."""
import sqlalchemy as sa
from alembic import op
from app.db.models import WorkerDevice, WorkerJob, WorkerPairing, WorkerRateLimit

revision = "20261112_worker_queue"
down_revision = "20261112_user_openai_keys"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if "ai_execution_mode" not in {c["name"] for c in sa.inspect(connection).get_columns("users")}:
        op.add_column("users", sa.Column("ai_execution_mode", sa.String(), nullable=False, server_default="stored_key"))
    for model in (WorkerPairing, WorkerDevice, WorkerJob, WorkerRateLimit):
        model.__table__.create(connection, checkfirst=True)


def downgrade():
    raise RuntimeError("데이터를 보존하려면 갱신 전 백업으로 복구하세요")
