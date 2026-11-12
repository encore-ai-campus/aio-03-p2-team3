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
    """제안 시점 회사 이미지. bytes는 Storage에서 읽은 값이고 file ID가 제안에 고정된다(계획 9절)."""
    seal: bytes
    logo: bytes | None = None
    seal_file_id: int | None = None
    logo_file_id: int | None = None


@dataclass(frozen=True)
class BrandingFiles:
    """제안이 고정한 회사 이미지 파일 ID. 렌더 때 Storage에서 bytes를 읽는다."""
    seal_file_id: int | None
    logo_file_id: int | None


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
    def proposal_branding(self, proposal: dict) -> Branding: ...
