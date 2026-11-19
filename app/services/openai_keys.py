"""실행 환경 OpenAI 키(.env 우선)와 사용자별 키의 암호화 저장·실행 범위."""
from contextlib import contextmanager
from dataclasses import dataclass, field

from cryptography.fernet import InvalidToken
from sqlalchemy import select

from app.config import Settings, get_settings, validate_runtime
from app.db.engine import Database
from app.db.models import User, UserOpenAIKey
from app.llm.client import OpenAIKeyError, use_user_key
from app.services.auth import TokenCipher, make_cipher


def local_key(settings: Settings) -> str:
    """실행 환경의 공용 OpenAI 키(.env). 로컬은 전용 실행 검증을 지나고 서버는 그대로 쓴다.

    서버에서 이 키가 비어 있으면 사용자가 /settings에 등록한 DB 키를 쓴다(개인 PC 위임은 폐지했다)."""
    if settings.ai_runtime == "local":
        try:
            validate_runtime(settings)
        except ValueError:
            raise OpenAIKeyError("LOCAL_RUNTIME_REQUIRED", "전용 로컬 실행 명령으로 다시 시작해 주세요.") from None
    value = settings.openai_api_key.strip()
    if not value:
        raise OpenAIKeyError("LOCAL_KEY_REQUIRED", "실행 환경의 OPENAI_API_KEY를 지정하고 다시 시작하세요.")
    return value


def key_registered(database: Database, user_id: int, *, settings: Settings | None = None) -> bool:
    configured = settings or get_settings()
    if configured.ai_runtime == "local" or configured.openai_api_key.strip():
        try:
            UserKeyAccess(database, user_id, None, configured).read()
            return True
        except OpenAIKeyError:
            return False
    with database.session() as session:
        return session.get(UserOpenAIKey, user_id) is not None


def _require_server_storage(settings: Settings | None):
    if (settings or get_settings()).ai_runtime == "local":
        raise OpenAIKeyError("LOCAL_KEY_ENV_ONLY", "로컬 모드에서는 .env에서 키를 관리하세요.")


def save_key(database: Database, user_id: int, value: str, cipher: TokenCipher | None,
             *, settings: Settings | None = None) -> None:
    _require_server_storage(settings)
    value = value.strip()
    if not value or len(value) > 512 or any(char.isspace() or ord(char) < 33 or ord(char) > 126 for char in value):
        raise OpenAIKeyError("OPENAI_KEY_INVALID", "공백 없는 OpenAI API 키를 입력해 주세요. (최대 512자)", 400)
    if cipher is None:
        raise OpenAIKeyError("OPENAI_KEY_STORAGE_UNAVAILABLE", "서버의 키 암호화 설정을 확인해 주세요.", 503)
    with database.session() as session:
        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:
            raise OpenAIKeyError("USER_NOT_FOUND", "사용자를 찾을 수 없습니다.", 404)
        row = session.get(UserOpenAIKey, user_id)
        if row is None:
            row = UserOpenAIKey(user_id=user_id)
            session.add(row)
        row.api_key_enc = cipher.encrypt(value)


def delete_key(database: Database, user_id: int, *, settings: Settings | None = None) -> None:
    _require_server_storage(settings)
    with database.session() as session:
        session.scalar(select(User).where(User.id == user_id).with_for_update())
        row = session.get(UserOpenAIKey, user_id)
        if row is not None:
            session.delete(row)


@dataclass
class UserKeyAccess:
    database: Database
    user_id: int
    cipher: TokenCipher | None
    settings: Settings = field(default_factory=get_settings, repr=False)
    issue: OpenAIKeyError | None = field(default=None, init=False, repr=False)

    def read(self) -> str:
        try:
            # .env 공용 키가 있으면 로컬·서버 모두 이를 먼저 쓴다. 서버에서 비워 둘 때만 DB 키를 읽는다.
            if self.settings.ai_runtime == "local" or self.settings.openai_api_key.strip():
                return local_key(self.settings)
            with self.database.session() as session:
                row = session.get(UserOpenAIKey, self.user_id)
                encrypted = row.api_key_enc if row is not None else None
            if encrypted is None:
                raise OpenAIKeyError()
            if self.cipher is None:
                raise OpenAIKeyError("OPENAI_KEY_UNAVAILABLE", "등록된 키를 읽을 수 없습니다. 서버의 암호화 설정을 확인해 주세요.")
            try:
                value = self.cipher.decrypt(encrypted).strip()
            except (InvalidToken, ValueError):
                raise OpenAIKeyError("OPENAI_KEY_UNAVAILABLE", "등록된 키를 읽을 수 없습니다. 설정에서 키를 다시 등록해 주세요.") from None
            if not value:
                raise OpenAIKeyError()
            return value
        except OpenAIKeyError as error:
            self.issue = error
            raise

@contextmanager
def user_openai(database: Database, user_id: int, *, settings: Settings | None = None,
                cipher: TokenCipher | None = None):
    """LLM 호출 범위를 연다. 개인 PC 위임(local_worker)은 폐지했고 언제나 실행 환경/DB 키로 직접 호출한다."""
    configured = settings or get_settings()
    access = UserKeyAccess(database, user_id,
                           None if configured.ai_runtime == "local" else cipher or make_cipher(configured), configured)
    with use_user_key(access.read, configured):
        yield access
