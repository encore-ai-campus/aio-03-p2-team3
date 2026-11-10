from app.tools.base import ToolResult
from app.tools.registry import TOOLS


def test_registered_tools_have_contract_inputs_and_no_business_implementation(email):
    assert set(TOOLS) == {"draft_replies", "extract_deal_terms", "check_required_fields",
                          "draft_followup_replies", "create_quote", "send_email"}
    deal_terms = {"customer_name": None, "items": [], "due_date": None, "contact_name": None,
                  "contact_phone": None, "delivery_place": None, "note": None, "evidence": {}}
    result = TOOLS["create_quote"].invoke({"user_id": 1, "thread_id": "fake-thread", "deal_terms": deal_terms})
    assert isinstance(result, ToolResult)
    assert not result.ok and result.error_kind == "internal" and result.attempts == 0
    send = TOOLS["send_email"].invoke({"user_id": 1, "thread_id": "fake-thread", "to_addrs": [], "subject": "가상", "body": "가상"})
    assert not send.ok and send.attempts == 0


def test_invalid_tool_input_is_a_result():
    result = TOOLS["send_email"].invoke({})
    assert isinstance(result, ToolResult)
    assert not result.ok and result.error_kind == "invalid_input" and result.attempts == 0
