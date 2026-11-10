from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.db.models import Base, ProcessedMessage, RunEvent, User


def test_contract_tables_and_postgres_jsonb(database):
    assert set(inspect(database.engine).get_table_names()) == {
        "users", "google_tokens", "gmail_watches", "processed_messages", "thread_messages",
        "thread_memory", "reply_candidates", "approvals", "deal_terms", "quotes",
        "user_preferences", "company_profiles", "price_list_items", "counterparty_history",
        "runs", "run_events",
    }
    ddl = str(CreateTable(RunEvent.__table__).compile(dialect=postgresql.dialect()))
    assert "JSONB" in ddl


def test_deduplication_is_per_user(database):
    with database.session() as session:
        session.add(User(id=2, google_sub="fake-sub-2", email="other@example.invalid"))
    for user_id in [1, 2]:
        with database.session() as session:
            session.add(ProcessedMessage(user_id=user_id, gmail_message_id="same-id", thread_id="thread"))
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(ProcessedMessage(user_id=1, gmail_message_id="same-id", thread_id="thread"))


def test_timezone_round_trip_and_session_factory_reuse(database):
    sessions = database.sessions
    with database.session() as session:
        user = session.scalar(select(User).where(User.id == 1))
        user.last_login_at = datetime(2026, 11, 9, tzinfo=UTC)
    with database.session() as session:
        user = session.scalar(select(User).where(User.id == 1))
        assert user.last_login_at == datetime(2026, 11, 9, tzinfo=UTC)
    assert database.sessions is sessions
