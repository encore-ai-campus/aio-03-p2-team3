"""PI 업무: 입력 → 가격·계산·검증 → 주입받은 저장소. HTTP·ORM·모델 생성과 분리한다."""
from copy import deepcopy
from typing import Callable

from pydantic import ValidationError

from app.trade.common.models import DocumentContext, DocumentError, DocumentResult, DocumentSummary
from app.trade.common import operations as common
from app.trade.common.results import document_result, editable_values
from app.trade.common.review_fields import _missing
from app.trade.pi.models import PIInput, PIItem, PIRepository
from app.trade.pi.samples import update_sample


def prepare_pi(values: dict, context: DocumentContext) -> dict:
    draft = deepcopy(values)
    draft["document_number"] = None
    for item in draft.get("items", []):
        if item.get("is_sample") is True:
            update_sample(item, name=item.get("product_name"), capacity=item.get("capacity"),
                          quantity=item.get("quantity") if item.get("quantity") is not None else item.get("paid_quantity"),
                          unit=item.get("unit"), price=item.get("unit_price"))
    result = common.prepare_priced(draft, context, "PI")
    for source, calculated in zip(draft.get("items", []), result["items"]):
        if source.get("discount_percent") is None and "discount_percent" in source:
            calculated["discount_percent"] = None
        if source.get("quantity") is None and source.get("paid_quantity") is None:
            calculated.update(quantity=None, paid_quantity=None)
    for key in ("BENEFICIARY", "BANK_NAME", "BRANCH", "SWIFT", "ACCOUNT_NUMBER", "BANK_ADDRESS"):
        if not (context.bank or {}).get(key):
            result["blocking_issues"].append(f"PI bank detail required: {key}")
    if result["blocking_issues"]:
        result.update(status="needs_input", ready_for_issue=False)
    return result


def _unconfirmed_inputs(document, values):
    # Calculated zeroes are useful for incomplete totals, but are not transaction inputs.
    # The existing validation messages also identify drafts saved before this change.
    issues = set(document.get("blocking_issues", []))
    for index, item in enumerate(values["items"], 1):
        if f"Valid number required for discount percent for item {index}" in issues:
            item["discount_percent"] = None
        if f"Valid number required for paid quantity for item {index}" in issues:
            item.update(quantity=None, paid_quantity=None)
    return values


def pi_result(document: dict) -> DocumentResult:
    values = _unconfirmed_inputs(document, editable_values(document, PIInput.model_fields, PIItem.model_fields))
    inputs = PIInput.model_validate(values).model_dump(mode="json")
    result = document_result(document, inputs)
    return result.model_copy(update={"missing_fields": list(dict.fromkeys([
        *result.missing_fields, *completion_fields(inputs),
    ]))})


def completion_fields(inputs):
    fields = [key for key in ("currency", "incoterms", "payment_terms", "product_family")
              if _missing(inputs.get(key), True)]
    fields.extend(f"{role}.{key}" for role in ("buyer", "seller") for key in ("legal_name", "address")
                  if _missing(inputs[role].get(key), True))
    for index, item in enumerate(inputs["items"] or [{}]):
        for key in ("product_name", "quantity", "unit", "unit_price", "price_basis", "discount_percent"):
            if key == "quantity" and item.get("paid_quantity") is not None:
                continue
            if _missing(item.get(key), True):
                fields.append(f"items.{index}.{key}")
    return fields


def completion_command(result: DocumentResult, changes: dict) -> PIInput:
    values = deepcopy(result.input)
    allowed = set(completion_fields(values))
    for path, value in changes.items():
        if path.endswith(".confirm_price_override"):
            price = path.rsplit(".", 1)[0] + ".unit_price"
            if price not in allowed or price not in changes or value is not True:
                raise DocumentError("PI_COMPLETION_INVALID", "입력할 수 없는 단가 확인 항목입니다")
        elif path not in allowed or not isinstance(value, str) or _missing(value, True):
            raise DocumentError("PI_COMPLETION_INVALID", "보완할 항목과 입력값을 확인하세요")
        parts = path.split(".")
        if parts[0] == "items":
            if not values["items"]:
                values["items"].append({})
            row = values["items"][int(parts[1])]
            row[parts[2]] = value
            if parts[2] == "quantity":
                row["paid_quantity"] = value
        elif len(parts) == 2:
            values[parts[0]][parts[1]] = value
        else:
            values[path] = value
    try:
        command = PIInput.model_validate(values)
        for row in command.items:
            if row.discount_percent is not None and row.discount_percent > 100:
                raise ValueError("discount")
        return command
    except (ValidationError, ValueError):
        raise DocumentError("PI_COMPLETION_INVALID", "입력 형식과 할인율 범위(0~100%)를 확인하세요") from None


def create_pi(command: PIInput, *, repository: PIRepository) -> DocumentResult:
    values = command.model_dump(mode="json")
    context = repository.context(command.currency)
    document = prepare_pi(values, context)
    return pi_result(repository.create(document))


def extract_pi(text: str, *, repository: PIRepository, extractor: Callable[[str], dict]) -> DocumentResult:
    values = deepcopy(extractor(text))
    for item in values.get("items", []):
        if item.get("discount_percent") is None:
            item["discount_percent"] = "0"
    context = repository.context(values.get("currency"))
    document = prepare_pi(values, context)
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
    values = common.revision_values(previous, command)
    context = common.revision_context(previous, repository.context(command.currency), command.currency)
    document = prepare_pi(values, context)
    if review_reference is not None:
        return pi_result(repository.replace(document_id, revision, document, review_reference))
    return pi_result(repository.replace(document_id, revision, document))


def refresh_issuer(document_id: int, revision: int, *, repository: PIRepository) -> DocumentResult:
    previous = repository.get(document_id)
    if previous["revision"] != revision:
        raise DocumentError("REVISION_CONFLICT", "최신 PI를 다시 확인하세요")
    if previous["status"] in {"sent", "sending"}:
        raise DocumentError("REVISION_CONFLICT", "발송 중이거나 발송된 PI는 수정할 수 없습니다")
    context = repository.context(previous.get("currency"))
    values = _unconfirmed_inputs(previous, common.refresh_settings_values(previous, context, "PI", PIInput, PIItem))
    refreshed = prepare_pi(values, context)
    refreshed["issue_date"] = previous.get("issue_date")
    return pi_result(repository.replace(document_id, revision, refreshed))


refresh_settings = refresh_issuer


def check_pi_for_review(document: dict) -> None:
    if not all((document.get("bank") or {}).get(key) for key in (
        "BENEFICIARY", "BANK_NAME", "BRANCH", "SWIFT", "ACCOUNT_NUMBER", "BANK_ADDRESS")):
        raise DocumentError("BANK_CONFIGURATION_REQUIRED", "PI 지급 계좌 6항목을 설정한 뒤 문서에 반영하세요")


# 공통 HTTP 흐름에 노출하는 업무 진입점. 기존 내부 함수 이름도 유지한다.
create = create_pi
extract = extract_pi
revise = revise_pi
result = pi_result
check = check_pi_for_review
