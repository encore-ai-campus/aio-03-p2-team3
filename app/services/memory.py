"""사용자·스레드별 기억 조회, 긴 대화 요약, 승인 발송 뒤 저장(계획 13절)."""

from datetime import datetime
from email.utils import parseaddr
import json

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.config import LIMITS
from app.db.models import (
    Approval, CompanyProfile, CounterpartyHistory, DealTerms, PriceListItem,
    ReplyCandidate, ThreadMemory, ThreadMessage, User, UserPreference, utcnow,
)
from app.llm.client import call_structured
from app.prompts.summarize_thread import PROMPT


class ThreadSummary(BaseModel):
    deal_conditions: list[str] = Field(max_length=30)
    confirmed_fields: list[str] = Field(max_length=30)
    unanswered_questions: list[str] = Field(max_length=30)

    @model_validator(mode="after")
    def bounded_summary(self):
        if len(self.model_dump_json()) > 4000:
            raise ValueError("요약은 4000자 이하여야 합니다")
        return self


class SummaryFailed(Exception):
    def __init__(self, result):
        self.result = result
        super().__init__("스레드 요약 실패")


def address(value: str) -> str:
    return parseaddr(value)[1].strip().lower()


def _memory(session, user_id, thread_id):
    row = session.get(ThreadMemory, (user_id, thread_id))
    if row is None:
        row = ThreadMemory(user_id=user_id, thread_id=thread_id, confirmed_terms={})
        session.add(row)
    return row


def _message(row):
    # 수신 원문 표에는 RFC Message-ID·발신자 이름이 없다. 발송은 원래 EmailMessage를 쓴다.
    return {
        "gmail_message_id": row.gmail_message_id, "thread_id": row.thread_id,
        "rfc_message_id": None, "from_addr": row.from_addr, "from_name": None,
        "to_addrs": row.to_addrs, "subject": row.subject, "body_text": row.body_text,
        "received_at": row.sent_at.isoformat(), "direction": row.direction,
    }


def load_memories(database, *, user_id: int, email: dict) -> dict:
    """현재 메일은 따로 전달하므로 중복하지 않는다. 미래 메시지도 읽지 않는다.

    요약 실패는 트랜잭션을 되돌린다. 원문은 지우지 않고, 성공한 요약만 커서를 옮긴다.
    """
    with database.session() as session:
        memory = _memory(session, user_id, email["thread_id"])
        memory.counterparty_email = address(email["from_addr"])
        rows = list(session.scalars(select(ThreadMessage).where(
            ThreadMessage.user_id == user_id, ThreadMessage.thread_id == email["thread_id"],
            ThreadMessage.gmail_message_id != email["gmail_message_id"],
            ThreadMessage.sent_at <= datetime.fromisoformat(email["received_at"]),
        ).order_by(ThreadMessage.sent_at, ThreadMessage.id)))
        pending = [row for row in rows if memory.summarized_until is None
                   or row.sent_at > memory.summarized_until]
        retries = 0
        if (len(pending) + 1 > LIMITS["SUMMARY_TRIGGER_MESSAGES"]
                or sum(len(row.body_text) for row in pending) + len(email["body_text"])
                > LIMITS["SUMMARY_TRIGGER_CHARS"]):
            older = pending[:-LIMITS["SUMMARY_KEEP_RECENT"]]
            recent = pending[-LIMITS["SUMMARY_KEEP_RECENT"]:]
            # 시각만으로 된 커서이므로 같은 시각의 메시지를 경계에서 나누지 않는다.
            if recent:
                older = [row for row in older if row.sent_at < recent[0].sent_at]
            if older:
                result = call_structured(PROMPT, ThreadSummary, {
                    "previous_summary": memory.summary or "없음",
                    "confirmed_terms": json.dumps(memory.confirmed_terms, ensure_ascii=False),
                    "last_result": json.dumps(memory.last_result, ensure_ascii=False),
                    "messages": json.dumps([_message(row) for row in older], ensure_ascii=False),
                })
                if not result.ok:
                    raise SummaryFailed(result)
                retries = max(result.attempts - 1, 0)
                memory.summary = result.value.model_dump_json()
                memory.summarized_until = older[-1].sent_at
                pending = [row for row in pending if row.sent_at > memory.summarized_until]
        context = {
            "summary": memory.summary, "recent_messages": [_message(row) for row in pending],
            "confirmed_terms": memory.confirmed_terms, "last_result": memory.last_result,
        }
        long_term = _long_term(session, user_id, memory.counterparty_email)
    return {"thread_context": context, "long_term": long_term, "call_retries": retries}


def _long_term(session, user_id, counterparty):
    preferences = list(session.scalars(select(UserPreference).where(UserPreference.user_id == user_id)))
    company = session.get(CompanyProfile, user_id)
    prices = list(session.scalars(select(PriceListItem).where(
        PriceListItem.user_id == user_id,
        PriceListItem.role.is_(None),  # 국내 견적서 행만(무역 행은 계약 15.7절)
    ).order_by(PriceListItem.item_name)))
    # 다른 거래처 기록은 읽지 않으며, 최근 다섯 건만 모델에 전달한다.
    history = list(session.scalars(select(CounterpartyHistory).where(
        CounterpartyHistory.user_id == user_id,
        CounterpartyHistory.counterparty_email == counterparty,
    ).order_by(CounterpartyHistory.sent_at.desc(), CounterpartyHistory.id.desc()).limit(5)))
    sources = []
    for kind, entries, time_field in (
        ("user_preferences", preferences, "updated_at"),
        ("company_profiles", [company] if company else [], "updated_at"),
        ("price_list", prices, "updated_at"),
        ("counterparty_history", history, "sent_at"),
    ):
        for row in entries:
            sources.append({
                "kind": kind, "fetched_at": getattr(row, time_field).isoformat(),
                "note": "저장/발송 당시 자료이며 현재 메일의 합의나 최신 외부 조회 결과가 아님; "
                        + str(getattr(row, "item_name", None) or getattr(row, "key", None)
                              or getattr(row, "thread_id", None) or "company"),
            })
    return {
        "preferences": {row.key: row.value for row in preferences},
        # 무역서류 발행사 기본값(apply_issuer_defaults)이 legal_name_en·address·phone·email까지 읽는다(계약 15.6절).
        "company": {key: getattr(company, key) for key in
                    ("company_name", "business_no", "ceo_name", "contact",
                     "legal_name_en", "address", "phone", "email")} if company else None,
        "price_list": [{"item_name": row.item_name, "unit": row.unit, "unit_price": row.unit_price}
                       for row in prices],
        "counterparty_history": [{"thread_id": row.thread_id, "summary": row.summary,
                                  "deal_terms": row.deal_terms, "sent_at": row.sent_at.isoformat()}
                                 for row in history],
        "sources": sources,
    }


def context_for_model(state: dict) -> dict:
    """기존 ThreadContext 입력에 참고 기억을 붙인다. 상태의 단기 기억 자체는 바꾸지 않는다."""
    context = {"summary": None, "recent_messages": [], "confirmed_terms": {}, "last_result": None,
               **(state["thread_context"] or {})}
    long_term = state["long_term"] or {}
    parts = [
        "기억 우선순위: 현재 메일의 명시 조건을 최우선으로 따른다. 과거 조건은 충돌하지 않는 부족분만 참고한다. "
        "다른 스레드의 거래 기록은 과거 참고이며 이번 수량·납기·합의 단가로 옮기지 않는다. "
        "승인한 답장 예시는 문체만 참고하고 사실·약속은 옮기지 않는다.",
        context.get("summary") or "",
    ]
    if long_term.get("counterparty_history"):
        parts.append("[상대방 과거 거래 기록·발송 시점]\n" + json.dumps(
            long_term["counterparty_history"], ensure_ascii=False,
        ))
    sources = [source for source in long_term.get("sources", [])
               if source["kind"] in ("counterparty_history", "user_preferences")]
    if sources:
        parts.append("[기억 출처·조회/저장 시점]\n" + json.dumps(sources, ensure_ascii=False))
    context["summary"] = "\n".join(parts)
    return context


def save_run_memory(session, state: dict, end_reason: str):
    """승인 대기 결과와 메일에서 확인한 조건만 저장. 후보는 장기 선호로 학습하지 않는다."""
    memory = _memory(session, state["user_id"], state["thread_id"])
    memory.counterparty_email = address(state["email"]["from_addr"])
    email = state["email"]
    original = session.scalar(select(ThreadMessage).where(
        ThreadMessage.user_id == state["user_id"], ThreadMessage.gmail_message_id == state["message_id"],
    ))
    # 알림 경로는 이미 저장했다. 시험·직접 실행 경로도 같은 단기 기억을 유지한다.
    if original is None:
        session.add(ThreadMessage(
            user_id=state["user_id"], thread_id=state["thread_id"], gmail_message_id=state["message_id"],
            direction=email["direction"], from_addr=email["from_addr"], to_addrs=email["to_addrs"],
            subject=email["subject"], body_text=email["body_text"],
            sent_at=datetime.fromisoformat(email["received_at"]),
        ))
    if state["deal_terms"] is not None and state["step_status"] == "ok":
        memory.confirmed_terms = state["deal_terms"]
    missing = state["missing_fields"]
    if state["step_status"] != "ok" and not missing:
        missing = (memory.last_result or {}).get("missing_fields", [])
    memory.last_result = {
        "end_reason": end_reason, "reply_mode": state["reply_mode"],
        "missing_fields": missing,
    }


def save_sent_memory(session, *, user_id: int, candidate_id: int, sent_at=None, to_addrs=None) -> bool:
    """승인 경로가 발송 성공 상태를 flush한 뒤 같은 트랜잭션에서 부를 훅.

    승인·후보 모두 sent이고 Gmail ID가 있어야 저장한다. 재호출은 원문·거래 기록을 중복하지 않는다.
    """
    approval = session.scalar(select(Approval).where(
        Approval.user_id == user_id, Approval.candidate_id == candidate_id,
    ).with_for_update())
    candidate = session.scalar(select(ReplyCandidate).where(
        ReplyCandidate.user_id == user_id, ReplyCandidate.id == candidate_id,
    ))
    if (approval is None or candidate is None or approval.send_status != "sent"
            or candidate.status != "sent" or not approval.sent_message_id):
        return False
    user = session.get(User, user_id)
    original = session.scalar(select(ThreadMessage).where(
        ThreadMessage.user_id == user_id, ThreadMessage.thread_id == candidate.thread_id,
        ThreadMessage.gmail_message_id == candidate.source_message_id, ThreadMessage.direction == "in",
    ))
    if original is None or user is None:
        raise ValueError("승인 답장의 원본 메일이나 사용자가 없습니다")
    sent = session.scalar(select(ThreadMessage).where(
        ThreadMessage.user_id == user_id, ThreadMessage.gmail_message_id == approval.sent_message_id,
    ))
    at = sent.sent_at if sent else (sent_at or utcnow())
    if sent is None:
        session.add(ThreadMessage(
            user_id=user_id, thread_id=candidate.thread_id, gmail_message_id=approval.sent_message_id,
            direction="out", from_addr=user.email,
            to_addrs=list(to_addrs) if to_addrs is not None else [address(original.from_addr)],
            subject=candidate.subject, body_text=candidate.body, sent_at=at,
        ))
    preference = session.get(UserPreference, (user_id, "approved_reply_style"))
    if preference is None:
        preference = UserPreference(user_id=user_id, key="approved_reply_style")
        session.add(preference)
    if preference.updated_at is None or preference.updated_at <= at:
        preference.value = {"label": candidate.label, "example": candidate.body[:1000]}
        preference.updated_at = at
    terms = session.scalar(select(DealTerms).where(
        DealTerms.user_id == user_id, DealTerms.run_id == candidate.run_id,
        DealTerms.thread_id == candidate.thread_id,
    ).order_by(DealTerms.id.desc()))
    if terms is not None:
        history = session.scalar(select(CounterpartyHistory).where(
            CounterpartyHistory.user_id == user_id, CounterpartyHistory.thread_id == candidate.thread_id,
        ).order_by(CounterpartyHistory.sent_at.desc(), CounterpartyHistory.id.desc()))
        if history is None:
            history = CounterpartyHistory(user_id=user_id, thread_id=candidate.thread_id)
            session.add(history)
        if history.sent_at is None or history.sent_at <= at:
            history.counterparty_email = address(original.from_addr)
            history.summary = f"승인 발송: {candidate.kind} / {candidate.label}"
            history.deal_terms = terms.terms
            history.quote_id = candidate.quote_id
            history.sent_at = at
    return True
