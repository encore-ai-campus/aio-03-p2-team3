"""extract_deal_terms: 계약의 입력 스키마와 실행 자리."""

from langchain_core.tools import tool
from pydantic import BaseModel

from app.graph.state import EmailMessage, ThreadContext
from app.tools.base import ToolResult, unimplemented


class Input(BaseModel):
    email: EmailMessage
    thread_context: ThreadContext | None = None
    feedback: str | None = None


@tool(args_schema=Input)
def extract_deal_terms(**kwargs) -> ToolResult:
    """후속 작업에서 채울 extract_deal_terms 도구."""
    return unimplemented()
