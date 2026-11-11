"""도메인별 실제 HTTP 업무와 공통 승인 경로. 외부 모델·메일·운영 DB를 호출하지 않는다."""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

import pytest
from pypdf import PdfReader

from app.llm.client import use_backend
from app.trade.pl.models import PLInput
from app.web.deps import current_user_id
from tests.fakes.llm import FakeLLM
from tests.test_pi_api import pi_client, create_pi, propose, decide
from tests.test_pi_domain import pi_input
from tests.test_trade_packing import packing_example


def post(client, path, values, expected=201):
    response = client.post(path, json=values)
    assert response.status_code == expected, response.text
    return response.json()


def review(client, kind, document):
    return post(client, f"/api/trade/{kind}/{document['document_id']}/reviews", {"revision": document["revision"]})


def choice(client, kind, proposal, action, **extra):
    return client.post(f"/api/trade/{kind}/{proposal['document_id']}/reviews/{proposal['id']}/decisions", json={
        "action": action, "revision": proposal["revision"], "content_hash": proposal["content_hash"], **extra})


def packing_choice(client, document, action="approve"):
    base = f"/api/trade/pl/{document['document_id']}/packing-review"
    comparison = client.get(base).json()
    return post(client, base + "/decisions", {"action": action, "revision": comparison["revision"],
                                             "content_hash": comparison["content_hash"]}, expected=200)


def po_values():
    values = pi_input().model_dump(mode="json")
    values["document_number"] = "PO-100"
    values["seller"] = values["buyer"]
    values["buyer"] = {}
    values["items"][0].pop("is_sample")
    return values


def pl_values():
    source = packing_example()
    return PLInput.model_validate({key: value for key, value in source.items() if key in PLInput.model_fields}).model_dump(mode="json")


def ready_document(client, kind):
    if kind == "po":
        assert client.put("/api/trade/settings/prices", json={"item_name": "Virtual Serum", "capacity": "50ml",
            "role": "purchase", "currency": "USD", "unit_price": "3", "price_basis": "PCS"}).status_code == 200
        return post(client, "/api/trade/po", po_values())
    if kind == "ci":
        original = create_pi(client)
        assert decide(client, propose(client, original), "approve").status_code == 200
        return post(client, "/api/trade/ci", {"source_pi_id": original["document_id"], "source_revision": 1,
            "document_number": "CI-100", "shipment_reference": "SHIP-TEST", "country_of_origin": "Republic of Korea"})
    return packing_choice(client, post(client, "/api/trade/pl", pl_values()))


@pytest.mark.parametrize("kind", ["po", "ci", "pl"])
def test_each_domain_cancel_modify_approve_download_and_version_history(pi_client, kind):
    client = pi_client
    document = ready_document(client, kind)
    assert document["status"] == "ready", document
    old = review(client, kind, document)
    cancelled = choice(client, kind, old, "cancel")
    assert cancelled.status_code == 200 and cancelled.json()["files"] == []
    assert choice(client, kind, old, "approve").status_code == 409
    proposal = review(client, kind, document)
    changed = deepcopy(document["input"])
    changed["document_number"] = kind.upper() + "-CHANGED"
    response = choice(client, kind, proposal, "modify", document=changed)
    assert response.status_code == 200, response.text
    assert choice(client, kind, proposal, "approve").status_code == 409
    if kind == "pl":
        modified = response.json()
        assert modified["status"] == "needs_input" and modified["document"]["packing_totals"]["approved"] is False
        approved_totals = packing_choice(client, modified)
        new_proposal = review(client, kind, approved_totals)
    else:
        new_proposal = response.json()
    assert new_proposal["id"] != proposal["id"]
    approved = choice(client, kind, new_proposal, "approve")
    assert approved.status_code == 200, approved.text
    assert choice(client, kind, new_proposal, "approve").json()["files"] == approved.json()["files"]
    for file in approved.json()["files"]:
        download = client.get(file["download_url"])
        assert download.status_code == 200
        if file["file_format"] == "pdf":
            text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(download.content)).pages)
        else:
            with ZipFile(BytesIO(download.content)) as archive:
                text = archive.read("xl/worksheets/sheet1.xml").decode()
        assert kind.upper() + "-CHANGED" in text
        if kind in {"ci", "pl", "po"}:
            assert "BANK INFORMATION" not in text and "000-0000" not in text
    base = f"/api/trade/{kind}/{document['document_id']}"
    assert client.get(base + f"/versions/{document['revision']}").json()["document_number"] == (kind.upper() + "-100" if kind != "pl" else "DRAFT")
    assert client.get(base).json()["files"] == approved.json()["files"]
    assert any(row["document_id"] == document["document_id"] for row in client.get(f"/api/trade/{kind}").json())
    client.app.dependency_overrides[current_user_id] = lambda: 2
    assert client.get(base).status_code == 404
    assert client.get(approved.json()["files"][0]["download_url"]).status_code == 404


def test_po_uses_purchase_price_and_zero_quantity_without_pi_bank(pi_client):
    po = ready_document(pi_client, "po")
    assert po["document"]["total"] == "30.00"  # 판매가 8과 별개로 매입가 3을 적용한다.
    assert po["document"]["buyer"]["legal_name"] == "Testworks Trading Co"
    assert po["document"]["bank"] is None
    values = po["input"]
    values["items"][0]["quantity"] = "0"
    values["items"][0]["paid_quantity"] = "0"
    response = pi_client.put(f"/api/trade/po/{po['document_id']}", json={"revision": 1, "document": values})
    assert response.status_code == 200 and response.json()["document"]["total"] == "0.00"
    assert pi_client.get(f"/api/trade/pi/{po['document_id']}").status_code == 404


def test_ci_is_bound_to_approved_pi_version_and_ignores_new_catalog_price(pi_client):
    values = pi_input().model_dump(mode="json")
    values["items"][0].update(discount_percent="10", promotion="2+1")
    original = create_pi(pi_client, values)
    source = {"source_pi_id": original["document_id"], "source_revision": 1,
              "document_number": "CI-BOUND", "shipment_reference": "SHIP", "country_of_origin": "Korea"}
    assert pi_client.post("/api/trade/ci", json=source).status_code == 409
    assert decide(pi_client, propose(pi_client, original), "approve").status_code == 200
    assert pi_client.put("/api/trade/settings/prices", json={"item_name": "Virtual Serum", "capacity": "50ml",
        "role": "sale", "currency": "USD", "unit_price": "99", "price_basis": "PCS"}).status_code == 200
    ci = post(pi_client, "/api/trade/ci", source)
    assert ci["status"] == "ready", ci
    assert ci["document"]["total"] == original["document"]["total"] == "72.00"
    assert ci["document"]["items"][0]["unit_price"] == "8"
    assert ci["document"]["items"][0]["free_quantity"] == "5"
    assert ci["document"]["bank"] is None and ci["document"]["payment_terms"] == "N/A"
    assert pi_client.post("/api/trade/ci", json={**source, "items": []}).status_code == 422
    changed_pi = original["input"]
    changed_pi["document_number"] = "PI-NEW"
    changed_pi["items"][0].update(unit_price="20", confirm_price_override=True)
    updated = pi_client.put(f"/api/trade/pi/{original['document_id']}", json={"revision": 1, "document": changed_pi}).json()
    assert updated["revision"] == 2
    still_original = post(pi_client, "/api/trade/ci", {**source, "document_number": "CI-OLD-VERSION"})
    assert still_original["document"]["total"] == "72.00"
    assert pi_client.put(f"/api/trade/ci/{ci['document_id']}", json={"revision": 1,
        "document": {**source, "source_revision": 2}}).status_code == 409
    pi_client.app.dependency_overrides[current_user_id] = lambda: 2
    assert pi_client.post("/api/trade/ci", json=source).status_code == 404


def test_ci_preserves_zero_price_sample_and_prints_foc_once(pi_client):
    values = pi_input().model_dump(mode="json")
    values["items"][0].update(promotion="2+1")
    values["items"].append({"product_name": "Manual Sample", "quantity": "2", "unit": "PCS",
                            "unit_price": "0", "is_sample": True})
    original = create_pi(pi_client, values)
    assert decide(pi_client, propose(pi_client, original), "approve").status_code == 200
    ci = post(pi_client, "/api/trade/ci", {"source_pi_id": original["document_id"], "source_revision": 1,
        "document_number": "CI-FOC", "shipment_reference": "SHIP", "country_of_origin": "Korea"})
    assert ci["status"] == "ready", ci
    assert ci["document"]["items"][1]["line_total"] == "0.00"
    approved = choice(pi_client, "ci", review(pi_client, "ci", ci), "approve").json()
    pdf = next(file for file in approved["files"] if file["file_format"] == "pdf")
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pi_client.get(pdf["download_url"]).content)).pages)
    assert "10+5" in text.replace(" ", "") and "15+5" not in text.replace(" ", "")


def test_pl_totals_need_explicit_review_preserve_units_source_and_reset_on_edit(pi_client):
    values = pl_values()
    values["container_count"] = "5 x 40FT Containers"
    pl = post(pi_client, "/api/trade/pl", values)
    assert pl["status"] == "needs_input"
    assert pi_client.post(f"/api/trade/pl/{pl['document_id']}/reviews", json={"revision": 1}).status_code == 409
    approved = packing_choice(pi_client, pl)
    assert approved["status"] == "ready", approved
    doc = approved["document"]
    assert doc["container_count"] == "5"
    assert doc["packing_totals"]["quantities"] == {"PCS": "616001", "KG": "2399.48"}
    assert doc["_packing_original_totals"]["declared_total_quantity"] == "618400"
    assert doc["declared_volume_cbm"] == "35.477"
    cancelled = packing_choice(pi_client, approved, "cancel")
    assert cancelled["status"] == "needs_input"
    assert cancelled["document"]["declared_volume_cbm"] == "35.475"
    assert cancelled["document"]["_packing_original_totals"]["container_count"] == "5 x 40FT Containers"
    values["items"][0]["gross_weight_kg"] = "1"
    revised = pi_client.put(f"/api/trade/pl/{pl['document_id']}", json={"revision": cancelled["revision"], "document": values}).json()
    comparison = pi_client.get(f"/api/trade/pl/{pl['document_id']}/packing-review").json()
    assert pi_client.post(f"/api/trade/pl/{pl['document_id']}/packing-review/decisions", json={
        "action": "approve", "revision": revised["revision"], "content_hash": comparison["content_hash"]}).status_code == 422


@pytest.mark.parametrize("kind", ["po", "pl", "ci"])
def test_domain_langchain_entry_points_are_used_by_http(pi_client, kind):
    source_fields = {}
    if kind == "po":
        ready_document(pi_client, "po")  # 매입 단가 설정을 준비한다.
        values = po_values()
        values["items"][0]["source"] = "Virtual Serum 10 PCS USD discount 0"
        text = "Acme Trading 1 Fiction Ave, Seoul PO-100 FOB Busan T/T Virtual Serum 10 PCS USD discount 0"
    elif kind == "pl":
        values = pl_values()
        text = "DRAFT Buyer Address Testworks Trading Co. Ltd Seoul EXW Cyberjaya Reference "
        for item in values["items"]:
            item["source"] = f"{item['product_name']} {item['quantity']} {item['unit']}"
            text += item["source"] + " "
    else:
        original = create_pi(pi_client)
        assert decide(pi_client, propose(pi_client, original), "approve").status_code == 200
        source_fields = {"source_pi_id": original["document_id"], "source_revision": 1}
        values = {"document_number": "CI-AI", "shipment_reference": "SHIP", "country_of_origin": "Korea"}
        text = "CI-AI SHIP Korea"
    fake = FakeLLM([values])
    with use_backend(fake):
        result = post(pi_client, f"/api/trade/{kind}/extract", {"text": text, **source_fields})
    assert len(fake.calls) == 1 and fake.schemas[0].__name__ == kind.upper() + "Extraction"
    assert result["document_type"] == kind.upper()
    assert result["status"] == ("needs_input" if kind == "pl" else "ready"), result


def test_pi_currency_revision_reprices_and_renders_the_selected_bank_currency(pi_client):
    original = create_pi(pi_client)
    bank = {"beneficiary": "Testworks Trading", "bank_name": "Euro Example Bank", "branch": "Branch",
            "swift": "EXAMPLE", "account_number": "EUR-000", "bank_address": "1 Bank Avenue"}
    assert pi_client.put("/api/trade/settings/banks/EUR", json=bank).status_code == 200
    assert pi_client.put("/api/trade/settings/prices", json={"item_name": "Virtual Serum", "capacity": "50ml",
        "role": "sale", "currency": "EUR", "unit_price": "6", "price_basis": "PCS"}).status_code == 200
    values = original["input"]
    values["currency"] = "EUR"
    updated = pi_client.put(f"/api/trade/pi/{original['document_id']}", json={"revision": 1, "document": values})
    assert updated.status_code == 200 and updated.json()["document"]["total"] == "60.00", updated.text
    approved = decide(pi_client, propose(pi_client, updated.json()), "approve").json()
    for file in approved["files"]:
        content = pi_client.get(file["download_url"]).content
        if file["file_format"] == "pdf":
            text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)
        else:
            with ZipFile(BytesIO(content)) as archive:
                text = archive.read("xl/worksheets/sheet1.xml").decode()
        assert "EUR" in text and "EUR-000" in text and "(USD)" not in text


def test_existing_ci_without_linked_pi_is_readable_and_requires_source_selection(pi_client):
    from app.db.models import TradeDocument
    with pi_client.app.state.database.session() as session:
        row = TradeDocument(user_id=1, doc_kind="CI", doc_no="LEGACY-CI", thread_id="old-thread", run_id="",
                            draft={"document_type": "CI", "document_number": "LEGACY-CI", "total": "80.00"},
                            status="ready", revision=1)
        session.add(row)
        session.flush()
        document_id = row.id
    response = pi_client.get(f"/api/trade/ci/{document_id}")
    assert response.status_code == 200 and response.json()["status"] == "needs_input"
    assert "source_pi_id" in response.json()["missing_fields"]
    assert pi_client.post(f"/api/trade/ci/{document_id}/reviews", json={"revision": 1}).status_code == 409


def test_ai_cannot_turn_an_ordinary_product_into_a_manual_sample(pi_client):
    values = pi_input().model_dump(mode="json")
    values["items"][0].update(is_sample=True, unit_price="9", source="Virtual Serum 10 PCS USD 9 discount 0")
    fake = FakeLLM([values])
    with use_backend(fake):
        result = post(pi_client, "/api/trade/pi/extract", {"text":
            "Acme Trading 1 Fiction Ave, Seoul PI-100 FOB Busan T/T Virtual Serum 10 PCS USD 9 discount 0"})
    assert result["status"] == "needs_input"
    assert result["document"]["items"][0]["is_sample"] is False
    assert result["document"]["items"][0]["price_override_confirmed"] is False
    assert any("sample designation" in issue["message"] for issue in result["issues"])
