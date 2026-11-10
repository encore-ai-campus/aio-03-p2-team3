"""check_required_fields: 계약의 입력 스키마와 실행 자리."""

from langchain_core.tools import tool
from pydantic import BaseModel

from app.graph.state import DealTerms, RequiredFields
from app.tools.base import ToolResult, unimplemented


class Input(BaseModel):
    deal_terms: DealTerms
    required_fields: RequiredFields


@tool(args_schema=Input)
def check_required_fields(**kwargs) -> ToolResult:
    """후속 작업에서 채울 check_required_fields 도구."""
    return unimplemented()
