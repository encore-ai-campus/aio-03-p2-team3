"""create_quote: 계약의 입력 스키마와 실행 자리."""

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.graph.state import DealTerms
from app.tools.base import ToolResult, unimplemented


class Input(BaseModel):
    user_id: int
    thread_id: str
    deal_terms: DealTerms
    company: dict | None = None
    price_list: list[dict] = Field(default_factory=list)


@tool(args_schema=Input)
def create_quote(**kwargs) -> ToolResult:
    """후속 작업에서 채울 create_quote 도구."""
    return unimplemented()
