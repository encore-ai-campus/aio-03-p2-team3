from typing import Literal, Protocol

from pydantic import Field

from app.trade.common.models import DocumentInput, DocumentRepository, InputModel, PricedItem, Text


class CIRepository(DocumentRepository, Protocol):
    def source_pi(self, document_id: int, revision: int) -> dict: ...


class CIInput(InputModel):
    # 가격·품목·거래처·통화는 서버가 승인된 원본 PI 버전에서 가져온다.
    source_pi_id: int = Field(ge=1, strict=True)
    source_revision: int = Field(ge=1, strict=True)
    document_number: Text | None = None
    shipment_reference: Text | None = None
    country_of_origin: Text | None = None
    incoterms: Text | None = None
    ship_to: Text | None = None
    bill_to: Text | None = None
    remarks: Text | None = None


class StandaloneCIInput(DocumentInput):
    mode: Literal["standalone"]
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    shipment_reference: Text | None = None
    country_of_origin: Text | None = None
    items: list[PricedItem] = Field(default_factory=list, max_length=500)


class StandaloneCIExtraction(StandaloneCIInput):
    mode: Literal["standalone"] = "standalone"
    document_type: Literal["CI"] = "CI"
    missing_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class CIExtraction(InputModel):
    # 원본 선택은 명시적인 사용자 입력이다. AI가 ID·버전을 결정하지 않는다.
    document_type: Literal["CI"] = "CI"
    document_number: Text | None = None
    shipment_reference: Text | None = None
    country_of_origin: Text | None = None
    incoterms: Text | None = None
    ship_to: Text | None = None
    bill_to: Text | None = None
    remarks: Text | None = None


class CIText(InputModel):
    text: str = Field(min_length=1, max_length=20000)
    source_pi_id: int = Field(ge=1, strict=True)
    source_revision: int = Field(ge=1, strict=True)


class SourcePI(InputModel):
    source_pi_id: int
    source_revision: int
    document_number: str | None
    currency: str | None
    total: str | None
    approved: bool
    current_revision: int
    missing_fields: list[str]
    issues: list[dict]


class SourcePIPage(InputModel):
    items: list[SourcePI]
    next_cursor: str | None
