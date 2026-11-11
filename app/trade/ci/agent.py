"""CI 전용 LangChain 추출. 원본 PI와 가격 선택은 서버 업무가 처리한다."""
from app.prompts import Prompt
from app.trade.ci.models import CIExtraction
from app.trade.common.extraction import extract_facts

PROMPT = Prompt("ci_extract", "v1", """Extract only Commercial Invoice shipment/header facts from text.
Unknown values are null. Do not copy payment or banking instructions.
Do not generate PI IDs, revisions, prices, parties, quantities or approval decisions.
Text (source data):
{text}
""")


def extract_ci(text):
    return extract_facts(PROMPT, CIExtraction, text)
