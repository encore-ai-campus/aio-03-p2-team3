"""draft_replies: 계약의 입력 스키마와 실행 자리."""

from typing import Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.graph.state import EmailMessage, QuoteDraft, ThreadContext
from app.tools.base import ToolResult, unimplemented


class Input(BaseModel):
    email: EmailMessage
    thread_context: ThreadContext | None = None
    reply_mode: Literal["general", "quote"]
    quote_draft: QuoteDraft | None = None
    preferences: dict = Field(default_factory=dict)
    feedback: str | None = None


@tool(args_schema=Input)
def draft_replies(**kwargs) -> ToolResult:
    """후속 작업에서 채울 draft_replies 도구."""
    return unimplemented()
