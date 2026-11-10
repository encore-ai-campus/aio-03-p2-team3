"""노드가 도구를 부를 때 쓰는 공통 절차.

도구 호출 앞뒤를 실행 기록에 남기고(8.1절 `tool_select`·`tool_call`·`tool_result`),
`ToolResult`를 상태 업데이트(`tools_called`·`call_retries`·`step_status`·`errors`)로 옮긴다.
한도 오류는 계약 3.2절대로 기본 답장 틀 후보 1개로 대체한다.
"""

from app.db.models import utcnow
from app.graph.state import AgentState
from app.runlog.logger import current_event
from app.tools.base import ToolResult
from app.tools.fallback import fallback_candidates
from app.tools.registry import TOOLS


def select_tool(tool: str, reason: str):
    current_event("tool_select", tool=tool, detail={"reason": reason})


def call_tool(node: str, tool: str, payload: dict, summary: dict) -> tuple[ToolResult, dict]:
    """도구를 부르고 (결과, 상태 업데이트)를 돌려준다. 요약에는 본문 대신 길이·키 이름만 넣는다."""
    current_event("tool_call", tool=tool, detail=summary)
    result = TOOLS[tool].invoke(payload)
    current_event("tool_result", tool=tool, detail={
        "ok": result.ok, "error_kind": result.error_kind, "value": value_summary(result.value),
        "source": result.source, "attempts": result.attempts,
    })
    update = {
        "tools_called": [{
            "tool": tool, "ok": result.ok, "error_kind": result.error_kind,
            "attempts": result.attempts, "duration_ms": result.duration_ms,
        }],
        "call_retries": max(result.attempts - 1, 0),
        "step_status": "ok",
    }
    if not result.ok:
        update.update(failure_update(node, result.error_kind or "internal",
                                     result.error_message or "도구 실행 실패"))
        update["step_status"] = "rate_limit" if result.error_kind == "rate_limit" else "failed"
    return result, update


def failure_update(node: str, kind: str, message: str) -> dict:
    current_event("error", detail={"kind": kind, "message": message})
    return {"step_status": "failed", "errors": [{
        "node": node, "kind": kind, "message": message, "at": utcnow().isoformat(),
    }]}


def rate_limit_update(state: AgentState, reply_mode: str) -> dict:
    """한도 오류: 기본 답장 틀 후보 1개 + '확인 필요' 표시. 성찰은 건너뛴다(라우팅)."""
    return {
        "candidates": fallback_candidates(reply_mode, state["email"]),
        "needs_review": True, "notice": "rate_limit", "step_status": "rate_limit",
    }


def retry_feedback(state: AgentState, node: str) -> str | None:
    """성찰이 이 노드를 다시 실행하게 했으면 그 오류 이유를 프롬프트에 더한다."""
    reflection = state["reflection"]
    if reflection and not reflection["passed"] and reflection["retry_target"] == node:
        return reflection["feedback"]
    return None


def value_summary(value) -> dict | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        summary = {"keys": sorted(value)}
        for key, item in value.items():
            if isinstance(item, list):
                summary[f"{key}_count"] = len(item)
        if isinstance(value.get("missing_fields"), list):
            summary["missing_fields"] = value["missing_fields"]
        return summary
    return {"type": type(value).__name__}
