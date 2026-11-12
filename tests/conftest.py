"""테스트 DB는 전부 실제 PostgreSQL을 쓴다(3절).

세션마다 임베디드 PostgreSQL 인스턴스 하나를 띄우고 테스트마다 별도 데이터베이스를
만들어 지운다. CI처럼 TEST_DATABASE_URL이 지정되면 그 접속을 같은 방식으로 쓴다.
.env의 실제 LLM 키가 단위 테스트에 스며들지 않게 환경을 비운다. 기본 경로에서 외부
HTTP를 낼 수 없게 키를 비우고, 가짜 응답은 각 테스트가 명시적으로 주입한다.
"""
import os
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pgserver
import psycopg
import pytest
from sqlalchemy import text

from app.db.engine import Database
from app.db.models import User


@pytest.fixture(autouse=True, scope="session")
def isolated_llm_keys():
    """단위 테스트는 실제 LLM 키 없이만 돈다.

    load_dotenv는 이미 있는 환경값을 덮어쓰지 않으므로 빈 문자열로 채워 둔다.
    app.main import 시점에 이미 캐시된 설정도 지운다.
    """
    from app.config import get_settings
    from app.llm.client import _backend_for_settings

    for name in ("OPENAI_API_KEY", "OPENAI_MODEL"):
        os.environ[name] = ""
    get_settings.cache_clear()
    _backend_for_settings.cache_clear()
    yield


@pytest.fixture(scope="session")
def postgres_uri(tmp_path_factory):
    """세션 PostgreSQL 접속. 로컬은 pgserver 임베디드, CI는 TEST_DATABASE_URL."""
    configured = os.environ.get("TEST_DATABASE_URL", "").strip()
    if configured:
        yield configured
        return
    with pgserver.get_server(tmp_path_factory.mktemp("pgserver"), cleanup_mode="delete") as server:
        yield server.get_uri()


@pytest.fixture
def database_url(postgres_uri):
    """테스트별 독립 DB. SQL 순서를 공유하지 않아 데이터가 새지 않는다."""
    name = f"test_{uuid4().hex}"
    with psycopg.connect(postgres_uri, autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{name}"')
    parts = urlsplit(postgres_uri)
    yield urlunsplit(parts._replace(path=f"/{name}"))
    with psycopg.connect(postgres_uri, autocommit=True) as connection:
        connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def database(database_url):
    db = Database(database_url)
    db.create_tables()
    with db.session() as session:
        session.add(User(id=1, google_sub="fake-sub-1", email="demo@example.invalid"))
        # 명시적 id로 심으면 시퀀스가 그대로라 이후 save_login 사용자와 겹친다. 다음 id를 2로 맞춘다.
        session.execute(text("SELECT setval(pg_get_serial_sequence('users', 'id'), 1)"))
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
