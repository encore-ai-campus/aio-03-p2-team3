"""check_required: 빠진 필수 항목을 코드로 찾고 거래 항목을 저장한다(계획 10절)."""

from sqlalchemy import select

from app.db.models import DealTerms as DealTermsRow
from app.graph.nodes.common import call_tool, failure_update
from app.graph.state import AgentState
from app.quote.required_fields import get_required_fields
from app.runlog.logger import current_database, current_event

NODE = "check_required"
TOOL = "check_required_fields"


def check_required(state: AgentState) -> dict:
    deal_terms = state["deal_terms"]
    if deal_terms is None:
        return failure_update(state, NODE, "invalid_input", "검토할 거래 항목이 없습니다")
    required = get_required_fields(state["user_id"], deal_terms.get("doc_kind", "quote"))
    keys = [field["key"] for field in required["fields"]]
    current_event("required_source", detail={
        "source": required["source"], "fields": keys, "evidence": required["evidence"],
    })
    result, update = call_tool(state, NODE, TOOL, {"deal_terms": deal_terms, "required_fields": required}, {
        "fields": keys, "items": len(deal_terms["items"]),
        "filled": sorted(k for k, v in deal_terms.items() if k not in ("items", "evidence") and v),
    })
    update["required_fields"] = required
    if not result.ok:
        return update  # 코드 검사라 한도 오류가 없다: 실패 종료
    missing = result.value["missing_fields"]
    update["missing_fields"] = missing
    if missing:
        update["reply_mode"] = "followup"
        current_event("tool_select", tool="draft_followup_replies", detail={
            "reason": f"필수 항목 {len(missing)}개가 빠져 견적서 대신 재질문 후보를 만듦",
            "missing_fields": missing,
        })
    else:
        current_event("tool_select", tool="create_quote", detail={
            "reason": "필수 항목이 모두 있어 견적서를 만듦",
        })
    save_deal_terms(state, deal_terms, missing, required["source"])
    return update


def save_deal_terms(state: AgentState, deal_terms: dict, missing: list[str], source: str):
    """실행마다 한 줄. 성찰로 다시 검토하면 같은 실행의 줄을 고친다."""
    with current_database().session() as session:
        row = session.scalar(select(DealTermsRow).where(
            DealTermsRow.run_id == state["run_id"], DealTermsRow.user_id == state["user_id"],
        ))
        if row is None:
            row = DealTermsRow(user_id=state["user_id"], run_id=state["run_id"],
                               thread_id=state["thread_id"], source_message_id=state["message_id"])
            session.add(row)
        row.terms = deal_terms
        row.missing_fields = missing
        row.required_source = source
