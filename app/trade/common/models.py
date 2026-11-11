"""HTTP/ORM/LangChain에 의존하지 않는 문서 업무의 입력·출력과 저장 인터페이스."""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Protocol
import re

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def decimal_input(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool) or isinstance(value, float) or len(str(value)) > 80:
        raise ValueError("수량·금액은 정수 또는 정확한 십진수 문자열로 입력하세요")
    try:
        text = str(value).strip()
        if "," in text and not re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", text):
            raise ValueError()
        number = Decimal(text.replace(",", ""))
    except (InvalidOperation, ValueError):
        raise ValueError("올바른 십진수가 필요합니다") from None
    if (not number.is_finite() or number < 0 or number > Decimal("1e15")
            or number.as_tuple().exponent < -12):
        raise ValueError("수량·금액의 범위를 확인하세요")
    return number


Number = Annotated[Decimal | None, BeforeValidator(decimal_input)]
Text = Annotated[str, Field(max_length=4000)]
Family = Literal["cosmetics", "polysilicon", "wafer", "solar_cell", "solar_module", "other"]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Party(InputModel):
    legal_name: Text | None = None
    address: Text | None = None
    contact: Text | None = None
    phone: Text | None = None
    email: Text | None = None
    registration_details: Text | None = None


class DocumentInput(InputModel):
    product_family: Family | None = None
    document_number: Text | None = None
    buyer: Party = Field(default_factory=Party)
    seller: Party = Field(default_factory=Party)
    incoterms: Text | None = None
    remarks: Text | None = None
    ship_to: Text | None = None
    bill_to: Text | None = None


class PricedItem(InputModel):
    product_name: Text | None = None
    product_code: Text | None = None
    capacity: Text | None = None
    quantity: Number = None
    paid_quantity: Number = None
    free_quantity: Number = None
    unit: Text | None = None
    unit_price: Number = None
    price_basis: Text | None = None
    discount_percent: Number = None
    promotion: Text | None = None
    source: Text | None = None
    # 사용자 입력의 명시적 거래 단가 변경 요청. AI 결과에서는 항상 False로 덮어쓴다.
    confirm_price_override: bool = False


@dataclass(frozen=True)
class DocumentContext:
    issuer: dict = field(default_factory=dict)
    bank: dict | None = None
    price_rows: list[dict] = field(default_factory=list)
    counterparties: list[dict] = field(default_factory=list)


class DocumentResult(BaseModel):
    document_id: int
    document_type: str
    revision: int
    status: str
    document: dict
    missing_fields: list[str] = Field(default_factory=list)
    issues: list[dict] = Field(default_factory=list)
    proposal_id: str | None = None
    files: list[dict] = Field(default_factory=list)


class DocumentRepository(Protocol):
    def context(self, currency: str | None) -> DocumentContext: ...
    def create(self, document: dict) -> dict: ...
    def get(self, document_id: int) -> dict: ...
    def replace(self, document_id: int, revision: int, document: dict) -> dict: ...


class DocumentError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code
