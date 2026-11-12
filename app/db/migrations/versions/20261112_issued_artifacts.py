"""발급 파일을 Storage 객체로 가리키는 열을 더한다(계획 10절).

trade_artifacts에 nullable `object_key`·`size_bytes`를 추가하고 `content`를 nullable로
바꿔 새 승인이 DB에 bytes를 두지 않게 한다. 기존 행의 `content`는 그대로 보존하며
backfill(app.trade.review.backfill)이 object_key를 채운다. 바이너리 열 DROP은 22절이다.
새 DB에서는 metadata.create_all이 이미 만든 열이므로 아무 것도 하지 않는다.
SQLite는 일회성 읽기 원본 경로만 남아 있어 nullable 변경 없이 열 추가만 한다.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261112_issued_artifacts"
down_revision = "20261112_company_images"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = {column["name"]: column
                for column in sa.inspect(bind).get_columns("trade_artifacts")}
    if "object_key" not in existing:
        op.add_column("trade_artifacts", sa.Column("object_key", sa.String(), nullable=True))
    if "size_bytes" not in existing:
        op.add_column("trade_artifacts", sa.Column("size_bytes", sa.Integer(), nullable=True))
    if (not existing["content"]["nullable"]) and bind.dialect.name != "sqlite":
        op.alter_column("trade_artifacts", "content", existing_type=sa.LargeBinary(), nullable=True)


def downgrade():
    raise RuntimeError("데이터를 보존하는 전진 갱신만 지원합니다. 복구에는 갱신 전 백업을 사용하세요.")
