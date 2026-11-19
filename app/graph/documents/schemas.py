from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, JsonValue, StringConstraints, model_validator

from app.graph.schemas import Contract

DocumentKind = Literal["PI", "PO", "CI", "PL"]
SearchText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class CounterpartySearch(Contract):
    query: SearchText = Field(description="사용자가 말한 등록 거래처의 이름, 별칭 또는 이메일.")


class TradePriceSearch(Contract):
    product: SearchText = Field(description="사용자가 말한 품목명 또는 SKU. 거래처나 수량을 넣지 않는다.")
    role: Literal["sale", "purchase"] | None = Field(default=None, description="판매 단가는 sale, 매입 단가는 purchase.")
    currency: Annotated[str, StringConstraints(to_upper=True, pattern=r"^[A-Za-z]{3}$")] | None = Field(default=None, description="사용자가 지정한 ISO 4217 통화 코드.")
    counterparty: SearchText | None = Field(default=None, description="사용자가 지정한 거래처명 또는 별칭.")


class DraftDocumentSearch(Contract):
    kind: DocumentKind | None = Field(default=None, description="사용자가 말한 PI·PO·CI·PL 종류. 생략하면 모두.")
    cursor: int | None = Field(default=None, gt=0, strict=True, description="같은 조회의 다음 페이지에 쓰는 next_cursor.")


class IssuedDocumentSearch(Contract):
    kind: DocumentKind | None = None
    document_number: SearchText | None = None
    counterparty: SearchText | None = None
    issued_from: date | None = None
    issued_to: date | None = None

    @model_validator(mode="after")
    def check_filters(self):
        if not any((self.kind, self.document_number, self.counterparty, self.issued_from, self.issued_to)):
            raise ValueError("issued_search_filter_required")
        if self.issued_from and self.issued_to and self.issued_from > self.issued_to:
            raise ValueError("invalid_issued_date_range")
        return self


class KnowledgeDocumentSearch(Contract):
    filename: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = None
    document_id: UUID | None = None
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=800)] | None = None

    @model_validator(mode="after")
    def check_scope(self):
        if not (self.filename or self.document_id or self.query):
            raise ValueError("knowledge_search_input_required")
        if self.filename and self.document_id:
            raise ValueError("choose_knowledge_filename_or_id")
        return self


class DocumentInput(Contract):
    kind: DocumentKind
    document_id: int | None = Field(default=None, gt=0, strict=True)
    revision: int | None = Field(default=None, gt=0, strict=True)
    values: dict[str, JsonValue] | None = None
    text: str | None = Field(default=None, min_length=1, max_length=20000)
    formats: list[Literal["pdf", "xlsx"]] = Field(default_factory=lambda: ["pdf", "xlsx"], min_length=1, max_length=2)

    @model_validator(mode="after")
    def one_input_source(self):
        if self.values is not None and self.text is not None:
            raise ValueError("choose_values_or_text")
        return self
