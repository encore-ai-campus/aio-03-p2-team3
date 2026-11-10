"""사용자별 Google OAuth·Gmail API 호출(CONTRACT 1·10절, 계획 6절).

실제 Google을 부르는 곳은 이 파일의 `GoogleClient` 하나다. 서버가 뜰 때 한 번 만들어
`app.state.google`에 두고, 테스트는 같은 메서드를 가진 가짜(`tests/fakes/google.py`)로 바꿔 끼운다.
토큰을 DB에서 꺼내고 갱신하는 일은 `app/services/auth.py`의 `get_access_token()`이 한다.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
import logging
import os

from app.config import GOOGLE_SCOPES, LIMITS, Settings

# Google은 'email'을 'https://www.googleapis.com/auth/userinfo.email'로 돌려주고,
# include_granted_scopes로 예전에 허용한 범위가 더해질 수 있다. 범위가 달라도 토큰 교환을 멈추지 않게 하고,
# 빠진 범위는 missing_scopes()로 직접 확인한다.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
HTTP_TIMEOUT_SECONDS = 15
SCOPE_ALIASES = {
    "email": "https://www.googleapis.com/auth/userinfo.email",
    "profile": "https://www.googleapis.com/auth/userinfo.profile",
}

log = logging.getLogger(__name__)


class GoogleError(Exception):
    """Google 호출 실패. `code`는 화면 안내와 `gmail_watches.last_error`에 쓰는 짧은 이름이다."""

    code = "google_error"


class TokenExpired(GoogleError):
    """갱신 토큰이 만료·취소됐거나 읽을 수 없다. 다시 로그인해야 한다."""

    code = "token_expired"


class GoogleUnavailable(GoogleError):
    """통신 오류처럼 잠시 뒤 다시 하면 될 수 있는 실패."""

    code = "google_unavailable"


class WatchFailed(GoogleError):
    """Gmail 감시 등록(users.watch) 실패."""

    code = "watch_failed"


@dataclass(frozen=True)
class GoogleLogin:
    """로그인 콜백에서 코드를 바꿔 받은 결과."""

    sub: str
    email: str
    name: str | None
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scopes: list[str]


@dataclass(frozen=True)
class AccessToken:
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class WatchResponse:
    history_id: str
    expiration: datetime


def normalize_scopes(scopes) -> set[str]:
    if isinstance(scopes, str):
        scopes = scopes.split()
    return {SCOPE_ALIASES.get(scope, scope) for scope in scopes or []}


def missing_scopes(granted) -> list[str]:
    """`GOOGLE_SCOPES` 중 허용되지 않은 범위(사용자가 동의 화면에서 뺀 것 포함)."""
    have = normalize_scopes(granted)
    return [scope for scope in GOOGLE_SCOPES if SCOPE_ALIASES.get(scope, scope) not in have]


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@lru_cache(maxsize=1)
def _gmail_discovery() -> str:
    # 패키지에 들어 있는 Gmail API 설명서를 한 번만 읽어 재사용한다(네트워크 호출 없음).
    from googleapiclient.discovery_cache import get_static_doc

    return get_static_doc("gmail", "v1")


class GoogleClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _flow(self, code_verifier: str, state: str | None = None):
        from google_auth_oauthlib.flow import Flow

        config = {"web": {
            "client_id": self.settings.google_oauth_client_id,
            "client_secret": self.settings.google_oauth_client_secret,
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
        }}
        flow = Flow.from_client_config(
            config, scopes=list(GOOGLE_SCOPES), state=state,
            code_verifier=code_verifier, autogenerate_code_verifier=False,
        )
        flow.redirect_uri = self.settings.google_oauth_redirect_uri
        return flow

    def authorization_url(self, state: str, code_verifier: str, consent: bool = False) -> str:
        """Google 동의 화면 주소. 갱신 토큰을 받도록 offline, 기존 허용 범위를 합치도록 include_granted_scopes."""
        options = {"access_type": "offline", "include_granted_scopes": "true"}
        if consent:
            options["prompt"] = "consent"
        url, _ = self._flow(code_verifier, state).authorization_url(**options)
        return url

    def exchange_code(self, code: str, code_verifier: str) -> GoogleLogin:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token

        try:
            token = self._flow(code_verifier).fetch_token(code=code)
            claims = id_token.verify_oauth2_token(
                token["id_token"], Request(), self.settings.google_oauth_client_id,
                clock_skew_in_seconds=10,
            )
        except Exception as error:  # oauthlib·통신·ID 토큰 검증 오류를 한 가지 실패로 묶는다
            log.warning("Google 코드 교환 실패: %s", type(error).__name__)
            raise GoogleError(type(error).__name__) from error
        if "expires_at" in token:
            expires_at = datetime.fromtimestamp(token["expires_at"], UTC)
        else:
            expires_at = datetime.now(UTC) + timedelta(seconds=int(token.get("expires_in", 0)))
        return GoogleLogin(
            sub=claims["sub"], email=claims.get("email", ""), name=claims.get("name"),
            access_token=token["access_token"], refresh_token=token.get("refresh_token"),
            expires_at=expires_at, scopes=sorted(normalize_scopes(token.get("scope", []))),
        )

    def refresh(self, refresh_token: str) -> AccessToken:
        from google.auth.exceptions import RefreshError, TransportError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        credentials = Credentials(
            None, refresh_token=refresh_token, token_uri=TOKEN_URI,
            client_id=self.settings.google_oauth_client_id,
            client_secret=self.settings.google_oauth_client_secret,
        )
        try:
            credentials.refresh(Request())
        except RefreshError as error:
            if "invalid_grant" in str(error):
                raise TokenExpired("invalid_grant") from error
            raise GoogleUnavailable(type(error).__name__) from error
        except TransportError as error:
            raise GoogleUnavailable(type(error).__name__) from error
        return AccessToken(credentials.token, _utc(credentials.expiry))

    def gmail(self, access_token: str):
        """접근 토큰 하나로 Gmail API 클라이언트를 만든다(7·9가 메일 읽기·보내기에 쓴다)."""
        import google_auth_httplib2
        import httplib2
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build_from_document

        http = google_auth_httplib2.AuthorizedHttp(
            Credentials(access_token), http=httplib2.Http(timeout=HTTP_TIMEOUT_SECONDS),
        )
        return build_from_document(_gmail_discovery(), http=http)

    def watch(self, access_token: str, topic: str) -> WatchResponse:
        # labelIds를 주면 그 라벨에 관한 변경만 알림이 온다(users.watch 공식 설명). 받은편지함만 본다.
        body = {"topicName": topic, "labelIds": ["INBOX"]}
        try:
            response = self.gmail(access_token).users().watch(userId="me", body=body).execute(
                num_retries=LIMITS["GMAIL_MAX_RETRIES"],
            )
        except Exception as error:  # HttpError·통신 오류
            raise WatchFailed(_error_label(error)) from error
        expiration = datetime.fromtimestamp(int(response["expiration"]) / 1000, UTC)
        return WatchResponse(str(response["historyId"]), expiration)

    def stop(self, access_token: str) -> None:
        try:
            self.gmail(access_token).users().stop(userId="me").execute(
                num_retries=LIMITS["GMAIL_MAX_RETRIES"],
            )
        except Exception as error:
            raise GoogleUnavailable(_error_label(error)) from error


def _error_label(error: Exception) -> str:
    status = getattr(error, "status_code", None)
    if status:
        log.warning("Gmail API 오류 HTTP %s: %s", status, error)
        return f"HTTP {status}"
    log.warning("Gmail API 호출 실패: %s", type(error).__name__)
    return type(error).__name__
