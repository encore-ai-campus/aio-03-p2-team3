"""draft_replies: 답장 후보 2~3개를 LLM 한 번(구조화 출력)으로 만든다(계약 4.4절).

DB 저장은 `save_pending` 노드가 한다(계약 3.1절). 이 도구는 예외를 던지지 않고 `ToolResult`로 돌려준다.
"""

from time import perf_counter
from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.config import LIMITS
from app.graph.state import EmailMessage, QuoteDraft, ReplyCandidate, ThreadContext
from app.llm.client import MODEL_SOURCE, call_structured
from app.prompts.draft_replies import PROMPT, REPLY_MODE_GUIDES
from app.prompts.format import email_text, preferences_text, thread_context_text
from app.tools.base import ToolResult
from app.tools.fallback import reply_subject, with_signature


class Input(BaseModel):
    email: EmailMessage
    thread_context: ThreadContext | None = None
    reply_mode: Literal["general", "quote"]
    quote_draft: QuoteDraft | None = None
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
    return (f"견적번호 {quote.get('quote_no')}, 합계 {quote.get('total')}원, "
            f"유효기간 {quote.get('valid_until')}, 단가 없는 품목 {missing}")


@tool(args_schema=Input)
def draft_replies(email, reply_mode, thread_context=None, quote_draft=None,
                  preferences=None, feedback=None) -> ToolResult:
    """받은 메일에 대한 답장 후보 2~3개를 만든다."""
    started = perf_counter()
    try:
        variables = {
            "candidate_min": LIMITS["CANDIDATE_MIN"], "candidate_max": LIMITS["CANDIDATE_MAX"],
            "reply_mode_guide": REPLY_MODE_GUIDES[reply_mode].format(quote_summary=_quote_summary(quote_draft)),
            "preferences": preferences_text(preferences), "feedback": feedback or "없음",
            "thread_context": thread_context_text(thread_context), "email": email_text(email),
        }
        result = call_structured(PROMPT, DraftOutput, variables)
        if not result.ok:
            return ToolResult(
                ok=False, error_kind=result.error_kind, source=MODEL_SOURCE,
                error_message=f"답장 후보 LLM 호출 실패 ({result.error_kind})",
                attempts=result.attempts, duration_ms=result.duration_ms,
            )
        candidates = [ReplyCandidate(
            label=item.label.strip(), subject=reply_subject(email),
            body=with_signature(item.body.strip(), preferences), kind=reply_mode,
            asks_fields=[], needs_review=False, notice=None,
        ) for item in result.value.candidates]
        return ToolResult(
            ok=True, value={"candidates": candidates}, source=MODEL_SOURCE,
            attempts=result.attempts, duration_ms=result.duration_ms,
        )
    except Exception as error:
        # 예외 문자열에는 본문이 섞일 수 있으므로 종류만 남긴다.
        return ToolResult(
            ok=False, error_kind="internal", source="code",
            error_message=f"답장 후보 도구 오류 ({type(error).__name__})",
            duration_ms=int((perf_counter() - started) * 1000),
        )
