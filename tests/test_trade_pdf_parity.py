"""kekorea-port 4절: 같은 문서 초안에 사본(reference)·이식본의 추출 텍스트가 같은지 비교.

원본 사본은 이 테스트가 sys.path로 임시로 읽기만 한다(이식 규칙 1: 앱 코드는 reference를
import하지 않는다). 회사 고유 값은 비교에서 제외한다 — 사본 PDF에는 원본의 고정 회사 문구가,
이식본 PDF에는 사용자별 설정(issuer 스냅샷)의 가상 회사 이름이 인쇄되므로, 차이가 회사 이름
토큰뿐인지를 확인하고 나머지 토큰이 같은지 본다.
PL 합계는 계약 15.5절대로 렌더러 입력(packing_totals)으로 주고, 사본은 원본 reconcile_packing을
스스로 호출하므로 두 결과가 같아야 한다.
"""

import re
import struct
import sys
import zipfile
import zlib
from collections import Counter
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from app.trade.common.pdf import render_trade_document
from app.trade.common.renderers import _pdf_bytes, _xlsx_bytes, document_lines

REFERENCE_ROOT = Path(__file__).resolve().parents[1] / "reference" / "kekorea"
if str(REFERENCE_ROOT) not in sys.path:
    sys.path.insert(0, str(REFERENCE_ROOT))

# 원본 사본(읽기 전용)
from Quotation_KEKOREA.agent.packing import reconcile_packing as ref_reconcile_packing
from Quotation_KEKOREA.agent.pi_pdf import render_trade_document as ref_render_trade_document
from Quotation_KEKOREA.agent.renderers import _xlsx_bytes as ref_xlsx_bytes
from Quotation_KEKOREA.agent.renderers import document_lines as ref_document_lines

ISSUER_NAME = "Acme Trading Co Ltd"  # 가상 발행 회사(원본 고정 회사명 대신 사용자별 설정값)
BANK = {key: f"TEST_{key}" for key in
        ("BENEFICIARY", "BANK_NAME", "BRANCH", "SWIFT", "ACCOUNT_NUMBER", "BANK_ADDRESS")}


def seal_png(width=1, height=1):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    pixels = (b"\0" + b"\xff" * (width * 3)) * height
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def issuer_snapshot():
    # 서명자는 원본 사본의 표시 문구 그대로 둬야 토큰 비교가 회사 이름에만 영향을 받는다.
    return {"company_name": ISSUER_NAME, "legal_name_en": ISSUER_NAME, "ceo_name": "[AUTHORIZED SIGNER]"}


def pi_doc():
    return {
        "document_type": "PI", "product_family": "cosmetics", "currency": "USD",
        "document_number": "PI-TEST-001", "incoterms": "FOB Busan", "payment_terms": "T/T 30 days",
        "ship_to": "Sample Warehouse 1, Seoul", "remarks": "Handle with care.", "total": "200",
        "seller": {"legal_name": ISSUER_NAME, "address": "10 Sample-gil, Seoul",
                   "contact": "Test Manager", "phone": "82-10-0000-0000", "email": "seller@example.invalid"},
        "buyer": {"legal_name": "Example Buyer Ltd", "address": "1 Sample Road, Seoul",
                  "contact": "Buyer Manager", "phone": "82-10-1111-1111", "email": "buyer@example.invalid"},
        "issuer": issuer_snapshot(),
        "items": [{"product_name": f"Product-{i:02}", "capacity": "100 ml", "quantity": "10",
                   "unit": "PCS", "unit_price": "1", "final_unit_price": "1", "line_total": "10",
                   "paid_quantity": "10", "free_quantity": "0", "shipped_quantity": "10"}
                  for i in range(20)],
    }


def pl_doc(*, item_weights=True):
    items = [{"product_name": "Packing Item A", "capacity": "100 ml", "quantity": "10",
              "display_quantity": "10", "unit": "PCS", "paid_quantity": "10", "free_quantity": "0",
              "shipped_quantity": "10"},
             {"product_name": "Packing Item B", "capacity": "200 ml", "quantity": "20",
              "display_quantity": "20", "unit": "PCS", "paid_quantity": "20", "free_quantity": "0",
              "shipped_quantity": "20"}]
    if item_weights:
        items[0].update({"package_type": "BOX", "package_count": "2", "net_weight_kg": "1.5",
                         "gross_weight_kg": "2.0", "volume_cbm": "0.01"})
        items[1].update({"package_type": "BOX", "package_count": "3", "net_weight_kg": "2.5",
                         "gross_weight_kg": "3.0", "volume_cbm": "0.02"})
        packages = []
    else:
        # 계산 합계·선언값이 모두 없고 packages 배열만 있을 때(원본 pi_pdf 폴백 경로)
        packages = [{"package_type": "BOX", "package_count": "5", "net_weight_kg": "4.0",
                     "gross_weight_kg": "5.0"}]
    return {
        "document_type": "PL", "product_family": "cosmetics", "currency": None,
        "document_number": "PL-TEST-001", "incoterms": "FOB Busan", "remarks": "Packed per instruction.",
        "shipment_reference": "SHIP-REF-1", "container_count": "1", "hs_code": "3304.99",
        "actual_package_count": "5",
        "seller": {"legal_name": ISSUER_NAME, "address": "10 Sample-gil, Seoul"},
        "buyer": {"legal_name": "Example Buyer Ltd", "address": "1 Sample Road, Seoul"},
        "issuer": issuer_snapshot(),
        "items": items, "packages": packages,
        "packing_totals": None,  # 아래 pl_packing_totals로 채운다
    }


def pl_packing_totals(doc):
    """D 묶음이 만들 PackingTotals 형식(계약 15.5절)을 원본 결과로 만들어 렌더러 입력으로 쓴다."""
    packing = ref_reconcile_packing(doc)
    return {
        "quantities": dict(packing["quantities"]),
        "quantity_complete": packing["quantity_complete"],
        "calculated": dict(packing["calculated"]),
        # 원본 pi_pdf 폴백 식 그대로(packages 배열 net/gross 합계)
        "packages_total": {
            "net_weight_kg": str(sum(Decimal(str(p.get("net_weight_kg") or 0)) for p in doc.get("packages", []))),
            "gross_weight_kg": str(sum(Decimal(str(p.get("gross_weight_kg") or 0)) for p in doc.get("packages", []))),
        },
        "issues": packing["issues"], "discrepancies": packing["discrepancies"],
        "changes": [], "approved": False,
    }


def _paren_strings(text):
    values, i = [], 0
    while True:
        start = text.find("(", i)
        if start < 0:
            return values
        j, chunks = start + 1, []
        while j < len(text):
            ch = text[j]
            if ch == "\\":
                nxt = text[j + 1] if j + 1 < len(text) else ""
                chunks.append({"n": "\n", "r": "\r", "t": "\t"}.get(nxt, nxt))
                j += 2
                continue
            if ch == ")":
                break
            chunks.append(ch)
            j += 1
        values.append("".join(chunks))
        i = j + 1


def text_tokens(pdf):
    """PDF 콘텐츠 스트림에서 텍스트 명령((…) Tj·<16진> Tj)의 문자열을 뽑는다."""
    tokens = []
    for stream in re.findall(rb"stream\n(.*?)endstream", pdf, re.S):
        if b"Tj" not in stream:
            continue  # 이미지 등 텍스트가 없는 스트림
        text = stream.decode("latin-1")
        tokens.extend(_paren_strings(text))
        tokens.extend(bytes.fromhex(match).decode("utf-16-be", "replace")
                      for match in re.findall(r"<([0-9A-Fa-f]+)>\s*Tj", text))
    return tokens


def xlsx_texts(xlsx):
    with zipfile.ZipFile(BytesIO(xlsx)) as workbook:
        sheet = workbook.read("xl/worksheets/sheet1.xml").decode()
    return re.findall(r"<t[^>]*>(.*?)</t>", sheet, re.S)


def assert_equal_excluding_company_values(reference, ported):
    """두 텍스트 모음이 회사 이름(사본=원본 고정 문구, 이식본=설정값) 토큰만 다른지 확인한다."""
    ref, port = Counter(reference), Counter(ported)
    only_ref, only_port = ref - port, port - ref
    assert all(ISSUER_NAME in token for token in only_port), sorted(only_port)
    assert sum(only_ref.values()) == sum(only_port.values())
    assert ref - only_ref == port - only_port


def page_count(pdf):
    return len(re.findall(rb"DRAFT - NOT FOR ISSUE", pdf))


def test_pi_document_lines_match_reference():
    doc = pi_doc()
    assert_equal_excluding_company_values(ref_document_lines(doc, BANK), document_lines(doc, BANK))


def test_pi_review_pdf_and_xlsx_match_reference(tmp_path):
    doc = pi_doc()
    seal = seal_png()
    seal_file = tmp_path / "seal.png"
    seal_file.write_bytes(seal)
    ref_pdf = _pdf_bytes_of_reference(doc)
    port_pdf = _pdf_bytes(document_lines(doc, BANK))
    assert_equal_excluding_company_values(text_tokens(ref_pdf), text_tokens(port_pdf))
    assert_equal_excluding_company_values(
        xlsx_texts(ref_xlsx_bytes(doc, BANK, seal_path=seal_file)),
        xlsx_texts(_xlsx_bytes(doc, BANK, seal=seal)))


def _pdf_bytes_of_reference(doc):
    from Quotation_KEKOREA.agent.renderers import _pdf_bytes as ref__pdf_bytes
    return ref__pdf_bytes(ref_document_lines(doc, BANK))


def test_pi_pdf_text_matches_reference(tmp_path):
    doc = pi_doc()
    seal = seal_png()
    seal_file = tmp_path / "seal.png"
    seal_file.write_bytes(seal)
    ref_pdf = ref_render_trade_document(doc, BANK, seal_path=seal_file)
    port_pdf = render_trade_document(doc, BANK, seal=seal)
    assert page_count(ref_pdf) == page_count(port_pdf)
    assert_equal_excluding_company_values(text_tokens(ref_pdf), text_tokens(port_pdf))


def test_pl_pdf_text_matches_reference(tmp_path):
    doc = pl_doc()
    doc["packing_totals"] = pl_packing_totals(doc)
    seal = seal_png()
    seal_file = tmp_path / "seal.png"
    seal_file.write_bytes(seal)
    ref_pdf = ref_render_trade_document(doc, None, seal_path=seal_file)
    port_pdf = render_trade_document(doc, None, seal=seal)
    assert page_count(ref_pdf) == page_count(port_pdf)
    assert_equal_excluding_company_values(text_tokens(ref_pdf), text_tokens(port_pdf))
    assert_equal_excluding_company_values(
        xlsx_texts(ref_xlsx_bytes(doc, None, seal_path=seal_file)),
        xlsx_texts(_xlsx_bytes(doc, None, seal=seal)))


def test_pl_packages_total_fallback_matches_reference(tmp_path):
    # 계산 합계·선언값이 모두 없을 때: 사본은 packages 배열을 더하고, 이식본은
    # packing_totals.packages_total(원본 폴백 식 그대로)을 읽는다. 두 출력은 같아야 한다.
    doc = pl_doc(item_weights=False)
    doc["packing_totals"] = pl_packing_totals(doc)
    seal = seal_png()
    seal_file = tmp_path / "seal.png"
    seal_file.write_bytes(seal)
    ref_pdf = ref_render_trade_document(doc, None, seal_path=seal_file)
    port_pdf = render_trade_document(doc, None, seal=seal)
    tokens = text_tokens(port_pdf)
    assert any("NET WEIGHT: 4" in token for token in tokens)  # packages 합계(4.0)가 쓰였다
    assert page_count(ref_pdf) == page_count(port_pdf)
    assert_equal_excluding_company_values(text_tokens(ref_pdf), tokens)
