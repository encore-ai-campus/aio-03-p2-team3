"""계획 21.1: SPA 주소 복구·정적 파일 경계·기존 서버 진입점의 회귀 검사."""

from base64 import b64encode
import json
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.main import create_app
from app.web import frontend
from tests.fakes.google import FakeGoogle

INDEX = '<!doctype html><html><div id="root">fake-react-shell</div></html>'


@pytest.fixture
def built_ui(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX)
    (dist / "assets" / "index-fakehash.js").write_text('console.log("fake bundle")')
    (dist / "assets" / "index-fakehash.css").write_text("body { color: black }")
    (dist / ".env").write_text("fake-secret-must-not-be-served")
    monkeypatch.setattr(frontend, "DIST", dist)
    return dist


@pytest.fixture
def ui_client(database_url, built_ui):
    settings = Settings(
        database_url=database_url, session_secret="fake-session-secret",
        token_encryption_key=Fernet.generate_key().decode(),
        google_oauth_client_id="fake-client", google_oauth_client_secret="fake-secret",
        google_oauth_redirect_uri="http://testserver/auth/google/callback",
        gmail_pubsub_topic="projects/fake/topics/fake", pubsub_push_token="fake-push-token",
        supabase_url="https://fake.supabase.example",
    )
    with TestClient(create_app(settings, google=FakeGoogle())) as client:
        yield client


def test_ui_entry_deep_link_reload_and_head(ui_client):
    redirect = ui_client.get("/app", follow_redirects=False)
    assert redirect.status_code == 307
    assert urlsplit(redirect.headers["location"]).path == "/app/"
    for path in ("/app/", "/app/login", "/app/trade/pi/123?tab=review", "/app/index.html"):
        response = ui_client.get(path)
        assert response.status_code == 200 and response.text == INDEX
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-cache"
        head = ui_client.head(path)
        assert head.status_code == 200 and head.content == b""
        assert head.headers["content-length"] == response.headers["content-length"]


def test_assets_have_correct_types_and_conditional_cache(ui_client):
    for name, content_type in (("index-fakehash.js", "javascript"), ("index-fakehash.css", "text/css")):
        path = f"/app/assets/{name}"
        response = ui_client.get(path)
        assert response.status_code == 200
        assert content_type in response.headers["content-type"]
        assert "fake-react-shell" not in response.text
        cached = ui_client.get(path, headers={"If-None-Match": response.headers["etag"]})
        assert cached.status_code == 304 and cached.content == b""
        assert cached.headers["cache-control"] == "no-cache"


def test_missing_assets_and_private_files_never_receive_spa(ui_client, built_ui):
    outside = built_ui.parent / "server-secret.txt"
    outside.write_text("fake-outside-secret")
    (built_ui / "leak.txt").symlink_to(outside)
    for path in (
        "/app/assets/missing.js", "/app/assets/missing.css", "/app/assets/no-extension",
        "/app/missing.png", "/app/.env", "/app/leak.txt", "/app/%2e%2e/server-secret.txt",
    ):
        response = ui_client.get(path)
        assert response.status_code == 404
        assert "fake-react-shell" not in response.text
        assert "fake-outside-secret" not in response.text
        assert "fake-secret-must-not-be-served" not in response.text
    assert ui_client.post("/app/trade/pi/123", json={}).status_code == 405


def test_api_health_public_pages_and_legacy_entry_stay_outside_spa(ui_client):
    for path in ("/api", "/api/does-not-exist", "/unknown"):
        response = ui_client.get(path)
        assert response.status_code == 404 and response.json() == {"detail": "Not Found"}
    assert ui_client.get("/api/me").status_code == 401
    assert ui_client.get("/healthz").json() == {"status": "ok"}
    for path in ("/docs", "/about", "/privacy", "/terms", "/login", "/static/css/app.css"):
        response = ui_client.get(path)
        assert response.status_code == 200 and "fake-react-shell" not in response.text
    home = ui_client.get("/", follow_redirects=False)
    assert home.status_code == 303 and home.headers["location"] == "/inbox"


def test_google_callback_and_authenticated_gmail_push_with_ui(ui_client):
    # state 없는 콜백은 기존 로그인 오류 흐름, 유효한 가짜 Google 왕복은 /inbox다.
    invalid = ui_client.get("/auth/google/callback?state=wrong&code=fake", follow_redirects=False)
    assert invalid.status_code == 303 and invalid.headers["location"] == "/login?notice=login_failed"
    start = ui_client.get("/auth/google/start", follow_redirects=False)
    state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
    callback = ui_client.get("/auth/google/callback", params={"state": state, "code": "fake-code"},
                             follow_redirects=False)
    assert callback.status_code == 303 and callback.headers["location"] == "/inbox"
    # 등록되지 않은 가상 주소라 외부 Gmail/LLM을 호출하지 않는다.
    data = json.dumps({"emailAddress": "unknown@example.invalid", "historyId": "1001"}).encode()
    envelope = {"message": {"data": b64encode(data).decode()}}
    assert ui_client.post("/gmail/push", json=envelope).status_code == 403
    assert ui_client.post("/gmail/push?token=fake-push-token", json={}).status_code == 400
    response = ui_client.post("/gmail/push?token=fake-push-token", json=envelope)
    assert response.status_code == 204 and response.content == b""


def test_absent_build_does_not_break_backend(database_url, tmp_path, monkeypatch):
    monkeypatch.setattr(frontend, "DIST", tmp_path / "missing-dist")
    with TestClient(create_app(Settings(database_url=database_url))) as client:
        for path in ("/app/", "/app/trade/pi/123"):
            response = client.get(path)
            assert response.status_code == 503
            assert response.json()["detail"].startswith("UI 빌드가 없습니다")
        assert client.get("/app/assets/missing.js").status_code == 404
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/api/missing").status_code == 404
        assert client.get("/privacy").status_code == 200
