"""extract_deal: 거래 메일에서 거래 항목을 뽑는다(계획 10절, 계약 15.6절 확장).

도구 선택(`tool_select`)은 `analyze_email`이 의도를 정하며 남긴다.
무역 경로의 거래처 자동 채움[임시: 협의 5·6]을 위해 거래처 프로필(`counterparties` 표,
계약 15.7절)과 발행 회사 설정(`long_term.company`)을 도구에 넘긴다(계약 15.6절).
"""

from sqlalchemy import select

from app.db.models import Counterparty
from app.graph.master.common import call_tool, retry_feedback
from app.graph.state import AgentState
from app.runlog.logger import current_database
from app.services.memory import context_for_model

NODE = "extract_deal"
TOOL = "extract_deal_terms"

PROFILE_FIELDS = ("company_key", "legal_name", "aliases", "address", "contact", "phone",
                  "email", "registration_details", "default_ship_to", "ship_to_phone")


def counterparty_profiles(user_id: int) -> list[dict]:
    """거래처 프로필 목록. 등록된 거래처가 없으면 빈 목록(자동 채움 없이 재질문으로 넘긴다)."""
    with current_database().session() as session:
        rows = session.scalars(select(Counterparty).where(Counterparty.user_id == user_id))
        return [{field: getattr(row, field) for field in PROFILE_FIELDS} for row in rows]


def extract_deal(state: AgentState) -> dict:
    feedback = retry_feedback(state, NODE)
    context = state["thread_context"]
    profiles = counterparty_profiles(state["user_id"])
    result, update = call_tool(state, NODE, TOOL, {
        "email": state["email"], "thread_context": context_for_model(state), "feedback": feedback,
        "user_id": state["user_id"],
        "counterparties": profiles,
        "company": (state["long_term"] or {}).get("company"),
    }, {
        "body_chars": len(state["email"]["body_text"] or ""),
        "thread_messages": len(context["recent_messages"]) if context else 0,
        "has_summary": bool(context and context.get("summary")),
        "has_feedback": feedback is not None,
        "counterparties": len(profiles),
    }, kind_of_reply="general")
    if result.ok:
        update["deal_terms"] = result.value
    return update
