"""PO 발행사 역할과 지급 조건."""
from app.trade.counterparties import name_key


def validate_header(data, issuer, block):
    if not issuer:
        block("Issuing company name is not configured")
    else:
        if issuer not in name_key((data.get("buyer") or {}).get("legal_name")):
            block("PO buyer must be the issuing company")
        seller_name = (data.get("seller") or {}).get("legal_name")
        if not seller_name or issuer in name_key(seller_name):
            block("PO seller must be the supplier and buyer must be the issuing company")
    if not data.get("payment_terms"):
        block("Payment terms")
