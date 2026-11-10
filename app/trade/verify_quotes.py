"""품목·당사자·조건의 원문 근거 검증(kekorea-port 2절 A 묶음).

원본: reference/kekorea/Quotation_KEKOREA/agent/extractor.py verify_item_quotes.
원본과 다른 점: 함수 안의 `__import__("decimal")`·`__import__("re")` 표현을 맨 위 import로
정리했다(동작은 같다). 원본의 번역 근거 예외 동작(근거 메모가 하나라도 인증되면 당사자·조건의
글자 그대로 검사를 건너뛰는 KNOWN_ERRORS ERR-08)은 사본·이식본 결과 비교(kekorea-port 2절
완료 기준)를 위해 그대로 두고, 점검은 kekorea-port 6절 점검표에서 한다.
"""
from decimal import Decimal
import re


# 원본: reference/kekorea/Quotation_KEKOREA/agent/extractor.py verify_item_quotes
def verify_item_quotes(draft, prompt, *, image_context=False):
    """Block item facts when their quoted support is absent from the original user prompt."""
    normalize = lambda text: " ".join(str(text or "").casefold().split())
    source = normalize(prompt)
    source_notes = draft.get("source_notes", [])
    verified_notes = []
    for note in source_notes:
        normalized_note = normalize(note)
        if not normalized_note or (not image_context and normalized_note not in source):
            draft.setdefault("conflicts", []).append(
                "A source note is not an exact quote from the prompt; review the translated fields")
        else:
            verified_notes.append(normalized_note)
    has_verified_translation_evidence = bool(verified_notes)
    if image_context:
        if not has_verified_translation_evidence:
            draft.setdefault("conflicts", []).append(
                "Attached order image has no quoted source evidence; confirm all extracted details")
        else:
            draft.setdefault("conflicts", []).append(
                "Order details were extracted from an image; visually confirm product names, sizes, and quantities")
    for index, item in enumerate(draft.get("items", []), 1):
        quote = normalize(item.get("source"))
        if not quote or (not image_context and quote not in source):
            draft.setdefault("conflicts", []).append(
                f"Item {index} has no verifiable exact quote from the prompt; confirm its extracted facts")
            continue
        # The exact source quote is retained for translated item names/capacities;
        # literal equality would incorrectly reject valid Chinese/Indonesian translations.
        numeric_fields = ("quantity", "unit_price", "discount_percent", "paid_quantity", "free_quantity", "shipped_quantity")
        for field in numeric_fields:
            value = item.get(field)
            if value in (None, ""):
                continue
            try:
                expected = Decimal(str(value).replace(",", ""))
                seen = [Decimal(token.replace(",", ""))
                        for token in re.findall(r"(?<!\d)(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\d)", quote)]
            except Exception:
                seen = []
                expected = None
            if expected is not None and expected not in seen:
                draft.setdefault("conflicts", []).append(
                    f"Item {index} {field.replace('_', ' ')} was not found in its source quote; confirm the value")
    for role in ("buyer", "seller"):
        for field in ("legal_name", "address", "phone", "email", "registration_details"):
            value = (draft.get(role) or {}).get(field)
            if value and normalize(value) not in source and not has_verified_translation_evidence:
                draft.setdefault("conflicts", []).append(
                    f"{role.title()} {field.replace('_', ' ')} was not found verbatim in the prompt; confirm it")
    for field in ("incoterms", "payment_terms", "remarks", "document_number", "issue_date", "shipment_reference", "country_of_origin", "ship_to", "bill_to"):
        value = draft.get(field)
        if value and normalize(value) not in source and not has_verified_translation_evidence:
            draft.setdefault("conflicts", []).append(
                f"{field.replace('_', ' ').title()} was not found verbatim in the prompt; confirm it")
    currency = draft.get("currency")
    currency_markers = {"USD": ("USD", "US$", "$", "美元"), "KRW": ("KRW", "₩", "WON", "韩元"),
                        "EUR": ("EUR", "€", "欧元"), "CNY": ("CNY", "RMB", "¥", "人民币", "元")}
    if currency and not image_context and not any(marker in prompt.upper() for marker in currency_markers.get(currency, (currency,))):
        draft.setdefault("conflicts", []).append("Currency was not explicitly identified in the prompt; confirm it")
    return draft
