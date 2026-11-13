from pydantic import Field

from app.graph.schemas import Contract


class ThreadInput(Contract):
    thread_id: str = Field(min_length=1)


class SendInput(Contract):
    candidate_id: int = Field(gt=0, strict=True)
    file_ids: list[str] = Field(default_factory=list, max_length=8)
