"""계약의 설정·상수. 비밀값은 환경에서만 읽는다."""

from dataclasses import dataclass, field
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
import os
import socket

from dotenv import load_dotenv

GOOGLE_SCOPES = (
    "openid", "email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
)

LIMITS = {
    "LLM_MAX_RETRIES": 2,
    "LLM_INVALID_OUTPUT_RETRIES": 1,
    "LLM_TIMEOUT_SECONDS": 20,
    "GMAIL_MAX_RETRIES": 2,
    "REFLECTION_MAX_RETRIES_TOTAL": 3,
    "REFLECTION_MAX_RETRIES_BY_TYPE": {
        "hallucination": 2, "wrong_tool": 1, "missing_param": 1, "inconsistent": 2,
    },
    "CANDIDATE_MIN": 2, "CANDIDATE_MAX": 3,
    "SUMMARY_TRIGGER_MESSAGES": 8, "SUMMARY_TRIGGER_CHARS": 12000,
    "SUMMARY_KEEP_RECENT": 4, "WATCH_RENEW_AFTER_HOURS": 24,
    "INBOX_POLL_SECONDS": 90, "QUOTE_VALID_DAYS": 30, "VAT_RATE": 0.10,
}

DEFAULT_REQUIRED_FIELDS = [
    {"key": "customer_name", "label": "거래처명"},
    {"key": "item_name", "label": "품목"},
    {"key": "quantity", "label": "수량"},
    {"key": "due_date", "label": "납기"},
]

_local_listener = ContextVar("local_listener", default=None)


@contextmanager
def local_listener(listener: socket.socket):
    """전용 실행기가 연 실제 소켓을 보관한다. 환경변수·요청 헤더는 허가가 아니다."""
    token = _local_listener.set(listener)
    try:
        yield
    finally:
        _local_listener.reset(token)


def validate_runtime(settings: "Settings") -> None:
    if settings.ai_runtime == "server":
        return
    if any(os.getenv(name) for name in ("RENDER", "RENDER_SERVICE_ID", "RENDER_EXTERNAL_URL", "PORT")):
        raise ValueError("공용 실행·Render에서는 AI_RUNTIME=local을 사용할 수 없습니다")
    listener = _local_listener.get()
    try:
        allowed = (listener is not None and listener.family in {socket.AF_INET, socket.AF_INET6}
                   and ip_address(listener.getsockname()[0]).is_loopback
                   and listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN))
    except (OSError, ValueError):
        allowed = False
    if not allowed:
        raise ValueError("AI_RUNTIME=local은 uv run python -m app.local로만 실행하세요")


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default="", repr=False)
    openai_api_key: str = field(default="", repr=False)
    openai_model: str = ""
    ai_runtime: str = "server"
    local_owner_google_sub: str = field(default="", repr=False)
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = field(default="", repr=False)
    google_oauth_redirect_uri: str = ""
    gmail_pubsub_topic: str = ""
    pubsub_push_audience: str = ""
    pubsub_push_service_account: str = ""
    pubsub_push_token: str = field(default="", repr=False)
    token_encryption_key: str = field(default="", repr=False)
    session_secret: str = field(default="", repr=False)
    app_base_url: str = ""
    reflection_enabled_default: bool = False
    frontend_origins: str = ""
    session_same_site: str = "lax"

    def __post_init__(self):
        if self.ai_runtime not in {"server", "local"}:
            raise ValueError("AI_RUNTIME은 server 또는 local이어야 합니다")

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        path = Path(__file__).parent / "db" / "local.sqlite3"
        return f"sqlite:///{path}"


@lru_cache(maxsize=1)
def get_settings(env_file: str | None = None) -> Settings:
    load_dotenv(env_file) if env_file is not None else load_dotenv()
    values = {name: os.getenv(name.upper(), "") for name in Settings.__dataclass_fields__
              if name != "openai_api_key"}
    values["ai_runtime"] = values["ai_runtime"].strip() or "server"
    if values["ai_runtime"] == "local":
        values["openai_api_key"] = os.getenv("OPENAI_API_KEY", "")
    values["reflection_enabled_default"] = (
        values["reflection_enabled_default"].lower() == "true"
    )
    return Settings(**values)
