"""실제 세션·SDK 모의 HTTP로 사용자별 과금 키, 암호화, 삭제와 공용 키 차단을 확인한다."""
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import re
from threading import Barrier

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import httpx
from itsdangerous import TimestampSigner
from langchain_openai import ChatOpenAI
import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.engine import Database
from app.db.migrations import upgrade_database
from app.db.models import ProcessedMessage, RunEvent, User, UserOpenAIKey
from app.graph.run import start_run
from app.llm import client as llm
from app.main import create_app
from app.services.auth import TokenCipher
from app.services.openai_keys import delete_key, key_registered, save_key, user_openai
from tests.fakes.gmail import FakeGmailGoogle
from tests.test_gmail_push import setup_user, push_payload
from tests.test_pi_domain import pi_input


@pytest.fixture
def sdk(monkeypatch):
    requests, clients = [], []

    def respond(request):
        payload = json.loads(request.content)
        name = payload["tools"][0]["name"]
        requests.append((request.headers["authorization"], name))
        values = {
            "EmailAnalysis": {"intent": "general", "reason": "가상 문의"},
            "DraftOutput": {"candidates": [{"label": "간단 안내", "body": "가상 답장입니다."},
                                           {"label": "상세 안내", "body": "가상 안내입니다."}]},
        }.get(name, {})
        return httpx.Response(200, json={
            "id": "resp_fake", "object": "response", "created_at": 1, "model": "gpt-6-luna",
            "status": "completed", "error": None, "incomplete_details": None,
            "output": [{"type": "function_call", "id": "fc_fake", "call_id": "call_fake",
                        "name": name, "arguments": json.dumps(values)}],
            "parallel_tool_calls": False, "tool_choice": payload["tool_choice"], "tools": payload["tools"],
            "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
        })

    def build(settings):
        http = httpx.Client(transport=httpx.MockTransport(respond))
        clients.append(http)
        return ChatOpenAI(model=llm.model_name(settings), api_key=settings.openai_api_key,
                          use_responses_api=True, http_client=http, http_socket_options=(), max_retries=0)

    monkeypatch.setattr(llm, "_backend_for_settings", build)
    yield requests
    for http in clients:
        http.close()


@pytest.fixture
def web(tmp_path, sdk):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'keys.sqlite3'}", session_secret="fake-session-secret",
                        token_encryption_key=Fernet.generate_key().decode(), openai_api_key="fake-server-key",
                        gmail_pubsub_topic="projects/fake/topics/fake", pubsub_push_token="fake-push-token")
    with TestClient(create_app(settings, google=FakeGmailGoogle())) as client:
        with client.app.state.database.session() as session:
            session.add_all([User(id=n, google_sub=f"fake-sub-{n}", email=f"user{n}@example.invalid")
                             for n in (1, 2, 3)])
        yield client, settings


def login(client, settings, user_id):
    data = b64encode(json.dumps({"user_id": user_id}).encode())
    cookie = TimestampSigner(settings.session_secret).sign(data).decode()
    client.cookies.clear()
    client.cookies.set("gq_session", cookie)
    page = client.get("/settings")
    assert page.status_code == 200
    return re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]


def test_registration_is_encrypted_owner_scoped_and_never_echoed(web, sdk):
    client, settings = web
    csrf = login(client, settings, 1)
    key = "fake-user-one-key"
    response = client.post("/settings/openai-key", data={"api_key": key, "csrf_token": csrf, "user_id": 2})
    assert response.status_code == 200 and "등록됨" in response.text
    assert key not in response.text and 'type="password"' in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert key not in repr(client.cookies) and sdk == []
    database = client.app.state.database
    with database.session() as session:
        encrypted = session.get(UserOpenAIKey, 1).api_key_enc
        assert key not in encrypted and session.get(UserOpenAIKey, 2) is None
        assert TokenCipher(settings.token_encryption_key).decrypt(encrypted) == key
    login(client, settings, 2)
    assert "미등록" in client.get("/settings").text
    assert not key_registered(database, 2)


def test_registration_and_deletion_require_login_and_csrf(web):
    client, settings = web
    assert client.post("/settings/openai-key", data={"api_key": "fake-key"}, follow_redirects=False).status_code == 303
    csrf = login(client, settings, 1)
    for token in ("", "wrong", "한글"):
        assert client.post("/settings/openai-key", data={"api_key": "fake-key", "csrf_token": token}).status_code == 403
        assert client.post("/settings/openai-key/delete", data={"csrf_token": token}).status_code == 403
    client.post("/settings/openai-key", data={"api_key": "fake-one", "csrf_token": csrf})
    other_csrf = login(client, settings, 2)
    client.post("/settings/openai-key/delete", data={"csrf_token": other_csrf, "user_id": 1})
    assert key_registered(client.app.state.database, 1)
    assert client.post("/settings/openai-key", data={"api_key": "fake-key", "csrf_token": csrf}).status_code == 403


@pytest.mark.parametrize("key", ["", "fake-key with-space", "x" * 513, "fake-키", "fake-\x00-key"])
def test_invalid_key_is_not_reflected_in_validation_response(web, key):
    client, settings = web
    csrf = login(client, settings, 1)
    response = client.post("/settings/openai-key", data={"api_key": key, "csrf_token": csrf})
    assert response.status_code == 400
    if key:
        assert key not in response.text
    assert not key_registered(client.app.state.database, 1)


def test_missing_encryption_configuration_blocks_storage_and_corruption_blocks_ai(web, sdk):
    client, settings = web
    csrf = login(client, settings, 1)
    access = client.app.state.google_access
    client.app.state.google_access = replace(access, cipher=None)
    response = client.post("/settings/openai-key", data={"api_key": "fake-private-key", "csrf_token": csrf})
    assert response.status_code == 503 and "fake-private-key" not in response.text
    client.app.state.google_access = access
    save_key(access.database, 1, "fake-user-key", access.cipher)
    with access.database.session() as session:
        session.get(UserOpenAIKey, 1).api_key_enc = "corrupt-fake-ciphertext"
    client.headers["X-CSRF-Token"] = client.get("/api/session").json()["csrf_token"]
    response = client.post("/api/trade/pi/extract", json={"text": "가상 문서"})
    assert response.status_code == 409 and response.json()["error"]["code"] == "OPENAI_KEY_UNAVAILABLE"
    assert sdk == []


@pytest.mark.parametrize("kind", ["pi", "po", "ci", "pl"])
def test_document_ai_requires_owner_key_and_never_uses_server_key(web, sdk, kind):
    client, settings = web
    database = client.app.state.database
    for user_id in (1, 2):
        save_key(database, user_id, f"fake-user-{user_id}", client.app.state.google_access.cipher)
    payload = {"text": "가상 문서"}
    if kind == "ci":
        payload.update(source_pi_id=1, source_revision=1)
    for user_id in (1, 2, 3):
        login(client, settings, user_id)
        client.headers["X-CSRF-Token"] = client.get("/api/session").json()["csrf_token"]
        before = len(sdk)
        response = client.post(f"/api/trade/{kind}/extract", json=payload)
        if user_id == 3:
            assert response.status_code == 409 and response.json()["error"]["code"] == "OPENAI_KEY_REQUIRED"
            assert len(sdk) == before
            # 수동 작성은 AI 키 없이도 계속 가능하다.
            assert client.post("/api/trade/pi", json=pi_input().model_dump(mode="json")).status_code == 201
        else:
            assert len(sdk) > before, response.text
            assert all(auth == f"Bearer fake-user-{user_id}" for auth, _ in sdk[before:])
    assert all("server" not in auth for auth, _ in sdk)


def test_background_push_uses_mailbox_owner_key_without_login_session(web, sdk):
    client, settings = web
    access = client.app.state.google_access
    setup_user(access, sub="fake-sub-1", address="user1@example.invalid")
    setup_user(access, sub="fake-sub-2", address="user2@example.invalid")
    for user_id in (1, 2):
        save_key(access.database, user_id, f"fake-owner-{user_id}", access.cipher)
        client.cookies.clear()  # Gmail 푸시는 사용자 로그인 세션 없이 실행된다.
        before = len(sdk)
        response = client.post("/gmail/push?token=fake-push-token", json=push_payload("9999", address=f"user{user_id}@example.invalid"))
        assert response.status_code == 204
        assert len(sdk) == before + 2
        assert all(auth == f"Bearer fake-owner-{user_id}" for auth, _ in sdk[before:])
    setup_user(access, sub="fake-sub-3", address="user3@example.invalid")
    before = len(sdk)
    client.post("/gmail/push?token=fake-push-token", json=push_payload("9999", address="user3@example.invalid"))
    assert len(sdk) == before
    with access.database.session() as session:
        blocked = session.scalar(select(ProcessedMessage).where(ProcessedMessage.user_id == 3))
        assert blocked.status == "error" and blocked.notice == "openai_key_required"
        events = list(session.scalars(select(RunEvent)))
        assert "fake-owner-" not in repr([event.detail for event in events])


@pytest.mark.parametrize("status,attempts", [(401, 1), (429, 1), (503, 3)])
def test_rejected_user_key_never_falls_back_to_server_key(web, monkeypatch, status, attempts):
    client, settings = web
    captured, clients = [], []

    def respond(request):
        captured.append(request.headers["authorization"])
        return httpx.Response(status, json={"error": {"message": "fake-private-sdk-response"}})

    def build(config):
        http = httpx.Client(transport=httpx.MockTransport(respond))
        clients.append(http)
        return ChatOpenAI(model="gpt-6-luna", api_key=config.openai_api_key, use_responses_api=True,
                          http_client=http, http_socket_options=(), max_retries=0)

    monkeypatch.setattr(llm, "_backend_for_settings", build)
    monkeypatch.setattr(llm, "sleep", lambda _: None)
    csrf = login(client, settings, 1)
    client.post("/settings/openai-key", data={"api_key": "fake-denied-owner", "csrf_token": csrf})
    client.headers["X-CSRF-Token"] = client.get("/api/session").json()["csrf_token"]
    try:
        response = client.post("/api/trade/pi/extract", json={"text": "가상 문서"})
        assert response.status_code == 503
        assert captured == ["Bearer fake-denied-owner"] * attempts
        assert "fake-private-sdk-response" not in response.text and "fake-denied-owner" not in response.text
    finally:
        for http in clients:
            http.close()


def test_rotation_deletion_and_restart_never_reuse_cached_keys(web, sdk):
    client, settings = web
    database = client.app.state.database
    csrf = login(client, settings, 1)
    client.post("/settings/openai-key", data={"api_key": "fake-first", "csrf_token": csrf})
    with user_openai(database, 1, settings=settings):
        assert llm.get_backend().openai_api_key.get_secret_value() == "fake-first"
        client.post("/settings/openai-key", data={"api_key": "fake-second", "csrf_token": csrf})
        assert llm.get_backend().openai_api_key.get_secret_value() == "fake-second"
        client.post("/settings/openai-key/delete", data={"csrf_token": csrf})
        with pytest.raises(llm.OpenAIKeyError):
            llm.get_backend()
    with pytest.raises(llm.OpenAIKeyError):
        llm.get_backend(settings)  # 사용자 범위 밖에서도 서버 키 사용 금지
    assert not key_registered(database, 1)
    save_key(database, 1, "fake-persisted", client.app.state.google_access.cipher)
    reopened = Database(settings.database_url)
    try:
        upgrade_database(reopened.engine)
        with user_openai(reopened, 1, settings=settings):
            assert llm.get_backend().openai_api_key.get_secret_value() == "fake-persisted"
    finally:
        reopened.close()


def test_simultaneous_graph_runs_keep_keys_isolated(web, sdk, email):
    client, settings = web
    database = client.app.state.database
    cipher = client.app.state.google_access.cipher
    barrier = Barrier(2)
    for user_id in (1, 2):
        save_key(database, user_id, f"fake-parallel-{user_id}", cipher)

    class ConcurrentGraph:
        def invoke(self, state, config):
            barrier.wait(timeout=10)
            assert llm.get_backend().openai_api_key.get_secret_value() == f"fake-parallel-{state['user_id']}"
            return {**state, "end_reason": "ignored"}

    def run(user_id):
        return start_run(user_id=user_id, email=email, database=database, key_cipher=cipher, graph=ConcurrentGraph())

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (1, 2)))
    assert all(result["end_reason"] == "ignored" for result in results)
    with pytest.raises(llm.OpenAIKeyError):
        llm.get_backend(settings)
