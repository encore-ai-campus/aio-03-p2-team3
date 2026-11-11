"""check_required_fields: 빠진 필수 항목을 코드로 찾는다(LLM 없음, 계약 4.4절·15.3절)."""

from langchain_core.tools import tool
from pydantic import BaseModel

from app.graph.state import DealTerms, RequiredFields, TradeDocTerms
from app.tools.base import ToolResult

ITEM_KEYS = ("item_name", "quantity")
# 무역 품목 키 대응(계약 15.3절): item_name은 TradeItem의 product_name을 보고,
# quantity는 quantity·paid_quantity(PL이면 shipped_quantity도) 중 하나라도 있으면 있다.
# discount_percent는 품목별 값이고 "0"(할인 없음)은 있음이다.
TRADE_ITEM_KEYS = {"item_name": ("product_name",), "unit": ("unit",),
                   "quantity": ("quantity", "paid_quantity"),
                   "discount_percent": ("discount_percent",)}
PL_ITEM_KEYS = {**TRADE_ITEM_KEYS, "quantity": ("quantity", "paid_quantity", "shipped_quantity")}
# 무역 상대방 키 대응(계약 15.3절): PO는 seller, 그 밖은 buyer의 legal_name·address다.
TRADE_PARTY_KEYS = {"counterparty_legal_name": "legal_name", "counterparty_address": "address"}


class Input(BaseModel):
    deal_terms: DealTerms | TradeDocTerms
    required_fields: RequiredFields


def find_missing(deal_terms: DealTerms | TradeDocTerms, required_fields: RequiredFields) -> list[str]:
    """필수 목록 순서대로 빠진 키를 돌려준다.

    품목 키(item_name·quantity)는 품목이 하나 이상이고 품목마다 값이 있어야 한다.
    그 밖의 키는 DealTerms의 같은 이름 값이 있어야 한다. 단가는 판매자가 채우므로 묻지 않는다.
    무역 형식(doc_kind가 PI·PO·CI·PL)이면 계약 15.3절 대응으로 찾는다.
    """
    doc_kind = deal_terms.get("doc_kind", "quote")
    items = deal_terms.get("items") or []
    party = (deal_terms.get("seller") if doc_kind == "PO" else deal_terms.get("buyer")) or {}
    item_keys = PL_ITEM_KEYS if doc_kind == "PL" else TRADE_ITEM_KEYS
    missing = []
    for field in required_fields["fields"]:
        key = field["key"]
        if key in missing or key == "unit_price":
            continue
        if doc_kind != "quote" and key in TRADE_PARTY_KEYS:
            value = party.get(TRADE_PARTY_KEYS[key])
            absent = value is None or (isinstance(value, str) and not value.strip())
        elif doc_kind != "quote" and key in item_keys:
            candidates = item_keys[key]
            absent = not items or any(
                all(item.get(candidate) in (None, "") for candidate in candidates) for item in items)
        elif key in ITEM_KEYS:
            absent = not items or any(item.get(key) in (None, "") for item in items)
        else:
            value = deal_terms.get(key)
            absent = value is None or (isinstance(value, str) and not value.strip())
        if absent:
            missing.append(key)
    return missing


@tool(args_schema=Input)
def check_required_fields(deal_terms: DealTerms | TradeDocTerms, required_fields: RequiredFields) -> ToolResult:
    """거래 항목에서 빠진 필수 항목 키 목록을 돌려준다."""
    try:
        return ToolResult(ok=True, value={"missing_fields": find_missing(deal_terms, required_fields)},
                          source="code")
    except Exception as error:
        return ToolResult(ok=False, error_kind="internal", source="code",
                          error_message=f"필수 항목 검토 중 오류 ({type(error).__name__})")
