"""업무 노드가 함께 쓰는 오류·한도 오류 처리(계약 3.2절·4.1절)."""

from app.db.models import utcnow
from app.graph.state import AgentError, AgentState, ToolCallRecord
from app.runlog.logger import current_event
from app.tools.base import ToolResult
from app.tools.fallback import fallback_candidates
from app.tools.registry import TOOLS


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


def call_tool(state: AgentState, node: str, tool: str, payload: dict, summary: dict, *,
              kind_of_reply="general", asks_fields=None) -> tuple[ToolResult, dict]:
    """도구를 `TOOLS`로 부르고 (결과, 상태 업데이트)를 돌려준다(계획 10절에서 더함).

    `tool_call`·`tool_result` 기록(요약에는 본문 대신 길이·키 이름만), `tools_called`·`call_retries`를 채우고,
    실패면 `failure_update`로 한도 오류는 대체 후보, 그 밖은 실패 종료로 보낸다.
    """
    current_event("tool_call", tool=tool, detail=summary)
    result = TOOLS[tool].invoke(payload)
    current_event("tool_result", tool=tool, detail={
        "ok": result.ok, "error_kind": result.error_kind, "value": value_summary(result.value),
        "source": result.source, "attempts": result.attempts,
    })
    record = ToolCallRecord(tool=tool, ok=result.ok, error_kind=result.error_kind,
                            attempts=result.attempts, duration_ms=result.duration_ms)
    retries = max(result.attempts - 1, 0)
    if result.ok:
        return result, {"tools_called": [record], "call_retries": retries, "step_status": "ok"}
    update = failure_update(state, node, result.error_kind or "internal",
                            result.error_message or f"{tool} 도구 실패", kind_of_reply=kind_of_reply,
                            asks_fields=asks_fields, call_retries=retries)
    return result, {**update, "tools_called": [record]}


def retry_feedback(state: AgentState, node: str) -> str | None:
    """성찰이 이 노드를 다시 실행하게 했을 때만 그 오류 이유를 돌려준다."""
    reflection = state["reflection"]
    if reflection and not reflection["passed"] and reflection["retry_target"] == node:
        return reflection["feedback"]
    return None


def value_summary(value) -> dict | None:
    if not isinstance(value, dict):
        return None if value is None else {"type": type(value).__name__}
    summary = {"keys": sorted(value)}
    for key, item in value.items():
        if isinstance(item, list):
            summary[f"{key}_count"] = len(item)
    if isinstance(value.get("missing_fields"), list):
        summary["missing_fields"] = value["missing_fields"]
    return summary
