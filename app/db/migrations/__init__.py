"""기존 데이터베이스를 보존하며 명시적인 Alembic 리비전을 적용한다."""
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.db.models import Base


def upgrade_database(engine) -> None:
    configuration = Config()
    configuration.set_main_option("script_location", str(Path(__file__).parent))
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            # 여러 웹 프로세스가 동시에 시작해도 스키마 갱신은 하나씩 수행한다.
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(2026111101)")
            # 표 이름이 스키마로 한정돼 있지 않으므로 만들·고칠 대상을 public으로 고정한다.
            # Supabase의 auth·storage 스키마를 실수로 건드리지 않게 하는 방어다(계획 4절).
            connection.exec_driver_sql("SET LOCAL search_path TO public")
            # vector 형식은 create_all보다 먼저 준비해야 한다. Supabase의 기존 extensions
            # 스키마 설치도 존중하고, 새 설치만 public에 둔다.
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            vector_schema = connection.exec_driver_sql(
                "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace "
                "WHERE e.extname='vector'").scalar_one()
            quoted = connection.dialect.identifier_preparer.quote(vector_schema)
            connection.exec_driver_sql(f"SET LOCAL search_path TO public, {quoted}")
        elif engine.dialect.name == "sqlite":
            # SQLite의 지연 BEGIN 이전에 DDL까지 같은 트랜잭션으로 묶는다.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        from app.knowledge import repository  # 새 도메인 표 등록. operations는 ORM에 의존하지 않는다.
        tables = list(Base.metadata.sorted_tables)
        if engine.dialect.name == "sqlite":
            # 과거 SQLite 이전/마이그레이션 검사 경로. 지식 문서 저장은 PostgreSQL 전용이다.
            tables = [table for table in tables if not table.name.startswith("knowledge_")]
        Base.metadata.create_all(connection, tables=tables)
        configuration.attributes["connection"] = connection
        command.upgrade(configuration, "head")
