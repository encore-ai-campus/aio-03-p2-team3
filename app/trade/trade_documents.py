"""무역서류 검증·계산(kekorea-port 3절 B).

원본: reference/kekorea/Quotation_KEKOREA/agent/trade_documents.py — 복사본.
- current_issue_date: 문서 출력(kekorea-port 4절, app/trade/renderers.py·app/trade/pi_pdf.py)이
  쓴다(docs/CONTRACT.md 15.4절 import 관계).
- normalize_quantity_unit·apply_promotion·상수(DOC_TYPES·FAMILIES·MONEY_QUANTUM·PRICE_QUANTUM):
  추출 후처리(kekorea-port 2절, app/trade/postprocess.py)가 쓴다.
- 바꾼 것(계약 15.4절): 발행사 역할 검사의 "KE KOREA" 고정 문자열 → `issuer_key`(발행 회사
  이름 키, `counterparties.name_key` 규칙) 비교. PO는 buyer 이름 키에, PI/CI는 seller 이름 키에
  `issuer_key`가 포함돼야 통과하고 발행사 키가 반대 역할 이름 키에 포함되면 차단한다.
  합산 결과의 `status` 값은 원본 "DRAFT"/"READY_FOR_USER_CONFIRMATION" 대신 계약 15.5절의
  "needs_input"/"ready"를 쓴다(판정 조건은 원본 그대로 `not blocking and not issues`).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from app.trade.counterparties import name_key

DOC_TYPES = {"PO", "PI", "CI", "PL"}
FAMILIES = {"cosmetics", "polysilicon", "wafer", "solar_cell", "solar_module", "other"}
MONEY_QUANTUM = Decimal("0.01")
PRICE_QUANTUM = Decimal("0.000001")


# 원본: reference/kekorea/Quotation_KEKOREA/agent/trade_documents.py current_issue_date
def current_issue_date():
    """Current English issue date in the company's Asia/Seoul time zone."""
    # South Korea uses UTC+09:00 year-round; fixed offset also works on runtimes
    # (notably some Windows and slim Linux builds) without an IANA tz database.
    today = datetime.now(timezone(timedelta(hours=9))).date()
    month = ("January", "February", "March", "April", "May", "June",
             "July", "August", "September", "October", "November", "December")[today.month - 1]
    return f"{today.day} {month} {today.year}"


# 원본: reference/kekorea/Quotation_KEKOREA/agent/trade_documents.py normalize_quantity_unit
def normalize_quantity_unit(value):
    """Normalize common singular/plural spellings for comparison and display."""
    unit = re.sub(r"\s+", " ", str(value or "").strip().upper().rstrip("."))
    aliases = {
        "KGS": "KG", "KILOGRAM": "KG", "KILOGRAMS": "KG",
        "MTS": "MT", "METRIC TON": "MT", "METRIC TONS": "MT", "TONNE": "MT", "TONNES": "MT",
        "PC": "PCS", "PIECE": "PCS", "PIECES": "PCS", "UNIT": "PCS", "UNITS": "PCS",
        "SETS": "SET", "BOXES": "BOX", "CTNS": "CTN", "CARTON": "CTN", "CARTONS": "CTN",
        "DRUMS": "DRUM", "ROLLS": "ROLL", "PALLETS": "PALLET",
        "GRAM": "G", "GRAMS": "G", "LITRE": "L", "LITRES": "L", "LITER": "L", "LITERS": "L",
    }
    return aliases.get(unit, unit)


# 원본: reference/kekorea/Quotation_KEKOREA/agent/trade_documents.py apply_promotion
def apply_promotion(paid_quantity, promotion):
    """Return paid/free/shipped quantities for a simple buy-N-get-M promotion."""
    paid = Decimal(str(paid_quantity))
    if not paid.is_finite() or paid < 0:
        raise ValueError("Paid quantity must be a non-negative number")
    free = Decimal("0")
    if promotion:
        match = re.fullmatch(r"\s*(\d+)\s*\+\s*(\d+)\s*", promotion)
        if not match or int(match.group(1)) < 1:
            raise ValueError("Promotion must use the simple N+M form, such as 2+1")
        buy, gift = map(int, match.groups())
        if paid != paid.to_integral_value():
            raise ValueError("Buy-N-get-M promotions require whole paid units")
        free = (paid // buy) * gift
    return {"paid_quantity": format(paid, "f"), "free_quantity": format(free, "f"),
            "shipped_quantity": format(paid + free, "f")}


# 원본: reference/kekorea/Quotation_KEKOREA/agent/trade_documents.py _decimal
def _decimal(value, field, issues, *, allow_zero=True):
    try:
        text = str(value).strip()
        if "," in text and not re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
            raise InvalidOperation
        result = Decimal(text.replace(",", ""))
        if not result.is_finite() or result < 0 or (not allow_zero and result == 0):
            raise InvalidOperation
        return result
    except (InvalidOperation, TypeError, ValueError):
        issues.append(f"Valid {'positive ' if not allow_zero else ''}number required for {field}")
        return Decimal("0")


# 원본: reference/kekorea/Quotation_KEKOREA/agent/trade_documents.py _has_korean
def _has_korean(value):
    return isinstance(value, str) and re.search(r"[\uac00-\ud7a3]", value) is not None


# 원본: reference/kekorea/Quotation_KEKOREA/agent/trade_documents.py _has_chinese
def _has_chinese(value):
    return isinstance(value, str) and re.search(r"[\u3400-\u9fff]", value) is not None


# 원본: reference/kekorea/Quotation_KEKOREA/agent/trade_documents.py _has_english_parenthetical
def _has_english_parenthetical(value):
    return isinstance(value, str) and re.search(r"\([^()]*[A-Za-z][^()]*\)", value) is not None


# 원본: reference/kekorea/Quotation_KEKOREA/agent/trade_documents.py _plain_decimal
def _plain_decimal(value):
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


# 원본: reference/kekorea/Quotation_KEKOREA/agent/trade_documents.py validate_and_calculate
# (발행사 역할 검사만 계약 15.4절대로 issuer_key 일반화. 머리글 참고)
def validate_and_calculate(data, *, issuer_key):
    """Validate extracted user data, calculate sums, and identify issue blockers."""
    # Issue date is a system field: the issue date is always the current Seoul date.
    data = {**data, "issue_date": current_issue_date()}
    from app.trade.promotions import recalculate_order_promotions
    data = recalculate_order_promotions(data)
    issues, blocking = [], []

    def block(message):
        if message not in blocking:
            blocking.append(message)

    doc_type = data.get("document_type")
    if doc_type not in DOC_TYPES:
        block("Document type must be PO, PI, CI, or PL")
    family = data.get("product_family")
    if family not in FAMILIES:
        block("Product family must be confirmed")
    currency = data.get("currency")
    if doc_type != "PL" and (not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency)):
        block("Currency must be confirmed as a three-letter code")
    elif doc_type != "PL" and currency not in {"USD", "KRW", "EUR", "CNY"}:
        block(f"Currency rounding rule for {currency} must be configured")
    money_quantum = Decimal("1") if currency == "KRW" else MONEY_QUANTUM

    for role in ("buyer", "seller"):
        party = data.get(role) or {}
        display = "Buyer" if role == "buyer" else "Seller"
        for field, label in (("legal_name", "legal name"), ("address", "address")):
            value = party.get(field)
            if not value:
                block(f"{display} {label} is required")
            elif _has_korean(value):
                block(f"{display} {label} must be English")
            elif _has_chinese(value) and not _has_english_parenthetical(value):
                block(f"{display} Chinese {label} must include its English translation in parentheses")
        for field in ("contact", "phone", "email"):
            if _has_chinese(party.get(field)):
                block(f"{display} {field} must be English only")

    # 기존 생성 경로도 도메인이 소유한 규칙을 사용한다. 계산·반올림은 아래에서 공유한다.
    if doc_type == "PO":
        from app.trade.po.rules import validate_header
    elif doc_type == "PI":
        from app.trade.pi.rules import validate_header
    elif doc_type == "CI":
        from app.trade.ci.rules import validate_header
    elif doc_type == "PL":
        from app.trade.pl.rules import validate_header
    if doc_type in DOC_TYPES:
        validate_header(data, str(issuer_key or "").strip(), block)

    if not data.get("document_number"):
        block("Document number is required or must be marked DRAFT")
    if not data.get("incoterms"):
        block("Incoterms and named place")

    items = data.get("items") or []
    if not items:
        block("At least one line item is required")
    calculated, total = [], Decimal("0")
    for i, original in enumerate(items, 1):
        item = dict(original)
        from app.trade.samples import is_manual_sample
        from app.trade.ci_import import pi_source_zero_price
        sample = is_manual_sample(data, item)
        row_issue_start = len(issues)
        row_block_start = len(blocking)
        name = item.get("product_name")
        if not name:
            block(f"Product name is required for item {i}")
        elif _has_korean(name):
            block(f"Product name for item {i} must be English")
        elif _has_chinese(name):
            block(f"Product name for item {i} must be translated into English")
        for field in ("capacity", "unit", "price_basis", "promotion", "price_source"):
            if _has_chinese(item.get(field)):
                block(f"{field.replace('_', ' ').title()} for item {i} must be translated into English")
        if not item.get("unit"):
            block(f"Quantity unit for item {i}")
        if doc_type != "PL" and not item.get("price_basis"):
            block(f"Price basis for {name or f'item {i}'}")
        quantity_keys = ("shipped_quantity", "quantity", "paid_quantity") if doc_type == "PL" else ("paid_quantity", "quantity")
        quantity_value = next((item.get(key) for key in quantity_keys if item.get(key) not in (None, "")), None)
        quantity = _decimal(quantity_value, f"paid quantity for item {i}", issues)
        base = Decimal("0") if doc_type == "PL" else _decimal(item.get("unit_price"), f"unit price for item {i}", issues, allow_zero=sample or pi_source_zero_price(data, item))
        discount = Decimal("0") if doc_type == "PL" else _decimal(item.get("discount_percent", 0), f"discount percent for item {i}", issues)
        if doc_type in {"PI", "CI"} and data.get("product_family") == "cosmetics" and item.get("discount_percent") is None:
            block(f"Confirm discount percentage, including whether no discount applies, for {name or f'item {i}'}")
        if discount > 100:
            block(f"Discount for item {i} must be between 0 and 100 percent")
            discount = Decimal("0")
        if doc_type != "PL" and not item.get("price_source"):
            block(f"Price source for {name or f'item {i}'} must be recorded")
        if doc_type != "PL" and data.get("product_family") == "cosmetics" and item.get("master_price") is not True and not item.get("price_override_confirmed"):
            block(f"Cosmetics price for {name or f'item {i}'} must match the verified price master")
        basis = str(item.get("price_basis") or "").upper().replace("USD/", "").replace("KRW/", "").replace("PER ", "").strip()
        basis = normalize_quantity_unit(basis)
        unit = normalize_quantity_unit(item.get("unit"))
        if doc_type != "PL" and data.get("product_family") in {"polysilicon", "wafer", "solar_cell", "solar_module"} and basis and unit and basis not in {unit, "SET"}:
            block(f"Price basis {basis} does not match quantity unit {unit} for {name or f'item {i}'}")
        unit_quantum = money_quantum if data.get("product_family") == "cosmetics" else PRICE_QUANTUM
        final = (base * (Decimal("1") - discount / Decimal("100"))).quantize(unit_quantum, rounding=ROUND_HALF_UP)
        line = (quantity * final).quantize(money_quantum, rounding=ROUND_HALF_UP)
        free = Decimal("0") if doc_type == "PL" else _decimal(item.get("free_quantity", 0), f"free quantity for item {i}", issues)
        shipped = quantity if doc_type == "PL" else _decimal(item.get("shipped_quantity", quantity + free), f"shipped quantity for item {i}", issues)
        if shipped != quantity + free:
            block(f"Shipped quantity must equal paid plus free quantity for {name or f'item {i}'}")
        if doc_type != "PL" and item.get("promotion"):
            try:
                expected = apply_promotion(quantity, item["promotion"])
                if Decimal(expected["free_quantity"]) != free:
                    block(f"Promotion quantity mismatch for {name or f'item {i}'}")
            except ValueError:
                block(f"Promotion rule for {name or f'item {i}'} must be confirmed")
        item.update({"base_unit_price": _plain_decimal(base), "final_unit_price": _plain_decimal(final),
                     "line_total": format(line, "f"), "quantity": format(quantity, "f"),
                     "paid_quantity": format(quantity, "f"), "free_quantity": format(free, "f"),
                     "shipped_quantity": format(shipped, "f"), "discount_percent": format(discount, "f")})
        item["display_quantity"] = format(shipped if doc_type == "PL" else quantity + free, "f")
        if sample and (len(issues) > row_issue_start or len(blocking) > row_block_start):
            block(f"Sample {i}: confirm a valid name, quantity, unit and non-negative unit price")
        calculated.append(item)
        total += line
    total = total.quantize(money_quantum, rounding=ROUND_HALF_UP)

    if doc_type == "PL":
        from app.trade.pl.rules import validate_packing
        validate_packing(data, calculated, issues, block)

    for field in ("incoterms", "payment_terms", "remarks", "ship_to", "bill_to", "country_of_origin",
                  "document_number", "issue_date", "shipment_reference", "actual_package_count"):
        if _has_chinese(data.get(field)):
            block(f"{field.replace('_', ' ').title()} must be translated into English")
    for i, package in enumerate(data.get("packages") or [], 1):
        for field in ("package_type", "dimensions", "shipping_marks"):
            if _has_chinese(package.get(field)):
                block(f"Package {i} {field.replace('_', ' ')} must be translated into English")
    for issue in data.get("conflicts", []):
        block(f"Resolve conflicting information: {issue}")
    for field in data.get("missing_fields", []):
        block(f"Confirm missing information: {field}")

    return {**data, "items": calculated, "subtotal": format(total, "f"), "total": format(total, "f"),
            "blocking_issues": blocking + issues, "ready_for_issue": not blocking and not issues,
            "status": "ready" if not blocking and not issues else "needs_input"}
