"""PO: 발행사는 구매자이며 공급처의 매입 단가를 적용한다."""
from app.trade.common import operations as common
from app.trade.common.results import document_result, editable_values
from app.trade.po.models import POInput, POItem, PORepository
from app.trade.common.counterparties import name_key
from app.trade.common.models import DocumentError


def prepare_po(values, context):
    document = common.prepare_priced(values, context, "PO")
    document["bank"] = None
    return document


def result(document):
    values = editable_values(document, POInput.model_fields, POItem.model_fields)
    return document_result(document, POInput.model_validate(values).model_dump(mode="json"))


def create(command: POInput, *, repository: PORepository):
    return result(repository.create(prepare_po(command.model_dump(mode="json"), repository.context(command.currency))))


def extract(text, *, repository: PORepository, extractor):
    values = extractor(text)
    return result(repository.create(prepare_po(values, repository.context(values.get("currency")))))


def revise(document_id, revision, command: POInput, *, repository: PORepository, review_reference=None):
    previous = repository.get(document_id)
    common.check_revision(previous, revision)
    context = common.revision_context(previous, repository.context(command.currency), command.currency)
    document = prepare_po(common.revision_values(previous, command), context)
    return result(repository.replace(document_id, revision, document, review_reference))


def check(document):
    issuer = document.get("issuer") or {}
    issuer_key = name_key(issuer.get("legal_name_en") or issuer.get("company_name"))
    if not issuer_key or issuer_key not in name_key((document.get("buyer") or {}).get("legal_name")):
        raise DocumentError("PO_BUYER_REQUIRED", "PO 구매자는 발행 회사여야 합니다")
