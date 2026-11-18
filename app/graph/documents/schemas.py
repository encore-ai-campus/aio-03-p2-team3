from datetime import date
from typing import Annotated, Literal

from pydantic import Field, JsonValue, StringConstraints, model_validator

from app.graph.schemas import Contract

DocumentKind = Literal["PI", "PO", "CI", "PL"]
SearchText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


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
