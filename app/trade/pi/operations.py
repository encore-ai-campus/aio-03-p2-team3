"""PI 업무: 입력 → 가격·계산·검증 → 주입받은 저장소. HTTP·ORM·모델 생성과 분리한다."""
from copy import deepcopy
from typing import Callable

from app.trade.common.models import DocumentContext, DocumentError, DocumentResult, DocumentSummary
from app.trade.common import operations as common
from app.trade.common.results import document_result, editable_values
from app.trade.pi.models import PIInput, PIItem, PIRepository
from app.trade.pi.samples import update_sample


def prepare_pi(values: dict, context: DocumentContext) -> dict:
    draft = deepcopy(values)
    for item in draft.get("items", []):
        if item.get("is_sample") is True:
            update_sample(item, name=item.get("product_name"), capacity=item.get("capacity"),
                          quantity=item.get("quantity") if item.get("quantity") is not None else item.get("paid_quantity"),
                          unit=item.get("unit"), price=item.get("unit_price"))
            if item.get("discount_percent") is None:
                item["discount_percent"] = "0"
    result = common.prepare_priced(draft, context, "PI")
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
    values = common.revision_values(previous, command)
    context = common.revision_context(previous, repository.context(command.currency), command.currency)
    document = prepare_pi(values, context)
    if review_reference is not None:
        return pi_result(repository.replace(document_id, revision, document, review_reference))
    return pi_result(repository.replace(document_id, revision, document))


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
