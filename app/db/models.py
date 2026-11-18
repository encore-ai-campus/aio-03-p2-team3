"""CONTRACT 7절. JSON은 Postgres JSONB / SQLite JSON으로 저장한다."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, LargeBinary, String, Text, UniqueConstraint, Uuid, text
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
    """google_sub는 Gmail/Calendar 연결 사용자가 쓰고 Supabase 로그인 사용자는 supabase_uid로
    구분한다(CONTRACT 7.1절, 계획 5절). 두 값 모두 유일하고 아직 연결 전이면 NULL이다."""
    __tablename__ = "users"
    __table_args__ = (Index("uq_users_supabase_uid", "supabase_uid", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    google_sub: Mapped[str | None] = mapped_column(String, unique=True)
    supabase_uid: Mapped[UUID | None] = mapped_column(Uuid())
    email: Mapped[str] = mapped_column(String)
    display_name: Mapped[str | None] = mapped_column(String)
    reflection_enabled: Mapped[bool] = mapped_column(Boolean, default=lambda: _default_reflection())
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    ai_execution_mode: Mapped[str] = mapped_column(String, default="stored_key", server_default="stored_key")


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


class CalendarToken(Base, Updated):
    __tablename__ = "calendar_tokens"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    google_sub: Mapped[str] = mapped_column(String)
    refresh_token_enc: Mapped[str] = mapped_column(Text)
    access_token_enc: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    scopes: Mapped[list] = mapped_column(JSON_VALUE, default=list)


class CalendarEventReceipt(Base, Created):
    """calendar_event_receipts — 일정 등록 멱영수증(계획 2절). 같은 action의 재실행은 이 표로
    같은 결과를 돌려주고 다른 content_hash는 거부한다. 이벤트 ID는 등록 때 결정적으로 정한다."""
    __tablename__ = "calendar_event_receipts"
    action_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_id: Mapped[str] = mapped_column(String(128))
    calendar_id: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String(64))


class CalendarOAuthAttempt(Base):
    """서명 쿠키를 복원해도 재사용하지 못하는 일회성 서버 state·암호화 PKCE."""
    __tablename__ = "calendar_oauth_attempts"
    state_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    google_sub: Mapped[str] = mapped_column(String)
    verifier_enc: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    consent: Mapped[bool] = mapped_column(Boolean)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class UserOpenAIKey(Base, Updated):
    __tablename__ = "user_openai_keys"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    api_key_enc: Mapped[str] = mapped_column(Text)


class WorkerPairing(Base, Created):
    __tablename__ = "worker_pairings"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    secret_hash: Mapped[str] = mapped_column(String)
    code_hash: Mapped[str] = mapped_column(String, unique=True)
    device_name: Mapped[str] = mapped_column(String(80))
    capabilities: Mapped[dict] = mapped_column(JSON_VALUE)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    last_polled_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class WorkerDevice(Base, Owned, Created):
    __tablename__ = "worker_devices"
    __table_args__ = (Index("uq_worker_active_user", "user_id", unique=True,
                           sqlite_where=text("revoked_at IS NULL"),
                           postgresql_where=text("revoked_at IS NULL")),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    scopes: Mapped[list] = mapped_column(JSON_VALUE, default=lambda: ["ai:claim", "ai:complete"])
    capabilities: Mapped[dict] = mapped_column(JSON_VALUE)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class WorkerJob(Base, Owned, Created):
    __tablename__ = "worker_jobs"
    # PC 폴링 claim과 대기열 용량 확인이 (user_id, status)로 걸러 만든 순서대로 찾는다.
    __table_args__ = (Index("ix_worker_jobs_user_status", "user_id", "status"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String, unique=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("worker_devices.id"), index=True)
    run_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    schema_id: Mapped[str] = mapped_column(String)
    schema_version: Mapped[str] = mapped_column(String)
    payload: Mapped[dict | None] = mapped_column(JSON_VALUE, nullable=True)
    result_hash: Mapped[str | None] = mapped_column(String)
    result_enc: Mapped[str | None] = mapped_column(Text)
    error_kind: Mapped[str | None] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    heartbeat_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class WorkerRateLimit(Base):
    __tablename__ = "worker_rate_limits"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    window: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


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
    # 메일함 목록의 스레드별 최신 처리(max id) 집계와 스레드 상세가 (user_id, thread_id)로 읽는다.
    # recovery는 시작 복구 pending()이 처리 중이면서 분류 결과가 있는 행만 골라내는 부분 인덱스다.
    __table_args__ = (UniqueConstraint("user_id", "gmail_message_id"),
                      Index("ix_processed_messages_user_thread", "user_id", "thread_id", "id"),
                      Index("ix_processed_messages_recovery", "id",
                            sqlite_where=text("status = 'processing' AND triage IS NOT NULL"),
                            postgresql_where=text("status = 'processing' AND triage IS NOT NULL")),)
    id: Mapped[int] = mapped_column(primary_key=True)
    gmail_message_id: Mapped[str] = mapped_column(String)
    thread_id: Mapped[str] = mapped_column(String, index=True)
    history_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="processing")
    skip_reason: Mapped[str | None] = mapped_column(String)
    notice: Mapped[str | None] = mapped_column(String)
    run_id: Mapped[str | None] = mapped_column(String)
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    triage: Mapped[dict | None] = mapped_column(JSON_VALUE)


class ThreadMessage(Base, Owned):
    __tablename__ = "thread_messages"
    # 메일함 목록·상세가 (user_id, gmail_message_id)로 원문을 조인하고, 스레드 조회·장기 기억
    # 요약이 (user_id, thread_id)의 원문을 보낸 시각 순으로 읽는다.
    __table_args__ = (Index("ix_thread_messages_user_gmail", "user_id", "gmail_message_id"),
                      Index("ix_thread_messages_user_thread_sent", "user_id", "thread_id", "sent_at"))
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
    # 스레드 상세가 (user_id, thread_id)의 후보를 만든 순서로 읽고, 메일함 폴링이
    # 대기 중 후보 집계를 (user_id, status)로 센다.
    __table_args__ = (Index("ix_reply_candidates_user_thread", "user_id", "thread_id"),
                      Index("ix_reply_candidates_user_status", "user_id", "status"))
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
    trade_doc_id: Mapped[int | None] = mapped_column(ForeignKey("trade_documents.id"))
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


class TradeDocument(Base, Owned, Created):
    """CONTRACT 15.7절 trade_documents — 무역서류(kekorea-port 2~6). draft는 `TradeDocDraft`
    (계약 15.5절) JSON이고 PL은 그 안 `packing_totals`에 원본/계산 합계 비교·승인 상태를 담는다."""
    __tablename__ = "trade_documents"
    # 문서 목록이 (user_id, doc_kind)의 최근 문서를, 작업현황이 본인 문서 전체를 만든 순서로 읽는다.
    __table_args__ = (UniqueConstraint("user_id", "doc_no"),
                      Index("ix_trade_documents_user_kind_id", "user_id", "doc_kind", "id"),
                      Index("ix_trade_documents_user_created", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[str] = mapped_column(String)
    run_id: Mapped[str] = mapped_column(String, index=True)
    deal_terms_id: Mapped[int | None] = mapped_column(ForeignKey("deal_terms.id"))
    doc_kind: Mapped[str] = mapped_column(String)  # PI·PO·CI·PL(계약 15.1절)
    doc_no: Mapped[str] = mapped_column(String)  # 내부 관리 번호 <doc_kind>-YYYYMMDD-NNN
    draft: Mapped[dict] = mapped_column(JSON_VALUE)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    status: Mapped[str] = mapped_column(String, default="needs_input")  # needs_input/ready/sent
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class TradeDocumentVersion(Base, Owned, Created):
    __tablename__ = "trade_document_versions"
    document_id: Mapped[int] = mapped_column(ForeignKey("trade_documents.id"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON_VALUE)


class TradeProposal(Base, Owned, Created):
    """검토 제안. 회사 이미지는 제안 시점의 `logo_file_id`/`seal_file_id`로 고정하고(계획 9절)
    렌더 때 Storage에서 bytes를 읽는다. `logo`/`seal` 바이너리 열은 9절 이전 행 보존용이며
    backfill(app.trade.settings.backfill) 뒤 22절에서 삭제한다."""
    __tablename__ = "trade_proposals"
    __table_args__ = (ForeignKeyConstraint(
        ["document_id", "revision"],
        ["trade_document_versions.document_id", "trade_document_versions.revision"]),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("trade_documents.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON_VALUE)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String, default="pending")
    decision: Mapped[str | None] = mapped_column(String)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    logo: Mapped[bytes | None] = mapped_column(LargeBinary)
    seal: Mapped[bytes | None] = mapped_column(LargeBinary)
    logo_file_id: Mapped[int | None] = mapped_column(ForeignKey("file_assets.id"))
    seal_file_id: Mapped[int | None] = mapped_column(ForeignKey("file_assets.id"))


class TradeArtifact(Base, Owned, Created):
    """CONTRACT 15.7·16.3절 trade_artifacts — 발급 파일 기록(계획 10절).

    bytes는 비공개 Storage의 결정적 `object_key` 위치에만 두고 새 승인은 `content`를 채우지
    않는다. `content` 바이너리 열은 10절 이전 행 보존용이며 backfill(app.trade.review.backfill)
    뒤 22절에서 삭제한다. 기존 파일 ID·형식·해시·승인 관계는 그대로 유지한다.
    """
    __tablename__ = "trade_artifacts"
    # 저장소 정리가 객체 키로 남은 참조를 확인한다.
    __table_args__ = (UniqueConstraint("proposal_id", "file_format"),
                      Index("ix_trade_artifacts_object_key", "object_key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("trade_proposals.id"), index=True)
    file_format: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    media_type: Mapped[str] = mapped_column(String)
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes | None] = mapped_column(LargeBinary)
    object_key: Mapped[str | None] = mapped_column(String)
    size_bytes: Mapped[int | None] = mapped_column(Integer)


class FileAsset(Base, Owned, Created):
    """CONTRACT 7.1·16.3절 file_assets — 첨부 파일 메타데이터(계획 8절).

    파일 bytes는 DB에 두지 않고 비공개 Storage 버킷의 `object_key` 위치에만 둔다.
    `content_type`은 확장자·클라이언트 값이 아니라 서버가 파일 시그니처로 확인한 실제 형식이다.
    """
    __tablename__ = "file_assets"
    # 저장소 정리가 객체 키로 남은 참조를 확인한다.
    __table_args__ = (Index("ix_file_assets_object_key", "object_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    original_filename: Mapped[str] = mapped_column(String)
    content_type: Mapped[str] = mapped_column(String)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String)


class TradeDocumentSource(Base, Owned, Created):
    """CONTRACT 7.1·16.3절 trade_document_sources — 문서 버전과 첨부 파일의 출처 연결(계획 8절).

    `revision`는 연결로 만들어진 문서 revision다. 출처를 바꾸면 새 revision 행이 쌓이고
    과거 revision의 연결 행은 보존된다. `origin`이 `email`인 행은 Gmail 첨부 가져오기(보류 범위) 뒤 생긴다.
    """
    __tablename__ = "trade_document_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    trade_document_id: Mapped[int] = mapped_column(ForeignKey("trade_documents.id"), index=True)
    doc_kind: Mapped[str] = mapped_column(String)
    revision: Mapped[int] = mapped_column(Integer)
    file_id: Mapped[int] = mapped_column(ForeignKey("file_assets.id"), index=True)
    origin: Mapped[str] = mapped_column(String)


class UserPreference(Base, Updated):
    __tablename__ = "user_preferences"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict | list | str | int | bool | None] = mapped_column(JSON_VALUE)


class CompanyProfile(Base, Updated):
    """CONTRACT 7절 + 15.7절. 무역서류 확장 열(legal_name_en·address·phone·email·
    registration_details)은 발행사 이름·영문 문서 규칙(계약 15.4·15.8절)에 쓴다(kekorea-port 6)."""
    __tablename__ = "company_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    company_name: Mapped[str | None] = mapped_column(String)
    business_no: Mapped[str | None] = mapped_column(String)
    ceo_name: Mapped[str | None] = mapped_column(String)
    contact: Mapped[str | None] = mapped_column(String)
    legal_name_en: Mapped[str | None] = mapped_column(String)  # 영문 법인명(무역 발행사 이름)
    address: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String)
    registration_details: Mapped[str | None] = mapped_column(Text)


class CompanyBankAccount(Base, Owned, Updated):
    """CONTRACT 15.7절 company_bank_accounts — 사용자별 계좌(PI 하단 6항목, kekorea-port 6).
    문서 통화 행을 우선해 초안 스냅숏(`TradeDocDraft.bank`)의 대문자 6키로 바꿔 담는다."""
    __tablename__ = "company_bank_accounts"
    __table_args__ = (UniqueConstraint("user_id", "currency"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(3))  # ISO 3자리
    beneficiary: Mapped[str | None] = mapped_column(String)
    bank_name: Mapped[str | None] = mapped_column(String)
    branch: Mapped[str | None] = mapped_column(String)
    swift: Mapped[str | None] = mapped_column(String)
    account_number: Mapped[str | None] = mapped_column(String)
    bank_address: Mapped[str | None] = mapped_column(Text)


class CompanyBranding(Base, Updated):
    """CONTRACT 15.7절 company_branding — 사용자별 직인·로고(kekorea-port 4). 현재 설정은
    `logo_file_id`/`seal_file_id`가 file_assets의 이미지를 가리키고(계획 9절) bytes는 Storage에만
    있다. `logo`/`seal`/`seal_sha256` 바이너리 열은 9절 이전 행 보존용이며 backfill 뒤 22절에서 삭제한다."""
    __tablename__ = "company_branding"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    logo: Mapped[bytes | None] = mapped_column(LargeBinary)
    seal: Mapped[bytes | None] = mapped_column(LargeBinary)
    seal_sha256: Mapped[str | None] = mapped_column(String)
    logo_file_id: Mapped[int | None] = mapped_column(ForeignKey("file_assets.id"))
    seal_file_id: Mapped[int | None] = mapped_column(ForeignKey("file_assets.id"))


class PriceListItem(Base, Owned, Updated):
    """CONTRACT 7절 + 15.7절 단가표. 국내 견적서 행(role NULL, 원 단위 정수 unit_price)은 그대로고
    무역 행(role 'purchase'/'sale')은 Decimal 문자열 단가(unit_price_text)·통화·가격 기준·거래처
    키를 함께 저장한다. 유일성은 유니크 제약 하나로 두지 않고 부분 유니크 인덱스 두 개로 정의한다
    (국내 행 (user_id, item_name) 유일 / 무역 행 (user_id, item_name, role, currency, party_key) 유일)."""
    __tablename__ = "price_list_items"
    __table_args__ = (
        Index("uq_price_list_items_domestic", "user_id", "item_name", unique=True,
              sqlite_where=text("role IS NULL"), postgresql_where=text("role IS NULL")),
        Index("uq_price_list_items_trade", "user_id", "item_name", "role", "currency", "party_key",
              unique=True, sqlite_where=text("role IS NOT NULL"), postgresql_where=text("role IS NOT NULL")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    item_name: Mapped[str] = mapped_column(String)
    unit: Mapped[str | None] = mapped_column(String)
    unit_price: Mapped[int | None] = mapped_column(BigInteger)  # 국내 행의 원 단위 정수(무역 행은 NULL, 단가는 unit_price_text)
    role: Mapped[str | None] = mapped_column(String)  # purchase(매입)·sale(판매), NULL이면 국내 견적서 행
    currency: Mapped[str | None] = mapped_column(String(3))  # ISO 3자리(무역 행)
    price_basis: Mapped[str | None] = mapped_column(String)
    product_code: Mapped[str | None] = mapped_column(String)
    capacity: Mapped[str | None] = mapped_column(String)
    unit_price_text: Mapped[str | None] = mapped_column(String)  # 무역 Decimal 문자열 단가
    party_key: Mapped[str | None] = mapped_column(String)  # 가격이 적용되는 거래처 company_key(공통 가격은 빈 문자열)


class Counterparty(Base, Owned, Updated):
    """CONTRACT 15.7절 counterparties — 거래처(별칭·기본 정보). 추출 경로의 거래처 자동
    채움(app.trade.common.counterparties.apply_company_profiles)이 읽는다[임시: 협의 5·6]."""
    __tablename__ = "counterparties"
    __table_args__ = (UniqueConstraint("user_id", "company_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_key: Mapped[str] = mapped_column(String)
    legal_name: Mapped[str] = mapped_column(String)
    aliases: Mapped[list] = mapped_column(JSON_VALUE, default=list)
    address: Mapped[str | None] = mapped_column(Text)
    contact: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String)
    registration_details: Mapped[str | None] = mapped_column(Text)
    default_ship_to: Mapped[str | None] = mapped_column(Text)
    ship_to_phone: Mapped[str | None] = mapped_column(String)


class CounterpartyHistory(Base, Owned):
    __tablename__ = "counterparty_history"
    # 장기 거래 기억이 같은 상대의 최근 5건을 발송 시각 역순으로 읽는다.
    __table_args__ = (Index("ix_counterparty_history_user_email_sent", "user_id", "counterparty_email",
                            "sent_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    counterparty_email: Mapped[str] = mapped_column(String)
    thread_id: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(Text)
    deal_terms: Mapped[dict] = mapped_column(JSON_VALUE)
    quote_id: Mapped[int | None] = mapped_column(ForeignKey("quotes.id"))
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime())


class Run(Base, Owned):
    __tablename__ = "runs"
    # 실행 기록 목록이 본인 실행을 최신 순으로 읽는다.
    __table_args__ = (Index("ix_runs_user_started", "user_id", "started_at"),)
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
