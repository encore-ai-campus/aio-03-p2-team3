from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings

# PostgreSQL 연결 풀 상한(계획 4절). 서버 프로세스가 Supabase Session pooler에
# 물고 있을 상시 연결을 제한한다. SSL은 접속 주소의 ?sslmode=require로 지정한다.
POSTGRES_POOL_SIZE = 5
POSTGRES_MAX_OVERFLOW = 10
POSTGRES_POOL_TIMEOUT_SECONDS = 30
POSTGRES_POOL_RECYCLE_SECONDS = 1800


class Database:
    """앱 DB 엔진. 운영 경로는 PostgreSQL(psycopg)만 받고, SQLite는
    일회성 데이터 이전(app.db.copy_data)과 역사적 migration 검사 경로만 쓴다."""

    def __init__(self, url: str):
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        options = {"pool_pre_ping": True}
        if url.startswith("postgresql"):
            options.update(
                pool_size=POSTGRES_POOL_SIZE,
                max_overflow=POSTGRES_MAX_OVERFLOW,
                pool_timeout=POSTGRES_POOL_TIMEOUT_SECONDS,
                pool_recycle=POSTGRES_POOL_RECYCLE_SECONDS,
            )
        elif url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
            if url in {"sqlite://", "sqlite:///:memory:"}:
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        if self.engine.dialect.name == "sqlite":
            @event.listens_for(self.engine, "connect")
            def enable_foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self._initialized = False

    def create_tables(self):
        if not self._initialized:
            from app.db.migrations import upgrade_database
            upgrade_database(self.engine)
            self._initialized = True

    @contextmanager
    def session(self):
        with self.sessions.begin() as session:
            yield session

    def close(self):
        self.engine.dispose()
        self._initialized = False


@lru_cache(maxsize=1)
def _database_for_url(url: str) -> Database:
    return Database(url)


def get_database(settings: Settings | None = None) -> Database:
    database = _database_for_url((settings or get_settings()).resolved_database_url)
    database.create_tables()
    return database
