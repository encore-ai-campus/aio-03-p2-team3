"""사용자별 OpenAI 키의 암호화 저장과 실행 범위. 서버 공용 키로 대체하지 않는다."""
from contextlib import contextmanager
from dataclasses import dataclass, field

from cryptography.fernet import InvalidToken
from sqlalchemy import select

from app.config import Settings, get_settings
from app.db.engine import Database
from app.db.models import User, UserOpenAIKey
from app.llm.client import OpenAIKeyError, use_user_key
from app.services.auth import TokenCipher, make_cipher


def key_registered(database: Database, user_id: int) -> bool:
    with database.session() as session:
        return session.get(UserOpenAIKey, user_id) is not None


def save_key(database: Database, user_id: int, value: str, cipher: TokenCipher | None) -> None:
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


def delete_key(database: Database, user_id: int) -> None:
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
    issue: OpenAIKeyError | None = field(default=None, init=False, repr=False)

    def read(self) -> str:
        try:
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
    configured = settings or get_settings()
    access = UserKeyAccess(database, user_id, cipher or make_cipher(configured))
    with use_user_key(access.read, configured):
        yield access
