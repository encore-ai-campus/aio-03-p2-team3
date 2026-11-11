"""공통 구조화 호출·원문 확인. 프롬프트와 입력 형식은 문서별 agent가 소유한다."""
from app.llm.client import call_structured
from app.trade.common.models import DocumentError
from app.trade.verify_quotes import verify_item_quotes


def extract_facts(prompt, schema, text):
    result = call_structured(prompt, schema, {"text": text})
    if not result.ok:
        raise DocumentError("AI_" + (result.error_kind or "internal").upper(),
                            "문서 내용을 추출하지 못했습니다. 다시 시도하거나 직접 입력하세요", 503)
    draft = result.value.model_dump(mode="json")
    draft["source_notes"] = []
    for item in draft.get("items", []):
        if "confirm_price_override" in item:
            item["confirm_price_override"] = False
        if item.get("product_code") and item["product_code"].casefold() not in str(item.get("source") or "").casefold():
            draft.setdefault("conflicts", []).append("Confirm product code against its exact source quote")
    verify_item_quotes(draft, text)
    return draft
