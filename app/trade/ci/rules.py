"""CI 발행사·선적 정보. 결제 조건을 요구하지 않는다."""
from app.trade.counterparties import name_key


def validate_header(data, issuer, block):
    if not issuer:
        block("Issuing company name is not configured")
    elif issuer not in name_key((data.get("seller") or {}).get("legal_name")):
        block("CI seller must be the issuing company")
    if not data.get("shipment_reference"):
        block("Shipment reference")
    if not data.get("country_of_origin"):
        block("Country of origin must be confirmed")
