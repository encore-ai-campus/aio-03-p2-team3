"""검토 제안이 참조할 기존 문서의 현재 버전을 보존한다. 새 표는 metadata가 생성한다."""
from alembic import op

revision = "20261111_trade_reviews"
down_revision = "20261111_trade_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""INSERT INTO trade_document_versions (document_id,revision,user_id,payload,created_at)
        SELECT d.id,d.revision,d.user_id,d.draft,d.created_at FROM trade_documents d
        WHERE NOT EXISTS (SELECT 1 FROM trade_document_versions v
                          WHERE v.document_id=d.id AND v.revision=d.revision)""")


def downgrade():
    raise RuntimeError("확정 문서와 승인 기록을 보존하려면 갱신 전 백업으로 복구하세요")
