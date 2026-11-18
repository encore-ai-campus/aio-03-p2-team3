"""자주 읽는 조회 경로의 인덱스 보강(메일함·작업현황·실행 기록·문서 목록·PC 큐·문서함).

새 데이터베이스는 시작 시 create_all이 app/db/models.py·app/knowledge/repository.py의 같은
인덱스를 이미 만들므로 if_not_exists로 통과하고, 기존 운영 DB에서는 이 리비전이 채운다.
정의 원본은 모델 파일이고 여기는 이름·표·열을 같게 유지한다.
"""
from alembic import op
from sqlalchemy import text

revision = "20261118_query_indexes"
down_revision = "20261118_master_agent"
branch_labels = None
depends_on = None

RECOVERY_WHERE = "status = 'processing' AND triage IS NOT NULL"

INDEXES = [
    # (인덱스 이름, 표, 열) — 모델 __table_args__와 같은 순서다.
    ("ix_thread_messages_user_gmail", "thread_messages", ["user_id", "gmail_message_id"]),
    ("ix_thread_messages_user_thread_sent", "thread_messages", ["user_id", "thread_id", "sent_at"]),
    ("ix_processed_messages_user_thread", "processed_messages", ["user_id", "thread_id", "id"]),
    ("ix_reply_candidates_user_thread", "reply_candidates", ["user_id", "thread_id"]),
    ("ix_reply_candidates_user_status", "reply_candidates", ["user_id", "status"]),
    ("ix_runs_user_started", "runs", ["user_id", "started_at"]),
    ("ix_trade_documents_user_kind_id", "trade_documents", ["user_id", "doc_kind", "id"]),
    ("ix_trade_documents_user_created", "trade_documents", ["user_id", "created_at"]),
    ("ix_counterparty_history_user_email_sent", "counterparty_history",
     ["user_id", "counterparty_email", "sent_at"]),
    ("ix_worker_jobs_user_status", "worker_jobs", ["user_id", "status"]),
    ("ix_file_assets_object_key", "file_assets", ["object_key"]),
    ("ix_trade_artifacts_object_key", "trade_artifacts", ["object_key"]),
]


def upgrade():
    postgresql = op.get_bind().dialect.name == "postgresql"
    indexes = list(INDEXES)
    if postgresql:
        # knowledge_* 표는 PostgreSQL 전용이다(migrations/__init__.py create_all과 같은 조건).
        indexes.append(("ix_knowledge_documents_user_created", "knowledge_documents",
                        ["user_id", "created_at"]))
    for name, table, columns in indexes:
        op.create_index(name, table, columns, if_not_exists=True)
    # 시작 복구 pending()용 부분 인덱스: 처리 중이면서 분류 결과가 있는 행만 골라 읽는다.
    where = {"postgresql_where": text(RECOVERY_WHERE)} if postgresql else {"sqlite_where": text(RECOVERY_WHERE)}
    op.create_index("ix_processed_messages_recovery", "processed_messages", ["id"],
                    if_not_exists=True, **where)


def downgrade():
    raise RuntimeError("인덱스 제거는 별도 리비전에서만 합니다.")
