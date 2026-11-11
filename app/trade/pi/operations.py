"""PI 업무: 입력 → 가격·계산·검증 → 주입받은 저장소. HTTP·ORM·모델 생성과 분리한다."""
from copy import deepcopy
from typing import Callable

from app.trade.ci_import import apply_document_prices
from app.trade.common.models import DocumentContext, DocumentError, DocumentResult
from app.trade.common.results import document_result
from app.trade.counterparties import apply_company_profiles, name_key
from app.trade.pi.models import PIInput, PIRepository
from app.trade.postprocess import apply_issuer_defaults, synchronize_quantities
from app.trade.pricing import build_trade_catalog
from app.trade.samples import update_sample
from app.trade.trade_documents import validate_and_calculate


def prepare_pi(values: dict, context: DocumentContext) -> dict:
    draft = deepcopy(values)
    draft.update(document_type="PI", doc_kind="PI", issuer=deepcopy(context.issuer), bank=deepcopy(context.bank))
    apply_issuer_defaults(draft, "PI", context.issuer)
    apply_company_profiles(draft, context.counterparties)
    for item in draft.get("items", []):
        override = item.pop("confirm_price_override", False)
        item["price_override_confirmed"] = override is True
        if item.get("unit_price") is not None:
            item["price_source"] = "User-confirmed transaction-specific override" if override else "Entered document value"
        if item.get("is_sample") is True:
            update_sample(item, name=item.get("product_name"), capacity=item.get("capacity"),
                          quantity=item.get("quantity") if item.get("quantity") is not None else item.get("paid_quantity"),
                          unit=item.get("unit"), price=item.get("unit_price"))
        if item.get("discount_percent") is None and item.get("is_sample") is True:
            item["discount_percent"] = "0"
    synchronize_quantities(draft)
    apply_document_prices(draft, build_trade_catalog(context.price_rows))
    issuer = context.issuer.get("legal_name_en") or context.issuer.get("company_name")
    return validate_and_calculate(draft, issuer_key=name_key(issuer))


def create_pi(command: PIInput, *, repository: PIRepository) -> DocumentResult:
    values = command.model_dump(mode="json")
    document = prepare_pi(values, repository.context(command.currency))
    return document_result(repository.create(document))


def extract_pi(text: str, *, repository: PIRepository, extractor: Callable[[str], dict]) -> DocumentResult:
    values = extractor(text)
    document = prepare_pi(values, repository.context(values.get("currency")))
    return document_result(repository.create(document))


def get_pi(document_id: int, *, repository: PIRepository) -> DocumentResult:
    return document_result(repository.get(document_id))


def revise_pi(document_id: int, revision: int, command: PIInput, *, repository: PIRepository) -> DocumentResult:
    previous = repository.get(document_id)
    if previous["revision"] != revision:
        raise DocumentError("REVISION_CONFLICT", "최신 PI를 다시 확인하세요")
    values = command.model_dump(mode="json")
    context = repository.context(command.currency)
    # 회사·계좌는 문서 작성 시점 스냅숏이다. 통화를 바꿀 때만 해당 통화 계좌를 새로 선택한다.
    context = DocumentContext(issuer=previous.get("issuer") or {},
                              bank=previous.get("bank") if previous.get("currency") == command.currency else context.bank,
                              price_rows=context.price_rows, counterparties=context.counterparties)
    document = prepare_pi(values, context)
    return document_result(repository.replace(document_id, revision, document))
