"""PL 포장 합계 회귀 pytest(원본 tests/test_packing_workflow.py 이식).

원본: reference/kekorea/Quotation_KEKOREA/tests/test_packing_workflow.py
- 원본의 실제 매입가는 이식 규칙(회사 고유 값 금지)에 따라 가상 값 8000을 쓴다
  (reference/kekorea/README.md '바꾼 것' 참고).
- 원본 `_xlsx_bytes`는 PL 합계를 직접 계산했지만 이식본은 문서 초안의 `packing_totals`를 읽는다
  (계약 15.4·15.5절). 이 테스트는 `finalize_draft`(app/services/trade_docs.py)가 만든
  `packing_totals`를 넣어 같은 시트 내용을 확인한다.
- 마지막 PO 매입가 시험은 계약 15.4절 일반화(가격 행 party_key 일치 판정, PO 통화 KRW 강제
  폐지)에 맞춰 공통 가격 행(party_key 빈 값)으로 바꿨다. 원본 의도(공급처 누락·불일치가 검증된
  매입가 적용을 막지 않는다)는 유지된다.
- 발행 회사 이름은 가상 값이다.
"""
from io import BytesIO
from zipfile import ZipFile

from app.trade.packing import reconcile_packing
from app.trade.pricing import apply_verified_catalog_prices, build_trade_catalog
from app.trade.renderers import _xlsx_bytes
from app.services.trade_docs import finalize_draft

ISSUER_NAME = "Testworks Trading Co. Ltd"
ISSUER_KEY = "testworkstrading"


def packing_example():
    values = [
        ("A", "351128", "PCS", "6", "3511.28", "3660.00", "9.306"),
        ("B", "280", "PCS", "0.5", "2.80", "305.00", "0.776"),
        ("C", "250552", "PCS", "5.5", "2505.52", "3355.00", "8.531"),
        ("D", "750", "PCS", "0.5", "7.50", "305.00", "0.776"),
        ("E", "13291", "PCS", "0.5", "1927.98", "3032.60", "0.644"),
        ("F", "2399.48", "KG", "12", "2399.48", "2759.48", "15.444"),
    ]
    return {"document_type": "PL", "product_family": "solar_cell", "currency": None,
            "seller": {"legal_name": ISSUER_NAME, "address": "Seoul"},
            "buyer": {"legal_name": "Buyer", "address": "Address"},
            "document_number": "DRAFT", "incoterms": "EXW Cyberjaya", "shipment_reference": "Reference",
            "actual_package_count": "25", "container_count": None,
            "declared_total_quantity": "618400", "declared_total_quantity_unit": "PCS",
            "declared_net_weight_kg": "10354.56", "declared_gross_weight_kg": "13417.08",
            "declared_volume_cbm": "35.475", "hs_code": "8541 42 000", "missing_fields": [], "conflicts": [],
            "items": [{"product_name": n, "quantity": q, "unit": unit, "package_type": "PALLET",
                       "package_count": count, "net_weight_kg": nw, "gross_weight_kg": gw, "volume_cbm": cbm}
                      for n, q, unit, count, nw, gw, cbm in values]}


def calculate(draft):
    # finalize_draft: 검증·계산 + PL 합계 비교 제안(packing_totals)까지 한 번에 확정한다(계약 15.5절).
    return finalize_draft({**draft, "issuer": {"legal_name_en": ISSUER_NAME}})


def test_mixed_units_and_supplier_total_mismatches_are_kept_separate():
    result = reconcile_packing(packing_example())
    assert result["quantities"] == {"PCS": "616001", "KG": "2399.48"}
    assert result["calculated"]["package_count"] == "25.0"
    assert result["calculated"]["net_weight_kg"] == "10354.56"
    assert result["calculated"]["gross_weight_kg"] == "13417.08"
    assert result["calculated"]["volume_cbm"] == "35.477"
    assert result["issues"] == []
    assert any("volume (CBM)" in issue for issue in result["discrepancies"])
    assert any("quantity total" in issue for issue in result["discrepancies"])


def test_pl_needs_no_currency_or_prices_and_excel_preserves_packing_columns():
    doc = packing_example()
    doc["declared_volume_cbm"] = "35.477"
    doc["declared_total_quantity"] = "616001"
    result = calculate(doc)
    assert not any("currency" in issue.lower() or "unit price" in issue.lower()
                   for issue in result["blocking_issues"])
    assert not any(issue.startswith("Packing:") for issue in result["blocking_issues"])
    with ZipFile(BytesIO(_xlsx_bytes(result))) as workbook:
        sheet = workbook.read("xl/worksheets/sheet1.xml").decode()
    for text in ("NW (KG)", "GW (KG)", "CBM", "2399.48", "35.477", "8541 42 000"):
        assert text in sheet


def test_missing_row_value_is_not_treated_as_zero():
    doc = packing_example()
    doc["items"][0]["net_weight_kg"] = None
    assert reconcile_packing(doc)["calculated"]["net_weight_kg"] is None


def test_discrepancies_use_row_totals_without_overwriting_source():
    doc = packing_example()
    doc["actual_package_count"] = "26"
    result = calculate(doc)
    assert result["declared_volume_cbm"] == "35.475"
    assert result["declared_total_quantity"] == "618400"
    assert not result["ready_for_issue"]
    assert any("Packing source discrepancy" in issue for issue in result["blocking_issues"])
    with ZipFile(BytesIO(_xlsx_bytes(result))) as workbook:
        sheet = workbook.read("xl/worksheets/sheet1.xml").decode()
    assert "35.477" in sheet
    assert ">25</t>" in sheet
    assert "616,001" in sheet
    assert "2,399.48" in sheet
    assert "35.475" not in sheet


def test_invalid_values_and_mixed_package_types_need_review():
    doc = packing_example()
    doc["items"][0]["gross_weight_kg"] = "1,2"
    doc["items"][1]["package_type"] = "BOX"
    issues = reconcile_packing(doc)["issues"]
    assert any("gross weight is invalid" in issue for issue in issues)
    assert any("different package types" in issue for issue in issues)


def test_missing_or_mismatched_po_seller_does_not_block_catalog_purchase_price():
    # 공통 매입 가격 행(party_key 빈 값): 공급처 이름이 누락되거나 달라도 검증된 매입가를 쓴다.
    catalog = build_trade_catalog([
        {"id": 1, "item_name": "Toner", "capacity": "150ml", "role": "purchase",
         "currency": "KRW", "unit_price_text": "8000", "party_key": ""},
    ])
    draft = {"document_type": "PO", "product_family": "cosmetics", "currency": None,
             "seller": {}, "items": [{"product_name": "Toner", "capacity": "150ml", "source": "Toner 150ml"}]}
    apply_verified_catalog_prices(draft, catalog)
    assert draft["currency"] == "KRW"  # 매입 행 통화가 하나뿐이라 추론된 값(계약 15.4절)
    assert draft["items"][0]["unit_price"] == "8000"
    assert not draft["pending_confirmations"]
    assert not draft["seller"].get("legal_name")
    draft["seller"] = {"legal_name": "Different Supplier"}
    apply_verified_catalog_prices(draft, catalog)
    assert draft["items"][0]["unit_price"] == "8000"
    assert draft["currency"] == "KRW"
    assert not draft["pending_confirmations"]
