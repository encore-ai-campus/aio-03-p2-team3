"""테스트 DB는 전부 실제 PostgreSQL을 쓴다(3절).

세션마다 임베디드 PostgreSQL 인스턴스 하나를 띄우고 테스트마다 별도 데이터베이스를
만들어 지운다. CI처럼 TEST_DATABASE_URL이 지정되면 그 접속을 같은 방식으로 쓴다.
.env의 실제 LLM 키가 단위 테스트에 스며들지 않게 환경을 비운다. 기본 경로에서 외부
HTTP를 낼 수 없게 키를 비우고, 가짜 응답은 각 테스트가 명시적으로 주입한다.
"""
import os
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

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

    for name in ("OPENAI_API_KEY", "OPENAI_MODEL"):
        os.environ[name] = ""
    get_settings.cache_clear()
    yield


@pytest.fixture(scope="session")
def postgres_uri(tmp_path_factory):
    """세션 PostgreSQL 접속. 로컬은 pgserver 임베디드, CI는 TEST_DATABASE_URL."""
    configured = os.environ.get("TEST_DATABASE_URL", "").strip()
    if configured:
        yield configured
        return
    import pgserver
    with pgserver.get_server(tmp_path_factory.mktemp("pgserver"), cleanup_mode="delete") as server:
        yield server.get_uri()


@pytest.fixture(scope="session")
def schema_template(postgres_uri):
    """세션당 한 번 앱 시작과 같은 마이그레이션으로 스키마를 완성한 템플릿 DB.

    테스트 DB는 이것을 복제해 테스트마다 테이블 DDL·Alembic 체인을 다시 만들지 않는다."""
    name = f"template_{uuid4().hex}"
    with psycopg.connect(postgres_uri, autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{name}"')
    try:
        db = Database(urlunsplit(urlsplit(postgres_uri)._replace(path=f"/{name}")))
        db.create_tables()
        db.close()
        yield name
    finally:
        with psycopg.connect(postgres_uri, autocommit=True) as connection:
            connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def database_url(postgres_uri, schema_template):
    """테스트별 독립 DB. SQL 순서를 공유하지 않아 데이터가 새지 않는다.

    스키마는 세션 템플릿을 복제해 이미 완성된 상태로 시작한다(앱 시작 마이그레이션 결과와 같다)."""
    name = f"test_{uuid4().hex}"
    with psycopg.connect(postgres_uri, autocommit=True) as connection:
        connection.execute(f'CREATE DATABASE "{name}" TEMPLATE "{schema_template}"')
    parts = urlsplit(postgres_uri)
    yield urlunsplit(parts._replace(path=f"/{name}"))
    with psycopg.connect(postgres_uri, autocommit=True) as connection:
        connection.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def empty_database_url(postgres_uri):
    """스키마 없는 빈 DB. 마이그레이션·확장 설치 자체를 검사하는 테스트가 쓴다."""
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


@pytest.fixture(autouse=True)
def isolated_mail_decisions(monkeypatch):
    """Gmail 회귀는 실제 Decisions를 호출하지 않는다. 어댑터 시험은 자체 대역을 주입한다."""
    from app.llm import mail_gate
    original = mail_gate.classify_email
    monkeypatch.setattr(mail_gate, "classify_email", lambda *args, **kwargs: mail_gate.GateResult(False, 1.0))
    return original
