"""설정 화면 계약: Bearer 소유권·단가 범위·거래처 갱신·새 문서/과거 발급 구분."""
from hashlib import sha256
from uuid import uuid4

from tests.fakes.storage import FakeStorage
from tests.test_files_storage import bearer, make_client
from tests.test_pi_domain import pi_input
from tests.test_supabase_auth import FakeJwks, write_settings
from tests.test_trade_flow import seal_png


def test_settings_preserve_user_role_currency_and_counterparty_scopes(database_url):
    jwks = FakeJwks()
    with make_client(database_url, jwks, FakeStorage()) as client:
        owner, other = bearer(jwks.token()), bearer(jwks.token(sub=uuid4()))
        write_settings(client, owner)
        for role, currency, party, amount in [("purchase", "USD", "", "4"),
                                               ("sale", "EUR", "", "7"),
                                               ("sale", "USD", "Other Trading", "11")]:
            response = client.put("/api/trade/settings/prices", headers=owner, json={
                "item_name": "Virtual Serum", "role": role, "currency": currency,
                "party_key": party, "unit_price": amount})
            assert response.status_code == 200, response.text
        owned = client.get("/api/trade/settings", headers=owner)
        assert owned.headers["cache-control"] == "private, no-store"
        rows = owned.json()["prices"]
        assert len(rows) == 4
        assert {(row["role"], row["currency"], row["unit_price"]) for row in rows} == {
            ("sale", "USD", "8"), ("purchase", "USD", "4"), ("sale", "EUR", "7"), ("sale", "USD", "11")}
        assert next(row for row in rows if row["unit_price"] == "11")["party_key"] == "othertrading"
        assert client.get("/api/trade/settings", headers=other).json() == {
            "company": None, "banks": [], "prices": [], "counterparties": [],
            "branding": {"has_logo": False, "has_seal": False, "logo_file_id": None, "seal_file_id": None}}
        assert client.get("/api/trade/settings").status_code == 401


def test_counterparty_upsert_is_owned_and_rejects_invalid_or_server_fields(database_url):
    jwks = FakeJwks()
    with make_client(database_url, jwks, FakeStorage()) as client:
        owner, other = bearer(jwks.token()), bearer(jwks.token(sub=uuid4()))
        path = "/api/trade/settings/counterparties"
        for name, address in [("Acme Trading Ltd.", "First address"), ("Acme Trading", "Updated address")]:
            response = client.put(path, headers=owner, json={
                "legal_name": name, "address": address, "aliases": ["Acme", "Acme"],
                "default_ship_to": "Test warehouse", "ship_to_phone": "000-000-0000"})
            assert response.status_code == 200, response.text
        [party] = response.json()["counterparties"]
        assert party["company_key"] == "acmetrading" and party["address"] == "Updated address"
        assert party["aliases"] == ["Acme"] and party["default_ship_to"] == "Test warehouse"
        client.put(path, headers=other, json={"legal_name": "Acme Trading", "address": "Other owner's address"})
        assert client.get("/api/trade/settings", headers=owner).json()["counterparties"] == [party]
        for invalid in [{"legal_name": ""}, {"legal_name": "Ltd."},
                        {"legal_name": "Acme", "aliases": [str(i) for i in range(21)]},
                        {"legal_name": "Acme", "user_id": 999}, {"legal_name": "Acme", "company_key": "forged"}]:
            assert client.put(path, headers=owner, json=invalid).status_code == 422


def test_saved_settings_apply_to_new_documents_and_preserve_existing_issue(database_url):
    jwks = FakeJwks()
    with make_client(database_url, jwks, FakeStorage()) as client:
        headers = bearer(jwks.token())
        write_settings(client, headers)
        image = client.post("/api/trade/settings/branding/seal", headers=headers,
                            files={"image": ("seal.png", seal_png(), "image/png")})
        assert image.status_code == 200
        file_id = image.json()["branding"]["seal_file_id"]
        assert client.get(f"/api/files/{file_id}/download", headers=headers).content == seal_png()
        assert client.get(f"/api/files/{file_id}/download", headers=bearer(jwks.token(sub=uuid4()))).status_code == 404
        created = client.post("/api/trade/pi", headers=headers, json=pi_input().model_dump(mode="json")).json()
        path = f"/api/trade/pi/{created['document_id']}/reviews"
        proposal = client.post(path, headers=headers, json={"revision": 1}).json()
        issued = client.post(f"{path}/{proposal['id']}/decisions", headers=headers, json={
            "action": "approve", "revision": 1, "content_hash": proposal["content_hash"]})
        assert issued.status_code == 200, issued.text
        files = issued.json()["files"]
        original = created["document"]
        client.put("/api/trade/settings/company", headers=headers, json={"legal_name_en": "New Example Company", "address": "New address"})
        client.put("/api/trade/settings/banks/USD", headers=headers, json={key: "Updated bank value" for key in (
            "beneficiary", "bank_name", "branch", "swift", "account_number", "bank_address")})
        client.put("/api/trade/settings/prices", headers=headers, json={"item_name": "Virtual Serum", "capacity": "50ml",
            "role": "sale", "currency": "USD", "unit_price": "9", "price_basis": "PCS"})
        fresh = client.post("/api/trade/pi", headers=headers, json=pi_input().model_dump(mode="json"))
        assert fresh.status_code == 201
        assert fresh.json()["document"]["issuer"]["legal_name_en"] == "New Example Company"
        assert fresh.json()["document"]["bank"]["BANK_NAME"] == "Updated bank value"
        assert fresh.json()["document"]["total"] == "90.00"
        old = client.get(f"/api/trade/pi/{created['document_id']}", headers=headers).json()["document"]
        assert old["issuer"] == original["issuer"] and old["bank"] == original["bank"] and old["total"] == original["total"]
        for file in files:
            response = client.get(file["download_url"], headers=headers)
            assert response.status_code == 200 and sha256(response.content).hexdigest() == file["content_hash"]
