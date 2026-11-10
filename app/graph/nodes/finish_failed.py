"""실패 종료. 처리한 메일 표와의 연결은 알림 수신 작업에서 채운다."""

from app.graph.state import AgentState


def finish_failed(state: AgentState) -> dict:
    return {"end_reason": "failed", "step_status": "failed"}
