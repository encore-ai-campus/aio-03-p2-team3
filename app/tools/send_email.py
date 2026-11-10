"""send_email: 계약의 입력 스키마와 실행 자리."""

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.tools.base import ToolResult, unimplemented


class Input(BaseModel):
    user_id: int
    thread_id: str
    to_addrs: list[str]
    subject: str
    body: str
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)
    attachments: list[dict[str, str]] = Field(default_factory=list)


@tool(args_schema=Input)
def send_email(**kwargs) -> ToolResult:
    """후속 작업에서 채울 send_email 도구."""
    return unimplemented()
