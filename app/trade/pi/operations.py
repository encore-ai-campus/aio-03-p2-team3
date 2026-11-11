"""PI 업무: 입력 → 가격·계산·검증 → 주입받은 저장소. HTTP·ORM·모델 생성과 분리한다."""
from copy import deepcopy
from typing import Callable

from app.trade.ci_import import apply_document_prices
from app.trade.common.models import DocumentContext, DocumentError, DocumentResult, DocumentSummary
from app.trade.common.results import document_result, editable_values
from app.trade.counterparties import apply_company_profiles, name_key
from app.trade.pi.models import PIInput, PIItem, PIRepository
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
    try:
        result = validate_and_calculate(draft, issuer_key=name_key(issuer))
    except ArithmeticError as error:
        raise DocumentError("NUMERIC_RANGE_EXCEEDED", "수량과 금액의 범위 또는 소수 자릿수를 확인하세요", 422) from error
    for key in ("BENEFICIARY", "BANK_NAME", "BRANCH", "SWIFT", "ACCOUNT_NUMBER", "BANK_ADDRESS"):
        if not (context.bank or {}).get(key):
            result["blocking_issues"].append(f"PI bank detail required: {key}")
    if result["blocking_issues"]:
        result.update(status="needs_input", ready_for_issue=False)
    return result


def pi_result(document: dict) -> DocumentResult:
    values = editable_values(document, PIInput.model_fields, PIItem.model_fields)
    return document_result(document, PIInput.model_validate(values).model_dump(mode="json"))


def create_pi(command: PIInput, *, repository: PIRepository) -> DocumentResult:
    values = command.model_dump(mode="json")
    document = prepare_pi(values, repository.context(command.currency))
    return pi_result(repository.create(document))


def extract_pi(text: str, *, repository: PIRepository, extractor: Callable[[str], dict]) -> DocumentResult:
    values = extractor(text)
    document = prepare_pi(values, repository.context(values.get("currency")))
    return pi_result(repository.create(document))


def get_pi(document_id: int, *, repository: PIRepository) -> DocumentResult:
    result = pi_result(repository.get(document_id))
    return result.model_copy(update=repository.latest_review(document_id, result.revision))


def list_pi(*, repository: PIRepository) -> list[DocumentSummary]:
    return [DocumentSummary(document_id=document["trade_doc_id"], document_type="PI",
                            document_number=document.get("document_number"), doc_no=document["doc_no"],
                            revision=document["revision"], status=document["status"],
                            currency=document.get("currency"), total=document.get("total"))
            for document in repository.list()]


def get_pi_version(document_id: int, revision: int, *, repository: PIRepository) -> dict:
    return repository.version(document_id, revision)


def revise_pi(document_id: int, revision: int, command: PIInput, *, repository: PIRepository,
              review_reference: tuple[str, str] | None = None) -> DocumentResult:
    previous = repository.get(document_id)
    if previous["revision"] != revision:
        raise DocumentError("REVISION_CONFLICT", "최신 PI를 다시 확인하세요")
    values = command.model_dump(mode="json")
    for index, item in enumerate(values["items"]):
        old_item = (previous.get("items") or [])[index] if index < len(previous.get("items") or []) else {}
        identity_changed = any(item.get(key) != old_item.get(key) for key in ("product_name", "product_code", "capacity", "unit"))
        if (previous.get("currency") != command.currency or identity_changed) and not item.get("confirm_price_override"):
            item["unit_price"] = None
    context = repository.context(command.currency)
    # 회사·계좌는 문서 작성 시점 스냅숏이다. 통화를 바꿀 때만 해당 통화 계좌를 새로 선택한다.
    issuer = {**context.issuer, **{key: value for key, value in (previous.get("issuer") or {}).items()
                                 if value not in (None, "")}}
    bank = context.bank
    if previous.get("currency") == command.currency:
        bank = {**(bank or {}), **{key: value for key, value in (previous.get("bank") or {}).items()
                                 if value not in (None, "")}} or None
    context = DocumentContext(issuer=issuer, bank=bank,
                              price_rows=context.price_rows, counterparties=context.counterparties)
    document = prepare_pi(values, context)
    if review_reference is not None:
        return pi_result(repository.replace(document_id, revision, document, review_reference))
    return pi_result(repository.replace(document_id, revision, document))


def check_pi_for_review(document: dict) -> None:
    if not all((document.get("bank") or {}).get(key) for key in (
        "BENEFICIARY", "BANK_NAME", "BRANCH", "SWIFT", "ACCOUNT_NUMBER", "BANK_ADDRESS")):
        raise DocumentError("BANK_CONFIGURATION_REQUIRED", "PI 지급 계좌 6항목을 설정한 뒤 문서에 반영하세요")
