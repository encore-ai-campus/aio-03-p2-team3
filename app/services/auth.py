"""Google 로그인 저장, 토큰 암호화, 사용자별 접근 토큰, 본인 데이터만 열기(CONTRACT 7·10절, 계획 6절).

- 토큰 암호화: `cryptography`의 Fernet(AES-128-CBC + HMAC-SHA256). 키는 `TOKEN_ENCRYPTION_KEY`
  (Fernet 키 형식, 만드는 법은 `.env.example`). 갱신 토큰·접근 토큰은 암호문으로만 DB에 둔다.
- 갱신 토큰이 만료·취소되면 저장한 토큰을 지우고 `gmail_watches`를 `error`/`token_expired`로 바꿔
  화면이 '다시 로그인'을 안내하게 한다.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from app.clients.gmail import GoogleError, GoogleLogin, TokenExpired
from app.config import Settings
from app.db.engine import Database
from app.db.models import GmailWatch, GoogleToken, User

ACCESS_TOKEN_MARGIN = timedelta(seconds=60)
LOGIN_SETTINGS = {
    "GOOGLE_OAUTH_CLIENT_ID": "google_oauth_client_id",
    "GOOGLE_OAUTH_CLIENT_SECRET": "google_oauth_client_secret",
    "GOOGLE_OAUTH_REDIRECT_URI": "google_oauth_redirect_uri",
    "GMAIL_PUBSUB_TOPIC": "gmail_pubsub_topic",
    "TOKEN_ENCRYPTION_KEY": "token_encryption_key",
    "SESSION_SECRET": "session_secret",
}

log = logging.getLogger(__name__)


class ConfigMissing(GoogleError):
    code = "config_missing"


class TokenCipher:
    def __init__(self, key: str):
        self._fernet = Fernet(key.encode())  # 형식이 틀리면 ValueError

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode()).decode()


def make_cipher(settings: Settings) -> TokenCipher | None:
    try:
        return TokenCipher(settings.token_encryption_key) if settings.token_encryption_key else None
    except ValueError:
        return None


def missing_login_settings(settings: Settings) -> list[str]:
    """로그인에 필요한데 비었거나 형식이 틀린 환경변수 이름(값은 내보내지 않는다)."""
    missing = [name for name, field in LOGIN_SETTINGS.items() if not getattr(settings, field)]
    if settings.token_encryption_key and make_cipher(settings) is None:
        missing.append("TOKEN_ENCRYPTION_KEY(형식 오류)")
    return missing


@dataclass(frozen=True)
class GoogleAccess:
    """Google을 부르는 데 필요한 준비물 묶음. 서버가 뜰 때 한 번 만들어 `app.state.google_access`에 둔다."""

    database: Database
    google: object  # GoogleClient 또는 테스트용 가짜
    cipher: TokenCipher | None
    topic: str


def utcnow() -> datetime:
    return datetime.now(UTC)


def save_login(access: GoogleAccess, login: GoogleLogin, now: datetime | None = None) -> int:
    """사용자를 google_sub로 찾거나 만들고 토큰을 암호화해 저장한다. 사용자 id를 돌려준다."""
    if access.cipher is None:
        raise ConfigMissing("TOKEN_ENCRYPTION_KEY")
    now = now or utcnow()
    with access.database.session() as session:
        user = session.scalar(select(User).where(User.google_sub == login.sub))
        if user is None:
            user = User(google_sub=login.sub, email=login.email)
            session.add(user)
        user.email = login.email
        user.display_name = login.name
        user.last_login_at = now
        session.flush()
        token = session.get(GoogleToken, user.id)
        if token is None:
            token = GoogleToken(user_id=user.id)
            session.add(token)
        token.access_token_enc = access.cipher.encrypt(login.access_token)
        token.expires_at = login.expires_at
        token.scopes = list(login.scopes)
        # Google은 갱신 토큰을 처음 동의할 때만 준다. 새로 오지 않으면 저장한 것을 그대로 둔다.
        if login.refresh_token:
            token.refresh_token_enc = access.cipher.encrypt(login.refresh_token)
        return user.id


def has_refresh_token(access: GoogleAccess, google_sub: str) -> bool:
    with access.database.session() as session:
        token = session.scalar(
            select(GoogleToken).join(User, User.id == GoogleToken.user_id)
            .where(User.google_sub == google_sub)
        )
        return bool(token and token.refresh_token_enc)


def stored_scopes(access: GoogleAccess, user_id: int) -> list[str]:
    with access.database.session() as session:
        token = session.get(GoogleToken, user_id)
        return list(token.scopes or []) if token else []


def get_access_token(access: GoogleAccess, user_id: int, now: datetime | None = None) -> str:
    """사용자의 접근 토큰. 만료가 1분 안쪽이면 갱신 토큰으로 새로 받아 암호화해 저장한다.

    갱신 토큰이 만료·취소됐거나 읽을 수 없으면 `mark_reauth_required()` 뒤 `TokenExpired`를 낸다.
    통신 오류는 `GoogleUnavailable`로 그대로 올린다(토큰은 지우지 않음).
    """
    if access.cipher is None:
        raise ConfigMissing("TOKEN_ENCRYPTION_KEY")
    now = now or utcnow()
    with access.database.session() as session:
        token = session.get(GoogleToken, user_id)
        stored = None if token is None else (token.access_token_enc, token.refresh_token_enc, token.expires_at)
    try:
        if stored is None:
            raise TokenExpired("no_token")
        access_enc, refresh_enc, expires_at = stored
        if access_enc and expires_at and expires_at - ACCESS_TOKEN_MARGIN > now:
            return access.cipher.decrypt(access_enc)
        if not refresh_enc:
            raise TokenExpired("no_refresh_token")
        refresh_token = access.cipher.decrypt(refresh_enc)
        fresh = access.google.refresh(refresh_token)
    except (TokenExpired, InvalidToken) as error:
        mark_reauth_required(access, user_id)
        if isinstance(error, TokenExpired):
            raise
        raise TokenExpired("unreadable_token") from error
    with access.database.session() as session:
        token = session.get(GoogleToken, user_id)
        token.access_token_enc = access.cipher.encrypt(fresh.token)
        token.expires_at = fresh.expires_at
    return fresh.token


def mark_reauth_required(access: GoogleAccess, user_id: int) -> None:
    """쓸 수 없는 토큰을 지우고 감시 상태에 '다시 로그인 필요'를 남긴다."""
    log.warning("사용자 %s: Google 토큰을 쓸 수 없어 다시 로그인이 필요합니다", user_id)
    with access.database.session() as session:
        token = session.get(GoogleToken, user_id)
        if token is not None:
            token.access_token_enc = None
            token.refresh_token_enc = None
            token.expires_at = None
        watch = session.get(GmailWatch, user_id)
        if watch is None:
            watch = GmailWatch(user_id=user_id, topic=access.topic)
            session.add(watch)
        watch.status = "error"
        watch.last_error = TokenExpired.code


def get_owned(session, model, key, user_id: int):
    """id(기본 키)로 행 하나를 열되, 로그인한 사용자 것이 아니면 None. 화면은 None이면 404로 답한다."""
    row = session.get(model, key)
    if row is None or getattr(row, "user_id", None) != user_id:
        return None
    return row
