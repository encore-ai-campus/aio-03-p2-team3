"""extract_deal_terms: 스레드에서 거래 항목을 뽑는다(LLM 1회, 계약 4.4절)."""

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.graph.state import DealTerms, EmailMessage, ThreadContext
from app.llm.client import call_structured, model_source
from app.prompts.extract_deal_terms import PROMPT
from app.prompts.format import email_text, thread_context_text
from app.tools.base import ToolResult
TEXT_FIELDS = ("customer_name", "due_date", "contact_name", "contact_phone", "delivery_place", "note")


class Input(BaseModel):
    email: EmailMessage
    thread_context: ThreadContext | None = None
    feedback: str | None = None


class ExtractedItem(BaseModel):
    item_name: str | None = None
    quantity: int | None = None
    unit: str | None = None
    unit_price: int | None = None


class Evidence(BaseModel):
    field: str
    excerpt: str


class ExtractedDealTerms(BaseModel):
    """LLM 구조화 출력 형식. Gemini가 자유 키 dict를 다루기 어려워 evidence는 목록으로 받는다."""
    customer_name: str | None = None
    items: list[ExtractedItem] = Field(default_factory=list)
    due_date: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    delivery_place: str | None = None
    note: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)


def to_deal_terms(extracted: ExtractedDealTerms) -> DealTerms:
    """빈 문자열·0 이하 수량은 '없음'으로 보고, 값이 하나도 없는 품목은 버린다."""
    def text(value):
        value = (value or "").strip()
        return value or None

    def positive(value):
        return value if isinstance(value, int) and value > 0 else None

    items = []
    for item in extracted.items:
        cleaned = {
            "item_name": text(item.item_name), "quantity": positive(item.quantity),
            "unit": text(item.unit), "unit_price": positive(item.unit_price),
        }
        if any(value is not None for value in cleaned.values()):
            items.append(cleaned)
    terms = {name: text(getattr(extracted, name)) for name in TEXT_FIELDS}
    filled = {name for name, value in terms.items() if value is not None}
    if any(item["item_name"] for item in items):
        filled.add("item_name")
    if any(item["quantity"] for item in items):
        filled.add("quantity")
    if any(item["unit_price"] for item in items):
        filled.add("unit_price")
    evidence = {e.field: e.excerpt.strip() for e in extracted.evidence
                if e.field in filled and e.excerpt.strip()}
    return {**terms, "items": items, "evidence": evidence}


@tool(args_schema=Input)
def extract_deal_terms(email: EmailMessage, thread_context: ThreadContext | None = None,
                       feedback: str | None = None) -> ToolResult:
    """메일과 앞 대화에서 거래처명·품목·수량·납기·합의 단가·선택 항목을 뽑는다. 원문에 없는 값은 None."""
    try:
        result = call_structured(PROMPT, ExtractedDealTerms, {
            "email": email_text(email),
            "thread": thread_context_text(thread_context),
            "received_date": email["received_at"][:10],
            "feedback": feedback or "없음",
        })
        if not result.ok:
            return ToolResult(ok=False, error_kind=result.error_kind, source=model_source(),
                              error_message="거래 항목을 뽑지 못했습니다",
                              attempts=result.attempts, duration_ms=result.duration_ms)
        return ToolResult(ok=True, value=to_deal_terms(result.value), source=model_source(),
                          attempts=result.attempts, duration_ms=result.duration_ms)
    except Exception as error:
        # 예외 문자열에는 메일 본문이 섞일 수 있어 종류만 남긴다.
        return ToolResult(ok=False, error_kind="internal", source=model_source(),
                          error_message=f"거래 항목 추출 중 오류 ({type(error).__name__})")
