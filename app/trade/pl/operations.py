"""PL의 포장 행·원본 합계 비교와 명시적 합계 승인. 금액과 단가를 다루지 않는다."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

from app.trade.common.models import DocumentError
from app.trade.common.operations import calculate, check_revision, revision_context
from app.trade.common.results import document_result, editable_values
from app.trade.common.counterparties import apply_company_profiles
from app.trade.pl.packing_review import (PACKING_SOURCE_FIELDS, apply_approved_packing_totals,
                                     normalize_packing_inputs, packing_total_changes, reconcile_packing)
from app.trade.pl.models import PLInput, PLItem, PLRepository, PackingDecision
from app.trade.common.postprocess import apply_issuer_defaults
from app.trade.review.operations import content_hash


def packing_summary(draft, approved=False):
    normalized = normalize_packing_inputs(draft)
    comparison = reconcile_packing(normalized)
    packages = normalized.get("packages") or []
    package_totals = {key: str(sum(Decimal(str(p.get(key) or 0)) for p in packages)) if packages else None
                      for key in ("net_weight_kg", "gross_weight_kg")}
    return normalized, {**comparison, "packages_total": package_totals,
                        "changes": packing_total_changes(normalized, comparison), "approved": approved}


def finalize(draft, approved=False):
    normalized, _ = packing_summary(draft, approved)
    document = calculate(normalized)
    _, totals = packing_summary(document, approved)
    document["packing_totals"] = totals
    for issue in totals["issues"]:
        message = "Packing: " + issue
        if message not in document["blocking_issues"]:
            document["blocking_issues"].append(message)
    if not approved:
        document["blocking_issues"].append("Confirm packing totals before final review")
    if document["blocking_issues"]:
        document.update(status="needs_input", ready_for_issue=False)
    return document


def prepare_pl(values, context):
    draft = deepcopy(values)
    draft.update(document_type="PL", doc_kind="PL", currency=None, bank=None, issuer=deepcopy(context.issuer))
    apply_issuer_defaults(draft, "PL", context.issuer)
    apply_company_profiles(draft, context.counterparties)
    return finalize(draft)


def result(document):
    values = editable_values(document, PLInput.model_fields, PLItem.model_fields)
    # 사용자는 처음 제시한 합계를 편집한다. 승인으로 계산값이 채워져도 원본은 보존한다.
    values.update(document.get("_packing_original_totals") or {})
    response = document_result(document, PLInput.model_validate(values).model_dump(mode="json"))
    # 컨테이너를 사용하지 않는 선적도 허용한다. 원본에 있을 때만 개수/규격을 검사한다.
    return response.model_copy(update={"missing_fields": [field for field in response.missing_fields if field != "container_count"]})


def create(command: PLInput, *, repository: PLRepository):
    return result(repository.create(prepare_pl(command.model_dump(mode="json"), repository.context(None))))


def extract(text, *, repository: PLRepository, extractor):
    return result(repository.create(prepare_pl(extractor(text), repository.context(None))))


def revise(document_id, revision, command: PLInput, *, repository: PLRepository, review_reference=None):
    previous = repository.get(document_id)
    check_revision(previous, revision)
    context = revision_context(previous, repository.context(None), None)
    document = prepare_pl(command.model_dump(mode="json"), context)
    document["packing_approval_log"] = [*previous.get("packing_approval_log", []),
                                        {"action": "modify", "at": datetime.now(timezone.utc).isoformat()}]
    return result(repository.replace(document_id, revision, document, review_reference))


def packing_review(document_id, *, repository: PLRepository):
    document = repository.get(document_id)
    payload = {"document_id": document_id, "revision": document["revision"], "document": document}
    return {"document_id": document_id, "revision": document["revision"],
            "content_hash": content_hash(payload), "payload": payload}


def decide_packing(document_id, decision: PackingDecision, *, repository: PLRepository):
    previous = repository.get(document_id)
    check_revision(previous, decision.revision)
    payload = {"document_id": document_id, "revision": previous["revision"], "document": previous}
    if content_hash(payload) != decision.content_hash:
        raise DocumentError("PACKING_REVIEW_MISMATCH", "확인한 포장 합계와 현재 내용이 다릅니다")
    if decision.action == "approve":
        try:
            draft = apply_approved_packing_totals(previous)
        except ValueError as error:
            raise DocumentError("PACKING_INVALID", "포장 행의 수량·단위·중량을 먼저 확인하세요", 422) from error
        approved = True
    else:
        draft = deepcopy(previous)
        draft.update(draft.get("_packing_original_totals") or {})
        draft.pop("_packing_approved_quantities", None)
        draft.pop("_packing_totals_approved", None)
        approved = False
    document = finalize(draft, approved)
    document["packing_approval_log"] = [*previous.get("packing_approval_log", []),
        {"action": decision.action, "at": datetime.now(timezone.utc).isoformat()}]
    return result(repository.replace(document_id, decision.revision, document))


def check(document):
    if not (document.get("packing_totals") or {}).get("approved") or document.get("_packing_totals_approved") is not True:
        raise DocumentError("PACKING_APPROVAL_REQUIRED", "원본과 계산 합계를 먼저 확인하고 승인하세요")
    comparison = reconcile_packing(document)
    if comparison["issues"] or comparison["discrepancies"]:
        raise DocumentError("PACKING_INVALID", "포장 합계를 다시 확인하세요")
