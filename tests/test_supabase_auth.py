"""Supabase Bearer 인증(계획 5절): 가짜 JWKS와 직접 서명한 토큰·실제 PostgreSQL로 검증한다.

정상·만료·위조·다른 issuer/audience/알고리즘/subject·동시 가입·타인 문서 404·Bearer 실패 때
쿠키 우회 금지·JWKS 장애(503)와 인증 실패(401) 구분·키 회전(unknown kid 재조회)을 본다.
실제 Supabase·외부 HTTP는 부르지 않는다.
"""
import json
import threading
import time
from uuid import uuid4

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from starlette.requests import Request as StarletteRequest

from app.auth.supabase import TokenVerifier, VerifiedToken, get_or_create_user
from app.config import Settings
from app.db.engine import Database
from app.db.models import User
from app.main import create_app
from tests.test_pi_domain import pi_input

SUPABASE_URL = "https://test-project.supabase.example"
ISSUER = f"{SUPABASE_URL}/auth/v1"


def _jwk(algorithm, private_key, kid):
    to_jwk = (pyjwt.algorithms.RSAAlgorithm if algorithm == "RS256"
              else pyjwt.algorithms.ECAlgorithm).to_jwk
    jwk = json.loads(to_jwk(private_key.public_key()))
    jwk.update({"kid": kid, "alg": algorithm, "use": "sig"})
    return jwk


class FakeJwks:
    """호출할 때마다 다른 JWKS를 내줄 수 있는 가짜 JWKS 서버(키 회전·장애 시험)."""

    def __init__(self):
        self.rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.rsa_kid = "rsa-2026-11"
        self.ec_key = ec.generate_private_key(ec.SECP256R1())
        self.ec_kid = "ec-2026-11"
        self.attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.document = {"keys": [_jwk("RS256", self.rsa_key, self.rsa_kid),
                                  _jwk("ES256", self.ec_key, self.ec_kid)]}
        self.error = None
        self.calls = 0
        self.admin_users = {}   # Supabase UUID(문자열) -> admin 사용자 응답(공급자 identity)
        self.admin_error = None
        self.admin_calls = 0

    def serve(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.document

    def admin_serve(self, url):
        """`TokenVerifier.provider_google_subject`가 부르는 admin 사용자 조회 가짜."""
        self.admin_calls += 1
        if self.admin_error is not None:
            raise self.admin_error
        return self.admin_users.get(url.rsplit("/", 1)[-1], {"identities": []})

    def with_google_identity(self, sub, google_sub):
        """Supabase 사용자 `sub`가 Google 로그인(google_sub)으로 가입했게 만든다."""
        self.admin_users[str(sub)] = {"identities": [
            {"provider": "google", "id": str(uuid4()), "provider_id": google_sub,
             "identity_data": {"sub": google_sub}},
        ]}

    def token(self, *, key=None, kid="default", sub=None, exp=None, iss=None, aud=None,
              alg="RS256", email="supabase@example.invalid", with_kid=True, extra_headers=None):
        now = int(time.time())
        sub = sub if sub is not None else uuid4()
        if str(sub) not in self.admin_users:
            self.with_google_identity(sub, "fake-sub-1")
        claims = {
            "sub": str(sub),
            "iss": iss if iss is not None else ISSUER,
            "aud": aud if aud is not None else "authenticated",
            "exp": exp if exp is not None else now + 3600,
            "iat": now,
            "email": email,
        }
        headers = {"kid": kid if kid != "default" else self.rsa_kid} if with_kid else {}
        headers.update(extra_headers or {})
        return pyjwt.encode(claims, key or self.rsa_key, algorithm=alg, headers=headers)


@pytest.fixture
def auth_pair(database_url):
    jwks = FakeJwks()
    verifier = TokenVerifier(SUPABASE_URL, fetch_jwks=jwks.serve)
    app = create_app(Settings(database_url=database_url, session_secret="fake-test-session"),
                     supabase_auth=verifier)
    with TestClient(app) as client:
        yield client, jwks


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def write_settings(client, headers):
    assert client.put("/api/trade/settings/company", headers=headers, json={
        "company_name": "Testworks Trading", "legal_name_en": "Testworks Trading Co",
        "address": "7 Test-ro, Seoul", "ceo_name": "Example Signer"}).status_code == 200
    assert client.put("/api/trade/settings/banks/USD", headers=headers, json={
        "beneficiary": "Testworks Trading", "bank_name": "Example Bank", "branch": "Example Branch",
        "swift": "EXAMPLE", "account_number": "000-0000", "bank_address": "1 Bank-ro, Seoul"}
                      ).status_code == 200
    assert client.put("/api/trade/settings/prices", headers=headers, json={
        "item_name": "Virtual Serum", "capacity": "50ml", "role": "sale", "currency": "USD",
        "unit_price": "8", "price_basis": "PCS"}).status_code == 200


def test_valid_token_creates_user_once_and_me_flow(auth_pair):
    client, jwks = auth_pair
    sub = uuid4()
    response = client.get("/api/me", headers=bearer(jwks.token(sub=sub)))
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["user_id"], int) and body["email"] == "supabase@example.invalid"
    assert body["display_name"] is None
    assert body["gmail"] == {"connected": False, "watch": "stopped"}  # Gmail 미연결 사용자
    assert client.get("/api/me", headers=bearer(jwks.token(sub=sub))).json()["user_id"] == body["user_id"]
    with client.app.state.database.session() as session:
        users = session.scalars(select(User).where(User.supabase_uid == sub)).all()
        assert [user.id for user in users] == [body["user_id"]]
        assert users[0].google_sub is None  # Google 미연결로 가입한 사용자


def test_es256_token_is_accepted_too(auth_pair):
    client, jwks = auth_pair
    token = jwks.token(key=jwks.ec_key, kid=jwks.ec_kid, alg="ES256")
    assert client.get("/api/me", headers=bearer(token)).status_code == 200


def test_token_header_cannot_direct_the_jwks_url(auth_pair):
    """토큰 헤더(jku 등)는 무시하고 JWKS 주소는 설정(SUPABASE_URL)에서 정한 값만 쓴다."""
    client, jwks = auth_pair
    assert client.app.state.supabase_auth.jwks_url == f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    token = jwks.token(extra_headers={"jku": "https://attacker.example/jwks.json"})
    assert client.get("/api/me", headers=bearer(token)).status_code == 200  # jku를 무시하고 정상 검증


def test_unconnected_user_writes_settings_and_documents_with_bearer_only(auth_pair):
    client, jwks = auth_pair
    headers = bearer(jwks.token())
    assert client.get("/api/trade/settings", headers=headers).json()["prices"] == []
    write_settings(client, headers)  # CSRF 토큰 없이 Bearer만으로 변경 요청이 통과한다
    created = client.post("/api/trade/pi", headers=headers, json=pi_input().model_dump(mode="json"))
    assert created.status_code == 201, created.text
    assert client.get("/api/trade/pi", headers=headers).json()[0]["document_id"] == \
        created.json()["document_id"]


def test_expired_forged_and_wrong_claim_tokens_are_rejected(auth_pair):
    client, jwks = auth_pair
    now = int(time.time())
    cases = {
        "만료": jwks.token(exp=now - 10),
        "다른 issuer": jwks.token(iss="https://other-project.supabase.example/auth/v1"),
        "다른 audience": jwks.token(aud="anon"),
        "위조 서명": jwks.token(key=jwks.attacker_key),
        "공유 비밀 알고리즘(HS256)": jwks.token(alg="HS256", key="attacker-shared-secret-0123456789abcdef"),
        "UUID가 아닌 subject": jwks.token(sub="not-a-uuid"),
        "kid 없음": jwks.token(with_kid=False),
        "깨진 토큰": "not-a-jwt-at-all",
    }
    for name, token in cases.items():
        response = client.get("/api/me", headers=bearer(token))
        assert response.status_code == 401, f"{name}: {response.text}"
        assert response.json()["error"]["code"] == "invalid_token", name


def test_missing_or_malformed_authorization_header(auth_pair):
    client, _ = auth_pair
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer"}).status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Token abc"}).status_code == 401


def test_bearer_failure_never_falls_back_to_cookie_session(auth_pair):
    """세션 쿠키가 유효해도 Bearer 헤더가 있으면 Bearer 검증만 한다(CONTRACT 9.1)."""
    client, jwks = auth_pair
    from app.auth.deps import current_user_id

    def request_with(headers, session=None):
        scope = {"type": "http", "app": client.app,
                 "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
                 "session": session or {}}
        return StarletteRequest(scope)

    invalid = request_with({"Authorization": "Bearer not-a-jwt"}, session={"user_id": 1})
    with pytest.raises(Exception) as caught:  # BearerAuthError는 앱 밖에서는 그대로 올라온다.
        current_user_id(invalid)
    assert getattr(caught.value, "code", None) == "invalid_token"
    # Authorization 헤더가 없으면 기존 쿠키 세션을 그대로 쓴다(전환 기간 legacy).
    assert current_user_id(request_with({"X-Anything": "1"}, session={"user_id": 1})) == 1


def test_other_users_documents_and_settings_are_invisible(auth_pair):
    client, jwks = auth_pair
    owner = bearer(jwks.token())
    write_settings(client, owner)
    document = client.post("/api/trade/pi", headers=owner,
                           json=pi_input().model_dump(mode="json")).json()
    other = bearer(jwks.token(sub=uuid4()))
    assert client.get("/api/trade/pi", headers=other).json() == []
    assert client.get(f"/api/trade/pi/{document['document_id']}", headers=other).status_code == 404
    assert client.get(f"/api/trade/pi/{document['document_id']}/versions/1",
                      headers=other).status_code == 404
    assert client.get(f"/api/trade/pi/{document['document_id']}/reviews/missing",
                      headers=other).status_code == 404
    assert client.get("/api/trade/settings", headers=other).json()["prices"] == []


def test_unknown_kid_refreshes_jwks_and_rotation_keeps_working(auth_pair):
    client, jwks = auth_pair
    assert client.get("/api/me", headers=bearer(jwks.token())).status_code == 200
    fetched = jwks.calls
    # 키 회전: 서버가 새 kid만 내려준다. unknown kid는 JWKS를 다시 가져와 통과한다.
    rotated_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks.document = {"keys": [_jwk("RS256", rotated_key, "rsa-2027-01")]}
    rotated = client.get("/api/me", headers=bearer(jwks.token(key=rotated_key, kid="rsa-2027-01")))
    assert rotated.status_code == 200, rotated.text
    assert jwks.calls == fetched + 1
    # JWKS에 없는 kid로 조작한 토큰은 401로 거부한다.
    assert client.get("/api/me", headers=bearer(jwks.token(kid="no-such-kid"))).status_code == 401


@pytest.mark.parametrize("kid", [["key"], {"id": "key"}, 123])
def test_non_string_kid_is_rejected_as_unauthorized(auth_pair, kid):
    from base64 import urlsafe_b64encode

    client, jwks = auth_pair
    _, payload, signature = jwks.token().split(".")
    header = urlsafe_b64encode(json.dumps({"alg": "RS256", "kid": kid}).encode()).rstrip(b"=").decode()
    response = client.get("/api/me", headers=bearer(f"{header}.{payload}.{signature}"))
    assert response.status_code == 401



def test_jwks_outage_is_503_not_401(auth_pair):
    client, jwks = auth_pair
    assert client.get("/api/me", headers=bearer(jwks.token())).status_code == 200  # 키 캐시
    jwks.error = httpx.ConnectError("fake network down")
    rotated = jwks.token(key=rsa.generate_private_key(public_exponent=65537, key_size=2048),
                         kid="rsa-2027-01")
    response = client.get("/api/me", headers=bearer(rotated))  # unknown kid → 재조회 실패
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "auth_unavailable"
    jwks.error = None
    assert client.get("/api/me", headers=bearer(jwks.token())).status_code == 200


def test_unconfigured_supabase_is_503(database_url):
    app = create_app(Settings(database_url=database_url, session_secret="fake-test-session"))
    with TestClient(app) as client:
        response = client.get("/api/me", headers=bearer("any-token"))
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "auth_not_configured"


def test_concurrent_first_login_ends_with_a_single_row(database_url):
    """같은 UUID로 동시 첫 접속은 유일 제약으로 한 행에서 끝난다(실제 PostgreSQL 잠금)."""
    database = Database(database_url)
    database.create_tables()
    sub = uuid4()
    try:
        with database.session() as held:  # 아직 커밋되지 않은 첫 가입(다른 세션의 INSERT는 여기서 막힌다)
            row = User(supabase_uid=sub, email="race@example.invalid")
            held.add(row)
            held.flush()
            results = []
            thread = threading.Thread(
                target=lambda: results.append(
                    get_or_create_user(database, VerifiedToken(sub=sub, email="race@example.invalid"))))
            thread.start()
            time.sleep(1.0)  # 스레드가 INSERT까지 도달하게 한다(못 미쳐도 아래 결과는 같다)
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert results == [row.id]
        with database.session() as session:
            count = session.scalar(select(func.count()).select_from(User).where(User.supabase_uid == sub))
            assert count == 1
    finally:
        database.close()
