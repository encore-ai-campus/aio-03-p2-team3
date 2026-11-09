"""draft_replies: 업무 동작은 후속 하위 작업에서 채운다."""

from app.graph.state import AgentState


def draft_replies(state: AgentState) -> dict:
    # LangGraph의 부분 업데이트: 빈 dict는 입력 상태를 그대로 유지한다.
    return {}
