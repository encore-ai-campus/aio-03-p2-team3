"""계획 6절: 가짜 Google 응답으로 로그인·토큰 암호화·감시 등록·갱신·접근 거부·안내를 확인한다(실제 API 호출 없음)."""

from base64 import b64encode
from datetime import UTC, datetime, timedelta
import json
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from fastapi.testclient import TestClient
import httplib2
from googleapiclient.errors import HttpError
from itsdangerous import TimestampSigner
import pytest
from sqlalchemy import select

from app.clients.gmail import GoogleClient, TokenExpired, WatchFailed, missing_scopes
from app.config import Settings
from app.db.models import GmailWatch, GoogleToken, ProcessedMessage, User
from app.main import create_app
from app.services.auth import GoogleAccess, TokenCipher, get_access_token, get_owned, save_login
from app.services.watch import renew_watch_if_due
from app.web.routes.auth import CONNECTION_NOTICES, LOGIN_NOTICES, require_user
from tests.fakes.google import FakeGoogle, fake_login

TOPIC = "projects/fake-project/topics/fake-topic"


@pytest.fixture
def settings():
    return Settings(
        database_url="sqlite://",
        google_oauth_client_id="fake-client.apps.example.invalid",
        google_oauth_client_secret="fake-secret",
        google_oauth_redirect_uri="http://testserver/auth/google/callback",
        gmail_pubsub_topic=TOPIC,
        token_encryption_key=Fernet.generate_key().decode(),
        session_secret="test-session-secret",
    )


@pytest.fixture
def fake():
    return FakeGoogle()


@pytest.fixture
def app(settings, fake):
    app = create_app(settings, google=fake)

    @app.get("/test/processed/{row_id}")
    def read_processed(row_id: int, request: Request, user: User = Depends(require_user)):
        with request.app.state.database.session() as session:
            row = get_owned(session, ProcessedMessage, row_id, user.id)
            if row is None:
                raise HTTPException(404)
            return {"thread_id": row.thread_id}

    return app


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


def sign_in(client, consent=False):
    start = client.get("/auth/google/start", params={"consent": 1} if consent else None, follow_redirects=False)
    assert start.status_code == 303
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    return client.get("/auth/google/callback", params={"code": "fake-code", "state": state},
                      follow_redirects=False)


def rows(client, model):
    with client.app.state.database.session() as session:
        return list(session.scalars(select(model)))


def watch_of(client, user_id=None):
    with client.app.state.database.session() as session:
        return session.get(GmailWatch, user_id or session.scalar(select(User.id)))


def cipher_of(client) -> TokenCipher:
    return client.app.state.google_access.cipher


def test_login_page_guides_test_account(client):
    page = client.get("/login")
    assert page.status_code == 200
    assert "테스트용 Gmail로 등록하세요" in page.text and "Gemini 무료 등급" in page.text
    assert 'href="/auth/google/start"' in page.text
    assert 'href="/login"' in client.get("/inbox").text  # 로그인 전 받은 메일 화면의 연결 링크


def test_login_encrypts_tokens_and_registers_watch(client, fake):
    response = sign_in(client)
    assert response.status_code == 303 and response.headers["location"] == "/inbox"

    [user] = rows(client, User)
    assert (user.google_sub, user.email) == ("fake-sub-1", "demo@example.invalid")
    [token] = rows(client, GoogleToken)
    assert "fake-refresh-1" not in token.refresh_token_enc and "fake-access-1" not in token.access_token_enc
    assert cipher_of(client).decrypt(token.refresh_token_enc) == "fake-refresh-1"
    assert cipher_of(client).decrypt(token.access_token_enc) == "fake-access-1"
    assert "https://www.googleapis.com/auth/gmail.send" in token.scopes

    watch = watch_of(client, user.id)
    assert (watch.status, watch.topic, watch.history_id) == ("active", TOPIC, "1000")
    assert watch.expiration > datetime.now(UTC) and watch.last_renewed_at is not None
    assert fake.called("watch") == [("watch", "fake-access-1", TOPIC)]
    exchange = fake.called("exchange")[0]
    assert exchange[1] == "fake-code" and len(exchange[2]) >= 43  # PKCE 검증값을 콜백까지 세션에 보관

    inbox = client.get("/inbox")
    assert "demo@example.invalid" in inbox.text and "새 메일 알림 켜짐" in inbox.text
    assert 'action="/logout"' in inbox.text
    assert len(fake.called("watch")) == 1  # 하루가 안 지났으면 화면 요청 때 다시 부르지 않는다
    assert client.get("/runs").status_code == 200  # 14절 화면(current_user_id)도 같은 세션으로 열린다


def test_callback_rejects_wrong_or_missing_state(client, fake):
    client.get("/auth/google/start", follow_redirects=False)
    wrong = client.get("/auth/google/callback", params={"code": "x", "state": "wrong"}, follow_redirects=False)
    assert wrong.headers["location"] == "/login?notice=login_failed"
    replay = client.get("/auth/google/callback", params={"code": "x", "state": "wrong"}, follow_redirects=False)
    assert replay.headers["location"] == "/login?notice=login_failed"
    assert rows(client, User) == [] and fake.called("exchange") == []
    assert LOGIN_NOTICES["login_failed"] in client.get("/login?notice=login_failed").text


def test_cancel_and_missing_scope_do_not_save_user(client, fake):
    start = client.get("/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    cancelled = client.get("/auth/google/callback", params={"error": "access_denied", "state": state},
                           follow_redirects=False)
    assert cancelled.headers["location"] == "/login?notice=cancelled"

    fake.logins.append(fake_login(scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"]))
    assert sign_in(client).headers["location"] == "/login?notice=scope_missing"
    assert rows(client, User) == [] and fake.called("watch") == []


def test_missing_refresh_token_asks_consent_once_then_keeps_stored_one(client, fake):
    fake.logins += [fake_login(refresh_token=None), fake_login(refresh_token="fake-refresh-2")]
    assert sign_in(client).headers["location"] == "/auth/google/start?consent=1"
    assert sign_in(client, consent=True).headers["location"] == "/inbox"
    assert fake.called("authorize")[-1] == ("authorize", True)

    fake.logins.append(fake_login(refresh_token=None, access_token="fake-access-3"))
    assert sign_in(client).headers["location"] == "/inbox"  # 다시 로그인: 새 갱신 토큰이 없으면 저장한 것을 쓴다
    [token] = rows(client, GoogleToken)
    assert cipher_of(client).decrypt(token.refresh_token_enc) == "fake-refresh-2"
    assert cipher_of(client).decrypt(token.access_token_enc) == "fake-access-3"


def test_watch_renewed_only_after_a_day_with_refreshed_token(client, fake):
    sign_in(client)
    access = client.app.state.google_access
    first = watch_of(client)
    renewed_at = first.last_renewed_at

    assert renew_watch_if_due(access, first.user_id, renewed_at + timedelta(hours=23)) is False
    assert len(fake.called("watch")) == 1

    later = renewed_at + timedelta(hours=25)  # 접근 토큰(1시간)도 지나 갱신 토큰으로 새로 받는다
    assert renew_watch_if_due(access, first.user_id, later) is True
    assert fake.called("watch")[-1] == ("watch", "fake-access-refreshed-1", TOPIC)
    assert fake.called("refresh") == [("refresh", "fake-refresh-1")]
    watch = watch_of(client)
    assert watch.last_renewed_at == later and watch.status == "active"
    assert watch.history_id == "1000"  # 켜져 있는 감시는 알림 처리(7)가 이어 읽도록 그대로 둔다
    [token] = rows(client, GoogleToken)
    assert cipher_of(client).decrypt(token.access_token_enc) == "fake-access-refreshed-1"


def test_screen_request_renews_stale_watch(client, fake):
    sign_in(client)
    with client.app.state.database.session() as session:
        session.scalar(select(GmailWatch)).last_renewed_at = datetime.now(UTC) - timedelta(hours=25)
    client.get("/inbox")
    assert len(fake.called("watch")) == 2
    assert datetime.now(UTC) - watch_of(client).last_renewed_at < timedelta(minutes=1)


def test_refresh_token_expiry_asks_to_log_in_again(client, fake):
    sign_in(client)
    with client.app.state.database.session() as session:
        session.scalar(select(GmailWatch)).last_renewed_at = datetime.now(UTC) - timedelta(days=2)
        session.scalar(select(GoogleToken)).expires_at = datetime.now(UTC) - timedelta(minutes=5)
    fake.refresh_error = TokenExpired("invalid_grant")

    client.get("/inbox")  # 응답 뒤 갱신이 갱신 토큰 만료를 만난다
    watch = watch_of(client)
    assert (watch.status, watch.last_error) == ("error", "token_expired")
    [token] = rows(client, GoogleToken)
    assert token.refresh_token_enc is None and token.access_token_enc is None

    page = client.get("/inbox")
    assert CONNECTION_NOTICES["token_expired"] in page.text
    assert 'href="/auth/google/start?consent=1"' in page.text
    assert len(fake.called("refresh")) == 1  # 다시 로그인할 때까지 갱신을 다시 시도하지 않는다

    fake.refresh_error = None
    fake.logins.append(fake_login(refresh_token="fake-refresh-new"))
    assert sign_in(client, consent=True).headers["location"] == "/inbox"
    watch = watch_of(client)
    assert (watch.status, watch.last_error, watch.history_id) == ("active", None, "1000")
    assert CONNECTION_NOTICES["token_expired"] not in client.get("/inbox").text


def test_watch_failure_is_shown_and_retried(client, fake):
    fake.watch_error = WatchFailed("HTTP 403")
    assert sign_in(client).headers["location"] == "/inbox"  # 등록에 실패해도 로그인은 마친다
    watch = watch_of(client)
    assert (watch.status, watch.last_error, watch.history_id) == ("error", "watch_failed: HTTP 403", None)
    assert CONNECTION_NOTICES["watch_failed"] in client.get("/inbox").text  # 이 요청 뒤 다시 시도(또 실패)

    fake.watch_error = None
    client.get("/inbox")  # 이 요청 뒤 다시 시도해 성공
    page = client.get("/inbox")
    assert CONNECTION_NOTICES["watch_failed"] not in page.text and "새 메일 알림 켜짐" in page.text
    assert watch_of(client).status == "active" and len(fake.called("watch")) == 3


def test_other_users_data_is_denied(client):
    sign_in(client)
    access = client.app.state.google_access
    me = rows(client, User)[0].id
    other = save_login(access, fake_login(sub="fake-sub-2", email="other@example.invalid"))
    with client.app.state.database.session() as session:
        mine = ProcessedMessage(user_id=me, gmail_message_id="m1", thread_id="mine")
        theirs = ProcessedMessage(user_id=other, gmail_message_id="m1", thread_id="theirs")
        session.add_all([mine, theirs])
    assert client.get(f"/test/processed/{mine.id}").json() == {"thread_id": "mine"}
    assert client.get(f"/test/processed/{theirs.id}").status_code == 404

    # 다른 키로 서명한(위조한) 세션 쿠키는 로그인으로 보지 않는다
    payload = b64encode(json.dumps({"user_id": other}).encode())
    client.cookies.clear()
    client.cookies.set("gq_session", TimestampSigner("wrong-secret").sign(payload).decode())
    denied = client.get(f"/test/processed/{theirs.id}", follow_redirects=False)
    assert denied.status_code == 303 and denied.headers["location"] == "/login"
    # 비교: 서버 키로 서명된 쿠키만 읽힌다(그래서 SESSION_SECRET은 밖에 내지 않는다)
    client.cookies.clear()
    client.cookies.set("gq_session", TimestampSigner("test-session-secret").sign(payload).decode())
    assert client.get(f"/test/processed/{theirs.id}").json() == {"thread_id": "theirs"}


def test_logout_stops_watch_and_relogin_starts_fresh(client, fake):
    sign_in(client)
    access = client.app.state.google_access
    response = client.post("/logout", follow_redirects=False)
    assert response.headers["location"] == "/login?notice=logged_out"
    assert fake.called("stop") == [("stop", "fake-access-1")]
    watch = watch_of(client)
    assert watch.status == "stopped"
    assert renew_watch_if_due(access, watch.user_id, datetime.now(UTC) + timedelta(days=3)) is False
    assert 'href="/login"' in client.get("/inbox").text

    sign_in(client)
    assert watch_of(client).history_id == "1001"  # 멈췄다 다시 켜면 그 시점부터 처리한다


def test_unreadable_token_is_treated_as_expired(client):
    sign_in(client)
    original = client.app.state.google_access
    user_id = rows(client, User)[0].id
    other_key = GoogleAccess(original.database, original.google,
                             TokenCipher(Fernet.generate_key().decode()), TOPIC)
    with pytest.raises(TokenExpired):
        get_access_token(other_key, user_id)
    assert watch_of(client).last_error == "token_expired"


def test_login_disabled_until_settings_exist(fake):
    with TestClient(create_app(Settings(database_url="sqlite://", token_encryption_key="bad"), google=fake)) as client:
        page = client.get("/login")
        assert "GOOGLE_OAUTH_CLIENT_ID" in page.text and "TOKEN_ENCRYPTION_KEY(형식 오류)" in page.text
        assert "disabled" in page.text
        start = client.get("/auth/google/start", follow_redirects=False)
        assert start.headers["location"] == "/login?notice=config_missing"
        assert fake.calls == []


def test_real_client_builds_consent_url_and_watch_request(settings, monkeypatch):
    google = GoogleClient(settings)
    url = urlparse(google.authorization_url("state-1", "v" * 64, consent=True))
    query = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert query["access_type"] == ["offline"] and query["include_granted_scopes"] == ["true"]
    assert query["prompt"] == ["consent"] and query["state"] == ["state-1"]
    assert query["code_challenge_method"] == ["S256"] and query["redirect_uri"] == [settings.google_oauth_redirect_uri]
    assert "https://www.googleapis.com/auth/gmail.send" in query["scope"][0].split()
    assert missing_scopes(["openid", "https://www.googleapis.com/auth/userinfo.email",
                           "https://www.googleapis.com/auth/gmail.readonly"]) == [
        "https://www.googleapis.com/auth/gmail.send"]

    sent = {}

    class Request:
        def __init__(self, result):
            self.result = result

        def execute(self, num_retries):
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    class Users:
        result = {"historyId": "42", "expiration": "1767225600000"}

        def watch(self, userId, body):
            sent.update(body)
            return Request(self.result)

    class Gmail:
        def users(self):
            return users

    users = Users()
    monkeypatch.setattr(google, "gmail", lambda token: Gmail())
    response = google.watch("token", TOPIC)
    assert sent == {"topicName": TOPIC, "labelIds": ["INBOX"]}
    assert response.history_id == "42" and response.expiration == datetime(2026, 1, 1, tzinfo=UTC)

    users.result = HttpError(httplib2.Response({"status": 403}), b'{"error": {"message": "forbidden"}}')
    with pytest.raises(WatchFailed, match="HTTP 403"):
        google.watch("token", TOPIC)
