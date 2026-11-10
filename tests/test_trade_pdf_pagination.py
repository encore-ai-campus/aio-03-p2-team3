"""kekorea-port 4절: 원본 test_pdf_pagination.py 이식 — 상품 행 분할과 하단 묶음(계좌·직인) 규칙.

원본: reference/kekorea/Quotation_KEKOREA/tests/test_pdf_pagination.py
바꾼 점: render_trade_document이 직인을 파일 경로 대신 PNG bytes로 받는다(계약 15.4절).
"""

import re
import struct
import zlib

import pytest

from app.trade.pi_pdf import _paginate_rows, render_trade_document

BANK_KEYS = ("BENEFICIARY", "BANK_NAME", "BRANCH", "SWIFT", "ACCOUNT_NUMBER", "BANK_ADDRESS")


def seal_png(width=1, height=1):
    """테스트 전용 1×1 RGB PNG(회사 자산이 아님)."""

    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    pixels = (b"\0" + b"\xff" * (width * 3)) * height
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def test_all_products_stay_on_first_page_when_only_closing_panels_overflow():
    rows = [{"height": 13.5, "name": str(i)} for i in range(20)]
    assert _paginate_rows(rows, 310, 40, False) == [rows, []]


def test_rows_move_only_when_the_next_row_exceeds_available_space():
    rows = [{"height": 13.5, "name": str(i)} for i in range(100)]
    pages = _paginate_rows(rows, 310, 40, False)
    assert [len(page) for page in pages] == [31, 42, 27]
    assert [row for page in pages for row in page] == rows


def test_exact_fit_and_tall_wrapped_rows_preserve_order():
    rows = [{"height": 425}, {"height": 400}]
    assert _paginate_rows(rows, 310, 40, False) == [[rows[0]], [rows[1]], []]


def test_packing_list_also_keeps_all_fitting_products_on_first_page():
    rows = [{"height": 13.5} for _ in range(20)]
    assert _paginate_rows(rows, 310, 40, True) == [rows, []]


def test_small_document_keeps_products_and_closing_panels_on_one_page():
    rows = [{"height": 13.5}]
    assert _paginate_rows(rows, 310, 40, False) == [rows]


def test_pdf_does_not_move_last_product_or_split_bank_and_seal_panels():
    doc = {"document_type": "PI", "currency": "USD", "remarks": "N/A", "total": "200",
           "seller": {"legal_name": "Test Seller"}, "buyer": {"legal_name": "Test Buyer"},
           "items": [{"product_name": f"Product-{i:02}", "quantity": "10", "unit": "PCS",
                      "unit_price": "1", "line_total": "10"} for i in range(20)]}
    bank = {key: f"TEST_{key}" for key in BANK_KEYS}
    pdf = render_trade_document(doc, bank, seal=seal_png())
    streams = re.findall(rb"stream\n(.*?)endstream", pdf, re.S)
    pages = [stream for stream in streams if b"DRAFT - NOT FOR ISSUE" in stream]
    assert len(pages) == 2
    assert b"Product-19" in pages[0]
    assert b"Product-19" not in pages[1]
    assert b"PRODUCT & PRICING" not in pages[1]
    for label in (b"BENEFICIARY", b"BANK NAME", b"BRANCH NAME", b"SWIFT CODE",
                  b"ACCOUNT NUMBER", b"BANK ADDRESS", b"AUTHORIZED REPRESENTATIVE"):
        assert label not in pages[0]
        assert label in pages[1]
    for value in bank.values():
        assert value.encode() in pages[1]
    assert b"/Im1 Do" in pages[1]


def test_missing_seal_blocks_pdf_creation():
    # PRESERVED_BEHAVIOR: 직인이 없으면 PDF 생성을 차단한다(원본 동작 유지[임시: 협의 3]).
    doc = {"document_type": "PI", "currency": "USD", "remarks": "N/A", "total": "200",
           "seller": {"legal_name": "Test Seller"}, "buyer": {"legal_name": "Test Buyer"},
           "items": [{"product_name": "Product-00", "quantity": "10", "unit": "PCS",
                      "unit_price": "1", "line_total": "10"}]}
    with pytest.raises(ValueError):
        render_trade_document(doc, {key: f"TEST_{key}" for key in BANK_KEYS}, seal=None)
