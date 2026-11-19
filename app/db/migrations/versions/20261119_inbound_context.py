"""수신 답장 근거와 문서함 계약 연결을 준비한다."""
from alembic import op
from sqlalchemy import Column, JSON, inspect

revision = "20261119_inbound_context"
down_revision = "20261119_chat_mail"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        existing = {column["name"] for column in inspect(connection).get_columns("processed_messages")}
        if "inbound_context" not in existing:
            op.add_column("processed_messages", Column("inbound_context", JSON))
        return
    connection.exec_driver_sql("""
        ALTER TABLE public.knowledge_documents ADD COLUMN IF NOT EXISTS counterparty_id integer
            REFERENCES public.counterparties(id) ON DELETE SET NULL
    """)
    connection.exec_driver_sql("""
        CREATE INDEX IF NOT EXISTS ix_knowledge_documents_counterparty_id
            ON public.knowledge_documents(counterparty_id)
    """)
    connection.exec_driver_sql("""
        CREATE INDEX IF NOT EXISTS ix_knowledge_chunks_fts ON public.knowledge_chunks
            USING gin (to_tsvector('simple'::regconfig, text))
    """)
    connection.exec_driver_sql("""
        ALTER TABLE public.processed_messages ADD COLUMN IF NOT EXISTS inbound_context jsonb
    """)


def downgrade():
    raise RuntimeError("계약서 연결과 수신 근거 보존을 위해 전진 갱신만 지원합니다.")
