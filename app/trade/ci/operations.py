"""CI: 승인된 PI 버전의 거래 사실과 금액을 보존하고 선적 정보만 보완한다."""
from copy import deepcopy

from app.trade.ci.models import CIInput, CIRepository
from app.trade.ci.imports import ci_import_issues, is_pi_import, prepare_ci_import
from app.trade.common.models import DocumentError
from app.trade.common.operations import calculate, check_revision
from app.trade.common.results import document_result


def prepare_ci(command: CIInput, source, conflicts=()):
    draft = deepcopy(source)
    for key in ("trade_doc_id", "doc_no", "revision", "bank", "proposal_id", "files"):
        draft.pop(key, None)
    draft.update(document_type="PI", source_document_type="PI", source_total=source["total"])
    for item in draft.get("items", []):
        item["source_line_total"] = item["line_total"]
        item["source"] = f"Approved PI {command.source_pi_id} revision {command.source_revision}; FOC if unit price is zero"
    values = command.model_dump(mode="json")
    # CI 문서번호는 따로 명시한다. 나머지 미지정 항목만 원본에서 가져온다.
    draft["document_number"] = values.pop("document_number")
    for key, value in values.items():
        if value is not None or key in {"shipment_reference", "country_of_origin"}:
            draft[key] = value
    draft = prepare_ci_import(draft, requested_type="CI", has_attachments=True)
    draft["bank"] = None
    draft["conflicts"] = list(conflicts)
    document = calculate(draft)
    document["blocking_issues"].extend(ci_import_issues(document))
    if document["blocking_issues"]:
        document.update(status="needs_input", ready_for_issue=False)
    return document


def result(document):
    values = {key: document.get(key) for key in CIInput.model_fields}
    if not values.get("source_pi_id") or not values.get("source_revision"):
        # 이전 메일 경로는 PI 원문만 보관했다. 조회를 막지 않고 새 API의 원본 선택을 요구한다.
        response = document_result(document, values)
        return response.model_copy(update={"status": "needs_input",
            "missing_fields": [*response.missing_fields, "source_pi_id", "source_revision"],
            "issues": [*response.issues, {"code": "SOURCE_PI_SELECTION_REQUIRED", "message": "승인된 원본 PI 버전을 선택하세요"}]})
    return document_result(document, CIInput.model_validate(values).model_dump(mode="json"))


def create(command: CIInput, *, repository: CIRepository):
    source = repository.source_pi(command.source_pi_id, command.source_revision)
    return result(repository.create(prepare_ci(command, source)))


def extract(text, *, repository: CIRepository, extractor, source_pi_id, source_revision):
    values = extractor(text)
    command = CIInput.model_validate({**{key: value for key, value in values.items() if key in CIInput.model_fields},
                                      "source_pi_id": source_pi_id, "source_revision": source_revision})
    document = prepare_ci(command, repository.source_pi(source_pi_id, source_revision), values.get("conflicts", []))
    return result(repository.create(document))


def revise(document_id, revision, command: CIInput, *, repository: CIRepository, review_reference=None):
    previous = repository.get(document_id)
    check_revision(previous, revision)
    if previous.get("source_pi_id") and (previous["source_pi_id"], previous["source_revision"]) != (command.source_pi_id, command.source_revision):
        raise DocumentError("SOURCE_PI_CHANGE_REQUIRES_NEW_CI", "다른 PI 버전은 새 CI로 작성하세요")
    document = prepare_ci(command, repository.source_pi(command.source_pi_id, command.source_revision))
    return result(repository.replace(document_id, revision, document, review_reference))


def check(document):
    if not is_pi_import(document) or not document.get("source_pi_id") or ci_import_issues(document):
        raise DocumentError("CI_SOURCE_INVALID", "원본 PI 버전과 거래 금액을 확인하세요")
