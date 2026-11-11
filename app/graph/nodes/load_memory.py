"""load_memory: 단기·장기 기억을 읽고 긴 스레드를 요약한다(계획 13절)."""

from app.graph.nodes.common import failure_update
from app.graph.state import AgentState
from app.runlog.logger import current_database
from app.services.memory import SummaryFailed, load_memories


def load_memory(state: AgentState) -> dict:
    try:
        return load_memories(current_database(), user_id=state["user_id"], email=state["email"])
    except SummaryFailed as error:
        result = error.result
        return failure_update(
            state, "load_memory", result.error_kind, "스레드 요약을 만들지 못했습니다",
            call_retries=max(result.attempts - 1, 0),
        )
