"""보내기 전 메일 초안 입력 계약."""
from email.errors import HeaderParseError
from email.headerregistry import Address
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Subject = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Body = Annotated[str, StringConstraints(min_length=1, max_length=25000)]


class ComposeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipients: list[str] = Field(min_length=1, max_length=10, description="사용자가 확인한 새 메일 수신자 주소.")
    subject: Subject = Field(description="새 메일의 제목.")
    body: Body = Field(description="검토할 편집 가능한 일반 텍스트 초안.")

    @field_validator("recipients")
    @classmethod
    def valid_recipients(cls, values):
        recipients = []
        for raw in values:
            candidate = raw.strip()
            try:
                address = Address(addr_spec=candidate)
            except (ValueError, HeaderParseError) as error:
                raise ValueError("메일 주소를 확인해 주세요.") from error
            if not address.username or "." not in address.domain or len(candidate) > 254:
                raise ValueError("메일 주소를 확인해 주세요.")
            if candidate not in recipients:
                recipients.append(candidate)
        return recipients

    @field_validator("subject")
    @classmethod
    def single_line(cls, value):
        if "\r" in value or "\n" in value:
            raise ValueError("제목은 한 줄로 입력해 주세요.")
        return value

    @field_validator("body")
    @classmethod
    def nonblank_body(cls, value):
        if not value.strip():
            raise ValueError("본문을 입력해 주세요.")
        return value


class EditComposeInput(ComposeInput):
    revision: int = Field(ge=1, strict=True)
