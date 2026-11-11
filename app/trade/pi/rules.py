"""PI 발행사 역할과 지급 조건."""
from app.trade.counterparties import name_key


def validate_header(data, issuer, block):
    if not issuer:
        block("Issuing company name is not configured")
    elif issuer not in name_key((data.get("seller") or {}).get("legal_name")):
        block("PI seller must be the issuing company")
    if not data.get("payment_terms"):
        block("Payment terms")
