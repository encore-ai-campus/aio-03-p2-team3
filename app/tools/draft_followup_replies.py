"""draft_followup_replies: 계약의 입력 스키마와 실행 자리."""

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.graph.state import DealTerms, EmailMessage, ThreadContext
from app.tools.base import ToolResult, unimplemented


class Input(BaseModel):
    email: EmailMessage
    thread_context: ThreadContext | None = None
    deal_terms: DealTerms
    missing_fields: list[str]
    field_labels: dict[str, str]
    preferences: dict = Field(default_factory=dict)
    feedback: str | None = None


@tool(args_schema=Input)
def draft_followup_replies(**kwargs) -> ToolResult:
    """후속 작업에서 채울 draft_followup_replies 도구."""
    return unimplemented()
