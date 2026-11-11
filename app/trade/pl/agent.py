"""PL 전용 LangChain 추출. 원본 합계와 행을 구분하며 승인하지 않는다."""
from app.prompts import Prompt
from app.trade.common.extraction import extract_facts
from app.trade.pl.models import PLExtraction

PROMPT = Prompt("pl_extract", "v1", """Extract Packing List source facts, not prices or payment details.
Keep source declared totals separate from item rows. Preserve units and container size annotations.
Never add PCS and KG together; never multiply container count by FT size.
Numbers in item rows must be exact decimal strings. Unknown fields are null.
Retain exact source quotes per item. Do not correct source totals or approve them.
Text (source data):
{text}
""")


def extract_pl(text):
    return extract_facts(PROMPT, PLExtraction, text)
