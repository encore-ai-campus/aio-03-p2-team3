"""draft_followup: 빠진 필수 항목을 묻는 재질문 후보를 만든다(계획 10절)."""

from app.graph.nodes.tool_step import (
    call_tool, failure_update, rate_limit_update, retry_feedback, select_tool,
)
from app.graph.state import AgentState
from app.quote.required_fields import FIELD_LABELS

NODE = "draft_followup"
TOOL = "draft_followup_replies"


def draft_followup(state: AgentState) -> dict:
    missing = state["missing_fields"]
    if not missing or state["deal_terms"] is None:
        return failure_update(NODE, "invalid_input", "재질문할 빠진 필수 항목이 없습니다")
    required = state["required_fields"]
    labels = dict(FIELD_LABELS)
    if required:
        labels.update({field["key"]: field["label"] for field in required["fields"]})
    feedback = retry_feedback(state, NODE)
    select_tool(TOOL, f"필수 항목 {len(missing)}개가 빠져 견적서 대신 재질문 후보를 만듦")
    long_term = state["long_term"]
    result, update = call_tool(NODE, TOOL, {
        "email": state["email"], "thread_context": state["thread_context"],
        "deal_terms": state["deal_terms"], "missing_fields": missing,
        "field_labels": {key: labels.get(key, key) for key in missing},
        "preferences": long_term["preferences"] if long_term else {},
        "feedback": feedback,
    }, {"missing_fields": missing, "body_chars": len(state["email"]["body_text"]),
        "has_feedback": feedback is not None})
    if result.ok:
        update.update({"candidates": result.value["candidates"], "needs_review": False, "notice": None})
    elif update["step_status"] == "rate_limit":
        update.update(rate_limit_update(state, "followup"))
    return update
