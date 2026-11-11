"""PL 포장 수량·중량 규칙. 원본 검증에서 옮겨 공통 계산과 분리한다.

원본: reference/kekorea/Quotation_KEKOREA/agent/trade_documents.py validate_and_calculate
"""
from decimal import Decimal, InvalidOperation

from app.trade.trade_documents import _decimal


def validate_header(data, issuer, block):
    if not data.get("shipment_reference"):
        block("Shipment reference")


def validate_packing(data, calculated, issues, block):
    from app.trade.pl.packing import reconcile_packing
    packing = reconcile_packing({**data, "items": calculated})
    for issue in packing["issues"]:
        block("Packing: " + issue)
    for discrepancy in packing["discrepancies"]:
        block("Packing source discrepancy: " + discrepancy)
    packages = data.get("packages") or []
    has_item_packing = any(item.get("net_weight_kg") or item.get("gross_weight_kg") or item.get("package_count") or item.get("volume_cbm") for item in calculated)
    if not has_item_packing and (not packages or not data.get("actual_package_count")):
        block("Actual package count and weights")
    actual_count = Decimal("0")
    if not has_item_packing:
        try:
            actual_count = Decimal(str(data.get("actual_package_count")))
            if not actual_count.is_finite() or actual_count <= 0 or actual_count != actual_count.to_integral_value():
                raise InvalidOperation
        except (InvalidOperation, TypeError, ValueError):
            block("Actual package count must be a positive whole number")
    declared_count = Decimal("0")
    for i, package in enumerate(packages if not has_item_packing else [], 1):
        net = _decimal(package.get("net_weight_kg"), f"package {i} net weight", issues, allow_zero=False)
        gross = _decimal(package.get("gross_weight_kg"), f"package {i} gross weight", issues, allow_zero=False)
        count = _decimal(package.get("package_count"), f"package {i} count", issues, allow_zero=False)
        if count != count.to_integral_value():
            block(f"Package count for package {i} must be a whole number")
        declared_count += count
        if net > gross:
            block(f"Net weight cannot exceed gross weight for package {i}")
    if packages and not has_item_packing and declared_count != actual_count:
        block("Sum of package counts must equal actual package count")
