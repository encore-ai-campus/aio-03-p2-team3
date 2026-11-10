"""노드는 이 목록을 통해서만 도구를 호출한다."""

from app.tools.draft_replies import draft_replies
from app.tools.extract_deal_terms import extract_deal_terms
from app.tools.check_required_fields import check_required_fields
from app.tools.draft_followup_replies import draft_followup_replies
from app.tools.create_quote import create_quote
from app.tools.create_trade_document import create_trade_document
from app.tools.send_email import send_email
from app.tools.base import invalid_input_result

TOOLS = {
    "draft_replies": draft_replies,
    "extract_deal_terms": extract_deal_terms,
    "check_required_fields": check_required_fields,
    "draft_followup_replies": draft_followup_replies,
    "create_quote": create_quote,
    "create_trade_document": create_trade_document,
    "send_email": send_email,
}

for registered_tool in TOOLS.values():
    registered_tool.handle_validation_error = invalid_input_result
