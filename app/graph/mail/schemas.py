from typing import Literal

from pydantic import AwareDatetime, Field, model_validator

from app.graph.schemas import Contract


class SearchInput(Contract):
    query: str = Field(default="", max_length=200, description="사용자가 말한 메일 본문의 구절, 제목, 또는 발신자 이름·주소.")
    cursor: int | None = Field(default=None, gt=0, strict=True, description="앞 검색 결과의 next_cursor. 같은 필터로 다음 페이지를 읽을 때만 사용.")
    field: Literal["all", "subject", "body", "sender"] = Field(default="all", description="검색 위치. 본문에만 찾을 때 body, 발신자만 sender, 제목만 subject.")
    received_from: AwareDatetime | None = Field(default=None, description="수신 기간 시작 포함. ISO 8601 오프셋 포함, 한국 날짜는 +09:00.")
    received_before: AwareDatetime | None = Field(default=None, description="수신 기간 끝 제외. 하루의 끝은 다음날 자정.")
    reply_status: Literal["any", "unanswered", "replied"] = Field(default="any", description="사용자가 요청한 실제 답장 발송 여부. 초안은 미답장.")

    @model_validator(mode="after")
    def ordered_window(self):
        if self.received_from and self.received_before and self.received_from >= self.received_before:
            raise ValueError("invalid_mail_search_window")
        return self


class ThreadInput(Contract):
    thread_id: str = Field(min_length=1)


class SendInput(Contract):
    candidate_id: int = Field(gt=0, strict=True)
    file_ids: list[str] = Field(default_factory=list, max_length=8)
