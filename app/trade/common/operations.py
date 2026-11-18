"""PO/PI가 함께 사용하는 가격 준비와 문서 조회. 문서별 승인 규칙은 각 업무에 둔다."""
from copy import deepcopy

from app.trade.common.models import DocumentContext, DocumentError, DocumentSummary
from app.trade.common.counterparties import apply_company_profiles, name_key
from app.trade.common.postprocess import apply_issuer_defaults, synchronize_quantities
from app.trade.common.pricing import build_trade_catalog, apply_verified_catalog_prices
from app.trade.common.results import editable_values
from app.trade.common.trade_documents import validate_and_calculate


def calculate(draft):
    issuer = draft.get("issuer") or {}
    try:
        return validate_and_calculate(draft, issuer_key=name_key(
            issuer.get("legal_name_en") or issuer.get("company_name")))
    except ArithmeticError as error:
        raise DocumentError("NUMERIC_RANGE_EXCEEDED", "수량과 금액의 범위 또는 소수 자릿수를 확인하세요", 422) from error


def prepare_priced(values, context, document_type):
    draft = deepcopy(values)
    draft.update(document_type=document_type, doc_kind=document_type,
                 issuer=deepcopy(context.issuer), bank=deepcopy(context.bank))
    apply_issuer_defaults(draft, document_type, context.issuer)
    apply_company_profiles(draft, context.counterparties)
    for item in draft.get("items", []):
        override = item.pop("confirm_price_override", False)
        item["price_override_confirmed"] = override is True or item.get("price_override_confirmed") is True
        if item.get("unit_price") is not None:
            item.setdefault("price_source", "User-confirmed transaction-specific override" if override else "Entered document value")
    synchronize_quantities(draft)
    apply_verified_catalog_prices(draft, build_trade_catalog(context.price_rows))
    return calculate(draft)


def revision_values(previous, command):
    """상품·통화가 바뀌면 이전 문서의 가격을 새 거래에 그대로 적용하지 않는다."""
    values = command.model_dump(mode="json")
    for index, item in enumerate(values["items"]):
        old = (previous.get("items") or [])[index] if index < len(previous.get("items") or []) else {}
        changed = any(item.get(key) != old.get(key) for key in ("product_name", "product_code", "capacity", "unit"))
        if (previous.get("currency") != command.currency or changed) and not item.get("confirm_price_override"):
            item["unit_price"] = None
    return values


def revision_context(previous, context, currency):
    issuer = {**context.issuer, **{key: value for key, value in (previous.get("issuer") or {}).items()
                                 if value not in (None, "")}}
    bank = context.bank
    if previous.get("currency") == currency:
        bank = {**(bank or {}), **{key: value for key, value in (previous.get("bank") or {}).items()
                                 if value not in (None, "")}} or None
    return DocumentContext(issuer=issuer, bank=bank, price_rows=context.price_rows, counterparties=context.counterparties)


def refresh_settings_values(previous, context, document_type, input_model, item_model):
    """Build editable values with current settings while retaining explicit transaction data."""
    values = editable_values(previous, input_model.model_fields, item_model.model_fields)
    values["_company_profile"] = deepcopy(previous.get("_company_profile") or {})
    role = "buyer" if document_type == "PO" else "seller"
    old_issuer = previous.get("issuer") or {}
    new_issuer = context.issuer or {}
    old_name = next((old_issuer.get(key) for key in ("legal_name_en", "legal_name", "company_name")
                     if old_issuer.get(key)), None)
    new_name = next((new_issuer.get(key) for key in ("legal_name_en", "legal_name", "company_name")
                     if new_issuer.get(key)), None)
    defaults = {"legal_name": new_name, **{key: new_issuer.get(key) for key in ("address", "contact", "phone", "email")}}
    old_defaults = {"legal_name": old_name, **{key: old_issuer.get(key) for key in ("address", "contact", "phone", "email")}}
    party = values.setdefault(role, {})
    for key, value in defaults.items():
        if value and (not party.get(key) or party.get(key) == old_defaults.get(key)):
            party[key] = value
    for index, item in enumerate(values.get("items", [])):
        old_item = (previous.get("items") or [])[index] if index < len(previous.get("items") or []) else {}
        item["price_source"] = old_item.get("price_source")
        item["master_price"] = old_item.get("master_price") is True
        item["confirm_price_override"] = old_item.get("price_override_confirmed") is True
        if old_item.get("master_price") is True and old_item.get("price_override_confirmed") is not True:
            item["unit_price"] = None
        elif item.get("unit_price") not in (None, ""):
            # Applying settings refreshes the catalog, not a manually entered price.
            item["confirm_price_override"] = True
    return values


def check_revision(previous, revision):
    if previous["revision"] != revision:
        raise DocumentError("REVISION_CONFLICT", "최신 문서를 다시 확인하세요")


def get_document(document_id, *, repository, result):
    response = result(repository.get(document_id))
    return response.model_copy(update=repository.latest_review(document_id, response.revision))


# 문서함 거래처 표시: 수출 증빙(PI·CI·PL)은 buyer, 구매(PO)는 seller가 상대다.
COUNTERPARTY_FIELD = {"PI": "buyer", "PO": "seller", "CI": "buyer", "PL": "buyer"}


def counterparty_name(doc):
    party = doc.get(COUNTERPARTY_FIELD.get(doc.get("document_type"), "buyer"), {})
    return party.get("legal_name") if isinstance(party, dict) else None


def list_documents(*, repository):
    return [DocumentSummary(document_id=doc["trade_doc_id"], document_type=doc["document_type"],
                            document_number=doc.get("document_number"), doc_no=doc["doc_no"],
                            revision=doc["revision"], status=doc["status"], currency=doc.get("currency"),
                            total=doc.get("total"), counterparty=counterparty_name(doc),
                            created_at=doc.get("created_at")) for doc in repository.list()]


def get_version(document_id, revision, *, repository):
    return repository.version(document_id, revision)
