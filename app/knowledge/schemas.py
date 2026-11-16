"""추출/임베딩 공급자와 DB에 의존하지 않는 수집 값·검증."""
from dataclasses import dataclass, field
from hashlib import sha256
import json
import math

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PAGES = 50
MAX_PIXELS = 20_000_000
MAX_TEXT_CHARS = 1_000_000
MAX_UNPACKED_BYTES = 100 * 1024 * 1024
CHUNK_VERSION = "clause-parent-child-chars-v1"
ACTIVE_STATUSES = {"queued", "extracting", "chunking", "embedding"}


class KnowledgeError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class Value(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelProfile(Value):
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    revision: str = Field(min_length=1, max_length=160)
    dimensions: int = Field(default=0, ge=0, le=16000)
    normalization: str = "provider"

    @property
    def fingerprint(self) -> str:
        return sha256(json.dumps(self.model_dump(), sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class PageImage:
    number: int
    source: str
    png: bytes = field(repr=False)


@dataclass(frozen=True)
class RenderedDocument:
    pages: list[PageImage]
    warnings: list[str]
    page_count: int = 0


class PageText(Value):
    number: int = Field(ge=1, le=MAX_PAGES)
    source: str = Field(default="", max_length=160)
    text: str = Field(max_length=MAX_TEXT_CHARS)
    blank: bool = False
    complete: bool = True
    uncertain: list[str] = Field(default_factory=list, max_length=100)


class ExtractionResult(Value):
    pages: list[PageText] = Field(min_length=1, max_length=MAX_PAGES)
    profile: ModelProfile
    warnings: list[str] = Field(default_factory=list, max_length=100)


class EmbeddingBatch(Value):
    vectors: list[list[float]]
    profile: ModelProfile

    def validate_for(self, count: int, expected: ModelProfile):
        if self.profile != expected or len(self.vectors) != count or not expected.dimensions:
            raise KnowledgeError("embedding_mismatch", "임베딩 개수 또는 모델 프로필이 맞지 않습니다.")
        if any(len(v) != expected.dimensions or any(not math.isfinite(x) for x in v)
               for v in self.vectors):
            raise KnowledgeError("embedding_mismatch", "임베딩 차원 또는 숫자 형식이 맞지 않습니다.")


class SourceSpan(Value):
    page: int
    source: str
    start: int
    end: int


class ParentChunk(Value):
    id: str
    ordinal: int
    text: str
    start: int
    end: int
    sources: list[SourceSpan]


class ChildChunk(Value):
    id: str
    parent_id: str
    ordinal: int
    text: str
    start: int
    end: int


class AttemptRequest(Value):
    attempt_id: str = Field(min_length=1, max_length=36)


class PageEdit(Value):
    number: int = Field(ge=1, le=MAX_PAGES)
    text: str = Field(max_length=MAX_TEXT_CHARS)


class ReviewRequest(AttemptRequest):
    revision: int = Field(ge=0)
    pages: list[PageEdit] = Field(min_length=1, max_length=MAX_PAGES)
    confirm: bool = False

    @model_validator(mode="after")
    def bounded_text(self):
        if sum(len(p.text) for p in self.pages) > MAX_TEXT_CHARS:
            raise ValueError("추출문은 총 100만 자 이하여야 합니다.")
        if self.confirm and not any(p.text.strip() for p in self.pages):
            raise ValueError("확정할 원문이 없습니다. 원본을 확인해 주세요.")
        return self
