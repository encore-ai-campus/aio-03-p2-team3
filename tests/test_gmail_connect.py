"""계획 7절: Gmail 연결을 앱 로그인에서 분리한 Bearer API를 가짜 Google·가짜 JWKS로 확인한다.

연결→watch→토큰 갱신(/api/me)→로그아웃 watch 중지→재연결, state 재사용/만료, 연결 취소·권한
누락, 타인 callback·계정 충돌 거부, 기존 정수 ID 보존 연결, 연결 해제(Google 토큰 폐기)를 본다.
실제 Google·Supabase HTTP는 부르지 않는다.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from cryptography.fernet import Fernet
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.supabase import TokenVerifier
from app.clients.gmail import GoogleUnavailable, TokenExpired
from app.config import Settings
from app.db.models import GmailWatch, GoogleToken, ProcessedMessage, User
from app.main import create_app
from app.services.auth import save_login
from tests.fakes.google import FakeGoogle, fake_login
from tests.test_supabase_auth import SUPABASE_URL, FakeJwks

TOPIC = "projects/fake-project/topics/fake-topic"


def settings_of(database_url):
    return Settings(
        database_url=database_url,
        google_oauth_client_id="fake-client.apps.example.invalid",
        google_oauth_client_secret="fake-secret",
        google_oauth_redirect_uri="http://testserver/auth/google/callback",
        gmail_pubsub_topic=TOPIC,
        token_encryption_key=Fernet.generate_key().decode(),
        session_secret="test-session-secret",
        supabase_secret_key="fake-server-secret",
    )


def make_client(database_url, jwks, fake, settings=None):
    verifier = TokenVerifier(SUPABASE_URL, fetch_jwks=jwks.serve, secret_key="fake-server-secret",
                             fetch_admin_user=jwks.admin_serve)
    app = create_app(settings or settings_of(database_url), google=fake, supabase_auth=verifier)
    return TestClient(app)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def start_connect(client, token):
    response = client.post("/api/gmail/connect", headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()["authorization_url"]


def state_of(url):
    return parse_qs(urlparse(url).query)["state"][0]


def complete(client, url, code="fake-code"):
    return client.get("/auth/google/callback",
                      params={"code": code, "state": state_of(url)}, follow_redirects=False)


def me(client, token):
    response = client.get("/api/me", headers=bearer(token))
    assert response.status_code == 200, response.text
    return response.json()


def users(client):
    with client.app.state.database.session() as session:
        return list(session.scalars(select(User)))


def watch_of(client, user_id):
    with client.app.state.database.session() as session:
        return session.get(GmailWatch, user_id)


def token_of(client, user_id):
    with client.app.state.database.session() as session:
        return session.get(GoogleToken, user_id)


def test_connect_registers_watch_and_me_reports_connected(database_url):
    jwks, fake = FakeJwks(), FakeGoogle()
    with make_client(database_url, jwks, fake) as client:
        sub = uuid4()
        jwks.with_google_identity(sub, "fake-sub-1")
        token = jwks.token(sub=sub)

        before = me(client, token)
        assert before["gmail"] == {"connected": False, "watch": "stopped"}

        url = start_connect(client, token)
        assert url.startswith("https://accounts.example.invalid/auth?")  # 동의 화면 주소
        result = complete(client, url)
        assert result.status_code == 303
        assert result.headers["location"] == "/app/settings?gmail=connected"

        [user] = [row for row in users(client) if row.supabase_uid == sub]
        assert user.id == before["user_id"] and user.google_sub == "fake-sub-1"
        assert me(client, token) == {
            "user_id": user.id, "email": "demo@example.invalid", "display_name": "데모 사용자",
            "gmail": {"connected": True, "watch": "active"},
        }
        watch = watch_of(client, user.id)
        assert (watch.status, watch.history_id) == ("active", "1000")
        assert fake.called("watch") == [("watch", "fake-access-1", TOPIC)]
        stored = token_of(client, user.id)  # 기존 방식 그대로 암호문으로만 저장됐다
        assert "fake-refresh-1" not in stored.refresh_token_enc
        assert client.app.state.google_access.cipher.decrypt(stored.refresh_token_enc) == "fake-refresh-1"


def test_connect_state_is_checked_single_use_and_expires(database_url, monkeypatch):
    jwks, fake = FakeJwks(), FakeGoogle()
    with make_client(database_url, jwks, fake) as client:
        from app.auth import gmail as gmail_module
        token = jwks.token()

        # state가 다르면 코드 교환을 하지 않고 실패 안내한다(대기 값도 그대로 버린다).
        url = start_connect(client, token)
        wrong = client.get("/auth/google/callback",
                           params={"code": "x", "state": "wrong"}, follow_redirects=False)
        assert wrong.headers["location"] == "/app/settings?gmail=login_failed"
        assert fake.called("exchange") == []
        late = client.get("/auth/google/callback",
                          params={"code": "fake-code", "state": state_of(url)}, follow_redirects=False)
        assert late.headers["location"] == "/login?notice=login_failed"  # 버린 대기 값은 못 쓴다

        # 만료된 state는 교환하지 않고 expired로 안내한다.
        monkeypatch.setattr(gmail_module, "STATE_TTL_SECONDS", -1)
        expired = complete(client, start_connect(client, token))
        assert expired.headers["location"] == "/app/settings?gmail=expired"
        assert fake.called("exchange") == []

        # 성공한 state는 한 번만 쓸 수 있다(재사용 거부).
        monkeypatch.setattr(gmail_module, "STATE_TTL_SECONDS", 600)
        good = start_connect(client, token)
        assert complete(client, good).headers["location"] == "/app/settings?gmail=connected"
        replay = client.get("/auth/google/callback",
                            params={"code": "x", "state": state_of(good)}, follow_redirects=False)
        assert replay.headers["location"] == "/login?notice=login_failed"
        assert len(fake.called("exchange")) == 1


def test_cancel_scope_missing_and_consent_retry(database_url):
    jwks, fake = FakeJwks(), FakeGoogle()
    with make_client(database_url, jwks, fake) as client:
        token = jwks.token()

        url = start_connect(client, token)
        cancelled = client.get("/auth/google/callback",
                               params={"error": "access_denied", "state": state_of(url)},
                               follow_redirects=False)
        assert cancelled.headers["location"] == "/app/settings?gmail=cancelled"

        fake.logins.append(fake_login(scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"]))
        assert complete(client, start_connect(client, token)).headers["location"] == \
            "/app/settings?gmail=scope_missing"
        assert users(client)[0].google_sub is None and fake.called("watch") == []

        # 갱신 토큰이 오지 않으면 같은 흐름으로 한 번만 다시 동의를 받는다.
        fake.logins += [fake_login(refresh_token=None), fake_login(refresh_token=None)]
        restart = complete(client, start_connect(client, token))
        parsed = urlparse(restart.headers["location"])
        assert parsed.netloc == "accounts.example.invalid" and parse_qs(parsed.query)["consent"] == ["1"]
        assert fake.called("authorize")[-1] == ("authorize", True)
        # 다시 동의를 받았는데도 갱신 토큰이 계속 없으면 실패로 끝낸다(무한 반복 없음).
        assert complete(client, restart.headers["location"]).headers["location"] == \
            "/app/settings?gmail=login_failed"
        assert users(client)[0].google_sub is None and fake.called("watch") == []

        # 갱신 토큰을 받으면 같은 흐름으로 연결을 마친다.
        fake.logins += [fake_login(refresh_token=None), fake_login(refresh_token="fake-refresh-2")]
        retry = complete(client, start_connect(client, token))
        assert retry.status_code == 303
        assert urlparse(retry.headers["location"]).netloc == "accounts.example.invalid"
        assert complete(client, retry.headers["location"]).headers["location"] == \
            "/app/settings?gmail=connected"
        stored = token_of(client, users(client)[0].id)
        assert client.app.state.google_access.cipher.decrypt(stored.refresh_token_enc) == "fake-refresh-2"


def test_other_users_google_callback_does_not_grant_their_data(database_url):
    """Supabase 사용자 A 상태로 사용자 B Google callback을 완성해도 B 자료를 얻지 못한다."""
    jwks, fake = FakeJwks(), FakeGoogle()
    with make_client(database_url, jwks, fake) as client:
        legacy_b = save_login(client.app.state.google_access,
                              fake_login(sub="B-sub", email="b@example.invalid"))
        with client.app.state.database.session() as session:
            session.add(ProcessedMessage(user_id=legacy_b, gmail_message_id="m1", thread_id="b-thread"))

        sub_a = uuid4()
        jwks.with_google_identity(sub_a, "A-sub")  # A의 앱 로그인 Google 계정은 A-sub다.
        token_a = jwks.token(sub=sub_a)
        a_before = me(client, token_a)

        fake.logins.append(fake_login(sub="B-sub", email="b@example.invalid"))
        result = complete(client, start_connect(client, token_a))
        assert result.headers["location"] == "/app/settings?gmail=different_account"

        after = me(client, token_a)
        assert after["gmail"] == {"connected": False, "watch": "stopped"}
        assert after["user_id"] == a_before["user_id"]
        row_b = [row for row in users(client) if row.google_sub == "B-sub"][0]
        assert row_b.id == legacy_b and row_b.supabase_uid is None  # B 행은 그대로다
        assert fake.called("watch") == [] and watch_of(client, legacy_b) is None

        # 우리 DB에 없는 새 Google 계정이어도 A 계정과 다르면 거부한다(다른 메일함 연결 금지).
        fake.logins.append(fake_login(sub="C-sub", email="c@example.invalid"))
        assert complete(client, start_connect(client, token_a)).headers["location"] == \
            "/app/settings?gmail=different_account"


def test_matching_subject_links_legacy_integer_id(database_url):
    """재인증으로 같은 Google 계정임이 확인되면 기존 정수 ID(자료)를 보존해 연결한다."""
    jwks, fake = FakeJwks(), FakeGoogle()
    with make_client(database_url, jwks, fake) as client:
        legacy = save_login(client.app.state.google_access,
                            fake_login(sub="G-sub", email="g@example.invalid"))
        with client.app.state.database.session() as session:
            session.add(ProcessedMessage(user_id=legacy, gmail_message_id="m2", thread_id="g-thread"))

        sub = uuid4()
        jwks.with_google_identity(sub, "G-sub")  # 같은 Google 계정으로 Supabase에 로그인한 경우
        token = jwks.token(sub=sub)
        shell_id = me(client, token)["user_id"]  # Bearer 첫 접속이 만든 빈 사용자 행
        assert shell_id != legacy

        fake.logins.append(fake_login(sub="G-sub", email="g@example.invalid"))
        assert complete(client, start_connect(client, token)).headers["location"] == \
            "/app/settings?gmail=connected"

        linked = me(client, token)
        assert linked["user_id"] == legacy  # 기존 정수 ID가 보존됐다
        assert linked["gmail"]["connected"] is True
        assert [row.id for row in users(client) if row.id == shell_id] == []  # 빈 껍데기 행은 지웠다
        row = [row for row in users(client) if row.id == legacy][0]
        assert row.supabase_uid == sub and row.google_sub == "G-sub"
        assert (watch_of(client, legacy).status, watch_of(client, legacy).history_id) == ("active", "1000")


def test_link_refuses_conflicts_instead_of_merging(database_url):
    jwks, fake = FakeJwks(), FakeGoogle()
    with make_client(database_url, jwks, fake) as client:
        access = client.app.state.google_access
        legacy = save_login(access, fake_login(sub="G-sub", email="g@example.invalid"))

        # ① 새 계정(껍데기)에 이미 자료가 있으면 자동 합병하지 않고 둘 다 보존한다.
        sub = uuid4()
        jwks.with_google_identity(sub, "G-sub")
        token = jwks.token(sub=sub)
        shell_id = me(client, token)["user_id"]
        with client.app.state.database.session() as session:
            session.add(ProcessedMessage(user_id=shell_id, gmail_message_id="m3", thread_id="shell"))
        fake.logins.append(fake_login(sub="G-sub", email="g@example.invalid"))
        assert complete(client, start_connect(client, token)).headers["location"] == \
            "/app/settings?gmail=account_conflict"
        row = [row for row in users(client) if row.id == legacy][0]
        assert row.supabase_uid is None and me(client, token)["gmail"]["connected"] is False
        assert [row.id for row in users(client) if row.id == shell_id] == [shell_id]

        # ② 공급자 subject를 확인할 수 없으면(이메일 로그인 등) 기존 행 연결 근거가 없어 거부한다.
        email_sub = uuid4()
        email_only = jwks.token(sub=email_sub)
        jwks.admin_users[str(email_sub)] = {"identities": []}
        denied = client.post("/api/gmail/connect", headers=bearer(email_only))
        assert denied.status_code == 409
        assert denied.json()["error"]["code"] == "google_identity_required"

        # ③ 기존 행이 이미 다른 Supabase 로그인에 연결돼 있어도 거부한다.
        newcomer, holder = uuid4(), uuid4()
        with client.app.state.database.session() as session:
            session.get(User, legacy).supabase_uid = holder
        jwks.with_google_identity(newcomer, "G-sub")
        fake.logins.append(fake_login(sub="G-sub", email="g@example.invalid"))
        assert complete(client, start_connect(client, jwks.token(sub=newcomer))).headers["location"] == \
            "/app/settings?gmail=account_conflict"


def test_fresh_connect_without_google_identity_attaches_to_current_user(database_url):
    jwks, fake = FakeJwks(), FakeGoogle()
    with make_client(database_url, jwks, fake) as client:
        token = jwks.token()  # 공급자 identity 없는 Supabase 사용자(admin 응답에 google이 없음)
        before = me(client, token)
        assert complete(client, start_connect(client, token)).headers["location"] == \
            "/app/settings?gmail=connected"
        after = me(client, token)
        assert after["user_id"] == before["user_id"] and after["gmail"]["connected"] is True


def test_logout_stops_watch_and_reconnect_resumes(database_url):
    jwks, fake = FakeJwks(), FakeGoogle()
    with make_client(database_url, jwks, fake) as client:
        token = jwks.token()
        user_id = me(client, token)["user_id"]
        complete(client, start_connect(client, token))

        response = client.post("/api/gmail/logout", headers=bearer(token))
        assert response.status_code == 200
        assert response.json() == {"connected": True, "watch": "stopped"}  # 토큰은 보존한다
        assert fake.called("stop") == [("stop", "fake-access-1")]
        assert watch_of(client, user_id).status == "stopped"
        assert me(client, token)["gmail"] == {"connected": True, "watch": "stopped"}

        # 재연결: 다시 감시가 켜지고 멈춘 뒤 온 메일은 건너뛴다(새 historyId부터).
        assert complete(client, start_connect(client, token)).headers["location"] == \
            "/app/settings?gmail=connected"
        assert (watch_of(client, user_id).status, watch_of(client, user_id).history_id) == \
            ("active", "1001")


def test_disconnect_revokes_google_token(database_url):
    jwks, fake = FakeJwks(), FakeGoogle()
    with make_client(database_url, jwks, fake) as client:
        token = jwks.token()
        user_id = me(client, token)["user_id"]
        complete(client, start_connect(client, token))

        response = client.post("/api/gmail/disconnect", headers=bearer(token))
        assert response.status_code == 200
        assert response.json() == {"connected": False, "watch": "stopped"}
        assert fake.called("revoke") == [("revoke", "fake-refresh-1")]
        assert fake.called("stop") == [("stop", "fake-access-1")]
        assert token_of(client, user_id) is None
        row = [row for row in users(client) if row.id == user_id][0]
        assert row.google_sub == "fake-sub-1"  # 계정 증명 기록은 남겨 같은 계정만 다시 연결한다
        assert me(client, token)["gmail"] == {"connected": False, "watch": "stopped"}

        # 폐기 호출이 실패하면 저장된 토큰을 지우지 않고 다시 시도하게 한다(데이터 손실 방지).
        fake.logins.append(fake_login(refresh_token="fake-refresh-9", access_token="fake-access-9"))
        complete(client, start_connect(client, token))
        fake.revoke_error = GoogleUnavailable("HTTP 500")
        failed = client.post("/api/gmail/disconnect", headers=bearer(token))
        assert failed.status_code == 503
        assert failed.json()["error"]["code"] == "google_unavailable"
        assert token_of(client, user_id) is not None

        # 이미 폐기된 토큰(TokenExpired)이면 로컬 정리만 계속한다.
        fake.revoke_error = TokenExpired("invalid_grant")
        assert client.post("/api/gmail/disconnect", headers=bearer(token)).status_code == 200
        assert token_of(client, user_id) is None


def test_me_renews_due_watch_with_refreshed_token(database_url):
    """감시 갱신이 legacy HTML 방문에만 의존하지 않는다: /api/me 요청 뒤에 갱신한다."""
    jwks, fake = FakeJwks(), FakeGoogle()
    with make_client(database_url, jwks, fake) as client:
        token = jwks.token()
        user_id = me(client, token)["user_id"]
        complete(client, start_connect(client, token))
        assert len(fake.called("watch")) == 1

        with client.app.state.database.session() as session:  # 하루를 넘기고 접근 토큰도 만료한다
            watch = session.get(GmailWatch, user_id)
            watch.last_renewed_at = datetime.now(UTC) - timedelta(hours=25)
            session.get(GoogleToken, user_id).expires_at = datetime.now(UTC) - timedelta(minutes=5)

        assert me(client, token)["gmail"]["watch"] == "active"
        assert fake.called("refresh") == [("refresh", "fake-refresh-1")]  # 갱신 토큰으로 새로 받았다
        assert fake.called("watch")[-1] == ("watch", "fake-access-refreshed-1", TOPIC)
        stored = token_of(client, user_id)
        assert client.app.state.google_access.cipher.decrypt(stored.access_token_enc) == \
            "fake-access-refreshed-1"


def test_connect_needs_server_settings(database_url):
    jwks = FakeJwks()
    token = jwks.token()
    # Google 로그인 설정이 비었으면 시작을 거부한다(값 이름만 안내).
    with make_client(database_url, jwks, FakeGoogle(),
                     settings=Settings(database_url=database_url, session_secret="s")) as client:
        response = client.post("/api/gmail/connect", headers=bearer(token))
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "config_missing"
        assert "GOOGLE_OAUTH_CLIENT_ID" in response.json()["error"]["message"]

    # 서버 비밀 키가 없으면 공급자 subject 확인 자체가 불가능하다.
    verifier = TokenVerifier(SUPABASE_URL, fetch_jwks=jwks.serve)
    with TestClient(create_app(settings_of(database_url), google=FakeGoogle(),
                               supabase_auth=verifier)) as client:
        response = client.post("/api/gmail/connect", headers=bearer(token))
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "auth_not_configured"

    # 인증 서버의 계정 조회가 실패하면 503 auth_unavailable이다(401이 아니다).
    jwks.admin_error = httpx.ConnectError("fake admin outage")
    with make_client(database_url, jwks, FakeGoogle()) as client:
        response = client.post("/api/gmail/connect", headers=bearer(token))
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "auth_unavailable"


def test_gmail_requires_verified_google_provider_identity(database_url):
    jwks = FakeJwks()
    sub = uuid4()
    jwks.admin_users[str(sub)] = {"identities": [], "user_metadata": {"sub": "fake-sub-1"}}
    with make_client(database_url, jwks, FakeGoogle()) as client:
        response = client.post("/api/gmail/connect", headers=bearer(jwks.token(sub=sub)))
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "google_identity_required"
