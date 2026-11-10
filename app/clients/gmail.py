"""사용자별 Google OAuth·Gmail API 호출(CONTRACT 1·10절, 계획 6절).

실제 Google을 부르는 곳은 이 파일의 `GoogleClient` 하나다. 서버가 뜰 때 한 번 만들어
`app.state.google`에 두고, 테스트는 같은 메서드를 가진 가짜(`tests/fakes/google.py`)로 바꿔 끼운다.
토큰을 DB에서 꺼내고 갱신하는 일은 `app/services/auth.py`의 `get_access_token()`이 한다.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from base64 import urlsafe_b64decode
from email.header import decode_header, make_header
from email.message import Message
from email.utils import getaddresses, parseaddr
from functools import lru_cache
from html.parser import HTMLParser
import logging
import os
from time import monotonic

from app.config import GOOGLE_SCOPES, LIMITS, Settings
from app.graph.state import EmailMessage

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

    def verify_push_token(self, token: str, audience: str, service_account: str) -> None:
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(token, _certificate_request, audience)
        if claims.get("email") != service_account or claims.get("email_verified") is not True:
            raise ValueError("Pub/Sub 서비스 계정 불일치")

    def list_history(self, gmail, history_id: str, page_token: str | None = None) -> dict:
        try:
            return gmail.users().history().list(
                userId="me", startHistoryId=history_id,
                historyTypes=["messageAdded"], pageToken=page_token,
            ).execute(num_retries=LIMITS["GMAIL_MAX_RETRIES"])
        except Exception as error:
            raise GoogleUnavailable(_error_label(error)) from error

    def get_message(self, gmail, message_id: str) -> dict:
        try:
            return gmail.users().messages().get(
                userId="me", id=message_id, format="full",
            ).execute(num_retries=LIMITS["GMAIL_MAX_RETRIES"])
        except Exception as error:
            raise GoogleUnavailable(_error_label(error)) from error

    def get_attachment(self, gmail, message_id: str, attachment_id: str) -> str:
        try:
            return gmail.users().messages().attachments().get(
                userId="me", messageId=message_id, id=attachment_id,
            ).execute(num_retries=LIMITS["GMAIL_MAX_RETRIES"])["data"]
        except Exception as error:
            raise GoogleUnavailable(_error_label(error)) from error

    def get_reply_headers(self, gmail, message_id: str) -> dict[str, str]:
        """답장에 필요한 원본 머리글(From·Reply-To·Message-ID·References)만 읽는다. 읽기라 재시도한다."""
        try:
            raw = gmail.users().messages().get(
                userId="me", id=message_id, format="metadata",
                metadataHeaders=["From", "Reply-To", "Message-ID", "References"],
            ).execute(num_retries=LIMITS["GMAIL_MAX_RETRIES"])
        except Exception as error:
            raise GoogleUnavailable(_error_label(error)) from error
        return {h["name"].lower(): h["value"] for h in raw.get("payload", {}).get("headers", [])}

    def send_message(self, gmail, raw: str, thread_id: str) -> str:
        """같은 threadId로 메일 하나를 보내고 보낸 메일 id를 돌려준다.

        자동 재시도하지 않는다(num_retries=0): 시간 초과여도 실제로는 나갔을 수 있어 다시 보내면 두 번 갈 수 있다.
        """
        try:
            response = gmail.users().messages().send(
                userId="me", body={"raw": raw, "threadId": thread_id},
            ).execute(num_retries=0)
        except Exception as error:
            raise GoogleUnavailable(_error_label(error)) from error
        return str(response["id"])


@lru_cache(maxsize=4)
def _certificate_response(url: str, window: int):
    from google.auth.transport.requests import Request

    return Request()(url, method="GET", timeout=HTTP_TIMEOUT_SECONDS)


def _certificate_request(url, method="GET", **kwargs):
    # 서명·대상·만료는 매번 확인하고 공개 키 응답만 5분 단위로 재사용한다.
    return _certificate_response(url, int(monotonic() // 300))


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"br", "p", "div", "li", "tr"} and not self.hidden:
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li", "tr"} and not self.hidden:
            self.text.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


def decode_message(raw: dict, own_email: str, attachment_loader=None) -> EmailMessage:
    """Gmail full 응답을 계약의 메일 형식으로 바꾼다. 첨부 파일 본문은 읽지 않는다."""
    payload = raw["payload"]
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    sender_name, sender = parseaddr(str(make_header(decode_header(headers.get("from", "")))))
    plain, html = [], []

    def read_part(part):
        part_headers = {h["name"].lower(): h["value"] for h in part.get("headers", [])}
        if part.get("filename") or part_headers.get("content-disposition", "").lower().startswith("attachment"):
            return
        mime = part.get("mimeType", "")
        if mime in {"text/plain", "text/html"}:
            body = part.get("body", {})
            encoded = body.get("data", "")
            if not encoded and body.get("attachmentId"):
                if attachment_loader is None:
                    raise ValueError("메일 본문 조회가 필요합니다")
                encoded = attachment_loader(body["attachmentId"])
            content_type = Message()
            content_type["content-type"] = part_headers.get("content-type", mime)
            decoded = urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            value = decoded.decode(content_type.get_content_charset() or "utf-8", errors="replace")
            (plain if mime == "text/plain" else html).append(value)
        for child in part.get("parts", []):
            read_part(child)

    read_part(payload)
    if plain:
        body_text = "\n".join(plain)
    else:
        parser = _HTMLText()
        parser.feed("\n".join(html))
        body_text = "\n".join(line.strip() for line in "".join(parser.text).splitlines() if line.strip())
    received_at = datetime.fromtimestamp(int(raw["internalDate"]) / 1000, UTC)
    return {
        "gmail_message_id": raw["id"], "thread_id": raw["threadId"],
        "rfc_message_id": headers.get("message-id"), "from_addr": sender,
        "from_name": sender_name or None,
        "to_addrs": [addr for _, addr in getaddresses([headers.get("to", "")])],
        "subject": str(make_header(decode_header(headers.get("subject", "")))),
        "body_text": body_text, "received_at": received_at.isoformat(),
        "direction": "out" if sender.casefold() == own_email.casefold() or "SENT" in raw.get("labelIds", []) else "in",
    }


def _error_label(error: Exception) -> str:
    status = getattr(error, "status_code", None) or getattr(getattr(error, "resp", None), "status", None)
    if status:
        log.warning("Gmail API 오류 HTTP %s (%s)", status, type(error).__name__)
        return f"HTTP {status}"
    log.warning("Gmail API 호출 실패: %s", type(error).__name__)
    return type(error).__name__
