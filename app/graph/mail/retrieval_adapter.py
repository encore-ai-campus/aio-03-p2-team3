"""수신 분류 뒤 일정과 문서 검색 근거를 준비한다."""
from collections.abc import Callable
from functools import partial

from app.graph.mail.calendar_context import AvailabilityReader, check_mail_availability
from app.graph.mail.classify_adapter import analyze_email, current_text
from app.graph.state import AgentState
from app.knowledge.ports import Embedder, Repository
from app.knowledge.retrieval import SearchPlan, retrieve
from app.knowledge.schemas import KnowledgeError
from app.runlog.logger import current_event


def analyze_with_knowledge(state: AgentState, *, repository: Repository,
                           get_embedder: Callable[[int], Embedder],
                           plan_query: Callable[[int, str], SearchPlan] | None = None,
                           rerank: Callable[[int, str, list[dict]], list[str]] | None = None,
                           calendar: AvailabilityReader | None = None) -> dict:
    result = analyze_email(state, enrich=True)
    if result.get("intent") not in {"general", "deal"}:
        return result
    owner, email = state["user_id"], state["email"]
    if result.get("calendar_related"):
        result["calendar_availability"] = (check_mail_availability(calendar, owner, result.get("calendar_proposal"))
                                           if calendar is not None else {"status": "unavailable"})
    try:
        counterparties, available = repository.mail_scope(owner, email["from_addr"])
        scope = "counterparty" if counterparties is not None else "personal"
        if not available:
            return {**result, "knowledge_evidence": {"scope": scope, "status": "no_evidence", "clauses": []}
                    if result.get("contract_question") else None}
        query = email["subject"] + "\n" + current_text(email["body_text"])
        current_event("tool_call", tool="search_knowledge_documents", detail={"scope": scope})
        clauses = retrieve(repository, owner, query=query, counterparty_ids=counterparties,
                           get_embedder=partial(get_embedder, owner),
                           plan_query=partial(plan_query, owner) if plan_query else None,
                           rerank=partial(rerank, owner) if rerank else None)
    except KnowledgeError as error:
        current_event("tool_result", tool="search_knowledge_documents", detail={"ok": False, "code": error.code})
        return {**result, "knowledge_evidence": {"scope": "unavailable", "status": "unavailable", "clauses": []}}
    current_event("tool_result", tool="search_knowledge_documents", detail={"ok": True, "matches": len(clauses)})
    if clauses or result.get("contract_question"):
        result["knowledge_evidence"] = {"scope": scope, "status": "found" if clauses else "no_evidence", "clauses": clauses}
    return result
