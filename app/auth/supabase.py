"""Supabase access token 검증과 기존 users 표 매핑(CONTRACT 9.1절, 계획 5절).

서버 JWT 검증은 이 모듈 한 곳에서 한다. JWKS 주소는 설정의 SUPABASE_URL에서만 정하고
요청 토큰(header)이 지정한 임의 JWKS URL은 부르지 않는다. 인증 실패(401)와 인증 서버
일시 장애(503)를 `BearerAuthError.code`로 구분하며 토큰 원문은 로그에 남기지 않는다.
서명 검증 라이브러리는 pyjwt(버전 고정, pyproject.toml)이고 JWT 암호는 직접 구현하지 않는다.
"""

from dataclasses import dataclass
from logging import getLogger
import time
from uuid import UUID

from fastapi import Request
import httpx
import jwt
from jwt.exceptions import PyJWTError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.engine import Database
from app.db.models import User

log = getLogger(__name__)

# Supabase 비대칭 signing key 검증 값(공식 확인: docs/guides/auth/signing-keys·jwt-fields, 2026-11-12).
AUDIENCE = "authenticated"  # 로그인한 사용자 access token의 aud(anon은 거부)
ALGORITHMS = ("RS256", "ES256")  # 비대칭만 허용. HS256(공유 비밀)·none 등은 거부한다
JWKS_PATH = "/auth/v1/.well-known/jwks.json"
JWKS_CACHE_SECONDS = 300.0  # 가져온 키 집합을 그대로 쓰는 기간. unknown kid는 바로 다시 가져온다(키 회전 대응)
JWKS_TIMEOUT_SECONDS = 5.0


class BearerAuthError(Exception):
    """Bearer 인증 실패(401)·인증 서버 장애(503). `app/main.py`가 `{"error": …}` JSON으로 바꾼다."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def invalid_token(message: str = "유효하지 않은 로그인 토큰입니다. 다시 로그인해 주세요.") -> BearerAuthError:
    return BearerAuthError(401, "invalid_token", message)


@dataclass(frozen=True)
class VerifiedToken:
    sub: UUID  # Supabase auth.users의 UUID subject
    email: str | None  # 인증 서버가 발급한 email 클레임(계정 연결 근거로는 쓰지 않는다)


class TokenVerifier:
    """JWKS를 가져와 Supabase access token을 검증한다. 앱마다 하나를 만들어 재사용한다."""

    def __init__(self, supabase_url: str, fetch_jwks=None, *, secret_key: str = "", fetch_admin_user=None):
        base = supabase_url.strip().rstrip("/")
        self.jwks_url = base + JWKS_PATH
        self.issuer = base + "/auth/v1"
        self._admin_users_url = base + "/auth/v1/admin/users"
        self.secret_key = secret_key
        self._fetch_jwks = fetch_jwks or self._fetch_over_http
        self._fetch_admin_user = fetch_admin_user or self._fetch_admin_user_over_http
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = float("-inf")

    def _fetch_over_http(self) -> dict:
        response = httpx.get(self.jwks_url, timeout=JWKS_TIMEOUT_SECONDS,
                             headers={"Accept": "application/json"})
        response.raise_for_status()
        return response.json()

    def _fetch_admin_user_over_http(self, url: str) -> dict:
        # 서버 비밀 키로 Auth 서비스의 사용자 조회(admin)를 부른다. 사용자가 고칠 수 있는
        # user_metadata이 아니라 서버 쪽 identities만 계정 연결 근거로 쓴다(CONTRACT 9.1).
        response = httpx.get(url, timeout=JWKS_TIMEOUT_SECONDS, headers={
            "apikey": self.secret_key, "Authorization": f"Bearer {self.secret_key}",
            "Accept": "application/json",
        })
        response.raise_for_status()
        return response.json()

    def provider_google_subject(self, sub: UUID) -> str | None:
        """Supabase Auth가 확인한 공급자 identity에서 Google subject를 읽는다(계획 7절).

        Google 로그인 사용자면 Google 계정의 subject(= 기존 `users.google_sub` 값)를 돌려주고,
        다른 방법으로 가입한 사용자면 None. 사용자가 고칠 수 있는 값(user_metadata)은 읽지 않는다.
        """
        if not self.secret_key:
            raise BearerAuthError(503, "auth_not_configured",
                                  "SUPABASE_SECRET_KEY가 설정되지 않아 Google 계정 일치를 확인할 수 없습니다.")
        try:
            document = self._fetch_admin_user(f"{self._admin_users_url}/{sub}")
        except BearerAuthError:
            raise
        except (httpx.HTTPError, ValueError) as error:
            log.warning("Supabase 사용자 조회 실패: %s", type(error).__name__)
            raise BearerAuthError(503, "auth_unavailable",
                                  "로그인 서버에서 계정 정보를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.") from error
        # GoTrue 버전에 따라 identities·user_identities 둘 다 쓰인다. 둘 다 서버가 만든 값이다.
        identities = (document.get("identities") or document.get("user_identities")) \
            if isinstance(document, dict) else None
        if not isinstance(identities, list):
            identities = []
        for identity in identities:
            if not isinstance(identity, dict) or identity.get("provider") != "google":
                continue
            subject = identity.get("id") or (identity.get("identity_data") or {}).get("sub")
            if isinstance(subject, str) and subject:
                return subject
        return None

    def _refresh(self) -> None:
        try:
            document = self._fetch_jwks()
        except BearerAuthError:
            raise
        except (httpx.HTTPError, ValueError) as error:
            # 주소·응답 원문에 비밀이 섞일 수 있어 오류 종류만 남긴다.
            log.warning("JWKS 가져오기 실패: %s", type(error).__name__)
            raise BearerAuthError(503, "auth_unavailable",
                                  "로그인 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.") from error
        entries = document.get("keys") if isinstance(document, dict) else None
        if not isinstance(entries, list):
            raise BearerAuthError(503, "auth_unavailable",
                                  "로그인 서버의 서명 키를 읽지 못했습니다. 잠시 후 다시 시도해 주세요.")
        keys: dict[str, jwt.PyJWK] = {}
        for entry in entries:
            try:
                key = jwt.PyJWK.from_dict(entry)
            except PyJWTError:
                continue  # 형식이 틀린 키 항목은 건너뛴다
            if key.algorithm_name in ALGORITHMS and key.key_id:
                keys[key.key_id] = key
        if not keys:
            raise BearerAuthError(503, "auth_unavailable",
                                  "로그인 서버의 서명 키를 읽지 못했습니다. 잠시 후 다시 시도해 주세요.")
        self._keys = keys
        self._fetched_at = time.monotonic()

    def _key_for(self, kid: str) -> jwt.PyJWK:
        key = self._keys.get(kid)
        if key is not None and time.monotonic() - self._fetched_at < JWKS_CACHE_SECONDS:
            return key
        # unknown kid(키 회전 직후)이거나 캐시 수명이 지났으면 키 집합을 다시 가져온다.
        self._refresh()
        key = self._keys.get(kid)
        if key is None:
            raise invalid_token("서명 키를 확인할 수 없는 토큰입니다. 다시 로그인해 주세요.")
        return key

    def verify(self, token: str) -> VerifiedToken:
        """토큰의 서명·알고리즘·issuer·audience·만료·UUID subject를 확인한다."""
        try:
            header = jwt.get_unverified_header(token)
        except PyJWTError:
            raise invalid_token() from None
        kid = header.get("kid")
        if not kid:
            raise invalid_token("서명 키 식별자(kid)가 없는 토큰입니다.")
        key = self._key_for(kid)
        try:
            claims = jwt.decode(token, key=key.key, algorithms=list(ALGORITHMS), audience=AUDIENCE,
                                issuer=self.issuer, leeway=0,
                                options={"require": ["exp", "iss", "aud", "sub"]})
        except PyJWTError:
            raise invalid_token() from None
        try:
            sub = UUID(str(claims["sub"]))
        except (KeyError, ValueError):
            raise invalid_token("사용자 식별자(subject)가 UUID가 아닌 토큰입니다.") from None
        email = claims.get("email")
        return VerifiedToken(sub=sub, email=email if isinstance(email, str) and email else None)


def get_or_create_user(database: Database, token: VerifiedToken) -> int:
    """검증된 UUID로 기존 정수 `users.id`를 찾고, 없으면 한 번만 만든다.

    동시 첫 접속은 `supabase_uid` 유일 제약으로 한 행에서 끝난다(먼저 커밋한 쪽의 id를 돌려준다).
    이메일은 프로필 표시용이고 같은 이메일이라는 이유로 기존 행에 연결하지 않는다(CONTRACT 9.1).
    """
    try:
        with database.session() as session:
            user = session.scalar(select(User).where(User.supabase_uid == token.sub))
            if user is not None:
                return user.id
            user = User(supabase_uid=token.sub, email=token.email or "")
            session.add(user)
            session.flush()
            return user.id
    except IntegrityError:
        with database.session() as session:
            user = session.scalar(select(User).where(User.supabase_uid == token.sub))
            if user is None:
                raise
            return user.id


def bearer_user_id(request: Request) -> int:
    """`Authorization: Bearer`만 받는 사용자 id 의존성. 쿠키 세션은 전혀 읽지 않는다(CONTRACT 9.1)."""
    if request.app.state.supabase_auth is None:
        raise BearerAuthError(503, "auth_not_configured",
                              "SUPABASE_URL이 설정되지 않아 이 로그인 방식을 쓸 수 없습니다.")
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    token = value.strip()
    if scheme.lower() != "bearer" or not token:
        raise invalid_token("Authorization: Bearer 로그인 토큰이 필요합니다.")
    return get_or_create_user(request.app.state.database, request.app.state.supabase_auth.verify(token))
