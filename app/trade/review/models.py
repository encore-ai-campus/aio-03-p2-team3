from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from app.trade.common.models import InputModel

FileFormat = Literal["pdf", "xlsx"]


class ReviewRequest(InputModel):
    revision: int = Field(ge=1, strict=True)
    formats: list[FileFormat] = Field(default_factory=lambda: ["pdf", "xlsx"], min_length=1, max_length=2)


class Decision(InputModel):
    action: Literal["approve", "cancel", "modify"]
    revision: int = Field(ge=1, strict=True)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArtifactView(BaseModel):
    id: str
    file_format: str
    filename: str
    media_type: str
    content_hash: str
    download_url: str


class ReviewView(BaseModel):
    id: str
    document_id: int
    revision: int
    payload: dict
    content_hash: str
    status: str
    decision: str | None
    created_at: str
    decided_at: str | None
    files: list[ArtifactView]


@dataclass(frozen=True)
class Branding:
    logo: bytes | None
    seal: bytes


@dataclass(frozen=True)
class RenderedFile:
    file_format: str
    filename: str
    media_type: str
    content: bytes


class ReviewRepository(Protocol):
    def document(self, document_id: int) -> dict: ...
    def branding(self) -> Branding: ...
    def create(self, document_id: int, revision: int, payload: dict, content_hash: str,
               branding: Branding) -> dict: ...
    def get(self, proposal_id: str) -> dict: ...
    def file(self, file_id: str) -> dict: ...
    def cancel(self, proposal_id: str, revision: int, content_hash: str) -> dict: ...
    def approve(self, proposal_id: str, revision: int, content_hash: str,
                files: list[RenderedFile]) -> dict: ...
