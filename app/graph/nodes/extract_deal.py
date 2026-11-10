"""extract_deal: 거래 메일에서 거래 항목을 뽑는다(계획 10절).

도구 선택(`tool_select`)은 `analyze_email`이 의도를 정하며 남긴다.
"""

from app.graph.nodes.common import call_tool, retry_feedback
from app.graph.state import AgentState

NODE = "extract_deal"
TOOL = "extract_deal_terms"


def extract_deal(state: AgentState) -> dict:
    feedback = retry_feedback(state, NODE)
    context = state["thread_context"]
    result, update = call_tool(state, NODE, TOOL, {
        "email": state["email"], "thread_context": context, "feedback": feedback,
    }, {
        "body_chars": len(state["email"]["body_text"] or ""),
        "thread_messages": len(context["recent_messages"]) if context else 0,
        "has_summary": bool(context and context.get("summary")),
        "has_feedback": feedback is not None,
    }, kind_of_reply="general")
    if result.ok:
        update["deal_terms"] = result.value
    return update
