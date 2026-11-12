"""암호화한 결과를 업무 호출자가 소비할 때까지만 전달한다. 기존 데이터 보존."""
import sqlalchemy as sa
from alembic import op

revision = "20261112_worker_delivery"
down_revision = "20261112_worker_queue"
branch_labels = None
depends_on = None


def upgrade():
    if "result_enc" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("worker_jobs")}:
        op.add_column("worker_jobs", sa.Column("result_enc", sa.Text(), nullable=True))


def downgrade():
    raise RuntimeError("데이터 복구는 갱신 전 백업을 사용하세요")
