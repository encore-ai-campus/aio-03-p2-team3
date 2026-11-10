from datetime import UTC, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

ErrorKind = Literal["rate_limit", "network", "invalid_output", "invalid_input", "auth", "not_found", "internal"]
T = TypeVar("T")


class ToolResult(BaseModel, Generic[T]):
    ok: bool
    value: T | None = None
    error_kind: ErrorKind | None = None
    error_message: str | None = None
    source: str
    fetched_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    attempts: int = Field(default=1, ge=0)
    duration_ms: int = Field(default=0, ge=0)


def unimplemented() -> ToolResult[Any]:
    return ToolResult(
        ok=False, error_kind="internal", error_message="아직 구현하지 않은 도구입니다",
        source="code", attempts=0,
    )


def invalid_input_result(_error) -> ToolResult[Any]:
    # Pydantic 오류 문자열에는 입력 값이 포함되므로 기록·응답에 복사하지 않는다.
    return ToolResult(
        ok=False, error_kind="invalid_input", error_message="도구 입력 형식을 확인해 주세요",
        source="code", attempts=0,
    )
