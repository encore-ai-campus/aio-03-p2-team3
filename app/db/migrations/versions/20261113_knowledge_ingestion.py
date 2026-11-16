"""지식 문서·조항 부모·pgvector 자식. 기존 auth/storage 데이터는 변경하지 않는다."""
from alembic import op
from sqlalchemy import text

revision = "20261113_knowledge_ingestion"
down_revision = "20261112_react_worker_merge"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return  # 과거 SQLite 이전 검사. 실행 앱의 DB 설정은 PostgreSQL만 허용한다.
    from app.knowledge.repository import KnowledgeChild, KnowledgeDocument, KnowledgeParent
    for model in (KnowledgeDocument, KnowledgeParent, KnowledgeChild):
        model.__table__.create(connection, checkfirst=True)
        table = model.__tablename__
        connection.exec_driver_sql(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
        connection.exec_driver_sql(f"REVOKE ALL ON public.{table} FROM PUBLIC")
        for role in ("anon", "authenticated"):
            if connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": role}).scalar():
                connection.exec_driver_sql(f"REVOKE ALL ON public.{table} FROM {role}")


def downgrade():
    raise RuntimeError("지식 문서 원문·벡터 보존을 위해 전진 갱신만 지원합니다. 백업으로 복구하세요.")
