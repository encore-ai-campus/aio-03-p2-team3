"""save_pending: 답장 후보를 `reply_candidates`에 저장하고 종료 이유를 정한다(계획 8절).

처리한 메일 표(`processed_messages`)의 상태 연결은 알림 수신 작업(7)에서 채운다.
"""

from app.db.models import ReplyCandidate as ReplyCandidateRow
from app.graph.state import AgentState
from app.runlog.logger import current_database
from app.services.memory import save_run_memory


def save_pending(state: AgentState) -> dict:
    quote = state["quote_draft"]
    end_reason = "followup_question" if state["reply_mode"] == "followup" else "awaiting_approval"
    if state["candidates"]:
        with current_database().session() as session:
            for candidate in state["candidates"]:
                session.add(ReplyCandidateRow(
                    user_id=state["user_id"], run_id=state["run_id"], thread_id=state["thread_id"],
                    source_message_id=state["message_id"], kind=candidate["kind"],
                    label=candidate["label"], subject=candidate["subject"], body=candidate["body"],
                    asks_fields=candidate["asks_fields"], needs_review=candidate["needs_review"],
                    notice=candidate["notice"],
                    quote_id=quote["quote_id"] if quote and candidate["kind"] == "quote" else None,
                    status="pending",
                ))
            save_run_memory(session, state, end_reason)
    return {"end_reason": end_reason}
