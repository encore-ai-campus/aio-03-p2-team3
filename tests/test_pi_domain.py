"""PI의 업무 경계와 독립 실행. FastAPI·기존 메일 그래프 없이 확인한다."""
from copy import deepcopy
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.llm.client import use_backend
from app.trade.common.models import DocumentContext, DocumentError
from app.trade.pi.agent import extract_pi as langchain_extract_pi
from app.trade.pi.models import PIInput
from app.trade.pi.operations import create_pi, extract_pi, get_pi, revise_pi
from app.trade.pi.repository import pi_repository
from tests.fakes.llm import FakeLLM
from tests.fakes.storage import FakeStorage
from tests.test_trade_flow import put_settings


def pi_input(**changes):
    values = {"product_family": "cosmetics", "currency": "USD", "document_number": "PI-100",
              "buyer": {"legal_name": "Acme Trading", "address": "1 Fiction Ave, Seoul"},
              "incoterms": "FOB Busan", "payment_terms": "T/T", "items": [
                  {"product_name": "Virtual Serum", "capacity": "50ml", "quantity": "10", "unit": "PCS",
                   "price_basis": "PCS", "discount_percent": "0"}]}
    values.update(changes)
    return PIInput.model_validate(values)


class MemoryPIRepository:
    def __init__(self):
        self.documents = {}
        self.settings = DocumentContext(
            issuer={"legal_name_en": "Testworks Trading Co", "address": "7 Test-ro, Seoul"},
            bank={key: "Example" for key in ("BENEFICIARY", "BANK_NAME", "BRANCH", "SWIFT", "ACCOUNT_NUMBER", "BANK_ADDRESS")},
            price_rows=[{"id": 1, "role": "sale", "item_name": "Virtual Serum", "capacity": "50ml",
                         "currency": "USD", "unit_price_text": "8", "party_key": "", "price_basis": "PCS"}])

    def context(self, currency):
        return deepcopy(self.settings)

    def create(self, document):
        result = {**deepcopy(document), "trade_doc_id": 1, "doc_no": "PI-TEST-1", "revision": 1}
        self.documents[1] = result
        return deepcopy(result)

    def get(self, document_id):
        return deepcopy(self.documents[document_id])

    def latest_review(self, document_id, revision):
        return {"proposal_id": None, "files": []}

    def replace(self, document_id, revision, document):
        if self.documents[document_id]["revision"] != revision:
            raise DocumentError("REVISION_CONFLICT", "최신 문서 필요")
        result = {**deepcopy(document), "trade_doc_id": document_id, "doc_no": "PI-TEST-1", "revision": revision + 1}
        self.documents[document_id] = result
        return deepcopy(result)


def test_pi_creates_without_database_or_graph_and_preserves_zero_quantity():
    repository = MemoryPIRepository()
    command = pi_input()
    command.items[0].quantity = Decimal("0")
    result = create_pi(command, repository=repository)
    assert result.document_type == "PI" and result.status == "ready"
    assert result.document["items"][0]["master_price"] is True
    assert result.document["total"] == "0.00"


def test_pi_direct_and_extracted_facts_use_the_same_business_calculation():
    command = pi_input()
    direct = create_pi(command, repository=MemoryPIRepository())
    via_ai = extract_pi("source", repository=MemoryPIRepository(),
                        extractor=lambda _: command.model_dump(mode="json"))
    assert direct.document == via_ai.document
    assert direct.document["total"] == "80.00"


def test_pi_revision_uses_snapshot_and_rejects_stale_revision():
    repository = MemoryPIRepository()
    created = create_pi(pi_input(), repository=repository)
    repository.settings.issuer["legal_name_en"] = "Changed Company"
    revised = revise_pi(created.document_id, 1, pi_input(document_number="PI-101"), repository=repository)
    assert revised.revision == 2 and revised.status == "ready"
    assert revised.document["issuer"]["legal_name_en"] == "Testworks Trading Co"
    with pytest.raises(DocumentError, match="최신 PI"):
        revise_pi(created.document_id, 1, pi_input(), repository=repository)


def test_pi_sql_store_is_scoped_to_user_and_document_kind(database):
    put_settings(database, FakeStorage())
    repository = pi_repository(database, 1)
    created = create_pi(pi_input(), repository=repository)
    assert get_pi(created.document_id, repository=repository).document["total"] == "80.00"
    with pytest.raises(DocumentError) as other_user:
        get_pi(created.document_id, repository=pi_repository(database, 2))
    assert other_user.value.code == "DOCUMENT_NOT_FOUND"
    from app.trade.common.repository import SQLDocuments
    with pytest.raises(DocumentError):
        SQLDocuments(database, 1, "PO").get(created.document_id)


def test_pi_input_rejects_server_fields_and_inexact_float():
    values = pi_input().model_dump(mode="json")
    for key in ("status", "issuer", "revision"):
        with pytest.raises(ValidationError):
            PIInput.model_validate({**values, key: "tampered"})
    values["items"][0]["unit_price"] = 0.1
    with pytest.raises(ValidationError):
        PIInput.model_validate(values)


def test_pi_langchain_cannot_authorize_price_override_or_bypass_evidence():
    values = pi_input().model_dump(mode="json")
    values["items"][0].update(unit_price="8", confirm_price_override=True,
                              product_code="INVENTED-CODE", source="Virtual Serum 10 PCS at USD 8")
    values["source_notes"] = ["Virtual Serum"]
    fake = FakeLLM([values])
    with use_backend(fake):
        draft = langchain_extract_pi("Virtual Serum 10 PCS at USD 8")
    assert draft["items"][0]["confirm_price_override"] is False
    assert any("product code" in issue for issue in draft["conflicts"])
    assert any("Buyer address" in issue for issue in draft["conflicts"])
