"""extract_deal: 거래 메일에서 거래 항목을 뽑는다(계획 10절)."""

from app.graph.nodes.tool_step import call_tool, rate_limit_update, retry_feedback, select_tool
from app.graph.state import AgentState

NODE = "extract_deal"
TOOL = "extract_deal_terms"


def extract_deal(state: AgentState) -> dict:
    feedback = retry_feedback(state, NODE)
    select_tool(TOOL, "성찰 피드백으로 거래 항목을 다시 추출" if feedback
                else "거래 내용이 있는 메일이라 견적서 필수 항목 검토 전에 거래 항목을 추출")
    context = state["thread_context"]
    result, update = call_tool(NODE, TOOL, {
        "email": state["email"], "thread_context": context, "feedback": feedback,
    }, {
        "body_chars": len(state["email"]["body_text"]),
        "thread_messages": len(context["recent_messages"]) if context else 0,
        "has_summary": bool(context and context.get("summary")),
        "has_feedback": feedback is not None,
    })
    if result.ok:
        update["deal_terms"] = result.value
    elif update["step_status"] == "rate_limit":
        update.update(rate_limit_update(state, "general"))
    return update
