"""draft_followup_replies: 빠진 필수 항목을 모두 묻는 답장 후보 2~3개(LLM 1회, 계약 4.4절)."""

import json

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.config import LIMITS
from app.graph.state import DealTerms, EmailMessage, ThreadContext
from app.llm.client import MODEL_SOURCE as SOURCE, call_structured
from app.prompts.draft_followup_replies import PROMPT
from app.prompts.format import email_text, preferences_text, thread_context_text
from app.tools.base import ToolResult
from app.tools.fallback import reply_subject, with_signature

NONE = "없음"


class Input(BaseModel):
    email: EmailMessage
    thread_context: ThreadContext | None = None
    deal_terms: DealTerms
    missing_fields: list[str]
    field_labels: dict[str, str]
    preferences: dict = Field(default_factory=dict)
    feedback: str | None = None


class FollowupCandidate(BaseModel):
    label: str = Field(min_length=1, description="후보 성격 한 줄")
    body: str = Field(min_length=1, description="그대로 보낼 수 있는 답장 본문(제목 제외)")


class FollowupDraft(BaseModel):
    """LLM 구조화 출력 형식. 개수가 2~3개가 아니면 형식 오류로 보고 call_structured가 재시도한다."""
    candidates: list[FollowupCandidate] = Field(
        min_length=LIMITS["CANDIDATE_MIN"], max_length=LIMITS["CANDIDATE_MAX"],
    )


def known_terms_text(deal_terms: DealTerms) -> str:
    known = {key: value for key, value in deal_terms.items()
             if key != "evidence" and value not in (None, "", [])}
    return json.dumps(known, ensure_ascii=False) if known else NONE


@tool(args_schema=Input)
def draft_followup_replies(email: EmailMessage, deal_terms: DealTerms, missing_fields: list[str],
                           field_labels: dict[str, str], thread_context: ThreadContext | None = None,
                           preferences: dict | None = None, feedback: str | None = None) -> ToolResult:
    """빠진 필수 항목을 모두 묻는 재질문 후보를 만든다. 후보마다 asks_fields는 빠진 항목 전부다."""
    if not missing_fields:
        return ToolResult(ok=False, error_kind="invalid_input", source="code", attempts=0,
                          error_message="빠진 필수 항목이 없어 재질문할 내용이 없습니다")
    try:
        labels = ", ".join(field_labels.get(key, key) for key in missing_fields)
        result = call_structured(PROMPT, FollowupDraft, {
            "missing_labels": labels,
            "known_terms": known_terms_text(deal_terms),
            "preferences": preferences_text(preferences),
            "email": email_text(email),
            "thread": thread_context_text(thread_context),
            "feedback": feedback or NONE,
        })
        if not result.ok:
            return ToolResult(ok=False, error_kind=result.error_kind, source=SOURCE,
                              error_message="재질문 후보를 만들지 못했습니다",
                              attempts=result.attempts, duration_ms=result.duration_ms)
        # 제목·서명은 답장 후보(8)와 같은 방식으로 코드가 정한다.
        candidates = [{
            "label": c.label.strip(),
            "subject": reply_subject(email),
            "body": with_signature(c.body.strip(), preferences),
            "kind": "followup",
            "asks_fields": list(missing_fields),
            "needs_review": False,
            "notice": None,
        } for c in result.value.candidates]
        return ToolResult(ok=True, value={"candidates": candidates}, source=SOURCE,
                          attempts=result.attempts, duration_ms=result.duration_ms)
    except Exception as error:
        return ToolResult(ok=False, error_kind="internal", source=SOURCE,
                          error_message=f"재질문 후보 생성 중 오류 ({type(error).__name__})")
