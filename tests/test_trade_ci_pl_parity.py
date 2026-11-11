"""kekorea-port 5절(D 묶음) 동일성 비교: 같은 입력을 원본 사본(reference) 함수와 이식본 함수에
넣어 결과가 같은지 확인한다.

- 원본 사본은 읽기 전용이고 sys.path 조작으로 테스트 도중에만 import한다(이식 규칙 1의 허용 범위).
  3절(B)의 tests/test_trade_parity.py가 packing(코어)·prepare_ci_import·ci_import_issues·
  ci_render_data를 이미 비교하므로, 여기서는 D가 이식한 나머지(packing_review 전체,
  apply_document_prices의 CI/PL 갈래, is_ci_conversion_request)와 PL 합계 제안 흐름을 비교한다.
- 회사 고유 값은 테스트 코드에 둘 수 없으므로(이식 규칙 4), 사본 상품 매칭이 기대하는 브랜드
  상수는 사본 소스에서 추출해 입력으로만 쓴다. 추출에 실패하면 그 비교는 건너뛴다.
"""
import copy
import importlib
import re
import sys
from pathlib import Path

import pytest

from app.services.trade_docs import finalize_draft
from app.trade import ci_import as port_ci_import
from app.trade import packing_review as port_review
from app.trade.trade_documents import validate_and_calculate
from tests.test_trade_packing import packing_example

REFERENCE_ROOT = Path(__file__).resolve().parents[1] / "reference" / "kekorea"
HAS_REFERENCE = (REFERENCE_ROOT / "Quotation_KEKOREA" / "agent" / "packing_review.py").exists()

pytestmark = pytest.mark.skipif(not HAS_REFERENCE, reason="원본 사본(reference/kekorea)이 없습니다")


@pytest.fixture(scope="module")
def ref():
    """원본 사본 모듈(테스트 도중에만 참고 경로를 sys.path에 둔다)."""
    sys.path.insert(0, str(REFERENCE_ROOT))
    try:
        names = ("packing", "packing_review", "ci_import", "trade_documents",
                 "product_matching", "pricing")
        return {name: importlib.import_module("Quotation_KEKOREA.agent." + name) for name in names}
    finally:
        sys.path.remove(str(REFERENCE_ROOT))


def _derive(source, pattern, what):
    match = re.search(pattern, source)
    if not match:
        pytest.skip(f"사본 소스에서 {what}를 찾지 못해 이 비교는 건너뛴다")
    return match.group(1)


def review_inputs():
    """PL 합계 검토 입력 변형(주석 파싱·단위 충돌·잘못된 행·컨테이너 규격)."""
    base = packing_example()
    annotated = packing_example()
    annotated.update(container_count='5 x 40FT Containers', declared_total_quantity='618400 pcs',
                     declared_net_weight_kg='10,354.56 kg', declared_volume_cbm='35.475 cbm')
    conflicting = packing_example()
    conflicting.update(declared_total_quantity='618400 kg', declared_total_quantity_unit='PCS')
    invalid = packing_example()
    invalid['items'][0]['gross_weight_kg'] = '1,2'
    mixed_types = packing_example()
    mixed_types['items'][1]['package_type'] = 'BOX'
    missing_row = packing_example()
    missing_row['items'][0]['net_weight_kg'] = None
    return [base, annotated, conflicting, invalid, mixed_types, missing_row]


def test_packing_review_functions_match(ref):
    for data in review_inputs():
        reference = copy.deepcopy(data)
        ported = copy.deepcopy(data)
        assert port_review.normalize_packing_inputs(ported) == \
               ref["packing_review"].normalize_packing_inputs(reference)
        assert ported == reference  # 원본 입력은 바뀌지 않는다
        normalized = copy.deepcopy(data)
        reference_normalized = ref["packing_review"].normalize_packing_inputs(copy.deepcopy(normalized))
        ported_normalized = port_review.normalize_packing_inputs(copy.deepcopy(normalized))
        assert port_review.reconcile_packing(ported_normalized) == \
               ref["packing_review"].reconcile_packing(reference_normalized)
        assert port_review.packing_total_changes(copy.deepcopy(ported_normalized)) == \
               ref["packing_review"].packing_total_changes(copy.deepcopy(reference_normalized))
    # 승인 적용: 성공 경우는 결과가 같고, 실패 경우는 양쪽 모두 ValueError를 낸다.
    clean = packing_example()
    clean.update(declared_volume_cbm='35.477', declared_total_quantity='616001')
    assert port_review.apply_approved_packing_totals(copy.deepcopy(clean)) == \
           ref["packing_review"].apply_approved_packing_totals(copy.deepcopy(clean))
    assert port_review.apply_approved_packing_totals(copy.deepcopy(packing_example())) == \
           ref["packing_review"].apply_approved_packing_totals(copy.deepcopy(packing_example()))
    for broken in review_inputs()[2:5]:
        for module in (port_review, ref["packing_review"]):
            with pytest.raises(ValueError):
                module.apply_approved_packing_totals(copy.deepcopy(broken))


def _catalog(ref, with_products):
    """CI/PL 상품 매칭용 카탈로그. 사본은 브랜드 상수를 요구하므로 소스에서 추출해 넣는다."""
    if not with_products:
        return {"products": [], "purchase_prices": [], "buyer_prices": []}
    brand = _derive(_source(ref["product_matching"]), r"p\.get\('brand'\) == '(\w+)'", "브랜드 상수")
    products = [dict(id='p1', brand=brand, item_name='Test Toner', capacity='150ml')]
    return {"products": products,
            "purchase_prices": [dict(product_id='p1', supplier_key='ACME_SUPPLIER',
                                     currency='KRW', unit_price='8000')],
            "buyer_prices": [dict(product_id='p1', buyer_key='ACME_BUYER',
                                  currency='USD', unit_price='99')]}


def _source(module):
    import inspect
    return inspect.getsource(module)


def _generalized(value, brand):
    """계약 15.4절이 일반화한 안내 문구(회사 브랜드 이름 → catalog)만 바꿔 비교한다."""
    if isinstance(value, str):
        value = value.replace(f"Exact {brand} product match", "Exact catalog product match")
        value = value.replace(f"unique {brand} catalog match", "unique catalog match")
        return value
    if isinstance(value, list):
        return [_generalized(item, brand) for item in value]
    if isinstance(value, dict):
        return {key: _generalized(item, brand) for key, item in value.items()}
    return value


def test_apply_document_prices_ci_pl_matches(ref):
    brand = _derive(_source(ref["product_matching"]), r"p\.get\('brand'\) == '(\w+)'", "브랜드 상수")
    for with_products in (False, True):
        catalog = _catalog(ref, with_products)
        drafts = []
        imported = packing_example()
        imported.update(document_type='CI', currency='USD', source_document_type='PI',
                        source_total='18.00', payment_terms='TT TEST PAYMENT',
                        bank_details={'account': 'TEST'}, remarks='Bank: TEST BANK',
                        product_family='other', document_number='CI-1', incoterms='FOB Busan',
                        shipment_reference='SHP-1', country_of_origin='KR',
                        items=[dict(product_name='Test Toner', capacity='150ml', quantity='10',
                                    paid_quantity='10', free_quantity='0', shipped_quantity='10',
                                    unit='PCS', unit_price='2', price_basis='PCS',
                                    price_source='User supplied', discount_percent='10',
                                    source='Test Toner 10 PCS USD 2.00 10%',
                                    source_line_total='18.00')])
        imported.update(_ci_from_pi=True)
        drafts.append(imported)
        blocked = copy.deepcopy(imported)
        blocked.pop('_ci_from_pi')
        blocked['items'][0]['unit_price'] = None  # PI 근거 없는 CI: 카탈로그 가격 대체 금지
        drafts.append(blocked)
        packing_list = packing_example()
        packing_list['items'][0].update(product_name='Test Toner', capacity='150ml')
        packing_list['items'][0]['unit_price'] = '42'
        drafts.append(packing_list)
        for base in drafts:
            reference_draft = ref["ci_import"].prepare_ci_import(
                copy.deepcopy(base), requested_type=base.get("document_type"), has_attachments=True)
            ported_draft = port_ci_import.prepare_ci_import(
                copy.deepcopy(base), requested_type=base.get("document_type"), has_attachments=True)
            ref["ci_import"].apply_document_prices(reference_draft, copy.deepcopy(catalog))
            port_ci_import.apply_document_prices(ported_draft, copy.deepcopy(catalog))
            # 안내 문구의 회사 브랜드 이름만 계약 15.4절이 'catalog'로 바꿨다.
            assert ported_draft == _generalized(reference_draft, brand)


def test_is_ci_conversion_request_matches(ref):
    phrases = ['Convert PI to CI', '첨부 PI를 CI로 작성해줘', 'PI를 상업송장으로 변환해 주세요',
               'Create CI from the attached PI', 'Make a commercial invoice from this proforma invoice',
               'use the proforma invoice as a commercial invoice',
               'Create a PI for Acme Buyer', 'PI 첨부했습니다', 'commercial invoice question']
    for phrase in phrases:
        assert port_ci_import.is_ci_conversion_request(phrase) == \
               ref["ci_import"].is_ci_conversion_request(phrase)


def test_pl_finalize_packing_totals_match_reference_review_flow(ref):
    """이식본 저장 흐름(finalize_draft)의 합계 제안이 원본 검토 흐름(정규화→비교→제안)과 같다."""
    issuer_token = _derive(_source(ref["trade_documents"]), r'if "([A-Z ]+)" not in buyer', "발행사 토큰")
    for data in review_inputs()[:3]:
        doc = copy.deepcopy(data)
        doc["issuer"] = {"legal_name_en": "Testworks Trading Co. Ltd"}
        reference_validated = ref["trade_documents"].validate_and_calculate(copy.deepcopy(doc))
        finalized = finalize_draft(copy.deepcopy(doc))
        # PL 합계 비교·제안은 원본 검토 함수 순서와 같은 값을 낸다.
        reference_normalized = ref["packing_review"].normalize_packing_inputs(
            copy.deepcopy(reference_validated))
        reference_check = ref["packing_review"].reconcile_packing(copy.deepcopy(reference_normalized))
        totals = finalized["packing_totals"]
        assert totals["quantities"] == reference_check["quantities"]
        assert totals["quantity_complete"] == reference_check["quantity_complete"]
        assert totals["calculated"] == reference_check["calculated"]
        assert totals["issues"] == reference_check["issues"]
        assert totals["discrepancies"] == reference_check["discrepancies"]
        assert totals["changes"] == ref["packing_review"].packing_total_changes(
            copy.deepcopy(reference_normalized))
        assert totals["packages_total"] == {"net_weight_kg": None, "gross_weight_kg": None}
        assert totals["approved"] is False
        # 코어 검증 결과(합계·행 계산)는 같다(발행사 문구·status 표기 제외는 3절 B 동일성 기준).
        # 이식본은 계약 15.5절대로 래퍼의 검토 입력 정규화 문제(_packing_input_issues)도
        # 차단 목록에 더하므로, 그 문구만 빼고 비교한다.
        input_issues = reference_normalized.get("_packing_input_issues", [])
        port_blocking = [issue for issue in finalized["blocking_issues"]
                         if not any(issue == text or issue == "Packing: " + text
                                    for text in input_issues)]
        reference_blocking = [issue for issue in reference_validated["blocking_issues"]
                              if issuer_token not in issue]
        assert port_blocking == reference_blocking
        for text in input_issues:  # 더해진 검토 입력 문제는 실제로 차단 목록에 있다
            assert "Packing: " + text in finalized["blocking_issues"]
