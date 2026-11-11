"""새 도메인 업무는 HTTP·구체 DB 없이도 같은 결과와 승인 규칙을 사용한다."""
from copy import deepcopy

from app.trade.ci import operations as ci
from app.trade.ci.models import CIInput
from app.trade.pi.operations import create_pi
from app.trade.pl import operations as pl
from app.trade.pl.models import PLInput, PackingDecision
from app.trade.po import operations as po
from app.trade.po.models import POInput
from tests.test_pi_domain import MemoryPIRepository, pi_input
from tests.test_trade_domain_api import pl_values, po_values


class MemoryDocuments(MemoryPIRepository):
    def replace(self, document_id, revision, document, review_reference=None):
        return super().replace(document_id, revision, document)


def test_po_direct_and_ai_facts_use_purchase_price_without_http_or_sql():
    def repository():
        repo = MemoryDocuments()
        repo.settings.price_rows.append({**repo.settings.price_rows[0], "id": 2, "role": "purchase", "unit_price_text": "3"})
        return repo
    command = POInput.model_validate(po_values())
    direct = po.create(command, repository=repository())
    extracted = po.extract("source", repository=repository(), extractor=lambda _: command.model_dump(mode="json"))
    assert direct.document == extracted.document and direct.document["total"] == "30.00"


def test_ci_uses_source_snapshot_even_when_context_has_a_different_price():
    source = create_pi(pi_input(), repository=MemoryDocuments()).document
    class Repository(MemoryDocuments):
        def source_pi(self, document_id, revision):
            assert (document_id, revision) == (10, 3)
            return deepcopy(source)
        def context(self, currency):
            raise AssertionError("CI must not select today's catalog or bank")
    command = CIInput(source_pi_id=10, source_revision=3, document_number="CI-TEST",
                      shipment_reference="SHIP", country_of_origin="Korea")
    direct = ci.create(command, repository=Repository())
    extracted = ci.extract("source", repository=Repository(), source_pi_id=10, source_revision=3,
                           extractor=lambda _: {"document_number": "CI-TEST", "shipment_reference": "SHIP", "country_of_origin": "Korea"})
    assert direct.document == extracted.document and direct.document["total"] == "80.00"
    assert direct.document["bank"] is None


def test_pl_keeps_source_totals_until_a_bound_explicit_decision():
    command = PLInput.model_validate(pl_values())
    repository = MemoryDocuments()
    direct = pl.create(command, repository=repository)
    extracted = pl.extract("source", repository=MemoryDocuments(), extractor=lambda _: command.model_dump(mode="json"))
    assert direct.document == extracted.document and direct.status == "needs_input"
    before = deepcopy(direct.document)
    proposal = pl.packing_review(1, repository=repository)
    approved = pl.decide_packing(1, PackingDecision(action="approve", revision=1, content_hash=proposal["content_hash"]), repository=repository)
    assert approved.status == "ready"
    assert approved.document["_packing_original_totals"]["declared_volume_cbm"] == before["declared_volume_cbm"]
    assert direct.document == before
