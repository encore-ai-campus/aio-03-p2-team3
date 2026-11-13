from typing import Literal

from pydantic import Field, JsonValue, model_validator

from app.graph.schemas import Contract


class DocumentInput(Contract):
    kind: Literal["PI", "PO", "CI", "PL"]
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
