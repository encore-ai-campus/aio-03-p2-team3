from hashlib import sha256
import struct
import zlib

from app.trade.common.models import DocumentError
from app.trade.common.counterparties import name_key
from app.trade.common.pdf import _read_png_rgb
from app.trade.settings.models import BankInput, CompanyInput, CounterpartyInput, PriceInput, SettingsRepository

MAX_BRANDING_BYTES = 2 * 1024 * 1024


def read_settings(*, repository: SettingsRepository) -> dict:
    return repository.read()


def save_company(command: CompanyInput, *, repository: SettingsRepository) -> dict:
    return repository.save_company(command.model_dump())


def save_bank(currency: str, command: BankInput, *, repository: SettingsRepository) -> dict:
    if not all(value for value in command.model_dump().values()):
        raise DocumentError("BANK_FIELDS_REQUIRED", "계좌 6항목을 모두 입력하세요", 422)
    return repository.save_bank(currency, command.model_dump())


def save_price(command: PriceInput, *, repository: SettingsRepository) -> dict:
    values = command.model_dump(mode="json")
    values["party_key"] = name_key(command.party_key)
    values["unit_price_text"] = values.pop("unit_price")
    return repository.save_price(values)


def save_counterparty(command: CounterpartyInput, *, repository: SettingsRepository) -> dict:
    values = command.model_dump()
    values["company_key"] = name_key(command.legal_name)
    if not values["company_key"]:
        raise DocumentError("COMPANY_NAME_REQUIRED", "거래처를 구분할 수 있는 회사명을 입력하세요", 422)
    values["aliases"] = list(dict.fromkeys(command.aliases))
    return repository.save_counterparty(values)


def save_branding(kind: str, content: bytes, *, repository: SettingsRepository, storage) -> dict:
    if not content or len(content) > MAX_BRANDING_BYTES:
        raise DocumentError("INVALID_IMAGE_SIZE", "이미지는 2MB 이하의 PNG로 업로드하세요", 413)
    try:
        _read_png_rgb(content)
    except (ValueError, ArithmeticError, IndexError, struct.error, zlib.error) as error:
        raise DocumentError("INVALID_PNG", "지원하는 RGB/RGBA PNG 이미지를 업로드하세요", 422) from error
    return repository.save_branding(kind, content, sha256(content).hexdigest(), storage)
