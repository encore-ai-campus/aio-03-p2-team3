from typing import Literal, Protocol

from pydantic import Field

from app.trade.common.models import DocumentRepository, InputModel, Text


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
