"""사용자별 OpenAI 키의 암호화 저장과 실행 범위. 서버 공용 키로 대체하지 않는다."""
from contextlib import contextmanager
from dataclasses import dataclass, field

from cryptography.fernet import InvalidToken
from sqlalchemy import select

from app.config import Settings, get_settings, validate_runtime
from app.db.engine import Database
from app.db.models import User, UserOpenAIKey
from app.llm.client import OpenAIKeyError, use_user_key
from app.services.auth import TokenCipher, make_cipher


def key_registered(database: Database, user_id: int, *, settings: Settings | None = None) -> bool:
    configured = settings or get_settings()
    if configured.ai_runtime == "local":
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
            if self.settings.ai_runtime == "local":
                return self._read_local()
            with self.database.session() as session:
                user = session.get(User, self.user_id)
                if user is not None and user.ai_execution_mode == "local_worker":
                    raise OpenAIKeyError("LOCAL_WORKER_NOT_READY", "개인 실행 프로그램의 AI 연결은 다음 단계에서 제공됩니다. 서버 저장 키로 전환하지 않습니다.")
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

    def _read_local(self) -> str:
        try:
            validate_runtime(self.settings)
        except ValueError:
            raise OpenAIKeyError("LOCAL_RUNTIME_REQUIRED", "전용 로컬 실행 명령으로 다시 시작해 주세요.") from None
        owner = self.settings.local_owner_google_sub.strip()
        if not owner:
            raise OpenAIKeyError("LOCAL_OWNER_REQUIRED", "본인 Google 식별자를 확인하고 .env의 LOCAL_OWNER_GOOGLE_SUB를 지정하세요.")
        with self.database.session() as session:
            user = session.get(User, self.user_id)
            verified_owner = user is not None and user.last_login_at is not None and user.google_sub == owner
        if not verified_owner:
            raise OpenAIKeyError("LOCAL_OWNER_MISMATCH", "로컬 AI는 지정한 본인 Google 계정으로만 사용할 수 있습니다.", 403)
        value = self.settings.openai_api_key.strip()
        if not value:
            raise OpenAIKeyError("LOCAL_KEY_REQUIRED", "로컬 .env에 OPENAI_API_KEY를 지정하고 다시 시작하세요.")
        return value


@contextmanager
def user_openai(database: Database, user_id: int, *, settings: Settings | None = None,
                cipher: TokenCipher | None = None):
    configured = settings or get_settings()
    access = UserKeyAccess(database, user_id,
                           None if configured.ai_runtime == "local" else cipher or make_cipher(configured), configured)
    with use_user_key(access.read, configured):
        yield access
