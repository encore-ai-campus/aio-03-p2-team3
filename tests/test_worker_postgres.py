"""실제 임시 PostgreSQL에서도 장치 격리·마이그레이션·여러 연결의 경합을 확인한다."""
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import inspect

pgserver = pytest.importorskip("pgserver", reason="실제 PostgreSQL 검사는 --with pgserver==0.1.4로 실행")

from app.config import Settings
from app.db.engine import Database
from app.db.migrations import upgrade_database
from app.db.models import User
from app.main import create_app
from app.worker import service
from tests.fakes.gmail import FakeGmailGoogle
from tests import test_worker_queue as suite


@pytest.fixture
def pgweb(tmp_path, monkeypatch):
    clock = [datetime(2026, 11, 12, 4, 0, tzinfo=UTC)]
    monkeypatch.setattr(service, "utcnow", lambda: clock[0])
    with pgserver.get_server(Path(tmp_path) / "worker-pg", cleanup_mode="delete") as server:
        config = Settings(database_url=server.get_uri(), app_base_url="https://testserver",
                          session_secret="fake-session", token_encryption_key=Fernet.generate_key().decode())
        with TestClient(create_app(config, google=FakeGmailGoogle()), base_url="https://testserver") as client:
            with client.app.state.database.session() as session:
                session.add_all([User(id=n, google_sub=f"fake-sub-{n}", email=f"user{n}@example.invalid",
                                     last_login_at=clock[0]) for n in (1, 2)])
            yield client, config, clock


def test_postgres_ownership_and_duplicate_results(pgweb):
    suite.test_two_users_pair_and_own_claim_complete_are_isolated(pgweb)


def test_postgres_concurrent_claim_and_complete(pgweb):
    suite.test_concurrent_claim_and_complete_across_distinct_database_engines(pgweb)


def test_postgres_reconnection_and_late_completion(pgweb):
    suite.test_rotation_requires_new_approval_revokes_old_credentials_and_jobs(pgweb)


def test_postgres_existing_user_upgrade_preserves_default_and_data(tmp_path):
    with pgserver.get_server(Path(tmp_path) / "worker-upgrade-pg", cleanup_mode="delete") as server:
        db = Database(server.get_uri())
        try:
            with db.engine.begin() as connection:
                User.__table__.create(connection)
                connection.execute(User.__table__.insert().values(id=1, google_sub="fake-legacy-sub",
                                                                  email="legacy@example.invalid"))
                connection.exec_driver_sql("ALTER TABLE users DROP COLUMN ai_execution_mode")
            db.create_tables()
            upgrade_database(db.engine)
            with db.session() as session:
                assert session.get(User, 1).ai_execution_mode == "stored_key"
                assert session.get(User, 1).google_sub == "fake-legacy-sub"
            assert "ai_execution_mode" in {c["name"] for c in inspect(db.engine).get_columns("users")}
        finally:
            db.close()
