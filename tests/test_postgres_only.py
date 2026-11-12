"""앱 DB PostgreSQL 전용 전환(계획 4절): 설정 거부·풀 상한·migration의 스키마 경계.

기존 DB의 데이터 보존 갱신·재실행 회귀는 tests/test_trade_upgrade.py가 PostgreSQL로 이미
담당하므로 여기서는 빈 DB 생성, 스키마 경계, 재실행 무해성만 본다.
"""
import pytest
from sqlalchemy import inspect

from app.config import Settings
from app.db.engine import (POSTGRES_MAX_OVERFLOW, POSTGRES_POOL_SIZE, Database, get_database)
from app.db.migrations import upgrade_database


@pytest.mark.parametrize("url", ["", "   ", "sqlite:///tmp/legacy.db", "sqlite://", "mysql://user@host/db"])
def test_non_postgres_database_url_is_rejected_without_sqlite_fallback(url, tmp_path):
    with pytest.raises(ValueError, match="DATABASE_URL"):
        Settings(database_url=url).resolved_database_url
    # SQLite 자동 fallback이 사라졌다: local.sqlite3 같은 파일을 만들지 않는다.
    assert list(tmp_path.iterdir()) == []


def test_get_database_rejects_non_postgres_url():
    with pytest.raises(ValueError, match="PostgreSQL"):
        get_database(Settings(database_url="sqlite:///legacy.sqlite3"))


def test_postgres_url_schemes_are_accepted():
    assert Settings(database_url="postgres://u:p@h:5432/db").resolved_database_url.startswith("postgres://")
    engine = Database("postgresql://u:p@h/db").engine
    assert engine.dialect.name == "postgresql" and engine.dialect.driver == "psycopg"


def test_postgres_engine_pool_is_bounded(database_url):
    engine = Database(database_url).engine
    assert engine.dialect.name == "postgresql"
    assert engine.pool.size() == POSTGRES_POOL_SIZE
    assert engine.pool._max_overflow == POSTGRES_MAX_OVERFLOW


def test_upgrade_targets_public_schema_and_keeps_supabase_schemas(database_url):
    db = Database(database_url)
    with db.engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA auth")
        connection.exec_driver_sql("CREATE TABLE auth.users (id integer PRIMARY KEY, mark text)")
        connection.exec_driver_sql("INSERT INTO auth.users VALUES (1, 'supabase-auth')")
        connection.exec_driver_sql("CREATE SCHEMA storage")
        connection.exec_driver_sql("CREATE TABLE storage.buckets (id text PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO storage.buckets VALUES ('trade-files')")
    upgrade_database(db.engine)  # 빈 DB: 앱 표와 리비전 표를 만든다.
    upgrade_database(db.engine)  # 재실행해도 데이터·스키마가 같다.
    inspector = inspect(db.engine)
    public_tables = set(inspector.get_table_names(schema="public"))
    assert {"users", "runs", "trade_documents", "trade_proposals", "alembic_version"} <= public_tables
    assert inspector.get_table_names(schema="auth") == ["users"]
    assert inspector.get_table_names(schema="storage") == ["buckets"]
    with db.engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT mark FROM auth.users").scalar() == "supabase-auth"
        assert connection.exec_driver_sql("SELECT id FROM storage.buckets").scalar() == "trade-files"
        assert connection.exec_driver_sql(
            "SELECT version_num FROM public.alembic_version").scalar() == "20261112_supabase_users"
        assert connection.exec_driver_sql(
            "SELECT attname FROM pg_attribute WHERE attrelid = 'public.users'::regclass"
            " AND attname = 'supabase_uid'").scalar() == "supabase_uid"
    db.close()
