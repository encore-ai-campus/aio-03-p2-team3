"""무역서류 PDF 출력(외부 라이브러리 없이 직접 생성).

원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py
원본과 다른 점(docs/CONTRACT.md 15.4·15.5·15.7절):
- 로고·직인 입력을 파일 경로에서 PNG bytes로 바꾼다(render_trade_document(data, bank_details,
  *, logo=None, seal=None)). 직인 저장은 원본의 Supabase 대신 이 서비스의 company_branding 표다.
- 발행 회사 이름·서명자를 원본 고정 문구 대신 문서 초안의 issuer 스냅샷(legal_name_en →
  company_name, 서명자 ceo_name)에서 읽는다[임시: 협의 1].
- PL 포장 합계를 reconcile_packing 직접 호출 대신 data["packing_totals"]에서 읽는다
  (calculated → 선언값 → packages_total 순서, 렌더러가 합계를 다시 계산하지 않는다).
- 계좌 6항목(PI만)·회사 명판·직인은 한 페이지 묶음으로 분할하지 않는다(PRESERVED_BEHAVIOR).
- 원본에서 뒤쪽 정의가 덮어쓰던 죽은 코드(프리미엄 PI 1페이지 레이아웃, _money·_draw_party_detail)와
  회사 로고 에셋 전용 crop_box 값은 옮기지 않았다.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import textwrap
import struct
import zlib

from .trade_documents import current_issue_date


PAGE_W, PAGE_H = 612, 792
NAVY = (0.035, 0.15, 0.28)
BRAND_BLUE = (0.02, 0.43, 0.75)
INK = (0.18, 0.18, 0.18)
MUTED = (0.43, 0.43, 0.42)
PALE = (0.95, 0.975, 0.995)
MID_BLUE = (0.10, 0.32, 0.50)
WARNING = (0.69, 0.29, 0.18)


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py issuer 스냅샷 읽기(회사 고정 문구 일반화)
def issuer_display_name(data):
    """발행 회사 표시 이름. 영문 법인명(legal_name_en) 우선, 없으면 company_name[임시: 협의 1]."""
    issuer = data.get("issuer") or {}
    return str(issuer.get("legal_name_en") or issuer.get("company_name") or "").strip()


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py issuer 스냅샷 읽기(회사 고정 문구 일반화)
def issuer_signer(data):
    """서명자 이름. 설정(ceo_name)이 없으면 원본 사본의 표시 문구를 쓴다."""
    issuer = data.get("issuer") or {}
    return str(issuer.get("ceo_name") or "").strip() or "[AUTHORIZED SIGNER]"


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py _pdf_escape
def _pdf_escape(value):
    return str(value).encode("ascii", "replace").decode("ascii").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py _Canvas
class _Canvas:
    def __init__(self):
        self.commands = []
        self.images = []

    @staticmethod
    def _rgb(color):
        return "%.3f %.3f %.3f" % color

    def rect(self, x, top, w, h, color=None, stroke=None, line_width=0.7):
        y = PAGE_H - top - h
        if color:
            self.commands.extend([self._rgb(color) + " rg", f"{x} {y} {w} {h} re f"])
        if stroke:
            self.commands.extend([self._rgb(stroke) + " RG", f"{line_width} w {x} {y} {w} {h} re S"])

    def line(self, x1, top1, x2, top2, color=MUTED, width=0.7):
        self.commands.extend([self._rgb(color) + " RG", f"{width} w {x1} {PAGE_H-top1} m {x2} {PAGE_H-top2} l S"])

    def text(self, x, top, value, size=8, bold=False, color=INK, *, align="left"):
        value = str(value or "")
        if align == "center":
            x -= _text_width(value, size) / 2
        if re.search(r"[\u3400-\u9fff]", value):
            encoded = value.encode("utf-16-be").hex().upper()
            font = "F3"
            command = f"<{encoded}> Tj"
        else:
            font = "F2" if bold else "F1"
            command = f"({_pdf_escape(value)}) Tj"
        self.commands.extend([self._rgb(color) + " rg", f"BT /{font} {size} Tf 1 0 0 1 {x} {PAGE_H-top} Tm {command} ET"])

    def image(self, data, x, top, max_w, max_h, *, watermark=False, crop_box=None):
        # 원본과 다른 점: 파일 경로 대신 PNG bytes를 받는다.
        if not data:
            return False
        try:
            width, height, pixels = _read_png_rgb(data)
            if crop_box:
                crop_x, crop_y, crop_w, crop_h = crop_box
                pixels = _crop_rgb(pixels, width, height, crop_x, crop_y, crop_w, crop_h)
                width, height = crop_w, crop_h
            raw = zlib.compress(pixels, level=9)
        except Exception as exc:
            raise ValueError("Could not load the brand PNG image") from exc
        crop_x = crop_y = 0
        crop_w, crop_h = width, height
        scale = min(max_w / width, max_h / height)
        draw_w, draw_h = width * scale, height * scale
        self.images.append({"bytes": raw, "width": width, "height": height, "watermark": watermark})
        image_id = len(self.images)
        image_x = x - crop_x * scale
        image_top = top - crop_y * scale
        y = PAGE_H - image_top - draw_h
        clip = ""
        if watermark:
            self.commands.extend(["q", clip + "/GS1 gs", f"{draw_w:.2f} 0 0 {draw_h:.2f} {image_x:.2f} {y:.2f} cm", f"/Im{image_id} Do", "Q"])
        else:
            self.commands.extend(["q", clip + f"{draw_w:.2f} 0 0 {draw_h:.2f} {image_x:.2f} {y:.2f} cm", f"/Im{image_id} Do", "Q"])
        return True


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py _text_width
def _text_width(value, size):
    """Estimate Helvetica point width for numeric/Latin text to center summary labels."""
    widths = {
        " ": 278, ",": 278, ".": 278, ":": 278, ";": 278, "!": 278,
        "(": 333, ")": 333, "-": 333, "+": 564, "$": 556, "/": 278,
        "0": 556, "1": 556, "2": 556, "3": 556, "4": 556, "5": 556, "6": 556, "7": 556, "8": 556, "9": 556,
        "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778, "H": 722,
        "I": 278, "J": 500, "K": 667, "L": 556, "M": 833, "N": 722, "O": 778, "P": 667,
        "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944, "X": 667,
        "Y": 667, "Z": 611,
    }
    return sum(widths.get(char.upper(), 556) for char in str(value)) * size / 1000


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py _read_png_rgb(입력을 bytes로 바꿈)
def _read_png_rgb(data):
    """Decode common 8-bit RGB/RGBA PNGs using only the Python standard library."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Expected PNG")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", data[16:29])
    if min(width, height) < 1 or max(width, height) > 4096 or width * height > 4194304:
        raise ValueError("Brand image dimensions exceed the supported size")
    if depth != 8 or color not in (2, 6) or interlace != 0:
        raise ValueError("Only non-interlaced 8-bit RGB/RGBA PNGs are supported")
    pos, chunks = 8, []
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos+4])[0]
        kind = data[pos+4:pos+8]
        payload = data[pos+8:pos+8+length]
        if pos + 12 + length > len(data):
            raise ValueError("Truncated PNG chunk")
        crc = struct.unpack(">I", data[pos+8+length:pos+12+length])[0]
        if crc != zlib.crc32(kind + payload) & 0xffffffff:
            raise ValueError("Invalid PNG checksum")
        if kind == b"IDAT": chunks.append(payload)
        pos += 12 + length
        if kind == b"IEND": break
    bpp = 3 if color == 2 else 4
    expected_size = height * (1 + width * bpp)
    decoder = zlib.decompressobj()
    scan = decoder.decompress(b"".join(chunks), expected_size + 1)
    if len(scan) != expected_size or not decoder.eof or decoder.unconsumed_tail:
        raise ValueError("PNG data size does not match its dimensions")
    stride = width*bpp
    rows, offset, previous = [], 0, bytearray(stride)
    for _ in range(height):
        mode = scan[offset]; offset += 1
        row = bytearray(scan[offset:offset+stride]); offset += stride
        for i in range(stride):
            left = row[i-bpp] if i >= bpp else 0
            up = previous[i]
            upper_left = previous[i-bpp] if i >= bpp else 0
            if mode == 1: row[i] = (row[i]+left)&255
            elif mode == 2: row[i] = (row[i]+up)&255
            elif mode == 3: row[i] = (row[i]+((left+up)//2))&255
            elif mode == 4:
                p = left+up-upper_left
                pa,pb,pc=abs(p-left),abs(p-up),abs(p-upper_left)
                predictor=left if pa<=pb and pa<=pc else up if pb<=pc else upper_left
                row[i]=(row[i]+predictor)&255
            elif mode != 0: raise ValueError("Unsupported PNG filter")
        rows.append(row); previous=row
    if color == 2: return width,height,b"".join(rows)
    rgb=bytearray(width*height*3); target=0
    for row in rows:
        for i in range(0,len(row),4):
            alpha=row[i+3]
            for channel in row[i:i+3]:
                rgb[target]=(channel*alpha+255*(255-alpha))//255; target+=1
    return width,height,bytes(rgb)


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py _crop_rgb
def _crop_rgb(pixels, width, height, x, y, crop_w, crop_h):
    if min(x,y,crop_w,crop_h)<0 or x+crop_w>width or y+crop_h>height:
        raise ValueError("PNG crop is outside the image")
    row_bytes=crop_w*3
    return b"".join(pixels[((y+line)*width+x)*3:((y+line)*width+x)*3+row_bytes] for line in range(crop_h))


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py _wrap
def _wrap(value, width):
    return textwrap.wrap(str(value or ""), width=width, break_long_words=True, break_on_hyphens=False) or [""]


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py _document_title
def _document_title(document_type):
    return {"PO": "PURCHASE ORDER", "PI": "PROFORMA INVOICE",
            "CI": "COMMERCIAL INVOICE", "PL": "PACKING LIST"}.get(document_type, "TRADE DOCUMENT")


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py _format_quantity
def _format_quantity(value):
    try:
        rendered = format(Decimal(str(value)), ",f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    except (InvalidOperation, TypeError, ValueError):
        return str(value or "-")


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py _total_quantity_summary
def _total_quantity_summary(items):
    totals = {}
    for item in items:
        try:
            paid = Decimal(str(item.get("paid_quantity") or item.get("quantity") or "0"))
            free = Decimal(str(item.get("free_quantity") or "0"))
            quantity = Decimal(str(item.get("shipped_quantity") or paid + free))
        except (InvalidOperation, TypeError, ValueError):
            continue
        unit = str(item.get("unit") or "PCS").strip()
        key = unit.upper()
        if key not in totals:
            totals[key] = [Decimal("0"), unit]
        totals[key][0] += quantity
    return " | ".join(f"{_format_quantity(amount)} {unit}".strip()
                      for amount, unit in totals.values()) or "TO BE CONFIRMED"


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py _formatted_money
def _formatted_money(value, currency):
    try:
        amount = Decimal(str(value)).quantize(Decimal("1") if currency == "KRW" else Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return "TO BE CONFIRMED"
    if currency == "USD":
        return "$" + f"{amount:,.2f}"
    return f"{currency} {amount:,.0f}" if currency == "KRW" else f"{currency} {amount:,.2f}"


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py _serialize_trade_pages
def _serialize_trade_pages(canvases):
    """Serialize all branded pages, assigning page references after image objects."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"",  # Pages object filled after image count is known.
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
               b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H /DescendantFonts [6 0 R] >>",
               b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> /DW 1000 >>",
               b"<< /Type /ExtGState /ca 0.075 /CA 0.075 >>",
               b"<< /Type /ExtGState /ca 1 /CA 1 >>"]
    page_image_ids = []
    for canvas in canvases:
        ids = []
        for image in canvas.images:
            ids.append(len(objects) + 1)
            raw = image["bytes"]
            objects.append(b"<< /Type /XObject /Subtype /Image /Width " + str(image["width"]).encode() +
                           b" /Height " + str(image["height"]).encode() +
                           b" /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length " +
                           str(len(raw)).encode() + b" >>\nstream\n" + raw + b"\nendstream")
        page_image_ids.append(ids)

    first_page_id = len(objects) + 1
    page_ids = [first_page_id + 2 * i for i in range(len(canvases))]
    objects[1] = ("<< /Type /Pages /Kids [" + " ".join(f"{page_id} 0 R" for page_id in page_ids) +
                  f"] /Count {len(page_ids)} >>").encode()
    for i, canvas in enumerate(canvases):
        page_id, stream_id = page_ids[i], page_ids[i] + 1
        xobjects = " ".join(f"/Im{j + 1} {image_id} 0 R" for j, image_id in enumerate(page_image_ids[i]))
        resources = (f"<< /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> "
                     f"/ExtGState << /GS1 7 0 R /GS2 8 0 R >> /XObject << {xobjects} >> >>")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources {resources} /Contents {stream_id} 0 R >>".encode())
        stream = ("\n".join(canvas.commands) + "\n").encode("ascii")
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{object_number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py _party_panel
def _party_panel(canvas, x, title, party):
    panel_top, panel_width = 136, 262
    name_lines = _wrap(party.get("legal_name") or "TO BE CONFIRMED", 48)
    details = [("Address", party.get("address")), ("Tel", party.get("phone")),
               ("Email", party.get("email")), ("Representative", party.get("contact"))]
    if party.get("registration_details"):
        details.append(("Registration", party["registration_details"]))
    value_x, wrap_width = x + 66, 58
    detail_lines = [(label, _wrap(value or "Not provided", wrap_width)) for label, value in details]
    y = panel_top + 34 + max(1, len(name_lines)) * 8.6 + 3
    for _, lines in detail_lines:
        y += max(8, len(lines) * 7.0)
    panel_height = max(92, y - panel_top + 7)
    canvas.rect(x, panel_top, panel_width, panel_height, (1, 1, 1), PALE, 0.8)
    canvas.line(x, panel_top, x + panel_width, panel_top, BRAND_BLUE, 1.3)
    canvas.text(x + 10, panel_top + 15, title, 6.5, True, BRAND_BLUE)
    for line_index, line in enumerate(name_lines):
        canvas.text(x + 10, panel_top + 34 + line_index * 8.6, line, 8.0, True)
    y = panel_top + 34 + max(1, len(name_lines)) * 8.6 + 3
    for label, lines in detail_lines:
        canvas.text(x + 10, y, label + ":", 5.5, False, INK)
        for line_index, line in enumerate(lines):
            canvas.text(value_x, y + line_index * 7.0, line, 5.5, False, INK)
        y += max(8, len(lines) * 7.0)
    return panel_top + panel_height


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py _document_row
def _document_row(item, is_packing_list, currency, *, paid_promotion=False):
    name = str(item.get("product_name") or "TO BE CONFIRMED")
    if is_packing_list and item.get("hs_code"):
        name += " | HS: " + str(item["hs_code"])
    capacity = str(item.get("capacity") or item.get("specification") or "-")
    quantity_value = (item.get("paid_quantity") if paid_promotion else
                      item.get("display_quantity") or item.get("paid_quantity") or item.get("quantity") or "-")
    quantity = _format_quantity(quantity_value if quantity_value not in (None, "") else "-")
    unit = str(item.get("unit") or "PCS")
    try:
        free_quantity = Decimal(str(item.get("free_quantity") or "0"))
    except (InvalidOperation, TypeError, ValueError):
        free_quantity = Decimal("0")
    if free_quantity:
        quantity += f" + {_format_quantity(free_quantity)} FOC"
    if not is_packing_list:
        quantity = f"{quantity} {unit}".strip()
    row = {"name": name, "capacity": capacity, "quantity": quantity, "unit": unit}
    row["name_lines"] = _wrap(name, 30 if is_packing_list else 52)
    row["capacity_lines"] = _wrap(capacity, 13 if is_packing_list else 23)
    row["quantity_lines"] = _wrap(quantity, 11 if is_packing_list else 16)
    if is_packing_list:
        package = " ".join(str(item.get(key) or "").strip() for key in ("package_count", "package_type")).strip()
        for key, value, width in (("package_lines", package, 11),
                                  ("net_lines", item.get("net_weight_kg"), 13),
                                  ("gross_lines", item.get("gross_weight_kg"), 13),
                                  ("volume_lines", item.get("volume_cbm"), 13)):
            row[key] = _wrap(str(value) if value not in (None, "") else "-", width)
    if not is_packing_list:
        row["price"] = _formatted_money(item.get("final_unit_price", item.get("unit_price", "")), currency)
        row["amount"] = _formatted_money(item.get("line_total", ""), currency)
        if currency in {"KRW", "EUR", "CNY"} and row["price"].startswith(currency + " "):
            row["price"] = row["price"][len(currency) + 1:]
        if currency in {"KRW", "EUR", "CNY"} and row["amount"].startswith(currency + " "):
            row["amount"] = row["amount"][len(currency) + 1:]
        row["price_lines"] = _wrap(row["price"], 16)
        row["amount_lines"] = _wrap(row["amount"], 17)
    line_count = max(len(row[key]) for key in row if key.endswith("_lines"))
    row["height"] = max(13.5, 4.5 + line_count * 7.0)
    return row


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py _paginate_rows
def _paginate_rows(rows, first_table_top, review_height, is_packing_list, packing_quantity_lines=1):
    """Fill product pages first; move the entire closing section when it cannot fit."""
    content_bottom = 752
    last_page_reserve = (185 + max(0, packing_quantity_lines - 1) * 8 if is_packing_list else 154) + review_height
    continuation_table_top = 166
    chunks, page = [], []
    table_top, used = first_table_top, 0
    for row in rows:
        if table_top + 17 + used + row["height"] > content_bottom:
            chunks.append(page)
            page, used, table_top = [], 0, continuation_table_top
        if table_top + 17 + row["height"] > content_bottom:
            raise ValueError("A product row is too tall to fit on one PDF page; shorten its description")
        page.append(row)
        used += row["height"]
    chunks.append(page)

    # An empty final chunk is a closing-section page, not a reason to relocate a product.
    table_bottom = table_top + (17 if page else 0) + used
    if table_bottom + last_page_reserve > content_bottom:
        chunks.append([])
    return chunks


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py render_trade_document
def render_trade_document(data, bank_details=None, *, logo=None, seal=None, issued_on=None,
                          footer_label="DRAFT - NOT FOR ISSUE"):
    """Render all trade documents with measured rows, safe footer space, and automatic pagination."""
    # 바꾼 점: logo·seal을 PNG bytes로 받고, 발행사 이름·서명자를 issuer 스냅샷에서 읽고,
    # PL 합계를 data["packing_totals"]에서 읽는다(모듈 머리 주석 참고).
    if not seal:
        raise ValueError("A company seal is required to create a trade-document PDF")
    doc_type = str(data.get("document_type") or "PI").upper()
    title = _document_title(doc_type)
    is_packing_list = doc_type == "PL"
    currency = str(data.get("currency") or "TO CONFIRM").upper()
    items = data.get("items") or []
    rows = [_document_row(item, is_packing_list, currency,
                          paid_promotion=data.get("document_type") in {"PO", "PI"} and bool(item.get("promotion")))
            for item in items]
    remark_lines = _wrap(str(data.get("remarks") or "N/A").replace("\n", " "), 145)
    review_height = max(40, 22 + len(remark_lines) * 6.5)

    # Party details expand naturally; the resulting table start feeds the page-fit calculation.
    probe = _Canvas()
    seller_bottom = _party_panel(probe, 35, "SELLER / SUPPLIER", data.get("seller") or {})
    buyer_bottom = _party_panel(probe, 315, "BUYER / CUSTOMER", data.get("buyer") or {})
    terms_top = max(seller_bottom, buyer_bottom) + 8
    terms_values = [data.get("incoterms") or "TO BE CONFIRMED",
                    data.get("payment_terms") or "TO BE CONFIRMED",
                    data.get("ship_to") or "N/A",
                    data.get("country_of_origin") or "N/A"]
    terms_lines = [_wrap(str(value), 26) for value in terms_values]
    terms_height = max(38, 18 + max(map(len, terms_lines)) * 7.0)
    first_table_top = terms_top + terms_height + 12
    total_quantity = _total_quantity_summary(items)
    packing_quantity_lines = _wrap("TOTAL QUANTITY: " + total_quantity, 130)
    chunks = _paginate_rows(rows, first_table_top, review_height, is_packing_list, len(packing_quantity_lines))
    canvases = []
    number = str(data.get("document_number") or "TBD")
    issue_date = issued_on or current_issue_date()
    number_label = {"PI": "INVOICE #", "CI": "INVOICE #", "PO": "PO #", "PL": "PACKING LIST #"}.get(doc_type, "DOCUMENT #")

    for page_index, page_rows in enumerate(chunks):
        canvas = _Canvas()
        canvases.append(canvas)
        canvas.rect(0, 0, PAGE_W, PAGE_H, (1, 1, 1))
        canvas.rect(0, 0, PAGE_W, 94, (1, 1, 1))
        canvas.rect(0, 91, PAGE_W, 3, BRAND_BLUE)
        has_logo = canvas.image(logo, 30, 4, 235, 84)
        canvas.text(376, 40, title, 14.2, True, NAVY)
        canvas.rect(376, 52, 202, 23, MID_BLUE)
        canvas.text(388, 68, f"{number_label} {number}"[:38], 6.7, True, (0.90, 0.95, 0.99))
        canvas.text(35, 109, number_label.replace("#", "NUMBER").strip(), 5.8, True, MUTED)
        canvas.text(35, 123, number[:25], 7.2, True, INK)
        canvas.text(220, 109, "ISSUE DATE", 5.8, True, MUTED)
        canvas.text(220, 123, issue_date, 7.2, True, INK)
        canvas.text(430, 109, "SHIPMENT REFERENCE" if is_packing_list else "CURRENCY", 5.8, True, MUTED)
        canvas.text(430, 123, str(data.get("shipment_reference") or "N/A")[:30] if is_packing_list else currency, 7.2, True, INK)

        if page_index == 0:
            _party_panel(canvas, 35, "SELLER / SUPPLIER", data.get("seller") or {})
            _party_panel(canvas, 315, "BUYER / CUSTOMER", data.get("buyer") or {})
            canvas.rect(35, terms_top, 542, terms_height, PALE)
            columns = [(47, "DELIVERY TERMS"), (185, "PAYMENT TERMS"),
                       (330, "SHIP TO"), (455, "COUNTRY OF ORIGIN")]
            for column_index, (x, label) in enumerate(columns):
                canvas.text(x, terms_top + 12, label, 5.6, True, MUTED)
                for line_index, line in enumerate(terms_lines[column_index]):
                    canvas.text(x, terms_top + 24 + line_index * 7, line, 5.8, True, INK)
            table_top = first_table_top
        else:
            canvas.text(35, 147, f"{title} - CONTINUED", 7.2, True, BRAND_BLUE)
            table_top = 166

        left = 35
        widths = [143, 62, 53, 30, 50, 66, 66, 72] if is_packing_list else [225, 90, 62, 78, 87]
        xs = [left]
        for width in widths:
            xs.append(xs[-1] + width)
        labels = (["PRODUCT", "SPEC.", "QTY", "UNIT", "PACKAGES", "NW (KG)", "GW (KG)", "CBM"] if is_packing_list else
                  ["PRODUCT DESCRIPTION", "CAPACITY / SPEC.", "QUANTITY / UNIT", f"UNIT PRICE ({currency})", f"AMOUNT ({currency})"])
        if page_rows:
            canvas.text(left, table_top - 7, "PACKING DETAILS" if is_packing_list else "PRODUCT & PRICING", 6.5, True, BRAND_BLUE)
            canvas.rect(left, table_top, 542, 17, NAVY)
            for column_index, label in enumerate(labels):
                canvas.text(xs[column_index] + 3, table_top + 11, label, 5.2, True, (1, 1, 1))

        y = table_top + (17 if page_rows else 0)
        for row_index, row in enumerate(page_rows):
            height = row["height"]
            if row_index % 2 == 0:
                canvas.rect(left, y, 542, height, PALE)
            canvas.line(left, y + height, left + 542, y + height, (0.86, 0.88, 0.90), 0.4)
            for column, key in enumerate(("name_lines", "capacity_lines", "quantity_lines")):
                for line_index, line in enumerate(row[key]):
                    canvas.text(xs[column] + 3, y + 8 + line_index * 7, line, 5.4, False, INK)
            if is_packing_list:
                canvas.text(xs[3] + 3, y + 8, row["unit"][:12], 5.4, False, INK)
                for column, key in ((4, "package_lines"), (5, "net_lines"), (6, "gross_lines"), (7, "volume_lines")):
                    for line_index, line in enumerate(row[key]):
                        canvas.text(xs[column] + 3, y + 8 + line_index * 7, line, 5.0, False, INK)
            else:
                for column, key in ((3, "price_lines"), (4, "amount_lines")):
                    for line_index, line in enumerate(row[key]):
                        canvas.text(xs[column] + 3, y + 8 + line_index * 7, line,
                                    5.2 if column == 3 else 5.3, column == 4, INK)
            y += height

        last_page = page_index == len(chunks) - 1
        if last_page:
            bottom = y + 8
            if is_packing_list:
                # 원본은 reconcile_packing을 직접 불렀다. 이식본은 문서 초안의 packing_totals를 읽고
                # 합계를 다시 계산하지 않는다(calculated → 선언값 → packages_total 순서).
                packing = data.get("packing_totals") or {}
                calculated = packing.get("calculated") or {}
                packages_total = packing.get("packages_total") or {}
                package_lines = []
                package_total = calculated.get("package_count") or data.get("actual_package_count")
                package_lines.append("TOTAL PACKAGES: " + (_format_quantity(package_total) if package_total else "TO BE CONFIRMED") +
                                     "  |  CONTAINERS: " + str(data.get("container_count") or "TO BE CONFIRMED"))
                try:
                    net = (calculated.get("net_weight_kg") or data.get("declared_net_weight_kg")
                           or packages_total.get("net_weight_kg"))
                    gross = (calculated.get("gross_weight_kg") or data.get("declared_gross_weight_kg")
                             or packages_total.get("gross_weight_kg"))
                    package_lines.append(f"NET WEIGHT: {_format_quantity(net) if net else 'TO BE CONFIRMED'} KG  |  GROSS WEIGHT: {_format_quantity(gross) if gross else 'TO BE CONFIRMED'} KG")
                    volume = calculated.get("volume_cbm") or data.get("declared_volume_cbm")
                    package_lines.append("TOTAL VOLUME: " + (_format_quantity(volume) if volume else "TO BE CONFIRMED") + " CBM")
                    if data.get("hs_code"):
                        package_lines.append("HS CODE: " + str(data["hs_code"]))
                except (InvalidOperation, TypeError, ValueError):
                    package_lines.append("NET WEIGHT / GROSS WEIGHT: TO BE CONFIRMED")
                for line_index, line in enumerate(package_lines):
                    canvas.text(left, bottom + 8 + line_index * 8, line, 5.8, True, MUTED)
                bottom += len(package_lines) * 8 + 4
                for line_index, line in enumerate(packing_quantity_lines):
                    canvas.text(left, bottom + 8 + line_index * 8, line, 5.8, True, MUTED)
                bottom += 17 + (len(packing_quantity_lines) - 1) * 8
            else:
                total_text = _formatted_money(data.get("total") or "0", currency)
                canvas.rect(374, bottom - 4, 203, 27, NAVY)
                box_center = 475.5
                canvas.text(box_center, bottom + 7, f"TOTAL AMOUNT ({currency})", 5.8, True,
                            (0.8, 0.9, 1), align="center")
                canvas.text(box_center, bottom + 19, total_text, 8.7, True, (1, 1, 1), align="center")
                quantity_lines = _wrap("TOTAL QUANTITY: " + total_quantity, 82)
                for line_index, line in enumerate(quantity_lines):
                    canvas.text(left, bottom + 10 + line_index * 7, line, 6.0, True, MUTED)
                bottom += 31

            canvas.rect(35, bottom, 542, review_height, (1, 1, 1), PALE, 0.7)
            canvas.rect(35, bottom, 3, review_height, BRAND_BLUE)
            canvas.text(45, bottom + 11, "REMARK", 5.7, True, BRAND_BLUE)
            for line_index, line in enumerate(remark_lines):
                canvas.text(45, bottom + 22 + line_index * 6.5, line, 5.0, False, INK)
            bottom += review_height + 7

            if doc_type == "PI":
                panel_top, panel_height = bottom, 86
                canvas.rect(35, panel_top, 350, panel_height, (1, 1, 1), PALE, 0.7)
                canvas.rect(35, panel_top, 350, 15, PALE)
                canvas.text(44, panel_top + 11, "USD BANK INFORMATION - PI ONLY", 5.8, True, BRAND_BLUE)
                bank_rows = [("BENEFICIARY", "BENEFICIARY"), ("BANK NAME", "BANK_NAME"), ("BRANCH NAME", "BRANCH"),
                             ("SWIFT CODE", "SWIFT"), ("ACCOUNT NUMBER", "ACCOUNT_NUMBER"), ("BANK ADDRESS", "BANK_ADDRESS")]
                for index, (label, key) in enumerate(bank_rows):
                    value = (bank_details or {}).get(key) or "[BANK DETAIL REQUIRED]"
                    if key == "ACCOUNT_NUMBER" and value != "[BANK DETAIL REQUIRED]":
                        value += " (USD)"
                    canvas.text(44, panel_top + 25 + index * 9, label, 5.0, True, MUTED)
                    canvas.text(136, panel_top + 25 + index * 9, value, 5.0, key == "ACCOUNT_NUMBER", INK)
                sign_x, sign_width = 398, 179
            else:
                sign_x, sign_width = 398, 179
            canvas.rect(sign_x, bottom, sign_width, 108, (1, 1, 1), PALE, 0.7)
            canvas.text(sign_x + 10, bottom + 17, "AUTHORIZED REPRESENTATIVE", 5.3, True, MUTED)
            canvas.text(sign_x + 10, bottom + 32, issuer_signer(data), 6.3, True, INK)
            canvas.text(sign_x + 10, bottom + 42, issuer_display_name(data) or "TO BE CONFIRMED", 5.8, False, INK)
            if not canvas.image(seal, sign_x + 10, bottom + 47, sign_width - 20, 53):
                raise ValueError("The company seal could not be embedded in the PDF")
            if bottom + 108 > 752:
                raise ValueError("Document content exceeds the reserved footer area; add a page break or shorten the source information")

        canvas.line(35, 778, 577, 778, (0.86, 0.85, 0.82), 0.5)
        footer = f"{footer_label}  |  PAGE {page_index + 1} OF {len(chunks)}"
        if not has_logo:
            canvas.text(468, 788, "LOGO ASSET PENDING", 5.0, True, BRAND_BLUE)
        canvas.text(35, 788, footer, 5.3, False, MUTED)

    return _serialize_trade_pages(canvases)


# 원본: reference/kekorea/Quotation_KEKOREA/agent/pi_pdf.py render_charcoal_gold_pi(뒤쪽 정의)
def render_charcoal_gold_pi(data, bank_details, *, logo=None, seal=None):
    """Backward-compatible name; all documents now share the same branded renderer."""
    data = {**data, "document_type": "PI"}
    return render_trade_document(data, bank_details, logo=logo, seal=seal)
