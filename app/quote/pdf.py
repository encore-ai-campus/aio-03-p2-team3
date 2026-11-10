"""서버에 포함한 NanumGothic TTF를 부분 포함하는 PDF. 임시 파일은 만들지 않는다."""

from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos


def money(value) -> str:
    return "단가 입력 필요" if value is None else f"{value:,}원"


def render_quote_pdf(quote_draft: dict) -> bytes:
    pdf = FPDF()
    pdf.add_font("NanumGothic", fname=Path(__file__).parent / "fonts" / "NanumGothic-Regular.ttf")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("NanumGothic", size=11)

    def text(value):
        pdf.multi_cell(0, 8, text=str(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT,
                       wrapmode="CHAR")

    text("견적서")
    text(f"견적번호: {quote_draft['quote_no']}")
    text(f"견적일: {quote_draft['quote_date']} / 유효기간: {quote_draft['valid_until']}")
    text(f"거래처: {quote_draft['customer_name']}")
    supplier = quote_draft["supplier"]
    for key, label in (("company_name", "공급자"), ("business_no", "사업자번호"),
                       ("ceo_name", "대표자"), ("contact", "연락처")):
        text(f"{label}: {supplier.get(key) or '미입력'}")
    pdf.ln(4)
    for index, line in enumerate(quote_draft["lines"], 1):
        text(f"{index}. {line['item_name']} / 수량 {line['quantity']}{line.get('unit') or ''}")
        text(f"단가 {money(line['unit_price'])} / 금액 {money(line['amount'])}")
    pdf.ln(4)
    text(f"공급가액: {money(quote_draft['supply_amount'])}")
    text(f"부가세(10%, 1원 미만 버림): {money(quote_draft['vat'])}")
    text(f"합계: {money(quote_draft['total'])}")
    if quote_draft["missing_prices"]:
        text("미완성 견적서: 단가 입력 후 합계가 확정됩니다.")
    return bytes(pdf.output())
