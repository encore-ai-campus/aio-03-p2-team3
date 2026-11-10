"""draft_replies: 답장 후보 2~3개를 LLM 한 번(구조화 출력)으로 만든다(계약 4.4절).

DB 저장은 `save_pending` 노드가 한다(계약 3.1절). 이 도구는 예외를 던지지 않고 `ToolResult`로 돌려준다.
"""

from time import perf_counter
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.config import LIMITS
from app.graph.state import EmailMessage, QuoteDraft, ReplyCandidate, ThreadContext, TradeDocDraft
from app.llm.client import call_structured, model_source
from app.prompts.draft_replies import PROMPT, REPLY_MODE_GUIDES
from app.prompts.format import email_text, preferences_text, thread_context_text
from app.tools.base import ToolResult
from app.tools.fallback import reply_subject, with_signature


class Input(BaseModel):
    email: EmailMessage
    thread_context: ThreadContext | None = None
    reply_mode: Literal["general", "quote"]
    quote_draft: QuoteDraft | None = None
    trade_doc_draft: TradeDocDraft | None = None  # 무역서류 초안(계약 15.6절, quote_draft 대신)
    preferences: dict = Field(default_factory=dict)
    feedback: str | None = None


class DraftCandidate(BaseModel):
    label: str = Field(min_length=1, description="후보 성격 한 줄. 예: 바로 수락")
    body: str = Field(min_length=1, description="그대로 보낼 수 있는 답장 본문(제목 제외)")


class DraftOutput(BaseModel):
    candidates: list[DraftCandidate] = Field(
        min_length=LIMITS["CANDIDATE_MIN"], max_length=LIMITS["CANDIDATE_MAX"],
    )


def _quote_summary(quote: dict | None) -> str:
    if not quote:
        return "없음"
    missing = ", ".join(quote.get("missing_prices") or []) or "없음"
    total = "미정(사용자 단가 입력 대기)" if quote.get("total") is None else f"{quote['total']}원"
    return (f"견적번호 {quote.get('quote_no')}, 합계 {total}, "
            f"유효기간 {quote.get('valid_until')}, 단가 없는 품목 {missing}")


def trade_doc_summary(doc: dict | None) -> str:
    """무역서류 요약 텍스트(계약 15.6절: 문서 종류·문서번호·합계)."""
    if not doc:
        return "없음"
    kind = doc.get("doc_kind") or doc.get("document_type") or "?"
    total = doc.get("total")
    amount = "미정(검토 입력 필요)" if total in (None, "") else f"{doc.get('currency') or ''} {total}".strip()
    status = doc.get("status") or "needs_input"
    return f"{kind} 문서번호 {doc.get('doc_no')}, 합계 {amount}, 상태 {status}"


@tool(args_schema=Input)
def draft_replies(email, reply_mode, thread_context=None, quote_draft=None, trade_doc_draft=None,
                  preferences=None, feedback=None) -> ToolResult:
    """받은 메일에 대한 답장 후보 2~3개를 만든다."""
    started = perf_counter()
    try:
        variables = {
            "candidate_min": LIMITS["CANDIDATE_MIN"], "candidate_max": LIMITS["CANDIDATE_MAX"],
            "reply_mode_guide": REPLY_MODE_GUIDES[reply_mode].format(
                quote_summary=_quote_summary(quote_draft), trade_doc=trade_doc_summary(trade_doc_draft)),
            "trade_doc": trade_doc_summary(trade_doc_draft),
            "preferences": preferences_text(preferences), "feedback": feedback or "없음",
            "thread_context": thread_context_text(thread_context), "email": email_text(email),
        }
        result = call_structured(PROMPT, DraftOutput, variables)
        if not result.ok:
            return ToolResult(
                ok=False, error_kind=result.error_kind, source=model_source(),
                error_message=f"답장 후보 LLM 호출 실패 ({result.error_kind})",
                attempts=result.attempts, duration_ms=result.duration_ms,
            )
        candidates = [ReplyCandidate(
            label=item.label.strip(), subject=reply_subject(email),
            body=with_signature(item.body.strip(), preferences), kind=reply_mode,
            asks_fields=[], needs_review=False, notice=None,
        ) for item in result.value.candidates]
        return ToolResult(
            ok=True, value={"candidates": candidates}, source=model_source(),
            attempts=result.attempts, duration_ms=result.duration_ms,
        )
    except Exception as error:
        # 예외 문자열에는 본문이 섞일 수 있으므로 종류만 남긴다.
        return ToolResult(
            ok=False, error_kind="internal", source="code",
            error_message=f"답장 후보 도구 오류 ({type(error).__name__})",
            duration_ms=int((perf_counter() - started) * 1000),
        )
