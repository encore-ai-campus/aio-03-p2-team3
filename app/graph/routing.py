"""状態は読むだけ。業務ノードは後続の作業で埋める。"""

from langgraph.graph import END

from app.graph.state import AgentState


def route_after_analyze(state: AgentState) -> str:
    if state["step_status"] == "failed":
        return "finish_failed"
    if state["step_status"] == "rate_limit":
        return "save_pending"
    return {"general": "draft_replies", "deal": "extract_deal", "ignore": END}.get(
        state["intent"], "finish_failed"
    )


def route_after_extract(state: AgentState) -> str:
    return {"ok": "check_required", "rate_limit": "save_pending"}.get(
        state["step_status"], "finish_failed"
    )


def route_after_check(state: AgentState) -> str:
    if state["step_status"] != "ok":
        return "finish_failed"
    return "draft_followup" if state["missing_fields"] else "make_quote"


def route_after_quote(state: AgentState) -> str:
    return "draft_replies" if state["step_status"] == "ok" else "finish_failed"


def route_after_draft(state: AgentState) -> str:
    if state["step_status"] == "failed":
        return "finish_failed"
    if state["step_status"] == "rate_limit" or not state["reflection_enabled"]:
        return "save_pending"
    return "reflect"


def route_after_reflect(state: AgentState) -> str:
    reflection = state["reflection"]
    if not reflection or reflection["passed"] or reflection["strategy"] == "fallback":
        return "save_pending"
    target = reflection["retry_target"]
    if target in {"extract_deal", "draft_replies", "draft_followup", "make_quote"}:
        return target
    return "save_pending"
