"""draft_replies: 답장 후보 도구를 불러 후보 2~3개를 상태에 둔다(계획 8절 general, 11절 quote)."""

from app.graph.mail.calendar_context import schedule_reply
from app.graph.master.common import failure_update, preferences_of
from app.graph.state import AgentState, ToolCallRecord
from app.runlog.logger import current_event
from app.tools.fallback import reply_subject, with_signature
from app.tools.registry import TOOLS
from app.services.memory import context_for_model


def draft_replies(state: AgentState) -> dict:
    reply_mode = "quote" if state["reply_mode"] == "quote" else "general"
    availability = state.get("calendar_availability")
    knowledge = state.get("knowledge_evidence") or {}
    if state.get("schedule_only") and availability and not state.get("contract_question"):
        notes = (schedule_reply(availability), "미팅 요청 감사합니다. " + schedule_reply(availability))
    elif state.get("contract_question") and (knowledge.get("scope") != "counterparty" or not knowledge.get("clauses")):
        notes = ("문의하신 계약 조건은 적용되는 계약서를 확인한 뒤 안내드리겠습니다.",
                 "문의하신 계약의 문서 번호나 적용 시점을 알려주시면 확인해 회신드리겠습니다.")
    else:
        notes = ()
    if notes:
        if availability and not state.get("schedule_only"):
            notes = tuple(note + "\n\n" + schedule_reply(availability) for note in notes)
        return {"candidates": [
            {"label": label, "subject": reply_subject(state["email"]),
             "body": with_signature(note, preferences_of(state)), "kind": "general",
             "asks_fields": [], "needs_review": False, "notice": None}
            for label, note in zip(("확인 후 회신", "추가 안내"), notes, strict=True)
        ], "reply_mode": "general", "step_status": "ok"}
    reflection = state["reflection"]
    feedback = reflection["feedback"] if reflection and not reflection["passed"] else None
    trade_doc = state["trade_doc_draft"]  # 무역서류 동봉 답장(계약 15.6절)
    current_event("tool_call", tool="draft_replies", detail={
        "reply_mode": reply_mode, "body_chars": len(state["email"]["body_text"] or ""),
        "has_thread_context": state["thread_context"] is not None,
        "has_quote": state["quote_draft"] is not None, "has_feedback": feedback is not None,
        "has_trade_doc": trade_doc is not None,
    })
    result = TOOLS["draft_replies"].invoke({
        "email": state["email"], "thread_context": context_for_model(state),
        "reply_mode": reply_mode, "quote_draft": state["quote_draft"],
        "trade_doc_draft": trade_doc,
        "preferences": preferences_of(state), "feedback": feedback,
    })
    candidates = result.value["candidates"] if result.ok else []
    if availability:
        candidates = [{**candidate, "body": schedule_reply(availability) + "\n\n" + candidate["body"]}
                      for candidate in candidates]
    current_event("tool_result", tool="draft_replies", detail={
        "ok": result.ok, "error_kind": result.error_kind, "candidates": len(candidates),
        "source": result.source, "attempts": result.attempts,
    })
    record = ToolCallRecord(
        tool="draft_replies", ok=result.ok, error_kind=result.error_kind,
        attempts=result.attempts, duration_ms=result.duration_ms,
    )
    retries = max(result.attempts - 1, 0)
    if not result.ok:
        update = failure_update(
            state, "draft_replies", result.error_kind, result.error_message or "답장 후보 실패",
            kind_of_reply=reply_mode, call_retries=retries,
        )
        return {**update, "tools_called": [record], "reply_mode": reply_mode}
    return {
        "candidates": candidates, "reply_mode": reply_mode, "step_status": "ok",
        "tools_called": [record], "call_retries": retries,
    }
