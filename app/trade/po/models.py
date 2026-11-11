from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.trade.common.models import DocumentInput, DocumentRepository, Number, PricedItem, Text

PORepository = DocumentRepository


class POItem(PricedItem):
    discount_percent: Number = Decimal("0")


class POInput(DocumentInput):
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    payment_terms: Text | None = None
    items: list[POItem] = Field(default_factory=list, max_length=500)


class POExtraction(POInput):
    document_type: Literal["PO"] = "PO"
    missing_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
