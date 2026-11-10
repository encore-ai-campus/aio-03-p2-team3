"""빠진 문서값의 서술·검토 입력(kekorea-port 3절 B 테스트가 쓰고, 5·6절이 화면 경로를 잇는다).

원본: reference/kekorea/Quotation_KEKOREA/agent/review_fields.py — 원본 복사본.
계약 15.4절 일정 대응: 3절(B)가 옮기는 원본 테스트(test_order_promotions·test_pi_samples)가 이
모듈을 직접 부르기 때문에 함께 넣었다. 바꾼 것은 import 경로뿐이다.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re


@dataclass(frozen=True)
# 원본: reference/kekorea/Quotation_KEKOREA/agent/review_fields.py ReviewField
class ReviewField:
    path: tuple
    label: str
    required: bool = True


# 원본: reference/kekorea/Quotation_KEKOREA/agent/review_fields.py _missing
def _missing(value, required):
    text = re.sub(r"[\s_.-]+", " ", "" if value is None else str(value)).strip().casefold()
    if text in {"", "not provided", "to be confirmed", "tobe confirmed", "to confirm", "tbd", "unknown", "none", "null"}:
        return True
    return required and text in {"n/a", "na", "not applicable"}


# 원본: reference/kekorea/Quotation_KEKOREA/agent/review_fields.py field_value
def field_value(data, field):
    value = data
    for part in field.path:
        if isinstance(value, dict):
            value = value.get(part)
        elif isinstance(value, list) and isinstance(part, int) and part < len(value):
            value = value[part]
        else:
            return None
    return value


# 원본: reference/kekorea/Quotation_KEKOREA/agent/review_fields.py missing_review_fields
def missing_review_fields(data):
    dtype = data.get("document_type")
    fields = [ReviewField(("document_number",), "Document number (or DRAFT)"),
              ReviewField(("incoterms",), "Delivery terms / Incoterms and named place"),
              ReviewField(("payment_terms",), "Payment terms", dtype in {"PI", "PO"}),
              ReviewField(("ship_to",), "Ship-to address", False),
              ReviewField(("country_of_origin",), "Country of origin", dtype == "CI"),
              ReviewField(("shipment_reference",), "Shipment reference", dtype in {"CI", "PL"})]
    if dtype != "PL":
        fields.append(ReviewField(("currency",), "Currency (USD / KRW / EUR / CNY)"))
    for role, party in (("seller", "Seller / supplier"), ("buyer", "Buyer / customer")):
        for key, label in (("legal_name", "legal name"), ("address", "address"),
                           ("contact", "contact / representative"), ("phone", "phone"), ("email", "email")):
            fields.append(ReviewField((role, key), f"{party}: {label}", key in {"legal_name", "address"}))
    for i, item in enumerate(data.get("items") or []):
        for key, label in (("product_name", "product name"), ("unit", "quantity unit"), ("quantity", "quantity")):
            if key == "quantity" and not _missing(item.get("paid_quantity"), True):
                continue
            fields.append(ReviewField(("items", i, key), f"Item {i + 1}: {label}"))
        if dtype != "PL":
            fields.extend([ReviewField(("items", i, "unit_price"), f"Item {i + 1}: unit price"),
                           ReviewField(("items", i, "discount_percent"), f"Item {i + 1}: discount % (0 if none)")])
    if dtype == "PL":
        fields.append(ReviewField(("container_count",), "Containers (0 if not containerized)"))
    return [field for field in fields if _missing(field_value(data, field), field.required)]


# 원본: reference/kekorea/Quotation_KEKOREA/agent/review_fields.py apply_review_value
def apply_review_value(data, field, value):
    value = ("" if value is None else str(value)).strip()
    if _missing(value, field.required):
        return
    target = data
    for part in field.path[:-1]:
        if isinstance(target, dict):
            target = target.setdefault(part, {})
        else:
            target = target[part]
    target[field.path[-1]] = value
    if field.path[0] == "items":
        if field.path[-1] == "unit_price":
            target['price_source'] = 'User-entered value in document review'
        if field.path[-1] == "quantity":
            target['paid_quantity'] = value
            try:
                target['shipped_quantity'] = format(Decimal(value) + Decimal(str(target.get('free_quantity') or '0')), 'f')
            except InvalidOperation:
                pass
        if field.path[-1] == "discount_percent":
            try:
                from app.trade.samples import is_manual_sample
                discounts = {Decimal(str(item.get('discount_percent'))) for item in data.get('items', [])
                             if not is_manual_sample(data, item)}
                valid = len(discounts) == 1 and all(rate.is_finite() and 0 <= rate <= 100 for rate in discounts)
            except InvalidOperation:
                valid = False
            if valid:
                resolved = {'Discount was mentioned without a percentage; specify a single discount rate.',
                            'Multiple discount rates were requested; specify one rate for this invoice.'}
                data['conflicts'] = [entry for entry in data.get('conflicts', []) if entry not in resolved]
    # Clear only an exact matching missing-field label, never unrelated evidence or conflicts.
    aliases = {field.path[-1].casefold(), field.path[-1].replace('_', ' ').casefold(), field.label.casefold()}
    data['missing_fields'] = [entry for entry in data.get('missing_fields', [])
                              if str(entry).strip().casefold() not in aliases]
