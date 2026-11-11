from typing import Literal

from pydantic import Field

from app.trade.common.models import DocumentInput, DocumentRepository, PricedItem, Text

PIRepository = DocumentRepository


class PIItem(PricedItem):
    is_sample: bool = False


class PIInput(DocumentInput):
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    payment_terms: Text | None = None
    items: list[PIItem] = Field(default_factory=list, max_length=500)


class PIExtraction(PIInput):
    document_type: Literal["PI"] = "PI"
    missing_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    source_notes: list[str] = Field(default_factory=list)
