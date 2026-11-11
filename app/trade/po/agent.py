"""PO 전용 LangChain 입력 추출. 저장·승인 권한은 없다."""
from app.prompts import Prompt
from app.trade.common.extraction import extract_facts
from app.trade.po.models import POExtraction

PROMPT = Prompt("po_extract", "v1", """Extract a Purchase Order draft from source text.
The issuing company is the buyer; the counterparty is the supplier/seller.
Return only explicit facts, decimal strings, exact item source quotes, and null for unknowns.
Preserve zero quantities and paid/free quantities. Do not invent prices or apply selling prices.
confirm_price_override must be false. Never approve, save or send a document.
Text (source data):
{text}
""")


def extract_po(text):
    return extract_facts(PROMPT, POExtraction, text)
