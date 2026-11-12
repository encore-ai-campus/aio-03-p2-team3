"""로컬 소켓·실제 .env 로더·검증된 로그인·모의 OpenAI HTTP로 키 경계를 확인한다."""
from contextlib import contextmanager
from base64 import b64encode
from dataclasses import replace
import hashlib
import json
import os
import socket
import sys

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
import pytest
from sqlalchemy import event, select

from app.config import Settings, get_settings, local_listener, validate_runtime
from app.db.models import RunEvent, User, UserOpenAIKey
from app.graph.run import start_run
from app.llm import client as llm
from app.main import create_app
from app.services.openai_keys import delete_key, key_registered, save_key, user_openai
from tests.fakes.google import FakeGoogle, fake_login
from tests.fakes.llm import FakeLLM
from tests.test_auth import sign_in
from tests.test_openai_keys import sdk  # 실제 LangChain/OpenAI SDK와 MockTransport fixture


@contextmanager
def listener(host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        sock.listen(16)
        with local_listener(sock):
            yield sock


def login(client, settings, user_id):
    data = b64encode(json.dumps({"user_id": user_id}).encode())
    client.cookies.clear()
    client.cookies.set("gq_session", TimestampSigner(settings.session_secret).sign(data).decode())
    return client.get("/api/session").json()["csrf_token"]


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    # load_dotenv가 실제로 변경하는 환경까지 시험 뒤 복원한다.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    for name in [*(name.upper() for name in Settings.__dataclass_fields__),
                 "RENDER", "RENDER_SERVICE_ID", "RENDER_EXTERNAL_URL", "PORT"]:
        os.environ.pop(name, None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def local_web(tmp_path, database_url, sdk):
    env = tmp_path / ".env"
    env.write_text("\n".join([
        "AI_RUNTIME=local", "LOCAL_OWNER_GOOGLE_SUB=fake-sub-1", "OPENAI_API_KEY=fake-local-private-key",
        f"DATABASE_URL={database_url}", "SESSION_SECRET=fake-session-secret",
        f"TOKEN_ENCRYPTION_KEY={Fernet.generate_key().decode()}",
        "GOOGLE_OAUTH_CLIENT_ID=fake-client", "GOOGLE_OAUTH_CLIENT_SECRET=fake-secret",
        "GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/auth/google/callback",
        "GMAIL_PUBSUB_TOPIC=projects/fake/topics/fake",
    ]))
    settings = get_settings(str(env))
    google = FakeGoogle()
    with listener(), TestClient(create_app(settings, google=google), base_url="http://127.0.0.1") as client:
        assert sign_in(client).status_code == 303
        google.logins.append(fake_login(sub="fake-sub-2", email="other@example.invalid"))
        assert sign_in(client).status_code == 303
        login(client, settings, 1)
        yield client, settings


def test_real_dotenv_loader_defaults_server_and_does_not_load_environment_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=fake-ignored-environment-key\nAI_RUNTIME=\n")
    settings = get_settings(str(env))
    assert settings.ai_runtime == "server" and settings.openai_api_key == ""
    env.write_text("AI_RUNTIME=local\nLOCAL_OWNER_GOOGLE_SUB=fake-owner\nOPENAI_API_KEY=fake-local\n")
    os.environ.pop("AI_RUNTIME", None)
    os.environ.pop("OPENAI_API_KEY", None)
    get_settings.cache_clear()
    settings = get_settings(str(env))
    assert settings.ai_runtime == "local" and settings.openai_api_key == "fake-local"
    assert settings.local_owner_google_sub == "fake-owner"
    assert "fake-local" not in repr(settings) and "fake-owner" not in repr(settings)


def test_invalid_runtime_is_rejected_without_echoing_input():
    with pytest.raises(ValueError, match="AI_RUNTIME") as error:
        Settings(ai_runtime="fake-secret-invalid-mode")
    assert "fake-secret" not in str(error.value)


@pytest.mark.parametrize("base_url", ["", "http://localhost:8000", "http://127.0.0.1:8000"])
def test_public_entry_rejects_local_even_with_loopback_app_base_url(base_url):
    with pytest.raises(ValueError, match="app.local"):
        create_app(Settings(ai_runtime="local", app_base_url=base_url))


@pytest.mark.parametrize("variable", ["RENDER", "RENDER_SERVICE_ID", "RENDER_EXTERNAL_URL", "PORT"])
def test_hosted_execution_rejected_even_with_local_listener(monkeypatch, variable):
    monkeypatch.setenv(variable, "fake-hosted-marker")
    with listener(), pytest.raises(ValueError, match="공용 실행"):
        create_app(Settings(ai_runtime="local"))


def test_public_or_closed_socket_is_not_local_authorization():
    with listener("0.0.0.0"), pytest.raises(ValueError, match="app.local"):
        validate_runtime(Settings(ai_runtime="local"))
    with listener() as sock:
        sock.close()
        with pytest.raises(ValueError, match="app.local"):
            validate_runtime(Settings(ai_runtime="local"))


def test_launcher_passes_actual_loopback_socket_to_uvicorn(monkeypatch):
    from app import local

    monkeypatch.setattr(sys, "argv", ["app.local", "--port", "0"])
    monkeypatch.setattr(local, "get_settings", lambda: Settings(ai_runtime="local"))
    captured = []

    def run(server, sockets):
        assert server.config.host == "127.0.0.1" and server.config.proxy_headers is False
        assert len(sockets) == 1 and sockets[0].getsockname()[0] == "127.0.0.1"
        validate_runtime(Settings(ai_runtime="local"))
        captured.append(True)

    monkeypatch.setattr(local.uvicorn.Server, "run", run)
    local.main()
    assert captured == [True]
    with pytest.raises(ValueError):
        validate_runtime(Settings(ai_runtime="local"))


def test_verified_owner_uses_dotenv_key_for_mail_without_db_key_access(local_web, sdk, email):
    client, settings = local_web
    database = client.app.state.database
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(database.engine, "before_cursor_execute", capture)
    try:
        # 메일 진입점도 실제 설정을 읽으며 상태·도구에는 키를 전달하지 않는다.
        get_settings.cache_clear()
        result = start_run(user_id=1, email=email, database=database)
        assert result["end_reason"] == "awaiting_approval"
        assert len(sdk) == 2 and all(auth == "Bearer fake-local-private-key" for auth, _ in sdk)
        assert not any("user_openai_keys" in statement.lower() for statement in statements)
    finally:
        event.remove(database.engine, "before_cursor_execute", capture)
    with database.session() as session:
        assert list(session.scalars(select(UserOpenAIKey))) == []
        details = repr([row.detail for row in session.scalars(select(RunEvent))])
        assert "fake-local-private-key" not in details
    assert "fake-local-private-key" not in repr(result)


@pytest.mark.parametrize("kind", ["pi", "po", "ci", "pl"])
def test_four_document_http_paths_use_local_owner_key_only(local_web, sdk, kind):
    client, settings = local_web
    payload = {"text": "가상 문서"}
    if kind == "ci":
        payload.update(source_pi_id=1, source_revision=1)
    client.headers["X-CSRF-Token"] = client.get("/api/session").json()["csrf_token"]
    response = client.post(f"/api/trade/{kind}/extract", json=payload)
    assert sdk and all(auth == "Bearer fake-local-private-key" for auth, _ in sdk), response.text
    assert "fake-local-private-key" not in response.text
    before = len(sdk)
    login(client, settings, 2)
    client.headers["X-CSRF-Token"] = client.get("/api/session").json()["csrf_token"]
    response = client.post(f"/api/trade/{kind}/extract", json=payload)
    assert response.status_code == 403 and response.json()["error"]["code"] == "LOCAL_OWNER_MISMATCH"
    assert len(sdk) == before


@pytest.mark.parametrize("changes,user_id,code", [
    ({"local_owner_google_sub": ""}, 1, "LOCAL_OWNER_REQUIRED"),
    ({"openai_api_key": ""}, 1, "LOCAL_KEY_REQUIRED"),
    ({}, 2, "LOCAL_OWNER_MISMATCH"),
    ({}, 9999, "LOCAL_OWNER_MISMATCH"),
])
def test_missing_owner_key_or_wrong_user_blocks_without_db_fallback(local_web, sdk, changes, user_id, code):
    client, settings = local_web
    database = client.app.state.database
    # 이전 서버 모드 DB 키가 있더라도 로컬 모드에서는 절대로 대체하지 않는다.
    with database.session() as session:
        session.add(UserOpenAIKey(user_id=1, api_key_enc="fake-unreadable-db-key"))
    with user_openai(database, user_id, settings=replace(settings, **changes)) as access:
        with pytest.raises(llm.OpenAIKeyError) as error:
            llm.get_backend()
        assert error.value.code == code and access.issue is error.value
    assert sdk == []


def test_unverified_subject_and_scope_outside_owner_are_denied(local_web, sdk):
    client, settings = local_web
    database = client.app.state.database
    with pytest.raises(llm.OpenAIKeyError):
        llm.get_backend(settings)
    with database.session() as session:
        session.get(User, 1).last_login_at = None
    with user_openai(database, 1, settings=settings):
        with pytest.raises(llm.OpenAIKeyError, match="본인 Google"):
            llm.get_backend()
    assert not key_registered(database, 1, settings=settings) and sdk == []


def test_local_settings_show_env_state_without_key_fingerprint_or_db_mutations(local_web, sdk):
    client, settings = local_web
    csrf = login(client, settings, 1)
    page = client.get("/settings")
    assert "로컬 .env 키 사용 가능" in page.text and "fake-sub-1" in page.text
    assert 'name="api_key"' not in page.text
    assert page.headers["cache-control"] == "private, no-store"
    key = settings.openai_api_key
    for secret in (key, key[-8:], hashlib.sha256(key.encode()).hexdigest()):
        assert secret not in page.text and secret not in repr(client.cookies)
    for path in ("/settings/openai-key", "/settings/openai-key/delete"):
        response = client.post(path, data={"api_key": "fake-submitted-secret", "csrf_token": csrf})
        assert response.status_code == 409 and "fake-submitted-secret" not in response.text
    with client.app.state.database.session() as session:
        assert list(session.scalars(select(UserOpenAIKey))) == []
    login(client, settings, 2)
    page = client.get("/settings")
    assert "로컬 AI 사용 불가" in page.text and "fake-sub-2" in page.text and "fake-sub-1" not in page.text
    inbox = client.get("/inbox")
    assert "본인 .env 키와 Google 소유자 설정" in inbox.text and "내 OpenAI API 키 등록하기" not in inbox.text
    assert sdk == []


def test_first_login_only_displays_own_subject_never_claims_owner(local_web, sdk):
    client, settings = local_web
    unclaimed = replace(settings, local_owner_google_sub="")
    with TestClient(create_app(unclaimed, google=FakeGoogle()), base_url="http://127.0.0.1") as fresh:
        assert sign_in(fresh).status_code == 303
        page = fresh.get("/settings")
        assert "LOCAL_OWNER_GOOGLE_SUB" in page.text and "fake-sub-1" in page.text
        assert "로컬 AI 사용 불가" in page.text and unclaimed.local_owner_google_sub == ""
        fresh.headers["X-CSRF-Token"] = fresh.get("/api/session").json()["csrf_token"]
        response = fresh.post("/api/trade/pi/extract", json={"text": "가상 문서"})
        assert response.status_code == 409 and response.json()["error"]["code"] == "LOCAL_OWNER_REQUIRED"
    assert sdk == []


def test_key_service_refuses_storage_and_disallows_local_key_without_listener(local_web, sdk):
    client, settings = local_web
    database = client.app.state.database
    for operation in (lambda: save_key(database, 1, "fake-new-key", None, settings=settings),
                      lambda: delete_key(database, 1, settings=settings)):
        with pytest.raises(llm.OpenAIKeyError) as error:
            operation()
        assert error.value.code == "LOCAL_KEY_ENV_ONLY"
    # 유효한 사용자와 키가 있어도 실행기의 소켓 권한을 벗어나면 거부한다.
    with local_listener(None), user_openai(database, 1, settings=settings):
        with pytest.raises(llm.OpenAIKeyError) as error:
            llm.get_backend()
        assert error.value.code == "LOCAL_RUNTIME_REQUIRED"
    assert sdk == []


def test_host_header_cannot_select_or_expose_local_mode(local_web, sdk):
    client, _ = local_web
    assert client.get("/settings", headers={"Host": "public.example.invalid"}).status_code == 400
    assert sdk == []


def test_server_mode_still_refuses_env_key_for_any_user(local_web, sdk):
    client, settings = local_web
    server_settings = replace(settings, ai_runtime="server")
    for user_id in (1, 2, 9999):
        with user_openai(client.app.state.database, user_id, settings=server_settings):
            with pytest.raises(llm.OpenAIKeyError) as error:
                llm.get_backend()
            assert error.value.code == "OPENAI_KEY_REQUIRED"
    assert sdk == []


def test_explicit_fake_backend_still_works_with_unconfigured_local_owner(local_web, email, sdk):
    client, settings = local_web
    client.app.state.settings = replace(settings, local_owner_google_sub="")
    # HTTP 추출 경로의 대역 주입은 키/소유자 설정과 독립적이다.
    with llm.use_backend(FakeLLM([{}])):
        client.headers["X-CSRF-Token"] = client.get("/api/session").json()["csrf_token"]
        response = client.post("/api/trade/pi/extract", json={"text": "가상 문서"})
    assert response.status_code == 201 and sdk == []
