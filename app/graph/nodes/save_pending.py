"""종료 이유만 정하는 틀. 후보·처리 상태 저장은 8·9에서 구현한다."""

from app.graph.state import AgentState


def save_pending(state: AgentState) -> dict:
    return {"end_reason": "followup_question" if state["reply_mode"] == "followup" else "awaiting_approval"}
