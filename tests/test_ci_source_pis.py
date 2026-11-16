"""CI 읽기 목록: 세 상태·정확한 버전·소유권·페이지 조회. 생성 승인 규칙은 유지한다."""
from copy import deepcopy
from hashlib import sha256
from uuid import uuid4

from app.auth.deps import current_user_id
from app.db.models import TradeDocument, TradeDocumentVersion, TradeProposal
from tests.test_pi_api import pi_client, create_pi, propose, decide
from tests.test_pi_domain import pi_input
from tests.test_trade_domain_api import review, choice
from app.llm.client import use_backend
from tests.fakes.llm import FakeLLM


def test_source_list_includes_incomplete_unapproved_and_approved_versions(pi_client):
    client = pi_client
    assert client.get("/api/trade/ci/source-pis").json() == {"items": [], "next_cursor": None}
    values = pi_input().model_dump(mode="json")
    values["document_number"] = "PI-INCOMPLETE"
    values["buyer"]["address"] = None
    incomplete = client.post("/api/trade/pi", json=values).json()
    assert incomplete["status"] == "needs_input"
    ready = create_pi(client)
    old_values = pi_input().model_dump(mode="json")
    old_values["document_number"] = "PI-APPROVED"
    old_values["items"][0].update(discount_percent="10", promotion="2+1")
    old = create_pi(client, old_values)
    proposal = propose(client, old)
    assert decide(client, proposal, "approve").status_code == 200
    with client.app.state.database.session() as session:
        session.add(TradeProposal(id=uuid4().hex, user_id=1, document_id=old["document_id"], revision=1,
                                  payload=proposal["payload"], content_hash=proposal["content_hash"],
                                  status="approved", decision="approve"))
    updated_input = deepcopy(old["input"])
    updated_input["items"][0].update(unit_price="20", confirm_price_override=True)
    response = client.put(f"/api/trade/pi/{old['document_id']}", json={"revision": 1, "document": updated_input})
    assert response.status_code == 200
    response = client.get("/api/trade/ci/source-pis")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    items = response.json()["items"]
    by_version = {(row["source_pi_id"], row["source_revision"]): row for row in items}
    assert len(items) == len(by_version) == 3
    assert by_version[incomplete["document_id"], 1]["missing_fields"]
    assert not by_version[incomplete["document_id"], 1]["approved"]
    assert not by_version[ready["document_id"], 1]["approved"]
    assert not by_version[old["document_id"], 2]["approved"]
    assert (old["document_id"], 1) not in by_version
    previous = client.get(f"/api/trade/ci/source-pis?source_pi_id={old['document_id']}&source_revision=1").json()["items"][0]
    assert previous["approved"] and previous["current_revision"] == 2
    assert previous["total"] == old["document"]["total"]
    source = {"source_pi_id": ready["document_id"], "source_revision": 1, "document_number": "CI-DEMO"}
    assert client.post("/api/trade/ci", json=source).status_code == 409
    assert client.get("/api/trade/ci").json() == []
    assert client.get(f"/api/trade/ci/source-pis?source_pi_id={old['document_id']}&source_revision=1").json()["items"] == [previous]
    # 새 revision 수정 뒤에도 목록에서 선택한 옛 승인 버전으로 발급한다.
    created = client.post("/api/trade/ci", json={"source_pi_id": old["document_id"], "source_revision": 1,
        "document_number": "CI-OLD", "shipment_reference": "SHIP", "country_of_origin": "Korea"}).json()
    assert created["status"] == "ready"
    assert created["document"]["total"] == "72.00"
    assert created["document"]["items"][0]["free_quantity"] == "5"
    issued = choice(client, "ci", review(client, "ci", created), "approve")
    assert issued.status_code == 200, issued.text
    assert {file["file_format"] for file in issued.json()["files"]} == {"pdf", "xlsx"}
    for file in issued.json()["files"]:
        download = client.get(file["download_url"])
        assert download.status_code == 200
        assert sha256(download.content).hexdigest() == file["content_hash"]
    client.app.dependency_overrides[current_user_id] = lambda: 2
    assert client.get("/api/trade/ci/source-pis").json()["items"] == []
    assert client.get(f"/api/trade/ci/source-pis?source_pi_id={old['document_id']}&source_revision=1").status_code == 404
    assert client.get(f"/api/trade/pi/{old['document_id']}/versions/1").status_code == 404
    assert client.post("/api/trade/ci", json=source).status_code == 404


def test_source_list_pages_and_validates_queries_without_changing_versions(pi_client):
    client = pi_client
    created = create_pi(client)
    document_id = created["document_id"]
    with client.app.state.database.session() as session:
        document = session.get(TradeDocument, document_id)
        payload = {**deepcopy(created["document"]), "revision": 2, "document_number": "PI-LATEST"}
        session.add(TradeDocumentVersion(document_id=document_id, user_id=1, revision=2, payload=payload))
        document.revision = 2
        document.draft = payload
        ids = [document_id]
        for number in range(2, 56):
            row = TradeDocument(user_id=1, thread_id="test", run_id="test", doc_kind="PI",
                                doc_no=f"PI-LIST-{number}", draft=deepcopy(payload), revision=1, status="ready")
            session.add(row)
            session.flush()
            ids.append(row.id)
            session.add(TradeDocumentVersion(document_id=row.id, user_id=1, revision=1, payload=deepcopy(payload)))
    first = client.get("/api/trade/ci/source-pis").json()
    assert len(first["items"]) == 50 and first["next_cursor"] == f"{ids[5]}:1"
    assert first["items"][0]["source_pi_id"] == ids[-1]
    second = client.get("/api/trade/ci/source-pis", params={"cursor": first["next_cursor"]}).json()
    assert [row["source_pi_id"] for row in second["items"]] == list(reversed(ids[:5]))
    assert second["items"][-1]["source_revision"] == 2
    assert second["next_cursor"] is None
    assert client.get(f"/api/trade/ci/source-pis?source_pi_id={document_id}&source_revision=1").json()["items"][0]["source_revision"] == 1
    for query in ["cursor=", "cursor=0:1", "cursor=1:-1", "cursor=1:2:3", "cursor=2147483648:1",
                  "source_pi_id=1", "source_revision=1", "source_pi_id=0&source_revision=1",
                  "cursor=1:1&source_pi_id=1&source_revision=1"]:
        assert client.get(f"/api/trade/ci/source-pis?{query}").status_code == 422, query
    assert client.get(f"/api/trade/pi/{document_id}").json()["revision"] == 2
    assert client.get("/api/trade/ci").json() == []


def test_extract_rejects_unapproved_and_foreign_pi_before_model_call(pi_client):
    client = pi_client
    source = create_pi(client)
    command = {"source_pi_id": source["document_id"], "source_revision": 1, "text": "CI-CHECK SHIP Korea"}
    fake = FakeLLM([{"document_number": "CI-CHECK", "shipment_reference": "SHIP", "country_of_origin": "Korea"}])
    with use_backend(fake):
        assert client.post("/api/trade/ci/extract", json=command).status_code == 409
        assert fake.calls == []
        client.app.dependency_overrides[current_user_id] = lambda: 2
        assert client.post("/api/trade/ci/extract", json=command).status_code == 404
        assert fake.calls == []
        client.app.dependency_overrides[current_user_id] = lambda: 1
        assert decide(client, propose(client, source), "approve").status_code == 200
        response = client.post("/api/trade/ci/extract", json=command)
        assert response.status_code == 201, response.text
        assert len(fake.calls) == 1
