from typing import Literal

from pydantic import Field

from app.trade.common.models import DocumentInput, DocumentRepository, InputModel, Number, Text

PLRepository = DocumentRepository


class Package(InputModel):
    package_type: Text | None = None
    package_count: Number = None
    net_weight_kg: Number = None
    gross_weight_kg: Number = None
    dimensions: Text | None = None
    shipping_marks: Text | None = None


class PLItem(Package):
    product_name: Text | None = None
    product_code: Text | None = None
    capacity: Text | None = None
    quantity: Number = None
    unit: Text | None = None
    volume_cbm: Number = None
    source: Text | None = None


class PLInput(DocumentInput):
    shipment_reference: Text | None = None
    hs_code: Text | None = None
    # 원문에 단위·컨테이너 규격이 같이 있어도 원본 문자열을 보존한다.
    actual_package_count: Text | None = None
    container_count: Text | None = None
    declared_net_weight_kg: Text | None = None
    declared_gross_weight_kg: Text | None = None
    declared_volume_cbm: Text | None = None
    declared_total_quantity: Text | None = None
    declared_total_quantity_unit: Text | None = None
    packages: list[Package] = Field(default_factory=list, max_length=500)
    items: list[PLItem] = Field(default_factory=list, max_length=500)


class PLExtraction(PLInput):
    document_type: Literal["PL"] = "PL"
    missing_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class PackingDecision(InputModel):
    action: Literal["approve", "cancel"]
    revision: int = Field(ge=1, strict=True)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
