"""업무 노드가 함께 쓰는 오류·한도 오류 처리(계약 3.2절·4.1절)."""

from app.db.models import utcnow
from app.graph.state import AgentError, AgentState
from app.runlog.logger import current_event
from app.tools.fallback import fallback_candidates


def agent_error(node: str, kind: str, message: str) -> AgentError:
    current_event("error", detail={"kind": kind, "message": message})
    return AgentError(node=node, kind=kind, message=message, at=utcnow().isoformat())


def preferences_of(state: AgentState) -> dict:
    return (state["long_term"] or {}).get("preferences") or {}


def failure_update(state: AgentState, node: str, kind: str, message: str, *, kind_of_reply="general",
                   asks_fields=None, call_retries=0) -> dict:
    """한도 오류는 대체 후보로, 그 밖의 오류는 실패 종료로 보낸다."""
    update = {"errors": [agent_error(node, kind, message)], "call_retries": call_retries}
    if kind == "rate_limit":
        update.update(
            step_status="rate_limit", needs_review=True, notice="rate_limit",
            candidates=fallback_candidates(
                state["email"], kind=kind_of_reply, asks_fields=asks_fields,
                preferences=preferences_of(state),
            ),
        )
    else:
        update["step_status"] = "failed"
    return update
