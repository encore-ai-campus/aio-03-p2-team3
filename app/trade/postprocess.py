"""추출 후처리(kekorea-port 2절 A 묶음).

원본: reference/kekorea/Quotation_KEKOREA/app_postprocess.py(원본 app.py 35~323행 발췌).
원본과 다른 점(docs/CONTRACT.md 15.4절 대응표):
- 비공개 함수 이름(`_xxx`)을 계약이 정한 공개 이름으로 바꿨다.
- `_apply_ke_korea_company_defaults`는 KE KOREA 고정값 대신 사용자별 발행 회사 설정
  스냅샷으로 채우는 `apply_issuer_defaults(draft, doc_kind, company)`가 됐다[임시: 협의 1].
- 원본의 import 경로(`Quotation_KEKOREA.agent...`)는 `app.trade...`로 바꿨다.
"""
from decimal import Decimal, InvalidOperation
import re

from app.trade.trade_documents import apply_promotion, normalize_quantity_unit


# 원본: reference/kekorea/Quotation_KEKOREA/app_postprocess.py _apply_ke_korea_company_defaults
def apply_issuer_defaults(draft, doc_kind, company):
    """Fill the issuing company profile on every shared document workflow.

    원본은 KE KOREA 고정값을 채웠다. 이식본은 사용자별 설정(company_profiles 스냅샷)에서
    영문 법인명(legal_name_en → legal_name → company_name)·주소·담당·전화·이메일을 읽어
    빈 값만 채운다. 설정이 없거나 비어 있으면 채우지 않고 재질문·검토 입력으로 넘긴다.
    """
    role = "buyer" if doc_kind == "PO" else "seller"
    party = dict(draft.get(role) or {})
    source = company or {}

    def configured(*keys):
        for key in keys:
            value = str(source.get(key) or "").strip()
            if value:
                return value
        return ""

    defaults = {
        "legal_name": configured("legal_name_en", "legal_name", "company_name"),
        "address": configured("address"),
        "contact": configured("contact"),
        "phone": configured("phone"),
        "email": configured("email"),
    }
    for field, value in defaults.items():
        if value and not str(party.get(field) or "").strip():
            party[field] = value
    draft[role] = party
    return draft


# 원본: reference/kekorea/Quotation_KEKOREA/app_postprocess.py _synchronize_extracted_quantities
def synchronize_quantities(draft):
    """Use one paid quantity consistently and calculate shipped quantities."""
    for item in draft.get("items", []):
        if draft.get("product_family") == "cosmetics" and not item.get("unit"):
            item["unit"] = "PCS"
        # The order quantity is the source of truth unless a promotion explicitly
        # separates paid units from free units. The validator calculates totals
        # from paid_quantity, so keep both quantity fields synchronized.
        paid = item.get("paid_quantity") if item.get("promotion") else item.get("quantity")
        if paid in (None, ""):
            paid = next((item.get(key) for key in ("quantity", "paid_quantity") if item.get(key) not in (None, "")), None)
        if paid in (None, ""):
            continue
        item["quantity"] = str(paid)
        item["paid_quantity"] = str(paid)
        if item.get("free_quantity") in (None, ""):
            item["free_quantity"] = "0"
        if item.get("promotion"):
            try:
                promotion = apply_promotion(paid, item["promotion"])
                item["free_quantity"] = promotion["free_quantity"]
            except (ValueError, InvalidOperation):
                pass
        try:
            free = Decimal(str(item.get("free_quantity") or "0"))
            item["shipped_quantity"] = format(Decimal(str(paid)) + free, "f")
        except (InvalidOperation, TypeError, ValueError):
            pass


# 원본: reference/kekorea/Quotation_KEKOREA/app_postprocess.py _format_quantity_display
def format_quantity_display(value):
    try:
        rendered = format(Decimal(str(value)), ",f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    except (InvalidOperation, TypeError, ValueError):
        return str(value or "—")


# 원본: reference/kekorea/Quotation_KEKOREA/app_postprocess.py _explicit_remark
def explicit_remark(prompt):
    """Only use remark text that the user explicitly labels in the prompt."""
    match = re.search(
        r"\b(?:REMARKS?|NOTES?|SPECIAL\s+INSTRUCTIONS?|ADDITIONAL\s+TERMS?)\s*[:=]\s*(.*?)(?=\s+(?:BUYER|PURCHASER|CUSTOMER|SELLER|SUPPLIER|VENDOR|PRODUCT|ITEM|GOODS|MATERIAL|DESCRIPTION|QUANTITY|QTY|Q['’]?TY|ORDER\s+QTY|ORDERED\s+QUANTITY|VOLUME|VOL\.?|UNIT\s+PRICE|PRICE|RATE|INCOTERMS?|SHIPPING\s+TERMS?|TERMS\s+OF\s+SHIPPING|SHIP(?:PING)?\s+CONDITIONS?|DELIVERY(?:\s+TERMS?|\s+CONDITIONS?)?|TERMS\s+OF\s+DELIVERY|PAYMENT(?:\s+TERMS?|\s+CONDITIONS?)?|TERMS\s+OF\s+PAYMENT|CURRENCY|SHIPMENT|SHIP\s+TO|DELIVER\s+TO|CONSIGNEE|BILL\s+TO|CONTACT|ATTN|TEL|PHONE|MOBILE|EMAIL)\s*(?::|=)|$)",
        prompt or "", flags=re.IGNORECASE | re.DOTALL)
    return (match.group(1).strip(" \t\r\n;,") or "N/A") if match else "N/A"


# 원본: reference/kekorea/Quotation_KEKOREA/app_postprocess.py _has_explicit_ship_to
def has_explicit_ship_to(prompt):
    """Require an explicitly labeled destination before treating text as ship-to."""
    labels = (
        r"ship[\s-]*to(?:\s*[- ]\s*party|\s+address)?", r"deliver(?:ed)?\s+to(?:\s+address)?",
        r"delivery\s+to(?:\s+address)?", r"delivery\s+address", r"destination(?:\s+address)?",
        r"consignee\s+address", r"shipping\s+address", r"delivery\s+location",
        r"ship\s+destination", r"납품처", r"배송지", r"도착지", r"인도\s*장소",
        r"送货地址", r"收货地址", r"交付地址", r"目的地",
        r"alamat\s+(?:pengiriman|pengantaran|tujuan)", r"tujuan\s+pengiriman",
    )
    label_pattern = "(?:" + "|".join(labels) + ")"
    return bool(re.search(label_pattern, prompt or "", re.IGNORECASE))


# 원본: reference/kekorea/Quotation_KEKOREA/app_postprocess.py _discount_instruction
def discount_instruction(prompt):
    """Return one discount rate; if omitted, use the undiscounted catalog price."""
    text = prompt or ""
    if not re.search(r"discount|할인", text, re.IGNORECASE):
        return "0", None

    # Remove rates that are explicitly denied before looking for active rates.
    # Without this, a phrase such as "10% 할인율 적용하지마" is incorrectly
    # parsed as a request to apply a 10% discount simply because it contains 10%.
    denied_patterns = (
        r"(?<![\w.])\d+(?:\.\d+)?\s*%\s*할인(?:율)?\s*(?:(?:을|은|는)\s*)?(?:적용\s*하지\s*마(?:세요|라)?|적용\s*안\s*(?:해|함|합니다|돼|됩니다)?|적용하지\s*않(?:아|는다|습니다)?|미적용|적용\s*제외|제외)",
        r"할인(?:율)?\s*(?:(?:을|은|는)\s*)?\d+(?:\.\d+)?\s*%\s*(?:적용\s*하지\s*마(?:세요|라)?|적용\s*안\s*(?:해|함|합니다|돼|됩니다)?|적용하지\s*않(?:아|는다|습니다)?|미적용|제외)",
        r"\b(?:do\s+not|don't|dont|does\s+not|doesn't)\s+(?:apply|use|give)\b[^.!?;\n]{0,40}\bdiscount(?:\s+rate)?\b",
        r"\bdiscount(?:\s+rate)?\b[^.!?;\n]{0,32}\b(?:not\s+applied|not\s+apply|do\s+not\s+apply|don't\s+apply|excluded|omit)\b",
    )
    denied_spans = []
    for pattern in denied_patterns:
        denied_spans.extend(match.span() for match in re.finditer(pattern, text, re.IGNORECASE))
    remaining = list(text)
    for start, end in denied_spans:
        remaining[start:end] = " " * (end - start)
    remaining_text = "".join(remaining)

    # "At list price" / "정가로" is also an explicit zero-discount instruction.
    list_price_instruction = re.search(
        r"\b(?:at\s+(?:the\s+)?list\s+price|full\s+price|regular\s+price|no\s+discount|without\s+discount)\b|정가(?:로|격으로)",
        text, re.IGNORECASE)
    rates = re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)\s*%", remaining_text)
    if not rates and (denied_spans or list_price_instruction):
        return "0", None
    if not rates:
        if re.search(r"할인\s*없|할인율\s*미적용|할인\s*미적용|할인\s*없이", text, re.IGNORECASE):
            return "0", None
        return None, "Discount was mentioned without a percentage; specify a single discount rate."
    correction = re.search(r"not|instead|rather than|아니라|아닌|대신|수정|변경", text, re.IGNORECASE)
    if len(set(rates)) == 1:
        return rates[-1], None
    if correction:
        return rates[-1], None
    return None, "Multiple discount rates were requested; specify one rate for this invoice."


# 원본: reference/kekorea/Quotation_KEKOREA/app_postprocess.py _normalize_quantity_aliases
def normalize_quantity_aliases(draft, prompt):
    """Recover explicitly labeled quantities the extractor left empty and flag Volume for confirmation."""
    items = draft.get("items", [])
    pending = []
    unit_pattern = r"KG|KGS|KILOGRAMS?|MT|MTS|METRIC\s+TONS?|TONNES?|PCS?|PIECES?|UNITS?|SETS?|BOXES?|BOX|CTNS?|CARTONS?|DRUMS?|ROLLS?|PALLETS?|GRAMS?|G|LITRES?|LITERS?|M3|CBM|WP|W"
    label_pattern = r"(?:quantity|qty|q['’]?ty|ordered\s+(?:quantity|qty|units?)|order\s+(?:quantity|qty|volume)|volume|vol\.?|sets?|boxes?|cartons?|ctns?|packages?|packs?|drums?|rolls?|pallets?)"
    quantity_pattern = re.compile(
        rf"(?<![A-Z])(?P<label>{label_pattern})(?![A-Z])\s*(?:[:=#-])?\s*"
        rf"(?P<amount>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>{unit_pattern})?\b",
        re.IGNORECASE)
    for item in items:
        source = str(item.get("source") or "")
        if len(items) == 1 or not source:
            source = source or (prompt or "")
        matches = list(quantity_pattern.finditer(source))
        if not matches and len(items) == 1:
            matches = list(quantity_pattern.finditer(prompt or ""))
        if len(matches) != 1:
            continue
        match = matches[0]
        label = match.group("label")
        amount = match.group("amount").replace(",", "")
        label_unit = label if re.fullmatch(r"(?:sets?|boxes?|cartons?|ctns?|packages?|packs?|drums?|rolls?|pallets?)", label, re.I) else None
        basis_unit = re.sub(r"^(?:USD|KRW|EUR|CNY)\s*/?\s*|^PER\s+", "", str(item.get("price_basis") or ""), flags=re.I)
        explicit_unit = match.group("unit") or label_unit
        raw_unit = explicit_unit or item.get("unit") or basis_unit
        unit = normalize_quantity_unit(raw_unit)
        ambiguous_label = bool(label_unit or re.fullmatch(r"vol(?:ume)?\.?", label, re.I))
        existing = item.get("paid_quantity") or item.get("quantity")
        if existing in (None, ""):
            item["quantity"] = amount
            item["paid_quantity"] = amount
            item["free_quantity"] = item.get("free_quantity") or "0"
            try:
                item["shipped_quantity"] = format(Decimal(amount) + Decimal(str(item["free_quantity"])), "f")
            except (InvalidOperation, TypeError, ValueError):
                item["shipped_quantity"] = amount
        if explicit_unit:
            item["unit"] = explicit_unit
        elif not item.get("unit") and raw_unit:
            item["unit"] = str(raw_unit).strip()
        if ambiguous_label:
            interpretation = (f'{amount} {unit}' if unit else amount)
            reason = "Confirm this is the ordered item quantity/unit and not package count or packaging volume." if label_unit else "Confirm this is ordered quantity, not package or cubic volume."
            pending.append(
                f'The source uses “{match.group(0).strip()}”. Treat it as {interpretation}? {reason}'
            )
    draft["pending_confirmations"] = pending
    return draft


# 원본: reference/kekorea/Quotation_KEKOREA/app_postprocess.py _normalize_currency_alias
def normalize_currency_alias(draft, prompt):
    """Infer currency only from explicit source markers; ask before treating bare $ as USD."""
    text = prompt or ""
    evidence = {
        "USD": bool(re.search(r"\bUSD\b|\bUS\s*\$|\$", text, re.I)),
        "KRW": bool(re.search(r"\bKRW\b|\bWON\b|₩|원화|한국\s*원", text, re.I)),
        "EUR": bool(re.search(r"\bEUR\b|\bEURO\b|€", text, re.I)),
        "CNY": bool(re.search(r"\bCNY\b|\bRMB\b|人民币|人民幣|人民币|元", text, re.I)),
    }
    found = [code for code, present in evidence.items() if present]
    if len(found) > 1:
        draft.setdefault("conflicts", []).append(
            "More than one currency is explicitly indicated; confirm the transaction currency")
        return draft
    if not found:
        return draft
    currency = found[0]
    current_raw = str(draft.get("currency") or "").strip().upper()
    current_match = re.match(r"^(USD|KRW|EUR|CNY)\b", current_raw)
    current = current_match.group(1) if current_match else current_raw
    if current and found and current != currency:
        draft.setdefault("conflicts", []).append(
            f"Extracted currency {current} conflicts with explicit {currency} price evidence; confirm the currency")
        return draft
    currency = currency if found else current
    if currency not in {"USD", "KRW", "EUR", "CNY"}:
        return draft
    draft["currency"] = currency
    bare_dollar = currency == "USD" and not re.search(r"\bUSD\b|\bUS\s*\$", text, re.I) and "$" in text
    model_uncertain = bool(re.search(r"candidate|confirm|ambiguous|uncertain", current_raw, re.I))
    if bare_dollar or model_uncertain:
        draft.setdefault("pending_confirmations", []).append(
            "The currency was identified as USD but marked uncertain or shown with '$'. Confirm USD (US dollars) before calculating the total.")
    return draft


# 원본: reference/kekorea/Quotation_KEKOREA/app_postprocess.py _requested_document_type
def recognize_doc_kind(prompt):
    """Recognize document aliases only when used as an explicit create request."""
    text = prompt or ""
    names = {
        "PI": r"(?:\bPI\b|pro\s*-?\s*forma\s+invoice|프로포마\s*인보이스|견적서)",
        "PO": r"(?:\bPO\b|purchase\s+order|구매주문서|발주서)",
        "CI": r"(?:\bCI\b|commercial\s+invoice|상업송장)",
        "PL": r"(?:\bPL\b|packing\s+list|포장명세서|패킹리스트)",
    }
    command = r"(?:create|make|prepare|generate|draft|issue|작성|만들|생성|발행)"
    for doc_type, alias in names.items():
        # Require a nearby action word so a buyer's attached PO or cited CI is
        # not mistaken for the document the user is asking the issuer to create.
        patterns = (rf"{command}.{{0,45}}?{alias}", rf"{alias}.{{0,25}}?(?:작성|만들|생성|발행)")
        if any(re.search(pattern, text, re.IGNORECASE | re.DOTALL) for pattern in patterns):
            return doc_type
    return None


# 원본: reference/kekorea/Quotation_KEKOREA/app_postprocess.py _keep_delivery_note_in_terms
def keep_delivery_note_in_terms(draft, auto_remark):
    """Keep a model-classified delivery deadline under delivery terms, not remarks."""
    if not auto_remark or not re.search(r"\b(delivery|deliver|shipment deadline|ship before)\b", str(auto_remark), re.I):
        return
    terms = str(draft.get("incoterms") or "").strip()
    note = str(auto_remark).strip()
    if note and note.casefold() not in terms.casefold():
        draft["incoterms"] = f"{terms}; {note}" if terms else note
