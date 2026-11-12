"""docs/CONTRACT.md 2·4.3·15.2절의 공통 상태 계약."""

from operator import add
from typing import Annotated, Literal, NotRequired, TypedDict


class EmailMessage(TypedDict):
    gmail_message_id: str
    thread_id: str
    rfc_message_id: str | None
    from_addr: str
    from_name: str | None
    to_addrs: list[str]
    subject: str
    body_text: str
    received_at: str
    direction: Literal["in", "out"]


class ThreadContext(TypedDict):
    summary: str | None
    recent_messages: list[EmailMessage]
    confirmed_terms: dict
    last_result: dict | None


class Source(TypedDict):
    kind: str
    fetched_at: str
    note: str | None


class LongTermMemory(TypedDict):
    preferences: dict
    company: dict | None
    price_list: list[dict]
    counterparty_history: list[dict]
    sources: list[Source]


class DealItem(TypedDict):
    item_name: str | None
    quantity: int | None
    unit: str | None
    unit_price: int | None


class DealTerms(TypedDict):
    doc_kind: NotRequired[Literal["quote"]]  # 문서 종류 판별 키. 없으면 "quote"(계약 15.2절)
    customer_name: str | None
    items: list[DealItem]
    due_date: str | None
    contact_name: str | None
    contact_phone: str | None
    delivery_place: str | None
    note: str | None
    evidence: dict[str, str]


class TradeParty(TypedDict, total=False):
    legal_name: str | None
    address: str | None
    contact: str | None
    phone: str | None
    email: str | None
    registration_details: str | None


class TradePackage(TypedDict, total=False):
    package_type: str | None
    package_count: str | None
    net_weight_kg: str | None
    gross_weight_kg: str | None
    dimensions: str | None
    shipping_marks: str | None


class TradeItem(TypedDict, total=False):
    product_name: str | None
    product_code: str | None
    capacity: str | None
    quantity: str | None
    unit: str | None
    unit_price: str | None
    price_basis: str | None
    discount_percent: str | None
    paid_quantity: str | None
    free_quantity: str | None
    shipped_quantity: str | None
    promotion: str | None
    price_source: str | None
    source: str | None
    package_type: str | None
    package_count: str | None
    net_weight_kg: str | None
    gross_weight_kg: str | None
    volume_cbm: str | None
    hs_code: str | None
    source_line_total: str | None  # CI 확장 키: 원본 PI에 인쇄된 행 금액(재계산 금지)


class TradeDocTerms(TypedDict, total=False):
    """무역서류 거래 항목(계약 15.2절). 원본 extractor.py 스키마 키를 그대로 쓴다."""

    doc_kind: Literal["PI", "PO", "CI", "PL"]  # document_type과 같은 값. 도구가 추출 직후 채운다
    document_type: str
    product_family: str | None
    currency: str | None
    buyer: TradeParty
    seller: TradeParty
    items: list[TradeItem]
    incoterms: str | None
    payment_terms: str | None
    remarks: str | None
    document_number: str | None
    issue_date: str | None
    ship_to: str | None
    ship_to_source: str | None  # 후처리가 꺼내(pop) SHIP TO 명시 확인에 쓰고 최종 초안에 남기지 않는다
    bill_to: str | None
    shipment_reference: str | None
    country_of_origin: str | None
    hs_code: str | None
    actual_package_count: str | None
    container_count: str | None
    declared_total_quantity: str | None
    declared_total_quantity_unit: str | None
    declared_net_weight_kg: str | None
    declared_gross_weight_kg: str | None
    declared_volume_cbm: str | None
    packages: list[TradePackage]
    source_document_type: str | None  # CI 확장 키: 원본 문서가 PI면 "PI"
    source_total: str | None  # CI 확장 키: 원본 PI에 인쇄된 총액(재계산 금지)
    missing_fields: list[str]
    conflicts: list[str]
    source_notes: list[str]


class RequiredField(TypedDict):
    key: str
    label: str


class RequiredFields(TypedDict):
    fields: list[RequiredField]
    source: Literal["config", "rag"]
    evidence: list[dict]


class ReplyCandidate(TypedDict):
    label: str
    subject: str
    body: str
    kind: Literal["general", "followup", "quote"]
    asks_fields: list[str]
    needs_review: bool
    notice: str | None


class QuoteLine(TypedDict):
    item_name: str
    quantity: int
    unit: str | None
    unit_price: int | None
    amount: int | None
    price_source: Literal["thread", "price_list", "user"] | None


class QuoteDraft(TypedDict):
    quote_id: int | None
    quote_no: str
    quote_date: str
    valid_until: str
    supplier: dict
    customer_name: str
    lines: list[QuoteLine]
    supply_amount: int | None
    vat: int | None
    total: int | None
    missing_prices: list[str]
    status: Literal["needs_price", "ready", "sent"]


class PackingTotals(TypedDict, total=False):
    """PL 원본/계산 합계 비교·승인(계약 15.5절)."""

    quantities: dict[str, str]  # 정규화 단위 → 행 합계(다른 단위는 합치지 않음)
    quantity_complete: bool
    calculated: dict[str, str | None]
    packages_total: dict[str, str | None]  # packages 배열 net/gross 합계(렌더러 폴백)
    issues: list[str]
    discrepancies: list[str]
    changes: list[dict]
    approved: bool


class TradeDocDraft(TypedDict, total=False):
    """무역서류 초안(계약 15.5절). 원본 validate_and_calculate 반환 키를 그대로 품고
    발행사·계좌 스냅샷과 채번 결과를 더한다. 문서 종류별 나머지 키는 원본 파이프라인이 채운다."""

    trade_doc_id: int | None  # DB 저장 뒤 채움
    doc_kind: str  # document_type과 같은 값(PI·PO·CI·PL)
    doc_no: str  # <doc_kind>-YYYYMMDD-NNN(내부 관리 번호)
    document_type: str
    currency: str | None
    buyer: TradeParty
    seller: TradeParty
    items: list[TradeItem]
    subtotal: str | None
    total: str | None
    blocking_issues: list[str]
    ready_for_issue: bool
    issuer: dict  # 발행 회사 스냅샷(company_profiles에서 복사)
    bank: dict | None  # 계좌 스냅샷(PI만. 대문자 6키 — 계약 15.7절)
    packing_totals: PackingTotals | None  # PL만
    status: Literal["needs_input", "ready", "sent"]


class ToolCallRecord(TypedDict):
    tool: str
    ok: bool
    error_kind: str | None
    attempts: int
    duration_ms: int


class ReflectionIssue(TypedDict):
    type: Literal["hallucination", "wrong_tool", "missing_param", "inconsistent"]
    detail: str
    evidence: str


class ReflectionResult(TypedDict):
    passed: bool
    issues: list[ReflectionIssue]
    cause: str | None
    strategy: Literal["reprompt", "reroute", "followup", "fallback"] | None
    retry_target: str | None
    feedback: str | None
    verified: bool | None


class AgentError(TypedDict):
    node: str
    kind: str
    message: str
    at: str


class AgentState(TypedDict):
    run_id: str
    user_id: int
    mode: Literal["live", "test"]
    message_id: str
    thread_id: str
    email: EmailMessage
    thread_context: ThreadContext | None
    long_term: LongTermMemory | None
    intent: Literal["general", "deal", "ignore"] | None
    selected_tool: str | None
    tool_reason: str | None
    tools_called: Annotated[list[ToolCallRecord], add]
    step_status: Literal["ok", "rate_limit", "failed"]
    deal_terms: DealTerms | TradeDocTerms | None  # 판별 키 doc_kind, 없으면 "quote"(계약 15.2절)
    required_fields: RequiredFields | None
    missing_fields: list[str]
    reply_mode: Literal["general", "followup", "quote"] | None
    candidates: list[ReplyCandidate]
    quote_draft: QuoteDraft | None
    trade_doc_draft: TradeDocDraft | None  # 무역서류 초안(계약 15.6절)
    reflection_enabled: bool
    reflection: ReflectionResult | None
    reflection_history: Annotated[list[ReflectionResult], add]
    call_retries: Annotated[int, add]
    reflection_retries: int
    reflection_retries_by_type: dict[str, int]
    errors: Annotated[list[AgentError], add]
    needs_review: bool
    notice: Literal["rate_limit", "reflection_limit", "openai_key_required", "worker_unavailable",
                    "worker_timeout", "worker_version_mismatch", "worker_key_required", "worker_owner_mismatch",
                    "worker_rate_limit", "worker_network", "worker_invalid_output", "worker_invalid_input", "worker_failed"] | None
    end_reason: Literal["awaiting_approval", "followup_question", "ignored", "failed"] | None


def initial_state(*, run_id: str, user_id: int, mode: Literal["live", "test"],
                  email: EmailMessage, reflection_enabled: bool) -> AgentState:
    return AgentState(
        run_id=run_id, user_id=user_id, mode=mode,
        message_id=email["gmail_message_id"], thread_id=email["thread_id"], email=email,
        reflection_enabled=reflection_enabled, thread_context=None, long_term=None,
        intent=None, selected_tool=None, tool_reason=None, tools_called=[], step_status="ok",
        deal_terms=None, required_fields=None, missing_fields=[], reply_mode=None,
        candidates=[], quote_draft=None, trade_doc_draft=None, reflection=None, reflection_history=[],
        call_retries=0, reflection_retries=0, reflection_retries_by_type={},
        errors=[], needs_review=False, notice=None, end_reason=None,
    )
