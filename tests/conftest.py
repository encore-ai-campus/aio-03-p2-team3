import pytest

from app.db.engine import Database
from app.db.models import User


@pytest.fixture
def database():
    db = Database("sqlite://")
    db.create_tables()
    with db.session() as session:
        session.add(User(id=1, google_sub="fake-sub-1", email="demo@example.invalid"))
    yield db
    db.close()


@pytest.fixture
def email():
    return {
        "gmail_message_id": "fake-message", "thread_id": "fake-thread", "rfc_message_id": None,
        "from_addr": "sender@example.invalid", "from_name": None,
        "to_addrs": ["demo@example.invalid"], "subject": "가상 문의",
        "body_text": "테스트용 가상 메일입니다.", "received_at": "2026-11-09T00:00:00+00:00",
        "direction": "in",
    }
