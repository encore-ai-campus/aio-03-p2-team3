"""check_required_fields: 빠진 필수 항목을 코드로 찾는다(LLM 없음, 계약 4.4절)."""

from langchain_core.tools import tool
from pydantic import BaseModel

from app.graph.state import DealTerms, RequiredFields
from app.tools.base import ToolResult

ITEM_KEYS = ("item_name", "quantity")


class Input(BaseModel):
    deal_terms: DealTerms
    required_fields: RequiredFields


def find_missing(deal_terms: DealTerms, required_fields: RequiredFields) -> list[str]:
    """필수 목록 순서대로 빠진 키를 돌려준다.

    품목 키(item_name·quantity)는 품목이 하나 이상이고 품목마다 값이 있어야 한다.
    그 밖의 키는 DealTerms의 같은 이름 값이 있어야 한다. 단가는 판매자가 채우므로 묻지 않는다.
    """
    items = deal_terms.get("items") or []
    missing = []
    for field in required_fields["fields"]:
        key = field["key"]
        if key in missing or key == "unit_price":
            continue
        if key in ITEM_KEYS:
            absent = not items or any(item.get(key) in (None, "") for item in items)
        else:
            value = deal_terms.get(key)
            absent = value is None or (isinstance(value, str) and not value.strip())
        if absent:
            missing.append(key)
    return missing


@tool(args_schema=Input)
def check_required_fields(deal_terms: DealTerms, required_fields: RequiredFields) -> ToolResult:
    """거래 항목에서 빠진 필수 항목 키 목록을 돌려준다."""
    try:
        return ToolResult(ok=True, value={"missing_fields": find_missing(deal_terms, required_fields)},
                          source="code")
    except Exception as error:
        return ToolResult(ok=False, error_kind="internal", source="code",
                          error_message=f"필수 항목 검토 중 오류 ({type(error).__name__})")
