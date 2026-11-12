from decimal import Decimal
from typing import Annotated, Literal, Protocol

from pydantic import BeforeValidator, Field

from app.trade.common.models import InputModel, Party, Text, decimal_input


ISSUER_FIELDS = ("company_name", "legal_name_en", "business_no", "ceo_name", "contact", "address",
                 "phone", "email", "registration_details")
BANK_FIELDS = ("beneficiary", "bank_name", "branch", "swift", "account_number", "bank_address")

class CompanyInput(InputModel):
    company_name: Text | None = None
    legal_name_en: Text | None = None
    business_no: Text | None = None
    ceo_name: Text | None = None
    address: Text | None = None
    contact: Text | None = None
    phone: Text | None = None
    email: Text | None = None
    registration_details: Text | None = None


class BankInput(InputModel):
    beneficiary: Text
    bank_name: Text
    branch: Text
    swift: Text
    account_number: Text
    bank_address: Text


class PriceInput(InputModel):
    item_name: str = Field(min_length=1, max_length=200)
    role: Literal["purchase", "sale"]
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    unit_price: Annotated[Decimal, BeforeValidator(decimal_input)]
    party_key: str = Field(default="", max_length=200)
    unit: str | None = Field(default=None, max_length=100)
    price_basis: str | None = Field(default=None, max_length=100)
    product_code: str | None = Field(default=None, max_length=200)
    capacity: str | None = Field(default=None, max_length=200)


class CounterpartyInput(Party):
    legal_name: str = Field(min_length=1, max_length=200)
    aliases: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=list, max_length=20)
    default_ship_to: Text | None = None
    ship_to_phone: Text | None = None


class SettingsRepository(Protocol):
    def read(self) -> dict: ...
    def save_company(self, values: dict) -> dict: ...
    def save_bank(self, currency: str, values: dict) -> dict: ...
    def save_price(self, values: dict) -> dict: ...
    def save_counterparty(self, values: dict) -> dict: ...
    def save_branding(self, kind: str, content: bytes, content_hash: str, storage) -> dict: ...
