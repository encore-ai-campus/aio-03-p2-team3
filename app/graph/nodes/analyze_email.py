"""analyze_email: LLM 한 번으로 의도를 정하고 다음 도구와 그 이유를 남긴다(계획 8절, R-02·R-04)."""

from typing import Literal

from pydantic import BaseModel, Field

from app.graph.nodes.common import failure_update
from app.graph.state import AgentState
from app.llm.client import call_structured
from app.prompts.analyze_email import PROMPT
from app.prompts.format import email_text, thread_context_text
from app.runlog.logger import current_event
from app.services.memory import context_for_model

NEXT_TOOL = {"general": "draft_replies", "deal": "extract_deal_terms", "ignore": None}


class EmailAnalysis(BaseModel):
    intent: Literal["general", "deal", "ignore"]
    reason: str = Field(min_length=1, description="판단 근거 한 문장")


def analyze_email(state: AgentState) -> dict:
    # load_memory의 고정 다음 노드. 기억 조회·요약 실패를 덮어쓰지 않는다.
    if state["step_status"] != "ok":
        return {}
    result = call_structured(PROMPT, EmailAnalysis, {
        "thread_context": thread_context_text(context_for_model(state)),
        "email": email_text(state["email"]),
    })
    retries = max(result.attempts - 1, 0)
    if not result.ok:
        return failure_update(
            state, "analyze_email", result.error_kind,
            f"메일 분석 LLM 호출 실패 ({result.error_kind})", call_retries=retries,
        )
    intent = result.value.intent
    selected = NEXT_TOOL[intent]
    reason = result.value.reason.strip()
    update = {
        "intent": intent, "selected_tool": selected, "tool_reason": reason,
        "step_status": "ok", "call_retries": retries,
    }
    if intent == "general":
        update["reply_mode"] = "general"
    elif intent == "ignore":
        update["end_reason"] = "ignored"
    if selected:
        current_event("tool_select", tool=selected, detail={"reason": reason, "intent": intent})
    return update
