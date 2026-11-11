"""포장 명세(PL) 행 합계 비교 코어(kekorea-port 5절 D).

원본: reference/kekorea/Quotation_KEKOREA/agent/packing.py — 복사본(고침 없음).
바꾼 것은 import 경로(`Quotation_KEKOREA.agent...` → `app.trade...`)뿐이다. 계약 15.4절 일정
대응으로 3절(B)이 원본 복사본을 먼저 넣었고, 5절(D)이 그 위에서 PL 승인 흐름
(`app/trade/packing_review.py`·`app/services/trade_docs.py`)을 이식했다. 검토 입력 정규화 문제까지
더한 PL 합계 비교는 `packing_review.reconcile_packing`(래퍼)을 부른다(계약 15.5절).
"""
from decimal import Decimal, InvalidOperation
import re

from app.trade.trade_documents import normalize_quantity_unit


# 원본: reference/kekorea/Quotation_KEKOREA/agent/packing.py _number
def _number(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        text = str(value).strip()
        if "," in text and not re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
            return None
        number = Decimal(text.replace(",", ""))
        return number if number.is_finite() and number >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


# 원본: reference/kekorea/Quotation_KEKOREA/agent/packing.py _plain
def _plain(number):
    return format(number, "f") if number is not None else None


# 원본: reference/kekorea/Quotation_KEKOREA/agent/packing.py reconcile_packing
def reconcile_packing(data):
    """Return calculated totals and discrepancies; printed totals are never overwritten."""
    items = data.get("items") or []
    issues, discrepancies = [], []
    quantities = {}
    quantity_complete = bool(items)
    for index, item in enumerate(items, 1):
        quantity_value = next((item.get(key) for key in ("shipped_quantity", "quantity", "paid_quantity")
                               if item.get(key) not in (None, "")), None)
        amount = _number(quantity_value)
        unit = normalize_quantity_unit(item.get("unit"))
        if amount is None or not unit:
            quantity_complete = False
            issues.append(f"Packing row {index}: quantity and unit must be confirmed")
        else:
            quantities[unit] = quantities.get(unit, Decimal("0")) + amount
        net = _number(item.get("net_weight_kg"))
        gross = _number(item.get("gross_weight_kg"))
        if net is not None and gross is not None and net > gross:
            issues.append(f"Packing row {index}: net weight exceeds gross weight")
        for field, label in (("package_count", "package count"), ("net_weight_kg", "net weight"),
                             ("gross_weight_kg", "gross weight"), ("volume_cbm", "CBM")):
            if item.get(field) not in (None, "") and _number(item.get(field)) is None:
                issues.append(f"Packing row {index}: {label} is invalid")

    calculated = {}
    for field, label, declared_field in (
        ("package_count", "package count", "actual_package_count"),
        ("net_weight_kg", "net weight (kg)", "declared_net_weight_kg"),
        ("gross_weight_kg", "gross weight (kg)", "declared_gross_weight_kg"),
        ("volume_cbm", "volume (CBM)", "declared_volume_cbm"),
    ):
        values = [_number(item.get(field)) for item in items]
        total = sum(values, Decimal("0")) if values and all(value is not None for value in values) else None
        if field == "package_count" and total is not None:
            package_types = {normalize_quantity_unit(item.get("package_type")) for item in items}
            if len(package_types) > 1:
                issues.append("Package counts use different package types; confirm their totals separately")
                total = None
        calculated[field] = _plain(total)
        declared_raw = data.get(declared_field)
        declared = _number(declared_raw)
        if declared_raw not in (None, "") and declared is None:
            message = f"Source {label} total is invalid"
            (discrepancies if total is not None else issues).append(message)
        elif total is not None and declared is not None and total != declared:
            discrepancies.append(f"Source {label} total {_plain(declared)} differs from row sum {_plain(total)}")

    declared_quantity = _number(data.get("declared_total_quantity"))
    declared_unit = normalize_quantity_unit(data.get("declared_total_quantity_unit"))
    if data.get("declared_total_quantity") not in (None, "") and declared_quantity is None:
        (discrepancies if quantity_complete else issues).append("Source quantity total is invalid")
    elif declared_quantity is not None:
        if not declared_unit or declared_unit not in quantities:
            discrepancies.append("Source quantity total unit does not match the item units; confirm the total")
        elif quantities[declared_unit] != declared_quantity:
            discrepancies.append(f"Source quantity total {_plain(declared_quantity)} {declared_unit} differs from row sum {_plain(quantities[declared_unit])} {declared_unit}")

    raw_containers = data.get("container_count")
    if raw_containers not in (None, ""):
        containers = _number(raw_containers)
        if containers is None or containers != containers.to_integral_value():
            issues.append("Container count must be a non-negative whole number")

    return {"quantities": {unit: _plain(value) for unit, value in quantities.items()},
            "quantity_complete": quantity_complete, "calculated": calculated,
            "issues": issues, "discrepancies": discrepancies}
