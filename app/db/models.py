"""CONTRACT 7절. JSON은 Postgres JSONB / SQLite JSON으로 저장한다."""

from datetime import UTC, datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow():
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("시각은 UTC 시간대와 함께 저장해야 합니다")
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


JSON_VALUE = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class Owned:
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)


class Created:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Updated:
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class User(Base, Created):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    google_sub: Mapped[str] = mapped_column(String, unique=True)
    email: Mapped[str] = mapped_column(String)
    display_name: Mapped[str | None] = mapped_column(String)
    reflection_enabled: Mapped[bool] = mapped_column(Boolean, default=lambda: _default_reflection())
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


def _default_reflection():
    from app.config import get_settings
    return get_settings().reflection_enabled_default


class GoogleToken(Base, Updated):
    __tablename__ = "google_tokens"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    access_token_enc: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    scopes: Mapped[list] = mapped_column(JSON_VALUE, default=list)


class GmailWatch(Base):
    __tablename__ = "gmail_watches"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    topic: Mapped[str] = mapped_column(String)
    history_id: Mapped[str | None] = mapped_column(String)
    expiration: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_renewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String, default="stopped")
    last_error: Mapped[str | None] = mapped_column(Text)


class ProcessedMessage(Base, Owned, Created):
    __tablename__ = "processed_messages"
    __table_args__ = (UniqueConstraint("user_id", "gmail_message_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    gmail_message_id: Mapped[str] = mapped_column(String)
    thread_id: Mapped[str] = mapped_column(String, index=True)
    history_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="processing")
    skip_reason: Mapped[str | None] = mapped_column(String)
    notice: Mapped[str | None] = mapped_column(String)
    run_id: Mapped[str | None] = mapped_column(String)
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ThreadMessage(Base, Owned):
    __tablename__ = "thread_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(String, index=True)
    gmail_message_id: Mapped[str] = mapped_column(String)
    direction: Mapped[str] = mapped_column(String)
    from_addr: Mapped[str] = mapped_column(String)
    to_addrs: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    subject: Mapped[str] = mapped_column(Text)
    body_text: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ThreadMemory(Base, Updated):
    __tablename__ = "thread_memory"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String, primary_key=True)
    counterparty_email: Mapped[str | None] = mapped_column(String)
    summary: Mapped[str | None] = mapped_column(Text)
    summarized_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    confirmed_terms: Mapped[dict] = mapped_column(JSON_VALUE, default=dict)
    last_result: Mapped[dict | None] = mapped_column(JSON_VALUE)


class ReplyCandidate(Base, Owned, Created):
    __tablename__ = "reply_candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    thread_id: Mapped[str] = mapped_column(String)
    source_message_id: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    label: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    asks_fields: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    notice: Mapped[str | None] = mapped_column(String)
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("quotes.id"))
    status: Mapped[str] = mapped_column(String, default="pending")


class Approval(Base, Owned):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("reply_candidates.id"), unique=True)
    approved_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    sent_message_id: Mapped[str | None] = mapped_column(String)
    send_status: Mapped[str] = mapped_column(String, default="sending")
    error: Mapped[str | None] = mapped_column(Text)


class DealTerms(Base, Owned, Created):
    __tablename__ = "deal_terms"
    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(String)
    source_message_id: Mapped[str] = mapped_column(String)
    run_id: Mapped[str] = mapped_column(String, index=True)
    terms: Mapped[dict] = mapped_column(JSON_VALUE)
    missing_fields: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    required_source: Mapped[str] = mapped_column(String)


class Quote(Base, Owned, Created):
    __tablename__ = "quotes"
    __table_args__ = (UniqueConstraint("user_id", "quote_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(String)
    run_id: Mapped[str] = mapped_column(String, index=True)
    deal_terms_id: Mapped[int | None] = mapped_column(ForeignKey("deal_terms.id"))
    quote_no: Mapped[str] = mapped_column(String)
    draft: Mapped[dict] = mapped_column(JSON_VALUE)
    status: Mapped[str] = mapped_column(String, default="needs_price")
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class UserPreference(Base, Updated):
    __tablename__ = "user_preferences"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict | list | str | int | bool | None] = mapped_column(JSON_VALUE)


class CompanyProfile(Base, Updated):
    __tablename__ = "company_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    company_name: Mapped[str | None] = mapped_column(String)
    business_no: Mapped[str | None] = mapped_column(String)
    ceo_name: Mapped[str | None] = mapped_column(String)
    contact: Mapped[str | None] = mapped_column(String)


class PriceListItem(Base, Owned, Updated):
    __tablename__ = "price_list_items"
    __table_args__ = (UniqueConstraint("user_id", "item_name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    item_name: Mapped[str] = mapped_column(String)
    unit: Mapped[str | None] = mapped_column(String)
    unit_price: Mapped[int] = mapped_column(BigInteger)


class CounterpartyHistory(Base, Owned):
    __tablename__ = "counterparty_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    counterparty_email: Mapped[str] = mapped_column(String)
    thread_id: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text)
    deal_terms: Mapped[dict] = mapped_column(JSON_VALUE)
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("quotes.id"))
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime())


class Run(Base, Owned):
    __tablename__ = "runs"
    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    mode: Mapped[str] = mapped_column(String)
    message_id: Mapped[str] = mapped_column(String)
    thread_id: Mapped[str] = mapped_column(String)
    reflection_enabled: Mapped[bool] = mapped_column(Boolean)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    end_reason: Mapped[str | None] = mapped_column(String)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    scenario: Mapped[str | None] = mapped_column(String)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    event: Mapped[str] = mapped_column(String)
    node: Mapped[str | None] = mapped_column(String)
    tool: Mapped[str | None] = mapped_column(String)
    detail: Mapped[dict] = mapped_column(JSON_VALUE, default=dict)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
