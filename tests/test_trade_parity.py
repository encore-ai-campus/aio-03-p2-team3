"""동일성 비교: 같은 입력을 원본 사본(reference) 함수와 이식본 함수에 넣어 결과가 같은지 확인한다.

- 원본 사본은 읽기 전용이고 sys.path 조작으로 임시로 import한다(이식 규칙 1의 허용 범위).
  참고 경로는 이 모듈의 테스트가 도는 동안만 sys.path에 있다.
- 회사 고유 값은 테스트 코드에 둘 수 없으므로(이식 규칙 4), 사본 코드가 기대하는 상수
  (브랜드·거래처 키·발행사 토큰)는 사본 소스에서 추출해 입력으로만 쓴다. 추출에 실패하면
  그 비교는 건너뛴다(지어낸 값으로 통과하게 두지 않는다).
- 계약 15.4절이 일부러 바꾼 동작(발행사 검사 문구·PO 통화 강제 폐지·가격 문구)은 비교 대상에서
  빼고, 그 규칙 자체는 tests/test_trade_documents.py·test_trade_pricing.py가 검증한다.
"""
import copy
import importlib
import re
import sys
from pathlib import Path

import pytest

from app.trade.common import counterparties as port_counterparties
from app.trade.pl import packing as port_packing
from app.trade.common import pricing as port_pricing
from app.trade.common import product_matching as port_matching
from app.trade.common import promotions as port_promotions
from app.trade.pi import samples as port_samples
from app.trade.common import trade_documents as port_trade

REFERENCE_ROOT = Path(__file__).resolve().parents[1] / "reference" / "kekorea"
HAS_REFERENCE = (REFERENCE_ROOT / "Quotation_KEKOREA" / "agent" / "trade_documents.py").exists()

pytestmark = pytest.mark.skipif(not HAS_REFERENCE, reason="원본 사본(reference/kekorea)이 없습니다")


@pytest.fixture(scope="module")
def ref():
    """원본 사본 모듈(테스트 도중에만 참고 경로를 sys.path에 둔다)."""
    sys.path.insert(0, str(REFERENCE_ROOT))
    try:
        names = ("trade_documents", "promotions", "samples", "product_matching",
                 "counterparties", "pricing", "ci_import", "packing")
        return {name: importlib.import_module("Quotation_KEKOREA.agent." + name) for name in names}
    finally:
        sys.path.remove(str(REFERENCE_ROOT))


def _derive(source, pattern, what):
    match = re.search(pattern, source)
    if not match:
        pytest.skip(f"사본 소스에서 {what}를 찾지 못해 이 비교는 건너뛴다")
    return match.group(1)


def _issuer_filtered(messages, issuer_token):
    return [m for m in messages if issuer_token not in m
            and m not in {"PO buyer must be the issuing company",
                          "PO seller must be the supplier and buyer must be the issuing company",
                          "PI seller must be the issuing company",
                          "CI seller must be the issuing company",
                          "Issuing company name is not configured"}]


def _compare_validation(reference_result, ported_result, issuer_token):
    """계약 15.4·15.5절이 바꾼 값(발행사 문구·status 표기)만 빼고 전체가 같은지 비교한다."""
    ref_doc = {key: value for key, value in reference_result.items()
               if key not in {"blocking_issues", "status"}}
    port_doc = {key: value for key, value in ported_result.items()
                if key not in {"blocking_issues", "status"}}
    assert ref_doc == port_doc
    assert _issuer_filtered(reference_result["blocking_issues"], issuer_token) == \
           _issuer_filtered(ported_result["blocking_issues"], issuer_token)
    expected_status = {"DRAFT": "needs_input", "READY_FOR_USER_CONFIRMATION": "ready"}
    assert expected_status[reference_result["status"]] == ported_result["status"]


def sample_docs():
    base_item = {"product_name": "Example Toner", "capacity": "100 ml", "quantity": "10",
                 "unit": "PCS", "unit_price": "12.50", "price_basis": "per PCS",
                 "discount_percent": "10", "paid_quantity": "10", "free_quantity": "0",
                 "shipped_quantity": "10", "source": "synthetic test"}
    base = {
        "document_type": "PI", "product_family": "cosmetics", "currency": "USD",
        "buyer": {"legal_name": "Example Buyer Ltd", "address": "1 Sample Road, Seoul"},
        "seller": {"legal_name": "Testworks Trading Co. Ltd", "address": "2 Issue Road, Seoul"},
        "items": [dict(base_item)],
        "incoterms": "FOB Busan", "payment_terms": "T/T in advance", "remarks": None,
        "document_number": "PI-TEST-1", "ship_to": None, "bill_to": None,
        "missing_fields": [], "conflicts": [], "source_notes": ["synthetic test"],
    }
    docs = [dict(base)]
    docs.append({**base, "items": [dict(base_item, quantity="0", paid_quantity="0",
                                        shipped_quantity="0", unit_price="0")]})
    docs.append({**base, "product_family": "other", "buyer": {"legal_name": "가상의 구매자"}})
    docs.append({**base, "buyer": {"legal_name": "华星贸易有限公司 (Huaxing Trading Co., Ltd.)",
                                   "address": "上海市浦东新区 (Pudong New Area, Shanghai)"}})
    docs.append({**base, "items": [dict(base_item, promotion="2+1", free_quantity="5",
                                        shipped_quantity="15")]})
    docs.append({**base, "items": [dict(base_item, discount_percent=None)]})
    docs.append({**base, "document_type": "PL", "currency": None,
                 "items": [dict(base_item, unit_price=None, price_basis=None,
                                net_weight_kg="1.5", gross_weight_kg="2")],
                 "declared_total_quantity": "10", "declared_total_quantity_unit": "PCS",
                 "container_count": "1", "shipment_reference": "SHP-1"})
    docs.append({**base, "document_type": "PO", "currency": "KRW",
                 "buyer": {"legal_name": "Testworks Trading Co", "address": "2 Issue Road"},
                 "seller": {"legal_name": "Acme Supplier Co. Ltd", "address": "3 Supply Road"},
                 "items": [dict(base_item, unit_price="1000")]})
    docs.append({**base, "document_type": "CI", "country_of_origin": "KR",
                 "shipment_reference": "SHP-2", "payment_terms": None})
    return docs


def test_pure_helpers_match(ref):
    issuer_token = _derive(inspect_source(ref["trade_documents"]), r'if "([A-Z ]+)" not in buyer', "발행사 토큰")
    assert port_trade.current_issue_date() == ref["trade_documents"].current_issue_date()
    for value in ("kg", "KGS", "Pcs", "BOXES", " MT ", "tonne", "Litre", None, ""):
        assert port_trade.normalize_quantity_unit(value) == ref["trade_documents"].normalize_quantity_unit(value)
    for paid, rule in (("5", "2+1"), ("7", "3+1"), ("0", "4+1"), ("10", None)):
        assert port_trade.apply_promotion(paid, rule) == ref["trade_documents"].apply_promotion(paid, rule)
    for paid, rule in (("-1", "2+1"), ("2.5", "2+1"), ("3", "0+1"), ("3", "x")):
        for module in (port_trade, ref["trade_documents"]):
            with pytest.raises(ValueError):
                module.apply_promotion(paid, rule)
    assert issuer_token  # 추출 성공 확인


def inspect_source(module):
    import inspect
    return inspect.getsource(module)


def test_validate_and_calculate_matches(ref):
    issuer_token = _derive(inspect_source(ref["trade_documents"]), r'if "([A-Z ]+)" not in buyer', "발행사 토큰")
    for doc in sample_docs():
        reference_result = ref["trade_documents"].validate_and_calculate(copy.deepcopy(doc))
        ported_result = port_trade.validate_and_calculate(copy.deepcopy(doc),
                                                          issuer_key="testworkstrading")
        _compare_validation(reference_result, ported_result, issuer_token)


def test_match_product_matches(ref):
    brand = _derive(inspect_source(ref["product_matching"]), r"p\.get\('brand'\) == '(\w+)'", "브랜드 상수")
    products = [dict(id='cream50', brand=brand, source_code='T-165',
                     item_name='Test Repair Cream', capacity='50g'),
                dict(id='cream200', brand=brand, source_code='T-166-1',
                     item_name='Test Repair Cream', capacity='200g')]
    for name, capacity, code in [
            ('Test Repair Cream (T-165)', '50g', None),
            ('T-165 | Test Repair Cream', '50g', None),
            ('Test Repair Cream', None, 'T165'),
            ('Test Repa1r Cream', '50g', None),
            ('Test Repaer Crem', '50g', None),
            ('Test Repair Cream (T-166-1)', '50g', None),
            ('Test Repair Cream (T999)', '50g', None),
            ('Test Repair Cream', '50ml', None),
            ('Unrelated Product', None, None)]:
        assert port_matching.match_product(name, capacity, products, code) == \
               ref["product_matching"].match_product(name, capacity, products, code)


def test_resolve_price_matches(ref):
    seed = {"purchase_prices": [{"product_id": "p1", "supplier_key": "TESTPARTY",
                                 "currency": "KRW", "unit_price": "8000"}],
            "buyer_prices": [{"product_id": "p1", "buyer_key": "TESTPARTY",
                              "currency": "USD", "unit_price": "10.25"},
                             {"product_id": "p1", "buyer_key": "TESTPARTY",
                              "currency": "EUR", "unit_price": "9"}]}
    for role, currency, party in (("sale", "USD", "TESTPARTY"), ("sale", None, "TESTPARTY"),
                                  ("sale", "USD", "OTHER"), ("purchase", "KRW", "TESTPARTY"),
                                  ("purchase", None, None), ("sale", "KRW", None)):
        assert port_pricing.resolve_price("p1", seed, role, currency, party) == \
               ref["pricing"].resolve_price("p1", seed, role, currency, party)


def test_apply_company_profiles_matches(ref):
    profile = dict(company_key="ACME_BUYER", legal_name="ACME BUYER PTE LTD",
                   aliases=["Acme Buyer", "AcmeBuyer"], address="Test Registered Address",
                   contact="MS. TEST CONTACT", default_ship_to="Test Delivery Address",
                   ship_to_phone="N/A")
    cases = [
        (dict(document_type="PI", buyer={}, seller={"legal_name": "Testworks Trading Co"}),
         [profile], "Acme Buyer에 인보이스 작성"),
        (dict(document_type="PO", buyer={"legal_name": "Testworks Trading Co"},
              seller={"legal_name": "Acme Buyer"}), [profile], ""),
        (dict(document_type="CI", buyer={"legal_name": "Different Buyer"}), [profile], "invoice please"),
        (dict(document_type="PI", buyer={"legal_name": "AcmeBuyer", "address": "Order Address"}),
         [profile, {**profile, "company_key": "OTHER"}], ""),
    ]
    for draft, profiles, prompt in cases:
        assert port_counterparties.apply_company_profiles(copy.deepcopy(draft),
                                                           copy.deepcopy(profiles),
                                                           prompt=prompt) == \
               ref["counterparties"].apply_company_profiles(copy.deepcopy(draft),
                                                             copy.deepcopy(profiles),
                                                             prompt=prompt)


def test_promotions_and_samples_match(ref):
    base = {"document_type": "PI", "currency": "USD", "product_family": "other",
            "buyer": {"legal_name": "Test Buyer", "address": "A"},
            "seller": {"legal_name": "Testworks Trading Co. Ltd", "address": "B"},
            "items": [{"product_name": "Test Toner", "quantity": "10", "paid_quantity": "10",
                       "free_quantity": "0", "shipped_quantity": "10", "unit": "PCS",
                       "unit_price": "2", "price_basis": "PCS", "discount_percent": "0",
                       "price_source": "User supplied"}]}
    for prompt in ("All products 3+1", "Test Toner 2+1", "Acme Buyer에 PI 작성. 4+3 행사 적용",
                   "All products 2+1 or 3+1"):
        reference = ref["promotions"].apply_promotion_commands(copy.deepcopy(base), prompt)
        ported = port_promotions.apply_promotion_commands(copy.deepcopy(base), prompt)
        assert ported == reference
    for dtype in ("PI", "PO"):
        draft = copy.deepcopy(base)
        draft["document_type"] = dtype
        draft["items"][0]["promotion"] = "3+1"
        draft["items"][0]["quantity"] = None
        draft["items"][0]["paid_quantity"] = None
        assert port_promotions.recalculate_order_promotions(copy.deepcopy(draft)) == \
               ref["promotions"].recalculate_order_promotions(copy.deepcopy(draft))
    # 샘플 행
    for prompt in ("샘플도 있어", "Acme Buyer PI sample", "regular order"):
        assert port_samples.ensure_sample_rows(copy.deepcopy(base), prompt) == \
               ref["samples"].ensure_sample_rows(copy.deepcopy(base), prompt)
    item = {"product_name": "Toner SAMPLE", "quantity": "5", "unit_price": "0"}
    assert port_samples.update_sample(dict(item), name="Trial Toner", capacity="2ml",
                                      quantity="5", unit="PCS", price="0") == \
           ref["samples"].update_sample(dict(item), name="Trial Toner", capacity="2ml",
                                        quantity="5", unit="PCS", price="0")


def test_packing_and_ci_import_match(ref):
    data = {"document_type": "PL", "items": [
        {"product_name": "Test Toner", "shipped_quantity": "10", "unit": "PCS",
         "net_weight_kg": "1.5", "gross_weight_kg": "2", "package_count": "2"},
        {"product_name": "Test Cream", "shipped_quantity": "3", "unit": "KG",
         "net_weight_kg": "0.5", "gross_weight_kg": "0.6"}],
        "declared_total_quantity": "10", "declared_total_quantity_unit": "PCS",
        "declared_net_weight_kg": "2", "container_count": "1"}
    assert port_packing.reconcile_packing(copy.deepcopy(data)) == \
           ref["packing"].reconcile_packing(copy.deepcopy(data))
    ci_draft = {"document_type": "CI", "source_document_type": "PI", "currency": "USD",
                "buyer": {"legal_name": "Example Buyer Ltd"}, "items": [
                    {"product_name": "Example Toner", "unit_price": "10", "source": "USD 10 each",
                     "quantity": "2", "paid_quantity": "2", "free_quantity": "0",
                     "shipped_quantity": "2", "unit": "PCS"}],
                "remarks": "Bank: test account", "missing_fields": ["Buyer full legal name"],
                "conflicts": ["Currency conflict: USD vs EUR"]}
    reference = ref["ci_import"].prepare_ci_import(copy.deepcopy(ci_draft),
                                                   requested_type="CI", has_attachments=True)
    from app.trade.ci import imports as port_ci_import
    ported = port_ci_import.prepare_ci_import(copy.deepcopy(ci_draft),
                                              requested_type="CI", has_attachments=True)
    assert ported == reference
    # CI 수량·금액 대조 문구도 회사 값 없이 그대로다.
    reference_result = ref["trade_documents"].validate_and_calculate(
        copy.deepcopy({**ci_draft, "document_type": "CI", "_ci_from_pi": True,
                       "product_family": "other", "incoterms": "FOB Busan",
                       "document_number": "CI-1", "country_of_origin": "KR",
                       "shipment_reference": "SHP-1", "source_total": "20.00"}))
    ported_result = port_trade.validate_and_calculate(
        copy.deepcopy({**ci_draft, "document_type": "CI", "_ci_from_pi": True,
                       "product_family": "other", "incoterms": "FOB Busan",
                       "document_number": "CI-1", "country_of_origin": "KR",
                       "shipment_reference": "SHP-1", "source_total": "20.00"}),
        issuer_key="testworkstrading")
    assert port_ci_import.ci_import_issues(ported_result) == ref["ci_import"].ci_import_issues(reference_result)
    issuer_token = _derive(inspect_source(ref["trade_documents"]), r'if "([A-Z ]+)" not in buyer', "발행사 토큰")
    _compare_validation(ref["ci_import"].ci_render_data(copy.deepcopy(reference_result)),
                        port_ci_import.ci_render_data(copy.deepcopy(ported_result)), issuer_token)


def test_apply_verified_prices_match_where_rules_are_unchanged(ref):
    """PI 판매가·PO 매입가 적용 경로는 계약 15.4절 일반화 뒤에도 같은 결과를 내야 한다."""
    source = inspect_source(ref["pricing"])
    po_key = _derive(source, r'resolve_price\(product\["id"\], seed, "purchase" if[^\n]*\n\s*"([A-Z_]+)" if',
                     "PO 거래처 키")
    pi_key = _derive(source, r'else "([A-Z_]+)"\)\n', "PI 거래처 키")
    brand = _derive(inspect_source(ref["product_matching"]), r"p\.get\('brand'\) == '(\w+)'", "브랜드 상수")
    catalog = {
        "products": [{"id": "p1", "brand": brand, "item_name": "Test Cream", "capacity": "50 ml"}],
        "purchase_prices": [{"product_id": "p1", "supplier_key": po_key,
                             "currency": "KRW", "unit_price": "1000", "source_row": 1}],
        "buyer_prices": [{"product_id": "p1", "buyer_key": pi_key,
                          "currency": "USD", "unit_price": "10.25", "source_row": 1}],
    }
    buyer = pi_key.replace("_", " ").title()
    seller = po_key.replace("_", " ").title() + " Co., Ltd."
    cases = [
        dict(document_type="PI", product_family="cosmetics", currency="USD",
             buyer={"legal_name": buyer},
             items=[{"product_name": "Test Cream", "capacity": "50 ml", "unit_price": None, "source": None}]),
        dict(document_type="PI", product_family="cosmetics", currency="USD",
             buyer={"legal_name": "Different Buyer Ltd"},
             items=[{"product_name": "Test Cream", "capacity": "50 ml", "unit_price": None, "source": None}]),
        dict(document_type="PO", product_family="cosmetics", currency="KRW",
             seller={"legal_name": seller},
             items=[{"product_name": "Test Cream", "capacity": "50 ml", "unit": "PCS",
                     "unit_price": None, "price_basis": "USD/PCS", "source": None}]),
    ]
    for base in cases:
        # 원본·이식본 모두 PO/PI 경로에서 반환값 대신 인자 draft를 직접 바꾼다(원본 동작).
        reference_draft = copy.deepcopy(base)
        ref["pricing"].apply_verified_eclado_prices(reference_draft, catalog)
        ported_draft = copy.deepcopy(base)
        port_pricing.apply_verified_catalog_prices(ported_draft, catalog)
        assert ported_draft["currency"] == reference_draft["currency"]
        assert ported_draft.get("product_family") == reference_draft.get("product_family")
        for ported_item, reference_item in zip(ported_draft["items"], reference_draft["items"]):
            for key in ("unit_price", "master_price", "product_id", "price_basis"):
                assert ported_item.get(key) == reference_item.get(key)
        # 문구만 바뀐 안내(회사 이름→catalog)는 접두어로 서로 대응하는지 확인한다.
        assert [e.startswith("Confirm a transaction-specific price for ")
                for e in ported_draft.get("missing_fields", [])] == \
               [e.startswith("Confirm a transaction-specific price for ")
                for e in reference_draft.get("missing_fields", [])]
