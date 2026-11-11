"""검토용 PDF·XLSX·HTML 렌더러(외부 라이브러리 없이 직접 생성).

원본: reference/kekorea/Quotation_KEKOREA/agent/renderers.py
서비스 경로(발송 첨부·미리보기)가 쓰는 PDF는 app.trade.common.pdf.render_trade_document이고,
이 모듈의 _xlsx_bytes는 문서 API의 Excel 발급도 담당한다. HTML·검토 PDF 보조는
테스트·사본 비교 검증에서 사용한다(docs/CONTRACT.md 15.4절).
원본과 다른 점:
- 발행 회사 이름·서명자를 원본 고정 문구 대신 문서 초안의 issuer 스냅샷(legal_name_en →
  company_name, 서명자 ceo_name)에서 읽는다[임시: 협의 1].
- document_lines·_xlsx_bytes의 PL 합계를 reconcile_packing 직접 호출 대신
  doc["packing_totals"]에서 읽는다(docs/CONTRACT.md 15.5절).
- render_files의 로고·직인 입력을 파일 경로에서 PNG bytes로 바꾼다.
"""
from datetime import date, datetime
from html import escape
from io import BytesIO
from pathlib import Path
import re
import zipfile
from xml.sax.saxutils import escape as xml_escape
from decimal import Decimal, ROUND_HALF_UP

from app.trade.common.pdf import issuer_display_name, issuer_signer
from app.trade.common.trade_documents import current_issue_date


# 원본: reference/kekorea/Quotation_KEKOREA/agent/renderers.py _english
def _english(value):
    if value is None:
        return ""
    value = str(value)
    value = value.translate(str.maketrans({"\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'}))
    if any(ord(ch) > 255 and not ("\u3400" <= ch <= "\u9fff") for ch in value):
        raise ValueError("Document values must be English or Latin-1; translate non-Chinese text before rendering")
    return value


# 원본: reference/kekorea/Quotation_KEKOREA/agent/renderers.py _format_quantity
def _format_quantity(value):
    try:
        amount = Decimal(str(value))
        rendered = format(amount, ",f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    except Exception:
        return str(value or "")


# 원본: reference/kekorea/Quotation_KEKOREA/agent/renderers.py format_currency_amount
def format_currency_amount(value, currency):
    """Format transaction money with KRW whole units and two decimal places otherwise."""
    currency = str(currency or "").upper()
    quantum = Decimal("1") if currency == "KRW" else Decimal("0.01")
    try:
        amount = Decimal(str(value or "0")).quantize(quantum, rounding=ROUND_HALF_UP)
    except Exception:
        return str(value or "")
    rendered = f"{amount:,.0f}" if currency == "KRW" else f"{amount:,.2f}"
    return f"${rendered}" if currency == "USD" else f"{currency} {rendered}".strip()


# 원본: reference/kekorea/Quotation_KEKOREA/agent/renderers.py _rows
def _rows(doc):
    if doc.get("document_type") == "PL":
        rows = [["Line", "Product", "Capacity / Specification", "Qty", "Unit", "Package Type", "Packages", "NW (KG)", "GW (KG)", "CBM", "HS Code"]]
        for i, item in enumerate(doc.get("items", []), 1):
            rows.append([str(i), _english(item.get("product_name")), _english(item.get("capacity")),
                         _format_quantity(item.get("display_quantity", item.get("quantity", ""))), _english(item.get("unit")),
                         _english(item.get("package_type")), _english(item.get("package_count")),
                         _english(item.get("net_weight_kg")), _english(item.get("gross_weight_kg")), _english(item.get("volume_cbm")), _english(item.get("hs_code"))])
        return rows
    rows = [["Line", "Product", "Capacity / Specification", "Qty", "Unit", "Unit Price", "Discount", "Amount"]]
    for i, item in enumerate(doc.get("items", []), 1):
        if doc.get("document_type") == "PL":
            price = "N/A"
            amount = "N/A"
        else:
            price = item.get("final_unit_price", "")
            amount = item.get("line_total", "")
            if doc.get("product_family") == "cosmetics":
                price = format_currency_amount(price, doc.get("currency"))
                amount = format_currency_amount(amount, doc.get("currency"))
        if float(item.get("free_quantity") or 0):
            rows.append([str(i), _english(item.get("product_name")) + " (PAID)", _english(item.get("capacity")),
                         _format_quantity(item.get("paid_quantity", "")), _english(item.get("unit")), price,
                         item.get("discount_percent", "0") + "%", amount])
            rows.append([str(i), _english(item.get("product_name")) + " (FREE OF CHARGE)", _english(item.get("capacity")),
                         _format_quantity(item.get("free_quantity", "")), _english(item.get("unit")),
                         format_currency_amount("0", doc.get("currency")) if doc.get("product_family") == "cosmetics" else "0",
                         "FOC", format_currency_amount("0", doc.get("currency")) if doc.get("product_family") == "cosmetics" else "0"])
        else:
            rows.append([str(i), _english(item.get("product_name")), _english(item.get("capacity")),
                         _format_quantity(item.get("display_quantity", item.get("shipped_quantity", item.get("quantity", "")))), _english(item.get("unit")), price,
                         item.get("discount_percent", "0") + "%", amount])
    return rows


# 원본: reference/kekorea/Quotation_KEKOREA/agent/renderers.py _under_1000
def _under_1000(n):
    ones = ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN", "ELEVEN", "TWELVE", "THIRTEEN", "FOURTEEN", "FIFTEEN", "SIXTEEN", "SEVENTEEN", "EIGHTEEN", "NINETEEN"]
    tens = ["", "", "TWENTY", "THIRTY", "FORTY", "FIFTY", "SIXTY", "SEVENTY", "EIGHTY", "NINETY"]
    words = []
    if n >= 100:
        words += [ones[n // 100], "HUNDRED"]
        n %= 100
    if n >= 20:
        words.append(tens[n // 10])
        if n % 10:
            words.append(ones[n % 10])
    elif n:
        words.append(ones[n])
    return " ".join(words)


# 원본: reference/kekorea/Quotation_KEKOREA/agent/renderers.py amount_in_english
def amount_in_english(amount, currency):
    value = Decimal(str(amount)).quantize(Decimal("1") if currency == "KRW" else Decimal("0.01"), rounding=ROUND_HALF_UP)
    integer = int(value)
    fraction = int((value - integer) * 100)
    groups = (("TRILLION", 10**12), ("BILLION", 10**9), ("MILLION", 10**6), ("THOUSAND", 10**3))
    words = []
    remainder = integer
    for label, base in groups:
        count, remainder = divmod(remainder, base)
        if count:
            words.extend([_under_1000(count), label])
    if remainder or not words:
        words.append(_under_1000(remainder))
    major, minor = {"USD": ("US DOLLARS", "CENTS"), "KRW": ("KOREAN WON", "JEON"),
                    "EUR": ("EUROS", "CENTS"), "CNY": ("CHINESE YUAN", "FEN")}.get(currency, (currency, "HUNDREDTHS"))
    result = " ".join(words) + " " + major
    if fraction:
        result += " AND " + _under_1000(fraction) + " " + minor
    return result + " ONLY"


# 원본: reference/kekorea/Quotation_KEKOREA/agent/renderers.py document_lines
def document_lines(doc, bank_details=None):
    # 바꾼 점: 회사 이름·서명자를 issuer 스냅샷에서 읽고, PL 합계를 doc["packing_totals"]에서 읽는다.
    status = doc.get("status", "DRAFT")
    dtype = doc.get("document_type", "TRADE DOCUMENT")
    issuer_name = issuer_display_name(doc) or "TO BE CONFIRMED"
    lines = [status.replace("_", " "), f"{issuer_name} - REVIEW DRAFT", "", dtype, "".join(["Document No.: ", _english(doc.get("document_number") or "TBD")]),
             "Issue Date: " + _english(doc.get("issue_date") or "TBD"),
             "Product Family: " + _english(doc.get("product_family") or "TBD").upper(),
             "Currency: " + _english(doc.get("currency") or "TBD"), "", "SELLER / SUPPLIER"]
    lines.extend([_english((doc.get("seller") or {}).get(k)) for k in ("legal_name", "address", "contact", "phone", "email") if (doc.get("seller") or {}).get(k)])
    lines += ["", "BUYER / CUSTOMER"]
    lines.extend([_english((doc.get("buyer") or {}).get(k)) for k in ("legal_name", "address", "contact", "phone", "email", "registration_details") if (doc.get("buyer") or {}).get(k)])
    for label, field in (("Bill To", "bill_to"), ("Ship To", "ship_to"), ("Incoterms", "incoterms"),
                         ("Payment Terms", "payment_terms"), ("Shipment Reference", "shipment_reference"),
                         ("Country of Origin", "country_of_origin")):
        if doc.get(field):
            lines.append(f"{label}: {_english(doc[field])}")
    lines += ["", "LINE ITEMS: " + " | ".join(_rows(doc)[0])]
    for row in _rows(doc)[1:]:
        lines.append(" | ".join(_english(cell) for cell in row))
    if doc.get("document_type") != "PL":
        total_display = (format_currency_amount(doc.get("total", "0"), doc.get("currency"))
                         if doc.get("product_family") == "cosmetics"
                         else _english(doc.get("currency") or "") + " " + _english(doc.get("total", "0")))
        lines += ["", "TOTAL: " + _english(total_display)]
        lines.append("AMOUNT IN WORDS: " + amount_in_english(doc.get("total", "0"), doc.get("currency") or ""))
    if doc.get("actual_package_count") and doc.get("document_type") != "PL":
        lines.append("Actual Package Count: " + _english(doc["actual_package_count"]))
    for i, package in enumerate(doc.get("packages", []), 1):
        lines.append(f"Package {i}: {_english(package.get('package_type'))}; Count {_english(package.get('package_count'))}; Net {_english(package.get('net_weight_kg'))} kg; Gross {_english(package.get('gross_weight_kg'))} kg")
    if (doc.get("document_type") == "PL" and doc.get("packages") and
            not any(item.get("package_count") or item.get("net_weight_kg") or item.get("gross_weight_kg") or item.get("volume_cbm") for item in doc.get("items", []))):
        try:
            net_total = sum(Decimal(str(p.get("net_weight_kg"))) for p in doc["packages"])
            gross_total = sum(Decimal(str(p.get("gross_weight_kg"))) for p in doc["packages"])
            lines.append(f"TOTAL PACKAGES: {_english(doc.get('actual_package_count'))}; TOTAL NET WEIGHT: {net_total:f} kg; TOTAL GROSS WEIGHT: {gross_total:f} kg")
        except Exception:
            lines.append("TOTAL PACKAGE WEIGHTS: REVIEW REQUIRED")
    if doc.get("document_type") == "PL":
        # 원본은 reconcile_packing을 직접 불렀다. 이식본은 문서 초안의 packing_totals를 읽는다.
        packing = doc.get("packing_totals") or {}
        calculated = packing.get("calculated") or {}
        package_total = calculated.get("package_count") or doc.get("actual_package_count")
        if packing.get("quantity_complete"):
            for unit, quantity in (packing.get("quantities") or {}).items():
                lines.append(f"Total quantity ({_english(unit)}): {_format_quantity(quantity)}")
        for label, value in (("Containers", doc.get("container_count")),
                             ("HS Code", doc.get("hs_code")),
                             ("Total packages", _format_quantity(package_total) if package_total else None),
                             ("Total net weight (kg)", calculated.get("net_weight_kg") or doc.get("declared_net_weight_kg")),
                             ("Total gross weight (kg)", calculated.get("gross_weight_kg") or doc.get("declared_gross_weight_kg")),
                             ("Total volume (CBM)", calculated.get("volume_cbm") or doc.get("declared_volume_cbm"))):
            lines.append(f"{label}: {_english(value or 'TO BE CONFIRMED')}")
    if doc.get("remarks"):
        lines += ["", "REMARKS", _english(doc["remarks"])]
    if doc.get("document_type") == "PI":
        bank_details = bank_details or {}
        lines += ["", "BANK INFORMATION"]
        for label, key in (("Beneficiary", "BENEFICIARY"), ("Bank Name", "BANK_NAME"),
                           ("Branch Name", "BRANCH"), ("SWIFT Code", "SWIFT"),
                           ("Account Number", "ACCOUNT_NUMBER"), ("Bank Address", "BANK_ADDRESS")):
            value = bank_details.get(key)
            if key == "ACCOUNT_NUMBER" and value:
                value = str(value) + f" ({doc.get('currency') or ''})"
            lines.append(f"{label}: {_english(value or '[BANK DETAIL REQUIRED]')}")
    lines += ["", "AUTHORIZED SIGNATURE", issuer_signer(doc), issuer_name,
              "[OFFICIAL COMPANY SEAL TO BE INSERTED]"]
    if doc.get("blocking_issues"):
        lines += ["", "OPEN ITEMS - DO NOT ISSUE"]
        for issue in doc["blocking_issues"]:
            if any(ord(ch) > 255 for ch in str(issue)):
                lines.append("- Review a non-English source note in the app")
            else:
                lines.append("- " + _english(issue))
    lines += ["", "Prepared in English. Review all transaction and shipping details before use."]
    return lines


# 원본: reference/kekorea/Quotation_KEKOREA/agent/renderers.py _pdf_bytes
def _pdf_bytes(lines):
    pages = [lines[i:i + 48] for i in range(0, len(lines), 48)] or [[]]
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    page_ids = [5 + 2 * i for i in range(len(pages))]
    objects.append(("<< /Type /Pages /Kids [" + " ".join(f"{n} 0 R" for n in page_ids) + f"] /Count {len(pages)} >>").encode())
    objects.append(b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H /DescendantFonts [4 0 R] >>")
    objects.append(b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> /DW 1000 >>")
    for i, page_lines in enumerate(pages):
        page_id, stream_id = 5 + 2 * i, 6 + 2 * i
        commands = ["BT", "/F1 9 Tf", "50 790 Td", "14 TL"]
        for line in page_lines:
            safe = _english(line)[:180].encode("utf-16-be").hex().upper()
            commands.append(f"<{safe}> Tj T*")
        commands.append("ET")
        stream = "\n".join(commands).encode("ascii")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>".encode())
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


# 원본: reference/kekorea/Quotation_KEKOREA/agent/renderers.py _xlsx_bytes(로고·직인 bytes 입력)
def _xlsx_bytes(doc, bank_details=None, *, seal=None):
    rows = [[doc.get("document_type", "DRAFT"), "STATUS", doc.get("status", "DRAFT")],
            ["Currency", doc.get("currency") or "TBD", "Product Family", doc.get("product_family") or "TBD"],
            ["Document Number", doc.get("document_number") or "TBD", "Issue Date", doc.get("issue_date") or "TBD"],
            ["Seller", (doc.get("seller") or {}).get("legal_name") or "TBD"],
            ["Seller Address", (doc.get("seller") or {}).get("address") or "TBD"],
            ["Seller Contact", (doc.get("seller") or {}).get("contact") or ""],
            ["Seller Tel", (doc.get("seller") or {}).get("phone") or ""],
            ["Seller Email", (doc.get("seller") or {}).get("email") or ""],
            ["Buyer", (doc.get("buyer") or {}).get("legal_name") or "TBD"],
            ["Buyer Address", (doc.get("buyer") or {}).get("address") or "TBD"],
            ["Buyer Contact", (doc.get("buyer") or {}).get("contact") or ""],
            ["Buyer Tel", (doc.get("buyer") or {}).get("phone") or ""],
            ["Buyer Email", (doc.get("buyer") or {}).get("email") or ""],
            ["Buyer Registration Details", (doc.get("buyer") or {}).get("registration_details") or ""], [], *_rows(doc),
            ["", "", "", "", "", "TOTAL", doc.get("currency") or "",
             format_currency_amount(doc.get("total", "0"), doc.get("currency")) if doc.get("product_family") == "cosmetics" else doc.get("total", "0")],
            ["Incoterms", doc.get("incoterms") or "TBD"], ["Payment Terms", doc.get("payment_terms") or "TBD"],
            ["Remarks", doc.get("remarks") or ""]]
    if doc.get("document_type") == "PL":
        # 원본은 reconcile_packing을 직접 불렀다. 이식본은 문서 초안의 packing_totals를 읽는다.
        packing = doc.get("packing_totals") or {}
        calculated = packing.get("calculated") or {}
        package_total = calculated.get("package_count") or doc.get("actual_package_count")
        rows = [row for row in rows if not (len(row) > 5 and row[:5] == ["", "", "", "", ""] and row[5] == "TOTAL")]
        rows += [["Containers", doc.get("container_count") or "TO BE CONFIRMED"],
                 ["HS Code", doc.get("hs_code") or "TO BE CONFIRMED"],
                 ["Total packages", _format_quantity(package_total) if package_total else "TO BE CONFIRMED"],
                 ["Total net weight (kg)", calculated.get("net_weight_kg") or doc.get("declared_net_weight_kg") or "TO BE CONFIRMED"],
                 ["Total gross weight (kg)", calculated.get("gross_weight_kg") or doc.get("declared_gross_weight_kg") or "TO BE CONFIRMED"],
                 ["Total volume (CBM)", calculated.get("volume_cbm") or doc.get("declared_volume_cbm") or "TO BE CONFIRMED"]]
        if packing.get("quantity_complete"):
            rows += [[f"Total quantity ({unit})", _format_quantity(quantity)]
                     for unit, quantity in (packing.get("quantities") or {}).items()]
    if doc.get("document_type") == "PI":
        bank_details = bank_details or {}
        rows += [["Bank Information", "Beneficiary", bank_details.get("BENEFICIARY") or "[BANK DETAIL REQUIRED]"],
                 ["", "Bank Name", bank_details.get("BANK_NAME") or "[BANK DETAIL REQUIRED]"],
                 ["", "Branch Name", bank_details.get("BRANCH") or "[BANK DETAIL REQUIRED]"],
                 ["", "SWIFT Code", bank_details.get("SWIFT") or "[BANK DETAIL REQUIRED]"],
                 ["", f"Account Number ({doc.get('currency') or ''})", bank_details.get("ACCOUNT_NUMBER") or "[BANK DETAIL REQUIRED]"],
                 ["", "Bank Address", bank_details.get("BANK_ADDRESS") or "[BANK DETAIL REQUIRED]"]]
    seal_bytes = seal if seal else None
    if seal_bytes:
        rows += [[], ["Authorized Representative", issuer_signer(doc)], [issuer_display_name(doc) or "TO BE CONFIRMED"]]
    xml_rows = []
    for ri, row in enumerate(rows, 1):
        cells = []
        for ci, value in enumerate(row, 1):
            if value is None or value == "":
                continue
            col = ""
            n = ci
            while n:
                n, rem = divmod(n - 1, 26)
                col = chr(65 + rem) + col
            cell = f"{col}{ri}"
            cells.append(f'<c r="{cell}" t="inlineStr"><is><t xml:space="preserve">{xml_escape(_english(value))}</t></is></c>')
        xml_rows.append(f'<row r="{ri}">{"".join(cells)}</row>')
    drawing = '<drawing r:id="rId1"/>' if seal_bytes else ""
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheetData>' + "".join(xml_rows) + "</sheetData>" + drawing + "</worksheet>")
    workbook = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Trade Document Draft" sheetId="1" r:id="rId1"/></sheets></workbook>'
    with BytesIO() as buf:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            drawing_types = '<Default Extension="png" ContentType="image/png"/><Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>' if seal_bytes else ""
            z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' + drawing_types + '</Types>')
            z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
            z.writestr("xl/workbook.xml", workbook)
            z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr("xl/worksheets/sheet1.xml", sheet)
            if seal_bytes:
                z.writestr("xl/worksheets/_rels/sheet1.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/></Relationships>')
                z.writestr("xl/drawings/drawing1.xml", '<?xml version="1.0" encoding="UTF-8"?><xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><xdr:oneCellAnchor><xdr:from><xdr:col>0</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>' + str(len(rows)) + '</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from><xdr:ext cx="4572000" cy="1542000"/><xdr:pic><xdr:nvPicPr><xdr:cNvPr id="1" name="Company Seal"/><xdr:cNvPicPr/></xdr:nvPicPr><xdr:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill><xdr:spPr><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/></xdr:oneCellAnchor></xdr:wsDr>')
                z.writestr("xl/drawings/_rels/drawing1.xml.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/seal.png"/></Relationships>')
                z.writestr("xl/media/seal.png", seal_bytes)
        return buf.getvalue()


# 원본: reference/kekorea/Quotation_KEKOREA/agent/renderers.py render_files(로고·직인 bytes 입력)
def render_files(doc, output_dir, *, bank_details=None, logo=None, seal=None):
    """Write draft outputs (even incomplete ones carry a DRAFT status and open-items list)."""
    # Keep the date and destination defaults consistent across PDF, Excel, and HTML.
    doc = {**doc, "issue_date": current_issue_date(), "ship_to": doc.get("ship_to") or "N/A"}
    dtype = re.sub(r"[^A-Za-z0-9_-]", "_", str(doc.get("document_type") or "DRAFT"))
    stamp = re.sub(r"[^0-9-]", "", str(doc.get("issue_date") or "")) or date.today().isoformat()
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
    stem = f"{dtype}_{stamp}_DRAFT_{run_id}"
    lines = document_lines(doc, bank_details)
    html_rows = "".join("<tr>" + "".join(f"<td>{escape(_english(v))}</td>" for v in row) + "</tr>" for row in _rows(doc))
    html_doc = "<!doctype html><meta charset='utf-8'><title>Trade Document Draft</title><h1>" + escape(dtype) + "</h1><h2>" + escape(doc.get("status", "DRAFT")) + "</h2><table border='1'>" + html_rows + "</table><pre>" + escape("\n".join(lines)) + "</pre>"
    paths = {"pdf": directory / f"{stem}.pdf", "xlsx": directory / f"{stem}.xlsx", "html": directory / f"{stem}.html"}
    from app.trade.common.pdf import render_trade_document
    paths["pdf"].write_bytes(render_trade_document(
        doc, bank_details or {}, logo=logo, seal=seal))
    paths["xlsx"].write_bytes(_xlsx_bytes(doc, bank_details, seal=seal))
    paths["html"].write_text(html_doc, encoding="utf-8")
    return paths
