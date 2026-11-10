"""계약의 설정·상수. 비밀값은 환경에서만 읽는다."""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
import os

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


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default="", repr=False)
    gemini_api_key: str = field(default="", repr=False)
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

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        path = Path(__file__).parent / "db" / "local.sqlite3"
        return f"sqlite:///{path}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    load_dotenv()
    values = {name: os.getenv(name.upper(), "") for name in Settings.__dataclass_fields__}
    values["reflection_enabled_default"] = (
        values["reflection_enabled_default"].lower() == "true"
    )
    return Settings(**values)
