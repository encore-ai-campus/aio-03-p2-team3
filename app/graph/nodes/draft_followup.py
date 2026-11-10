"""draft_followup: 빠진 필수 항목을 묻는 재질문 후보를 만든다(계획 10절)."""

from app.graph.nodes.common import call_tool, failure_update, preferences_of, retry_feedback
from app.graph.state import AgentState
from app.quote.required_fields import FIELD_LABELS

NODE = "draft_followup"
TOOL = "draft_followup_replies"


def draft_followup(state: AgentState) -> dict:
    missing = state["missing_fields"]
    if not missing or state["deal_terms"] is None:
        return failure_update(state, NODE, "invalid_input", "재질문할 빠진 필수 항목이 없습니다")
    labels = dict(FIELD_LABELS)
    if state["required_fields"]:
        labels.update({field["key"]: field["label"] for field in state["required_fields"]["fields"]})
    feedback = retry_feedback(state, NODE)
    result, update = call_tool(state, NODE, TOOL, {
        "email": state["email"], "thread_context": state["thread_context"],
        "deal_terms": state["deal_terms"], "missing_fields": missing,
        "field_labels": {key: labels.get(key, key) for key in missing},
        "preferences": preferences_of(state), "feedback": feedback,
    }, {
        "missing_fields": missing, "body_chars": len(state["email"]["body_text"] or ""),
        "has_feedback": feedback is not None,
    }, kind_of_reply="followup", asks_fields=missing)
    if result.ok:
        update.update({"candidates": result.value["candidates"], "needs_review": False, "notice": None})
    return update
