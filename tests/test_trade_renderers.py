"""kekorea-port 4절: 원본 test_trade_documents.py의 출력 부분 이식 — 금액 영문 표기·검토 파일·영문 규칙.

원본: reference/kekorea/Quotation_KEKOREA/tests/test_trade_documents.py
바꾼 점: 계산(validate_and_calculate)은 3절(B 묶음) 이식 전이라 문서 초안을 직접 만들고,
로고·직인을 파일 경로 대신 PNG bytes로 쓴다. 회사 이름은 가상 값(issuer 스냅샷)으로 바꿨다.
"""

import struct
import zipfile
import zlib
from io import BytesIO

import pytest

from app.trade.renderers import (
    _pdf_bytes, _xlsx_bytes, amount_in_english, document_lines, format_currency_amount, render_files,
)

ISSUER = {"company_name": "Acme Trading Co Ltd", "legal_name_en": "Acme Trading Co Ltd",
          "ceo_name": "Test Signer"}


def sample_trade(**updates):
    """원본 sample_trade와 같은 형태(회사 고유 값은 가상 값). 계산 결과 키는 미리 넣는다."""
    data = {
        "document_type": "PI", "product_family": "cosmetics", "currency": "USD",
        "buyer": {"legal_name": "Example Buyer Ltd", "address": "1 Sample Road, Seoul",
                  "contact": None, "phone": None, "email": None},
        "seller": {"legal_name": "Acme Trading Co Ltd", "address": None, "contact": None,
                   "phone": None, "email": None},
        "issuer": dict(ISSUER),
        "items": [{"product_name": "Example Toner", "capacity": "100 ml", "quantity": "10",
                   "unit": "PCS", "unit_price": "12.50", "final_unit_price": "11.25",
                   "line_total": "112.50", "price_basis": "per PCS", "discount_percent": "10",
                   "paid_quantity": "10", "free_quantity": "0", "shipped_quantity": "10",
                   "source": "synthetic test"}],
        "incoterms": None, "payment_terms": None, "remarks": None, "document_number": None,
        "issue_date": "2026-10-30", "ship_to": None, "bill_to": None, "total": "112.50",
        "missing_fields": [], "conflicts": [], "source_notes": ["synthetic test"],
    }
    data.update(updates)
    return data


def seal_png(width=2, height=2):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    pixels = (b"\0" + b"\x80" * (width * 3)) * height
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def test_amount_words():
    assert amount_in_english("112.50", "USD") == "ONE HUNDRED TWELVE US DOLLARS AND FIFTY CENTS ONLY"


def test_format_currency_amount_rounds_by_currency():
    assert format_currency_amount("112.505", "USD") == "$112.51"
    assert format_currency_amount("112.5", "KRW") == "KRW 113"
    assert format_currency_amount("112.50", "EUR") == "EUR 112.50"


def test_document_lines_use_issuer_settings_for_name_and_signer():
    # 협의 1 임시값: 발행 회사 이름·서명자는 사용자별 설정(issuer 스냅샷)에서 읽는다.
    lines = document_lines(sample_trade())
    assert "Acme Trading Co Ltd - REVIEW DRAFT" in lines
    assert "Test Signer" in lines
    assert "Acme Trading Co Ltd" in lines


def test_pi_bank_information_is_one_bundle_with_placeholder_for_missing_values():
    bank = {key: f"TEST_{key}" for key in
            ("BENEFICIARY", "BANK_NAME", "BRANCH", "SWIFT", "ACCOUNT_NUMBER", "BANK_ADDRESS")}
    lines = document_lines(sample_trade(), bank)
    head = lines.index("BANK INFORMATION")
    tail = [line for line in lines[head:] if line.startswith(("Beneficiary", "Bank Name", "Branch Name",
                                                              "SWIFT Code", "Account Number", "Bank Address"))]
    assert len(tail) == 6
    assert "Account Number: TEST_ACCOUNT_NUMBER (USD)" in tail
    empty = document_lines(sample_trade(), None)
    assert "Account Number: [BANK DETAIL REQUIRED]" in empty


def test_chinese_company_name_is_preserved_in_review_files():
    data = sample_trade()
    data["buyer"]["legal_name"] = "华星贸易有限公司 (Huaxing Trading Co., Ltd.)"
    data["buyer"]["address"] = "上海市浦东新区 (Pudong New Area, Shanghai)"
    pdf = _pdf_bytes(document_lines(data))
    assert "华星贸易有限公司".encode("utf-16-be").hex().upper().encode() in pdf
    with zipfile.ZipFile(BytesIO(_xlsx_bytes(data))) as workbook:
        assert "华星贸易有限公司".encode("utf-8") in workbook.read("xl/worksheets/sheet1.xml")


def test_generated_review_files_are_readable_containers(tmp_path):
    data = sample_trade()
    seal = seal_png()
    paths = render_files(data, tmp_path, seal=seal)
    try:
        assert paths["pdf"].read_bytes().startswith(b"%PDF-1.4")
        with zipfile.ZipFile(paths["xlsx"]) as workbook:
            assert "xl/worksheets/sheet1.xml" in workbook.namelist()
            sheet = workbook.read("xl/worksheets/sheet1.xml").decode()
            assert "112.50" in sheet
            assert workbook.read("xl/media/seal.png") == seal
        assert "AMOUNT IN WORDS" in paths["html"].read_text(encoding="utf-8")
    finally:
        for path in paths.values():
            path.unlink(missing_ok=True)


def test_renderer_rejects_non_english_document_text_instead_of_corrupting_it():
    data = sample_trade()
    data["buyer"]["legal_name"] = "구매자"
    with pytest.raises(ValueError, match="English or Latin-1"):
        document_lines(data)


def test_pl_totals_come_from_packing_totals_input():
    # 계약 15.5절: PL 합계는 렌더러 입력(packing_totals)으로 받는다(D의 함수를 기다리지 않는다).
    data = sample_trade(document_type="PL", currency=None)
    data["items"] = [{"product_name": "Packing Item", "capacity": "100 ml", "quantity": "10",
                      "display_quantity": "10", "unit": "PCS", "hs_code": "3304.99"}]
    data["packing_totals"] = {
        "quantities": {"PCS": "10"}, "quantity_complete": True,
        "calculated": {"package_count": "2", "net_weight_kg": "1.5", "gross_weight_kg": "2.0",
                       "volume_cbm": "0.01"},
        "packages_total": {"net_weight_kg": "1.5", "gross_weight_kg": "2.0"},
        "issues": [], "discrepancies": [], "changes": [], "approved": False,
    }
    lines = document_lines(data)
    assert "Total quantity (PCS): 10" in lines
    assert "Total packages: 2" in lines
    assert "Total net weight (kg): 1.5" in lines
    with zipfile.ZipFile(BytesIO(_xlsx_bytes(data))) as workbook:
        sheet = workbook.read("xl/worksheets/sheet1.xml").decode()
        assert "Total net weight (kg)" in sheet and "1.5" in sheet
