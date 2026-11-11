"""KE Korea blue-brand Proforma Invoice PDF layout with PI-only bank details."""
from io import BytesIO
from pathlib import Path
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


def _pdf_escape(value):
    return str(value).encode("ascii", "replace").decode("ascii").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


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

    def image(self, path, x, top, max_w, max_h, *, watermark=False, crop_box=None):
        if not path or not Path(path).is_file():
            return False
        try:
            width, height, pixels = _read_png_rgb(Path(path))
            if crop_box:
                crop_x, crop_y, crop_w, crop_h = crop_box
                pixels = _crop_rgb(pixels, width, height, crop_x, crop_y, crop_w, crop_h)
                width, height = crop_w, crop_h
            raw = zlib.compress(pixels, level=9)
        except Exception as exc:
            raise ValueError(f"Could not load PI brand PNG: {Path(path).name}") from exc
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


def _read_png_rgb(path):
    """Decode common 8-bit RGB/RGBA PNGs using only the Python standard library."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Expected PNG")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", data[16:29])
    if depth != 8 or color not in (2, 6) or interlace != 0:
        raise ValueError("Only non-interlaced 8-bit RGB/RGBA PNGs are supported")
    pos, chunks = 8, []
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos+4])[0]
        kind = data[pos+4:pos+8]
        payload = data[pos+8:pos+8+length]
        if kind == b"IDAT": chunks.append(payload)
        pos += 12 + length
        if kind == b"IEND": break
    bpp = 3 if color == 2 else 4
    scan = zlib.decompress(b"".join(chunks))
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


def _crop_rgb(pixels, width, height, x, y, crop_w, crop_h):
    if min(x,y,crop_w,crop_h)<0 or x+crop_w>width or y+crop_h>height:
        raise ValueError("PNG crop is outside the image")
    row_bytes=crop_w*3
    return b"".join(pixels[((y+line)*width+x)*3:((y+line)*width+x)*3+row_bytes] for line in range(crop_h))


def _wrap(value, width):
    return textwrap.wrap(str(value or ""), width=width, break_long_words=True, break_on_hyphens=False) or [""]


def _draw_party_detail(canvas, x, top, label, value, *, size=7.1, value_offset=62, width=48, leading=9):
    """Draw labels in a fixed column and values from one shared start position."""
    value = str(value or "Not provided")
    lines = _wrap(value, width)
    value_x = x + value_offset
    canvas.text(x, top, label + ":", size, False, INK)
    canvas.text(value_x, top, lines[0], size, False, INK)
    for offset, line in enumerate(lines[1:], 1):
        canvas.text(value_x, top + offset * leading, line, size, False, INK)
    return top + len(lines) * leading


def _money(value):
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return str(value or "0.00")


def render_charcoal_gold_pi(data, bank_details, *, logo_path=None, seal_path=None):
    """Render a one-page premium PI. Bank information is deliberately PI-only."""
    canvas = _Canvas()
    # Use the supplied logo in the header; omit the obscured body watermark.
    canvas.rect(0, 0, PAGE_W, PAGE_H, (1, 1, 1))

    # Header and document identity
    canvas.rect(0, 0, PAGE_W, 116, (1, 1, 1))
    canvas.rect(0, 116, PAGE_W, 3, BRAND_BLUE)
    has_logo = canvas.image(logo_path, 39, 5, 230, 106, watermark=False,
                            crop_box=(290, 145, 1190, 620))
    canvas.text(383, 48, "PROFORMA INVOICE", 15, True, NAVY)
    canvas.rect(383, 63, 190, 24, MID_BLUE)
    pi_number = str(data.get("document_number") or "DRAFT - TBD").strip()
    canvas.text(396, 79, "PI NO.  " + pi_number, 7, True, (0.90, 0.95, 0.99))

    canvas.text(40, 143, "PI NUMBER", 6.5, True, MUTED)
    canvas.text(40, 158, data.get("document_number") or "DRAFT", 9, True, INK)
    canvas.text(190, 143, "ISSUE DATE", 6.5, True, MUTED)
    canvas.text(190, 158, data.get("issue_date") or "TO CONFIRM", 8.5, True, INK)
    canvas.text(357, 143, "CURRENCY", 6.5, True, MUTED)
    canvas.text(357, 158, data.get("currency") or "USD", 8.5, True, INK)
    canvas.text(472, 143, "VALIDITY", 6.5, True, MUTED)
    canvas.text(472, 158, "TO CONFIRM", 7.5, True, WARNING)

    # Seller and buyer panels
    panel_top, panel_h = 174, 153
    canvas.rect(38, panel_top, 261, panel_h, (1, 1, 1), PALE, 0.8)
    canvas.rect(313, panel_top, 261, panel_h, (1, 1, 1), PALE, 0.8)
    canvas.line(38, panel_top, 299, panel_top, BRAND_BLUE, 1.4)
    canvas.line(313, panel_top, 574, panel_top, BRAND_BLUE, 1.4)
    seller = data.get("seller") or {}
    buyer = data.get("buyer") or {}
    canvas.text(50, 192, "SELLER", 6.8, True, BRAND_BLUE)
    canvas.text(50, 211, str(seller.get("legal_name") or "KE KOREA CO. LTD"), 9.5, True)
    seller_y = 227
    for label, value in (
        ("Address", seller.get("address")),
        ("Tel", seller.get("phone")),
        ("Email", seller.get("email")),
        ("Representative", re.sub(r"^\s*representative\s*:\s*", "", str(seller.get("contact") or "[AUTHORIZED SIGNER]"), flags=re.I)),
    ):
        seller_y = _draw_party_detail(canvas, 50, seller_y, label, value)

    canvas.text(325, 192, "BUYER", 6.8, True, BRAND_BLUE)
    canvas.text(325, 211, str(buyer.get("legal_name") or "Not provided"), 9.5, True)
    buyer_y = 227
    for label, value in (
        ("Address", buyer.get("address")),
        ("Tel", buyer.get("phone")),
        ("Email", buyer.get("email")),
        ("Representative", buyer.get("contact")),
    ):
        buyer_y = _draw_party_detail(canvas, 325, buyer_y, label, value)
    if buyer.get("registration_details"):
        buyer_y = _draw_party_detail(canvas, 325, buyer_y, "Registration", buyer["registration_details"])

    # Trade terms
    terms_top = 340
    canvas.rect(38, terms_top, 536, 45, PALE)
    canvas.text(51, terms_top+14, "DELIVERY TERM", 6.2, True, MUTED)
    canvas.text(51, terms_top+31, data.get("incoterms") or "TO CONFIRM", 8, True)
    canvas.line(213, terms_top+8, 213, terms_top+37, (0.83,0.82,0.79), 0.6)
    canvas.text(229, terms_top+14, "PAYMENT", 6.2, True, MUTED)
    canvas.text(229, terms_top+31, data.get("payment_terms") or "TO CONFIRM", 7.6, True)
    canvas.line(394, terms_top+8, 394, terms_top+37, (0.83,0.82,0.79), 0.6)
    canvas.text(410, terms_top+14, "EST. CONTAINER LOAD", 6.2, True, MUTED)
    canvas.text(410, terms_top+31, "APPROX. 5", 8, True)

    # Item table
    table_top = 404
    canvas.text(38, table_top, "PRODUCT & PRICING", 7, True, BRAND_BLUE)
    canvas.rect(38, table_top+10, 536, 23, NAVY)
    for x, label in ((49,"DESCRIPTION"),(274,"QUANTITY"),(369,"UNIT PRICE"),(481,"AMOUNT")):
        canvas.text(x, table_top+25, label, 6.3, True, (1,1,1))
    canvas.rect(38, table_top+33, 536, 50, PALE)
    item = (data.get("items") or [{}])[0]
    canvas.text(49, table_top+53, item.get("product_name") or "M10R Yingfa Renhui Solar Cell", 8.2, True)
    canvas.text(49, table_top+70, "Cell type: M10R  |  Price basis: per Wp", 6.6, False, MUTED)
    canvas.text(274, table_top+54, "100 MW", 8, True)
    canvas.text(274, table_top+70, "100,000,000 Wp", 6.1, False, MUTED)
    canvas.text(369, table_top+54, "USD 0.047", 7.7, True)
    canvas.text(369, table_top+70, "per Wp", 6.1, False, MUTED)
    canvas.text(481, table_top+54, _money(data.get("total")), 7.3, True)
    canvas.text(481, table_top+70, "USD", 6.1, False, MUTED)

    # Totals and status notes
    total_top = 504
    canvas.text(38, total_top+14, "100 MW = 100,000,000 Wp", 7, False, MUTED)
    canvas.text(38, total_top+29, "FOUR MILLION SEVEN HUNDRED THOUSAND US DOLLARS ONLY", 7.3, True, INK)
    canvas.rect(360, total_top-2, 214, 49, NAVY)
    canvas.text(376, total_top+14, "TOTAL AMOUNT (USD)", 6.3, True, (0.73,0.87,0.98))
    canvas.text(376, total_top+35, _money(data.get("total")), 14, True, (1,1,1))

    warnings = data.get("conflicts") or data.get("missing_fields") or []
    warning_text = str(warnings[0]) if warnings else "Review all commercial and packing details before issue."
    if len(warning_text) > 92:
        warning_text = warning_text[:89] + "..."
    shipping_note = str(data.get("remarks") or "Confirm loading quantity against final packing specifications.")
    if len(shipping_note) > 92:
        shipping_note = shipping_note[:89] + "..."
    canvas.rect(38, 562, 536, 41, (1.0,0.97,0.94))
    canvas.rect(38, 562, 4, 41, WARNING)
    canvas.text(51, 576, "REVIEW REQUIRED BEFORE ISSUE", 6.3, True, WARNING)
    canvas.text(51, 589, warning_text, 6.0)
    canvas.text(51, 599, shipping_note, 6.0)

    # PI-only USD beneficiary details
    canvas.rect(38, 613, 340, 103, (1,1,1), PALE, 0.8)
    canvas.rect(38, 613, 340, 19, PALE)
    canvas.text(49, 627, "USD BANK INFORMATION", 6.5, True, BRAND_BLUE)
    labels = ["BENEFICIARY", "BANK NAME", "BRANCH NAME", "SWIFT CODE", "ACCOUNT NUMBER", "BANK ADDRESS"]
    keys = ["BENEFICIARY", "BANK_NAME", "BRANCH", "SWIFT", "ACCOUNT_NUMBER", "BANK_ADDRESS"]
    for i,(label,key) in enumerate(zip(labels,keys)):
        y=644+i*11
        canvas.text(49,y,label,5.7,True,MUTED)
        val = (bank_details or {}).get(key) or "[CONFIGURE BANK DETAILS]"
        if key == "ACCOUNT_NUMBER" and val != "[CONFIGURE BANK DETAILS]":
            val += " (USD)"
        canvas.text(156,y,val,6.0,key=="ACCOUNT_NUMBER",INK if key!="ACCOUNT_NUMBER" else WARNING)

    # Authorized representative and reserved company seal/logo image
    canvas.rect(392, 613, 182, 103, (1,1,1), PALE, 0.8)
    canvas.text(404, 630, "AUTHORIZED REPRESENTATIVE", 6.0, True, MUTED)
    canvas.text(404, 648, "[AUTHORIZED SIGNER]", 7.5, True, INK)
    if not canvas.image(seal_path, 440, 657, 120, 54, watermark=False):
        canvas.rect(398, 654, 170, 58, None, BRAND_BLUE, 0.7)
        canvas.text(441, 686, "COMPANY SEAL", 6.2, True, BRAND_BLUE)

    canvas.line(38, 754, 574, 754, (0.86,0.85,0.82), 0.6)
    canvas.text(38, 770, "DRAFT - NOT FOR ISSUE  |  REVIEW ALL COMMERCIAL AND SHIPPING DETAILS", 6.0, False, MUTED)
    if not has_logo:
        canvas.text(455, 770, "LOGO ASSET PENDING", 5.5, True, BRAND_BLUE)

    # PDF object tree, including the image states used for embedded brand assets.
    image_count = len(canvas.images)
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [" + str(9+image_count).encode() + b" 0 R] /Count 1 >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
               b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /UniGB-UCS2-H /DescendantFonts [6 0 R] >>",
               b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light /CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> /DW 1000 >>",
               b"<< /Type /ExtGState /ca 0.075 /CA 0.075 >>",
               b"<< /Type /ExtGState /ca 1 /CA 1 >>"]
    image_ids=[]
    for image in canvas.images:
        image_ids.append(len(objects)+1)
        raw=image["bytes"]
        objects.append(b"<< /Type /XObject /Subtype /Image /Width "+str(image["width"]).encode()+b" /Height "+str(image["height"]).encode()+b" /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length "+str(len(raw)).encode()+b" >>\nstream\n"+raw+b"\nendstream")
    page_id=len(objects)+1
    content_id=page_id+1
    xobjects=" ".join(f"/Im{i+1} {oid} 0 R" for i,oid in enumerate(image_ids))
    resource=(f"<< /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> /ExtGState << /GS1 7 0 R /GS2 8 0 R >> /XObject << {xobjects} >> >>")
    objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources {resource} /Contents {content_id} 0 R >>".encode())
    stream=("\n".join(canvas.commands)+"\n").encode("ascii")
    objects.append(b"<< /Length "+str(len(stream)).encode()+b" >>\nstream\n"+stream+b"endstream")
    output=bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"); offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(output)); output.extend(f"{i} 0 obj\n".encode()+obj+b"\nendobj\n")
    xref=len(output); output.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]: output.extend(f"{offset:010} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


def _document_title(document_type):
    return {"PO": "PURCHASE ORDER", "PI": "PROFORMA INVOICE",
            "CI": "COMMERCIAL INVOICE", "PL": "PACKING LIST"}.get(document_type, "TRADE DOCUMENT")


def _format_quantity(value):
    try:
        rendered = format(Decimal(str(value)), ",f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
    except (InvalidOperation, TypeError, ValueError):
        return str(value or "-")


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


def _formatted_money(value, currency):
    try:
        amount = Decimal(str(value)).quantize(Decimal("1") if currency == "KRW" else Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return "TO BE CONFIRMED"
    if currency == "USD":
        return "$" + f"{amount:,.2f}"
    return f"{currency} {amount:,.0f}" if currency == "KRW" else f"{currency} {amount:,.2f}"


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


def render_trade_document(data, bank_details=None, *, logo_path=None, seal_path=None):
    """Render all trade documents with measured rows, safe footer space, and automatic pagination."""
    if not seal_path or not Path(seal_path).is_file():
        raise ValueError("KE KOREA company seal is required to create a trade-document PDF")
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

    logo_path = Path(logo_path) if logo_path else None
    seal_path = Path(seal_path) if seal_path else None
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
    issue_date = current_issue_date()
    number_label = {"PI": "INVOICE #", "CI": "INVOICE #", "PO": "PO #", "PL": "PACKING LIST #"}.get(doc_type, "DOCUMENT #")

    for page_index, page_rows in enumerate(chunks):
        canvas = _Canvas()
        canvases.append(canvas)
        canvas.rect(0, 0, PAGE_W, PAGE_H, (1, 1, 1))
        canvas.rect(0, 0, PAGE_W, 94, (1, 1, 1))
        canvas.rect(0, 91, PAGE_W, 3, BRAND_BLUE)
        has_logo = canvas.image(logo_path, 30, 4, 235, 84, crop_box=(290, 145, 1190, 620))
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
                from .packing import reconcile_packing
                packing = reconcile_packing(data)
                calculated = packing["calculated"]
                packages = data.get("packages") or []
                package_lines = []
                package_total = calculated.get("package_count") or data.get("actual_package_count")
                package_lines.append("TOTAL PACKAGES: " + (_format_quantity(package_total) if package_total else "TO BE CONFIRMED") +
                                     "  |  CONTAINERS: " + str(data.get("container_count") or "TO BE CONFIRMED"))
                try:
                    net = calculated.get("net_weight_kg") or data.get("declared_net_weight_kg")
                    gross = calculated.get("gross_weight_kg") or data.get("declared_gross_weight_kg")
                    if packages and not net and not gross:
                        net = str(sum(Decimal(str(p.get("net_weight_kg") or 0)) for p in packages))
                        gross = str(sum(Decimal(str(p.get("gross_weight_kg") or 0)) for p in packages))
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
            canvas.text(sign_x + 10, bottom + 32, "[AUTHORIZED SIGNER]", 6.3, True, INK)
            canvas.text(sign_x + 10, bottom + 42, "KE KOREA CO. LTD", 5.8, False, INK)
            if not canvas.image(seal_path, sign_x + 10, bottom + 47, sign_width - 20, 53):
                raise ValueError("KE KOREA company seal could not be embedded in the PDF")
            if bottom + 108 > 752:
                raise ValueError("Document content exceeds the reserved footer area; add a page break or shorten the source information")

        canvas.line(35, 778, 577, 778, (0.86, 0.85, 0.82), 0.5)
        footer = f"DRAFT - NOT FOR ISSUE  |  PAGE {page_index + 1} OF {len(chunks)}"
        if not has_logo:
            canvas.text(468, 788, "LOGO ASSET PENDING", 5.0, True, BRAND_BLUE)
        canvas.text(35, 788, footer, 5.3, False, MUTED)

    return _serialize_trade_pages(canvases)


def render_charcoal_gold_pi(data, bank_details, *, logo_path=None, seal_path=None):
    """Backward-compatible name; all documents now share the same branded renderer."""
    data = {**data, "document_type": "PI"}
    return render_trade_document(data, bank_details, logo_path=logo_path, seal_path=seal_path)
