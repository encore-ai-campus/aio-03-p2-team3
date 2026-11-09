"""docs/CONTRACT.md 2·4.3절의 공통 상태 계약."""

from operator import add
from typing import Annotated, Literal, TypedDict


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
    customer_name: str | None
    items: list[DealItem]
    due_date: str | None
    contact_name: str | None
    contact_phone: str | None
    delivery_place: str | None
    note: str | None
    evidence: dict[str, str]


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
    deal_terms: DealTerms | None
    required_fields: RequiredFields | None
    missing_fields: list[str]
    reply_mode: Literal["general", "followup", "quote"] | None
    candidates: list[ReplyCandidate]
    quote_draft: QuoteDraft | None
    reflection_enabled: bool
    reflection: ReflectionResult | None
    reflection_history: Annotated[list[ReflectionResult], add]
    call_retries: Annotated[int, add]
    reflection_retries: int
    reflection_retries_by_type: dict[str, int]
    errors: Annotated[list[AgentError], add]
    needs_review: bool
    notice: Literal["rate_limit", "reflection_limit"] | None
    end_reason: Literal["awaiting_approval", "followup_question", "ignored", "failed"] | None


def initial_state(*, run_id: str, user_id: int, mode: Literal["live", "test"],
                  email: EmailMessage, reflection_enabled: bool) -> AgentState:
    return AgentState(
        run_id=run_id, user_id=user_id, mode=mode,
        message_id=email["gmail_message_id"], thread_id=email["thread_id"], email=email,
        reflection_enabled=reflection_enabled, thread_context=None, long_term=None,
        intent=None, selected_tool=None, tool_reason=None, tools_called=[], step_status="ok",
        deal_terms=None, required_fields=None, missing_fields=[], reply_mode=None,
        candidates=[], quote_draft=None, reflection=None, reflection_history=[],
        call_retries=0, reflection_retries=0, reflection_retries_by_type={},
        errors=[], needs_review=False, notice=None, end_reason=None,
    )
