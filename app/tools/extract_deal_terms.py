"""extract_deal_terms: 스레드에서 거래 항목을 뽑는다(LLM 1회, 계약 4.4절·15.1·15.2절).

문서 종류는 이 도구가 정한다(계약 15.1절). `recognize_doc_kind`가 PI·PO·CI·PL로 인식하면
무역 경로(`extract_trade_terms.v1`, `TradeDocTerms`)로, 아니면 기존 국내 견적서 경로
(`extract_deal_terms.v1`, `DealTerms`)로 뽑는다.
"""

import re

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.graph.state import DealTerms, EmailMessage, ThreadContext
from app.llm.client import call_structured, model_source
from app.prompts.extract_deal_terms import PROMPT
from app.prompts.extract_trade_terms import PROMPT as TRADE_PROMPT
from app.prompts.format import email_text, thread_context_text
from app.tools.base import ToolResult
from app.trade.postprocess import (
    apply_issuer_defaults,
    discount_instruction,
    explicit_remark,
    has_explicit_ship_to,
    keep_delivery_note_in_terms,
    normalize_currency_alias,
    normalize_quantity_aliases,
    recognize_doc_kind,
    synchronize_quantities,
)

TEXT_FIELDS = ("customer_name", "due_date", "contact_name", "contact_phone", "delivery_place", "note")


class Input(BaseModel):
    email: EmailMessage
    thread_context: ThreadContext | None = None
    feedback: str | None = None
    user_id: int = 0  # 계약 15.6절: 무역 경로의 거래처·발행사 주인(quote 경로는 쓰지 않는다)
    counterparties: list[dict] = Field(default_factory=list)  # 거래처 프로필 목록(계약 15.7절 표)
    company: dict | None = None  # 발행 회사 설정 스냅샷(company_profiles)


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


class ExtractedTradeParty(BaseModel):
    legal_name: str | None = None
    address: str | None = None
    contact: str | None = None
    phone: str | None = None
    email: str | None = None
    registration_details: str | None = None


class ExtractedTradePackage(BaseModel):
    package_type: str | None = None
    package_count: str | None = None
    net_weight_kg: str | None = None
    gross_weight_kg: str | None = None
    dimensions: str | None = None
    shipping_marks: str | None = None


class ExtractedTradeItem(BaseModel):
    """무역 품목. 키는 원본 extractor.py 스키마 그대로(계약 15.2절)."""

    product_name: str | None = None
    product_code: str | None = None
    capacity: str | None = None
    quantity: str | None = None
    unit: str | None = None
    unit_price: str | None = None
    price_basis: str | None = None
    discount_percent: str | None = None
    paid_quantity: str | None = None
    free_quantity: str | None = None
    shipped_quantity: str | None = None
    promotion: str | None = None
    price_source: str | None = None
    source: str | None = None
    package_type: str | None = None
    package_count: str | None = None
    net_weight_kg: str | None = None
    gross_weight_kg: str | None = None
    volume_cbm: str | None = None
    hs_code: str | None = None


class ExtractedTradeItemCI(ExtractedTradeItem):
    source_line_total: str | None = None  # CI 확장 키(계약 15.2절)


class ExtractedTradeDoc(BaseModel):
    """무역서류 구조화 출력 형식. 키는 원본 extractor.py 스키마 그대로다."""

    document_type: str | None = None  # 도구가 인식 결과로 덮어쓴다(원본처럼 선택이 권위)
    product_family: str | None = None
    currency: str | None = None
    buyer: ExtractedTradeParty = Field(default_factory=ExtractedTradeParty)
    seller: ExtractedTradeParty = Field(default_factory=ExtractedTradeParty)
    items: list[ExtractedTradeItem] = Field(default_factory=list)
    incoterms: str | None = None
    payment_terms: str | None = None
    remarks: str | None = None
    document_number: str | None = None
    issue_date: str | None = None
    ship_to: str | None = None
    ship_to_source: str | None = None
    bill_to: str | None = None
    shipment_reference: str | None = None
    country_of_origin: str | None = None
    hs_code: str | None = None
    actual_package_count: str | None = None
    container_count: str | None = None
    declared_total_quantity: str | None = None
    declared_total_quantity_unit: str | None = None
    declared_net_weight_kg: str | None = None
    declared_gross_weight_kg: str | None = None
    declared_volume_cbm: str | None = None
    packages: list[ExtractedTradePackage] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    source_notes: list[str] = Field(default_factory=list)


class ExtractedTradeCIDoc(ExtractedTradeDoc):
    """CI일 때만 쓰는 확장 키(원본 조건 requested_document_type == 'CI'와 같다)."""

    source_document_type: str | None = None
    source_total: str | None = None
    items: list[ExtractedTradeItemCI] = Field(default_factory=list)


# 원본: reference/kekorea/Quotation_KEKOREA/agent/extractor.py의 CI 조건 지시문(첨부·이미지 문구는 범위 밖이라 뺐다)
CI_RULES = (
    "\nFor CI output, identify the source document type separately in source_document_type "
    "(PI for a Proforma Invoice; null if unknown), regardless of the selected output type. If the source is a PI, "
    "transcribe every goods/sample/zero-value/FOC row, seller, buyer, explicit ship-to, currency, delivery terms, "
    "reference number, printed unit prices and discounts. Preserve paid and free quantities separately; never count "
    "FOC units twice. A printed net unit price already includes its discount: use that net price and "
    "discount_percent=0, rather than discounting it twice. Otherwise preserve an explicitly printed base price and "
    "discount. Set source_line_total and source_total to the printed numeric line amounts and invoice total, not "
    "invented/recalculated values; use null if absent. Exclude all bank/account/SWIFT details and payment terms from "
    "the CI data and remarks; payment_terms=null. Do not treat bank currency as the transaction currency. Do not "
    "substitute catalog prices for values visible in the PI. Quote source rows and explicit destination labels for "
    "review. Other CI sources retain the ordinary extraction rules."
)

SHIP_TO_PLACEHOLDER = re.compile(
    r"\s*(?:N/?A|NONE|NOT\s+PROVIDED|TO\s+CONFIRM|TBC|TBD|UNKNOWN)\s*[.!]?\s*", re.IGNORECASE)


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
    return {"doc_kind": "quote", **terms, "items": items, "evidence": evidence}


# 원본: reference/kekorea/Quotation_KEKOREA/app_postprocess.py _extract_draft(후처리 부분)
def postprocess_trade_draft(draft: dict, doc_kind: str, prompt: str, company: dict | None,
                            counterparties: list[dict]) -> dict:
    """무역 초안 후처리. 원본 _extract_draft의 호출 순서를 그대로 따른다(계약 15.2·15.4절).

    원본과 다른 점:
    - 첨부 이미지·PDF 플래그(source_image_attached·source_pdf_attached)는 옮기지 않았다
      (첨부 읽기가 범위 밖이라 원문 근거는 메일 본문 인용뿐이다, 계약 15.2절).
    - 카탈로그 가격 적용(apply_verified_eclado_prices)은 계약 15.5절에 따라 문서 생성 도구
      create_trade_document(kekorea-port 3절)로 옮겼다.
    - 지연 import·호출 순서는 원본 그대로 둔다(계약 15.4절: 모듈 top import로 올리지 않는다).
    """
    from app.trade.ci_import import prepare_ci_import, is_pi_import
    from app.trade.counterparties import apply_company_profiles
    from app.trade.promotions import apply_promotion_commands
    from app.trade.samples import ensure_sample_rows, is_manual_sample
    from app.trade.trade_documents import current_issue_date
    from app.trade.verify_quotes import verify_item_quotes

    prepare_ci_import(draft, requested_type=doc_kind, has_attachments=True)
    draft = normalize_quantity_aliases(draft, prompt)
    draft = normalize_currency_alias(draft, prompt)
    # 인식된 문서 종류가 권위다(원본은 사이드바 선택이 권위였다).
    draft["document_type"] = doc_kind
    draft["doc_kind"] = doc_kind
    draft = verify_item_quotes(draft, prompt, image_context=False)
    draft["issue_date"] = current_issue_date()
    draft.pop("ship_to_source", None)
    if not has_explicit_ship_to(prompt):
        draft["ship_to"] = None
    elif SHIP_TO_PLACEHOLDER.fullmatch(str(draft.get("ship_to") or "")):
        draft["ship_to"] = None
    draft["missing_fields"] = [field for field in draft.get("missing_fields", [])
                               if not re.search(r"issue\s+date|date\s+of\s+issue", str(field), re.IGNORECASE)]
    auto_remark = draft.get("remarks")
    if not is_pi_import(draft):
        keep_delivery_note_in_terms(draft, auto_remark)
        draft["remarks"] = explicit_remark(prompt)
    elif explicit_remark(prompt) != "N/A":
        draft["remarks"] = explicit_remark(prompt)
    draft["conflicts"] = [issue for issue in draft.get("conflicts", [])
                          if not issue.lower().startswith("remarks was not found verbatim")]
    ensure_sample_rows(draft, prompt)
    apply_promotion_commands(draft, prompt, products=())
    synchronize_quantities(draft)
    apply_issuer_defaults(draft, doc_kind, company)
    apply_company_profiles(draft, counterparties, prompt=prompt)
    if is_pi_import(draft):
        return draft  # Printed PI prices/discounts remain transaction-specific.
    discount_rate, discount_issue = discount_instruction(prompt)
    if discount_rate is not None:
        for item in draft.get("items", []):
            if is_manual_sample(draft, item):
                continue
            item["discount_percent"] = discount_rate
        draft["conflicts"] = [issue for issue in draft.get("conflicts", [])
                              if "discount percent was not found in its source quote" not in issue.lower()]
    else:
        for item in draft.get("items", []):
            if is_manual_sample(draft, item):
                continue
            item["discount_percent"] = None
        if not draft.get("_samples_requested") or any(not is_manual_sample(draft, item) for item in draft.get("items", [])):
            draft.setdefault("conflicts", []).append(discount_issue)
    return draft


def source_text_of(email: EmailMessage, thread_context: ThreadContext | None) -> str:
    """근거 검증·후처리 정규식이 볼 원문. 스레드 원문과 현재 메일을 잇는다.

    스레드 요약·확인한 조건은 LLM이 다시 쓴 글이라 원문 근거에서 뺀다(글자 그대로 인용만 근거).
    """
    parts = [f"{message.get('subject') or ''}\n{message.get('body_text') or ''}".strip()
             for message in (thread_context or {}).get("recent_messages") or []]
    parts.append(f"{email.get('subject') or ''}\n{email.get('body_text') or ''}".strip())
    return "\n\n".join(part for part in parts if part)


def _extract_quote(email: EmailMessage, thread_context: ThreadContext | None, feedback: str | None) -> ToolResult:
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


def _extract_trade(email: EmailMessage, thread_context: ThreadContext | None, feedback: str | None,
                   doc_kind: str, company: dict | None, counterparties: list[dict]) -> ToolResult:
    result = call_structured(TRADE_PROMPT, ExtractedTradeCIDoc if doc_kind == "CI" else ExtractedTradeDoc, {
        "document_type": doc_kind,
        "ci_rules": CI_RULES if doc_kind == "CI" else "",
        "thread": thread_context_text(thread_context),
        "email": email_text(email),
        "feedback": feedback or "없음",
    })
    if not result.ok:
        return ToolResult(ok=False, error_kind=result.error_kind, source=model_source(),
                          error_message="무역서류 거래 항목을 뽑지 못했습니다",
                          attempts=result.attempts, duration_ms=result.duration_ms)
    draft = postprocess_trade_draft(result.value.model_dump(), doc_kind,
                                    source_text_of(email, thread_context), company, counterparties)
    return ToolResult(ok=True, value=draft, source=model_source(),
                      attempts=result.attempts, duration_ms=result.duration_ms)


@tool(args_schema=Input)
def extract_deal_terms(email: EmailMessage, thread_context: ThreadContext | None = None,
                       feedback: str | None = None, user_id: int = 0,
                       counterparties: list[dict] | None = None,
                       company: dict | None = None) -> ToolResult:
    """메일과 앞 대화에서 거래 항목을 뽑는다. 원문에 없는 값은 None.

    문서 종류 인식(`recognize_doc_kind`, 계약 15.1절)이 PI·PO·CI·PL이면 무역서류 형식
    (`TradeDocTerms`)으로 뽑아 후처리하고, 아니면 국내 견적서 형식(`DealTerms`)으로 뽑는다.
    """
    try:
        # 문서 종류 인식 입력은 메일 제목+본문이다(계약 15.1절).
        prompt_text = f"{email['subject'] or ''}\n{email['body_text'] or ''}"
        doc_kind = recognize_doc_kind(prompt_text)
        if doc_kind is None:
            return _extract_quote(email, thread_context, feedback)
        return _extract_trade(email, thread_context, feedback, doc_kind, company, counterparties or [])
    except Exception as error:
        # 예외 문자열에는 메일 본문이 섞일 수 있어 종류만 남긴다.
        return ToolResult(ok=False, error_kind="internal", source=model_source(),
                          error_message=f"거래 항목 추출 중 오류 ({type(error).__name__})")
