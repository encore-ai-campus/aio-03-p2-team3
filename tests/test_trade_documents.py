"""무역서류 검증·계산 pytest(원본 tests/test_trade_documents.py의 계산 부분 이식).

원본: reference/kekorea/Quotation_KEKOREA/tests/test_trade_documents.py
- 출력 부분(test_amount_words·test_generated_review_files·test_chinese_company_name_is_preserved·
  test_renderer_rejects_non_english)은 kekorea-port 4절(C 문서 출력) 범위라 여기에 두지 않았다.
- 가격 시드 테스트 3종은 회사 가격 시드 대신 가상 단가표(build_trade_catalog)로 바꿨다.
- 발행사 이름·거래처 이름은 가상 값으로 바꿨고, 원본의 "KE KOREA" 고정 검사는 계약 15.4절대로
  issuer_key 비교로 바꿨다.
"""
from decimal import Decimal

from app.trade.common.counterparties import name_key
from app.trade.common.pricing import (
    apply_verified_catalog_prices,
    build_trade_catalog,
    match_catalog_product,
    resolve_price,
)
from app.trade.common.trade_documents import validate_and_calculate


ISSUER_NAME = "Testworks Trading Co"
ISSUER_KEY = name_key(ISSUER_NAME)


def sample_trade(**updates):
    data = {
        "document_type": "PI", "product_family": "cosmetics", "currency": "USD",
        "buyer": {"legal_name": "Example Buyer Ltd", "address": "1 Sample Road, Seoul", "contact": None, "phone": None, "email": None},
        "seller": {"legal_name": ISSUER_NAME + ". LTD", "address": None, "contact": None, "phone": None, "email": None},
        "items": [{"product_name": "Example Toner", "capacity": "100 ml", "quantity": "10", "unit": "PCS", "unit_price": "12.50", "price_basis": "per PCS", "discount_percent": "10", "paid_quantity": "10", "free_quantity": "0", "shipped_quantity": "10", "source": "synthetic test"}],
        "incoterms": None, "payment_terms": None, "remarks": None, "document_number": None,
        "issue_date": "2026-10-30", "ship_to": None, "bill_to": None,
        "missing_fields": [], "conflicts": [], "source_notes": ["synthetic test"],
    }
    data.update(updates)
    return data


def calculate(data):
    return validate_and_calculate(data, issuer_key=ISSUER_KEY)


def test_explicit_zero_quantity_is_valid_and_kept_in_every_document_type():
    for dtype in ("PI", "PO", "CI", "PL"):
        for zero in ("0", "0.0", 0):
            doc = sample_trade(document_type=dtype)
            doc["items"][0].update(quantity=zero, paid_quantity=zero, shipped_quantity=zero)
            result = calculate(doc)
            assert not any("paid quantity" in issue for issue in result["blocking_issues"])
            assert Decimal(result["items"][0]["quantity"]) == 0
            assert result["items"][0]["line_total"] == "0.00"
            assert result["total"] == "0.00"
            assert len(result["items"]) == 1


def test_missing_negative_and_nonfinite_quantities_remain_invalid():
    for value in (None, "", "-1", "invalid", "NaN", "Infinity"):
        doc = sample_trade()
        doc["items"][0].update(quantity=value, paid_quantity=value, shipped_quantity=value)
        result = calculate(doc)
        assert any("paid quantity" in issue for issue in result["blocking_issues"])


def test_image_quantity_total_includes_zero_row_without_blocking_calculation():
    quantities = [10, 15, 23, 20, 30, 405, 0, 10, 20, 30, 40, 50, 60, 70, 70, 40,
                  320, 10, 2040, 20, 10, 10, 20, 20]
    doc = sample_trade(product_family="other")
    template = doc["items"][0]
    doc["items"] = [{**template, "quantity": str(qty), "paid_quantity": str(qty),
                     "shipped_quantity": str(qty), "unit_price": "1", "discount_percent": "0"}
                    for qty in quantities]
    result = calculate(doc)
    assert not any("paid quantity" in issue for issue in result["blocking_issues"])
    assert sum(Decimal(item["quantity"]) for item in result["items"]) == 3343
    assert result["total"] == "3343.00"


def test_decimal_discount_is_applied_once_to_final_unit_price():
    result = calculate(sample_trade())
    item = result["items"][0]
    assert item["final_unit_price"] == "11.25"
    assert item["line_total"] == "112.50"
    assert result["total"] == "112.50"


def test_missing_transaction_terms_block_document_render():
    result = calculate(sample_trade())
    assert "Incoterms and named place" in result["blocking_issues"]
    assert result["ready_for_issue"] is False
    assert result["status"] == "needs_input"


def test_conflicting_or_unknown_price_basis_blocks_document():
    data = sample_trade(product_family="solar")
    data["items"][0]["price_basis"] = None
    result = calculate(data)
    assert "Price basis for Example Toner" in result["blocking_issues"]


def test_promotion_separates_paid_free_and_shipped_quantities():
    from app.trade.common.trade_documents import apply_promotion
    item = apply_promotion("5", "2+1")
    assert item == {"paid_quantity": "5", "free_quantity": "2", "shipped_quantity": "7"}


def test_free_items_are_not_charged():
    data = sample_trade()
    data["items"][0].update({"quantity": "5", "paid_quantity": "5", "free_quantity": "2", "shipped_quantity": "7"})
    result = calculate(data)
    assert result["items"][0]["line_total"] == "56.25"


def test_non_english_document_fields_are_rejected():
    data = sample_trade()
    data["buyer"]["legal_name"] = "가상의 구매자"
    result = calculate(data)
    assert "Buyer legal name must be English" in result["blocking_issues"]


def test_chinese_company_name_and_address_require_original_plus_english():
    data = sample_trade()
    data["buyer"]["legal_name"] = "华星贸易有限公司"
    data["buyer"]["address"] = "上海市浦东新区"
    result = calculate(data)
    assert "Buyer Chinese legal name must include its English translation in parentheses" in result["blocking_issues"]
    assert "Buyer Chinese address must include its English translation in parentheses" in result["blocking_issues"]


def test_chinese_company_name_and_address_with_english_translation_are_allowed():
    data = sample_trade()
    data["buyer"]["legal_name"] = "华星贸易有限公司 (Huaxing Trading Co., Ltd.)"
    data["buyer"]["address"] = "上海市浦东新区 (Pudong New Area, Shanghai)"
    result = calculate(data)
    assert "Buyer Chinese legal name must include its English translation in parentheses" not in result["blocking_issues"]
    assert "Buyer Chinese address must include its English translation in parentheses" not in result["blocking_issues"]


def test_chinese_remarks_must_be_translated_to_english_only():
    data = sample_trade(remarks="尽快发货")
    result = calculate(data)
    assert "Remarks must be translated into English" in result["blocking_issues"]


def test_po_and_pi_party_roles_are_checked():
    data = sample_trade(document_type="PO")
    assert ("PO buyer must be the issuing company"
            in calculate(data)["blocking_issues"])


def test_issuer_key_must_be_configured_for_role_checks():
    result = validate_and_calculate(sample_trade(), issuer_key="")
    assert "Issuing company name is not configured" in result["blocking_issues"]


def test_issuer_key_substring_allows_affiliate_names():
    """원본 허용 범위(본사↔해외 법인)를 이름 키 포함 관계로 유지한다(계약 15.4절)."""
    data = sample_trade(document_type="PO")
    data["buyer"] = {"legal_name": ISSUER_NAME + " America", "address": "Test"}
    data["seller"] = {"legal_name": "Acme Supplier Ltd", "address": "Test"}
    issues = calculate(data)["blocking_issues"]
    assert "PO buyer must be the issuing company" not in issues
    assert "PO seller must be the supplier and buyer must be the issuing company" not in issues
    # 발행사 키가 반대 역할(seller)에 포함되면 차단한다.
    data["seller"] = {"legal_name": ISSUER_NAME + " Supplier", "address": "Test"}
    issues = calculate(data)["blocking_issues"]
    assert "PO seller must be the supplier and buyer must be the issuing company" in issues


def test_unconfirmed_packing_cannot_be_finalized():
    data = sample_trade(document_type="PL")
    data["packages"] = []
    assert "Actual package count and weights" in calculate(data)["blocking_issues"]


# --- 가격 시드 테스트 3종을 가상 단가표로 옮긴 것(원본 load_local_seed 대신 build_trade_catalog) ---

def virtual_catalog_rows():
    return [
        {"id": 1, "item_name": "Test Repair Cream", "capacity": "50g", "product_code": "T-165",
         "role": "purchase", "currency": "KRW", "unit_price_text": "1000", "party_key": "ACME_SUPPLIER"},
        {"id": 2, "item_name": "Test Repair Cream", "capacity": "50g", "product_code": "T-165",
         "role": "sale", "currency": "USD", "unit_price_text": "10.25", "party_key": "ACME_BUYER"},
    ]


def test_virtual_catalog_separates_purchase_and_sale_price_roles():
    catalog = build_trade_catalog(virtual_catalog_rows())
    assert len(catalog["products"]) == 1  # 같은 품목의 매입·판매 행은 product 하나로 합친다
    product = catalog["products"][0]
    assert match_catalog_product(product["item_name"], product.get("capacity"),
                                 catalog["products"])["status"] == "matched"
    assert resolve_price(product["id"], catalog, "purchase", "KRW") is not None
    assert resolve_price(product["id"], catalog, "sale", "USD") is not None
    assert resolve_price(product["id"], catalog, "purchase", "USD") is None
    assert resolve_price(product["id"], catalog, "sale", "KRW") is None


def test_sale_price_is_not_applied_to_an_unregistered_buyer():
    catalog = build_trade_catalog(virtual_catalog_rows())
    product = catalog["products"][0]
    draft = {"document_type": "PI", "product_family": "cosmetics", "currency": "USD",
             "buyer": {"legal_name": "Different Buyer Ltd"}, "items": [{
                 "product_name": product["item_name"], "capacity": product["capacity"],
                 "unit_price": None, "source": None}]}
    apply_verified_catalog_prices(draft, catalog)
    assert draft["items"][0].get("master_price") is not True
    assert any("local catalog price is only for ACME_BUYER" in issue
               for issue in draft["missing_fields"])


def test_purchase_and_sale_prices_are_selected_by_document_direction():
    catalog = build_trade_catalog(virtual_catalog_rows())
    product = catalog["products"][0]
    item = {"product_name": product["item_name"], "capacity": product["capacity"],
            "unit_price": None, "source": None}
    pi = {"document_type": "PI", "product_family": "cosmetics", "currency": "USD",
          "buyer": {"legal_name": "Acme Buyer Pte Ltd"}, "items": [dict(item)]}
    po = {"document_type": "PO", "product_family": "cosmetics", "currency": "KRW",
          "seller": {"legal_name": "Acme Supplier Co. Ltd"}, "items": [dict(item)]}
    apply_verified_catalog_prices(pi, catalog)
    apply_verified_catalog_prices(po, catalog)
    assert pi["items"][0]["price_source"].split(";")[0] == "Verified catalog price"
    assert po["items"][0]["price_source"].split(";")[0] == "Verified catalog price"
    assert pi["currency"] == "USD"
    assert po["currency"] == "KRW"
