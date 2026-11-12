"""React가 쓰는 실제 ASGI 요청으로 설정 → 작성 → 검토/선택 → 파일을 확인한다."""
from hashlib import sha256
from contextlib import contextmanager
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import func, select

from app.config import Settings
from app.db.models import TradeArtifact, TradeDocument, TradeDocumentVersion, TradeProposal, User
from app.main import create_app
from app.web.deps import current_user_id
from tests.fakes.storage import FakeStorage
from tests.test_pi_domain import pi_input
from tests.test_trade_flow import seal_png


@contextmanager
def configured_client(database_url):
    app = create_app(Settings(database_url=database_url, session_secret="fake-test-session-key"),
                     storage=FakeStorage())  # 회사 이미지는 Storage에서 읽는다(계획 9절)
    app.dependency_overrides[current_user_id] = lambda: 1
    with TestClient(app) as client:
        with app.state.database.session() as session:
            session.add_all([User(id=1, google_sub="fake-sub-1", email="one@example.invalid"),
                             User(id=2, google_sub="fake-sub-2", email="two@example.invalid")])
        client.headers["X-CSRF-Token"] = client.get("/api/session").json()["csrf_token"]
        assert client.put("/api/trade/settings/company", json={
            "company_name": "Testworks Trading", "legal_name_en": "Testworks Trading Co",
            "address": "7 Test-ro, Seoul", "ceo_name": "Example Signer"}).status_code == 200
        assert client.put("/api/trade/settings/banks/USD", json={
            "beneficiary": "Testworks Trading", "bank_name": "Example Bank", "branch": "Example Branch",
            "swift": "EXAMPLE", "account_number": "000-0000", "bank_address": "1 Bank-ro, Seoul"}).status_code == 200
        assert client.put("/api/trade/settings/prices", json={
            "item_name": "Virtual Serum", "capacity": "50ml", "role": "sale", "currency": "USD",
            "unit_price": "8", "price_basis": "PCS"}).status_code == 200
        assert client.post("/api/trade/settings/branding/seal", files={
            "image": ("seal.png", seal_png(), "image/png")}).status_code == 200
        yield client


@pytest.fixture
def pi_client(database_url):
    with configured_client(database_url) as client:
        yield client


def create_pi(client, values=None):
    response = client.post("/api/trade/pi", json=values or pi_input().model_dump(mode="json"))
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "ready", response.text
    return response.json()


def propose(client, document):
    response = client.post(f"/api/trade/pi/{document['document_id']}/reviews", json={"revision": document["revision"]})
    assert response.status_code == 201, response.text
    return response.json()


def decide(client, proposal, action, **extra):
    return client.post(f"/api/trade/pi/{proposal['document_id']}/reviews/{proposal['id']}/decisions", json={
        "action": action, "revision": proposal["revision"], "content_hash": proposal["content_hash"], **extra})


def test_pi_http_end_to_end_approval_and_idempotent_download(pi_client):
    client = pi_client
    created = create_pi(client)
    assert client.get("/api/trade/pi").json()[0]["document_id"] == created["document_id"]
    proposal = propose(client, created)
    assert "branding" not in proposal  # 이미지 bytes는 응답에 노출하지 않는다.
    response = decide(client, proposal, "approve")
    assert response.status_code == 200, response.text
    approved = response.json()
    assert approved["status"] == "approved" and approved["decision"] == "approve"
    assert {file["file_format"] for file in approved["files"]} == {"pdf", "xlsx"}
    for file in approved["files"]:
        download = client.get(file["download_url"])
        assert download.status_code == 200
        assert sha256(download.content).hexdigest() == file["content_hash"]
        assert download.headers["cache-control"] == "private, no-store"
        if file["file_format"] == "pdf":
            text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(download.content)).pages)
            assert "PI-100" in text and "80.00" in text and "APPROVED DOCUMENT" in text
            assert "DRAFT - NOT FOR ISSUE" not in text
        else:
            with ZipFile(BytesIO(download.content)) as archive:
                sheet = archive.read("xl/worksheets/sheet1.xml").decode()
            assert "PI-100" in sheet and "$80.00" in sheet
    repeated = decide(client, proposal, "approve")
    assert repeated.status_code == 200
    assert repeated.json()["files"] == approved["files"]
    with client.app.state.database.session() as session:
        assert session.scalar(select(func.count()).select_from(TradeArtifact)) == 2
        assert session.get(TradeDocument, created["document_id"]).status == "issued"


def test_cancel_is_normal_and_keeps_document_without_files(pi_client):
    created = create_pi(pi_client)
    proposal = propose(pi_client, created)
    cancelled = decide(pi_client, proposal, "cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["files"] == []
    assert decide(pi_client, proposal, "cancel").status_code == 200
    assert decide(pi_client, proposal, "approve").status_code == 409
    assert pi_client.get(f"/api/trade/pi/{created['document_id']}").json()["status"] == "ready"
    with pi_client.app.state.database.session() as session:
        assert session.scalar(select(func.count()).select_from(TradeArtifact)) == 0


def test_modify_creates_new_proposal_and_keeps_version_history(pi_client):
    created = create_pi(pi_client)
    old = propose(pi_client, created)
    changed = pi_input(document_number="PI-CHANGED").model_dump(mode="json")
    response = decide(pi_client, old, "modify", document=changed)
    assert response.status_code == 200, response.text
    new = response.json()
    assert new["id"] != old["id"] and new["revision"] == 2 and new["status"] == "pending"
    assert decide(pi_client, old, "approve").status_code == 409
    version = pi_client.get(f"/api/trade/pi/{created['document_id']}/versions/1").json()
    assert version["document_number"] == "PI-100"
    assert decide(pi_client, new, "approve").status_code == 200
    with pi_client.app.state.database.session() as session:
        assert session.get(TradeProposal, old["id"]).decision == "modify"
        assert session.get(TradeDocumentVersion, (created["document_id"], 2)).payload["document_number"] == "PI-CHANGED"


def test_modify_incomplete_input_returns_normal_needs_input(pi_client):
    created = create_pi(pi_client)
    old = propose(pi_client, created)
    values = pi_input(payment_terms=None).model_dump(mode="json")
    response = decide(pi_client, old, "modify", document=values)
    assert response.status_code == 200 and response.json()["status"] == "needs_input"
    assert response.json()["revision"] == 2
    assert decide(pi_client, old, "approve").status_code == 409


def test_edit_invalidates_previous_proposal_and_stale_input(pi_client):
    created = create_pi(pi_client)
    old = propose(pi_client, created)
    body = {"revision": 1, "document": pi_input(document_number="PI-NEW").model_dump(mode="json")}
    assert pi_client.put(f"/api/trade/pi/{created['document_id']}", json=body).status_code == 200
    assert pi_client.put(f"/api/trade/pi/{created['document_id']}", json=body).status_code == 409
    assert decide(pi_client, old, "approve").status_code == 409


def test_tampered_approval_content_and_server_fields_are_rejected(pi_client):
    created = create_pi(pi_client)
    proposal = propose(pi_client, created)
    assert decide(pi_client, proposal, "approve", content_hash="0" * 64).status_code == 409
    assert decide(pi_client, proposal, "approve", document=pi_input().model_dump(mode="json")).status_code == 422
    for key in ("user_id", "status", "revision", "issuer"):
        body = {**pi_input().model_dump(mode="json"), key: "tampered"}
        assert pi_client.post("/api/trade/pi", json=body).status_code == 422
    with pi_client.app.state.database.session() as session:
        assert session.scalar(select(func.count()).select_from(TradeArtifact)) == 0


def test_json_api_login_csrf_and_other_user_isolation(pi_client):
    created = create_pi(pi_client)
    proposal = propose(pi_client, created)
    approved = decide(pi_client, proposal, "approve").json()
    pi_client.app.dependency_overrides[current_user_id] = lambda: 2
    assert pi_client.get("/api/trade/pi").json() == []
    assert pi_client.get(f"/api/trade/pi/{created['document_id']}").status_code == 404
    assert pi_client.get(f"/api/trade/pi/{created['document_id']}/reviews/{proposal['id']}").status_code == 404
    assert pi_client.get(approved["files"][0]["download_url"]).status_code == 404
    assert pi_client.get("/api/trade/settings").json()["prices"] == []
    pi_client.app.dependency_overrides.clear()
    assert pi_client.get("/api/trade/pi").status_code == 401
    pi_client.app.dependency_overrides[current_user_id] = lambda: 1
    pi_client.headers.pop("X-CSRF-Token")
    assert pi_client.post("/api/trade/pi", json=pi_input().model_dump(mode="json")).status_code == 403


def test_render_failure_preserves_waiting_proposal_for_retry(pi_client, monkeypatch):
    from app.trade.common import rendering
    created = create_pi(pi_client)
    proposal = propose(pi_client, created)
    original = rendering.render_trade_document
    def fail(*_):
        raise ValueError("fake invalid image")
    monkeypatch.setattr(rendering, "render_trade_document", fail)
    assert decide(pi_client, proposal, "approve").status_code == 422
    with pi_client.app.state.database.session() as session:
        assert session.get(TradeProposal, proposal["id"]).status == "pending"
        assert session.get(TradeDocument, created["document_id"]).status == "ready"
        assert session.scalar(select(func.count()).select_from(TradeArtifact)) == 0
    monkeypatch.setattr(rendering, "render_trade_document", original)
    assert decide(pi_client, proposal, "approve").status_code == 200


def test_saved_proposal_and_download_links_are_discoverable_after_reload(pi_client):
    created = create_pi(pi_client)
    proposal = propose(pi_client, created)
    reloaded = pi_client.get(f"/api/trade/pi/{created['document_id']}").json()
    assert reloaded["proposal_id"] == proposal["id"]
    assert "master_price" not in reloaded["input"]["items"][0]
    assert "revision" not in reloaded["input"]
    approved = decide(pi_client, proposal, "approve").json()
    assert pi_client.get(f"/api/trade/pi/{created['document_id']}").json()["files"] == approved["files"]


def test_proposal_keeps_company_bank_and_seal_snapshot(pi_client):
    proposal = propose(pi_client, create_pi(pi_client))
    assert pi_client.put("/api/trade/settings/company", json={
        "legal_name_en": "Changed Company", "address": "Changed Address", "ceo_name": "Changed Signer"}).status_code == 200
    assert pi_client.put("/api/trade/settings/banks/USD", json={
        "beneficiary": "Changed Company", "bank_name": "Changed Bank", "branch": "Changed Branch",
        "swift": "CHANGED", "account_number": "CHANGED", "bank_address": "Changed Address"}).status_code == 200
    assert pi_client.post("/api/trade/settings/branding/seal", files={
        "image": ("new.png", seal_png(2, 1), "image/png")}).status_code == 200
    approved = decide(pi_client, proposal, "approve").json()
    pdf = next(file for file in approved["files"] if file["file_format"] == "pdf")
    content = pi_client.get(pdf["download_url"]).content
    reader = PdfReader(BytesIO(content))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "000-0000" in text and "CHANGED" not in text and "Changed Company" not in text
    assert "Example Signer" in text
    assert all(image.image.width == 1 for page in reader.pages for image in page.images)


def test_ai_http_extraction_uses_pi_agent_without_mail_graph(pi_client):
    from app.llm.client import use_backend
    from tests.fakes.llm import FakeLLM
    values = pi_input().model_dump(mode="json")
    values["items"][0].update(unit_price="8", source="Virtual Serum 10 PCS at USD 8 discount 0")
    fake = FakeLLM([values])
    text = ("Acme Trading, 1 Fiction Ave, Seoul. PI-100. FOB Busan, T/T. "
            "Virtual Serum 10 PCS at USD 8 discount 0")
    with use_backend(fake):
        response = pi_client.post("/api/trade/pi/extract", json={"text": text})
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "ready" and response.json()["document"]["total"] == "80.00"
    assert len(fake.calls) == 1


def test_reload_after_new_database_connection_keeps_approved_files(pi_client):
    from app.db.engine import Database
    approved = decide(pi_client, propose(pi_client, create_pi(pi_client)), "approve").json()
    old_database = pi_client.app.state.database
    new_database = Database(str(old_database.engine.url))
    new_database.create_tables()
    pi_client.app.state.database = new_database
    try:
        repeated = decide(pi_client, approved, "approve")
        assert repeated.status_code == 200 and repeated.json()["files"] == approved["files"]
        assert pi_client.get(approved["files"][0]["download_url"]).status_code == 200
    finally:
        new_database.close()
        pi_client.app.state.database = old_database


def test_unsupported_images_and_missing_csrf_are_rejected(pi_client):
    assert pi_client.post("/api/trade/settings/branding/seal", files={
        "image": ("bad.png", b"not a png", "image/png")}).status_code == 422
    assert pi_client.post("/api/trade/settings/branding/seal", files={
        "image": ("wide.png", seal_png(4097, 1), "image/png")}).status_code == 422
    assert pi_client.post("/api/trade/settings/branding/seal", files={
        "image": ("large.png", b"x" * (2 * 1024 * 1024 + 1), "image/png")}).status_code == 413


def test_react_cors_and_cookie_configuration(database_url):
    settings = Settings(database_url=database_url, session_secret="fake-session",
                        frontend_origins="https://frontend.example", app_base_url="https://api.example",
                        session_same_site="none")
    app = create_app(settings)
    app.dependency_overrides[current_user_id] = lambda: 1
    with TestClient(app, base_url="https://api.example") as client:
        response = client.options("/api/trade/pi", headers={
            "Origin": "https://frontend.example", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type, X-CSRF-Token, Authorization"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://frontend.example"
        assert response.headers["access-control-allow-credentials"] == "true"
        assert "Authorization" in response.headers["access-control-allow-headers"]
        rejected = client.options("/api/trade/pi", headers={
            "Origin": "https://untrusted.example", "Access-Control-Request-Method": "POST"})
        assert "access-control-allow-origin" not in rejected.headers
        session_response = client.get("/api/session")
        cookie = session_response.headers["set-cookie"].lower()
        assert "; samesite=none" in cookie
        assert "; secure" in cookie
    with pytest.raises(ValueError, match="HTTPS"):
        create_app(Settings(session_same_site="none", app_base_url="http://localhost"))
