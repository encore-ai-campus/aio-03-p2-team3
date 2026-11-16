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
        fresh = client.post("/api/trade/pi", headers=headers, json=pi_input(document_number="PI-NEW-SETTINGS").model_dump(mode="json"))
        assert fresh.status_code == 201
        assert fresh.json()["document"]["issuer"]["legal_name_en"] == "New Example Company"
        assert fresh.json()["document"]["bank"]["BANK_NAME"] == "Updated bank value"
        assert fresh.json()["document"]["total"] == "90.00"
        old = client.get(f"/api/trade/pi/{created['document_id']}", headers=headers).json()["document"]
        assert old["issuer"] == original["issuer"] and old["bank"] == original["bank"] and old["total"] == original["total"]
        for file in files:
            response = client.get(file["download_url"], headers=headers)
            assert response.status_code == 200 and sha256(response.content).hexdigest() == file["content_hash"]


def test_gmail_settings_browser_callbacks_failures_and_mobile(database_url, tmp_path, monkeypatch):
    """실제 React/FastAPI/PostgreSQL + 가짜 Google/JWKS, 외부 API 호출 없음."""
    import json
    from dataclasses import replace
    import os
    from pathlib import Path
    import subprocess
    import time
    from urllib.parse import parse_qs, urlencode, urlparse

    import httpx
    from playwright.sync_api import expect, sync_playwright

    from app.auth.supabase import TokenVerifier
    from app.clients.gmail import GoogleUnavailable
    from app.main import create_app
    from app.web import frontend
    from tests.fakes.google import FakeGoogle, fake_login
    from tests.test_gmail_connect import settings_of
    from tests.test_knowledge_browser import serve
    from tests.test_supabase_auth import SUPABASE_URL

    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "frontend-dist"
    subprocess.run(["npm", "run", "build", "--", "--outDir", str(output)], cwd=root / "frontend",
                   env={**os.environ, "SUPABASE_URL": SUPABASE_URL,
                        "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_fake_for_browser_test"},
                   check=True, capture_output=True, timeout=120, shell=os.name == "nt")
    monkeypatch.setattr(frontend, "DIST", output)
    jwks, google = FakeJwks(), FakeGoogle()
    subject = uuid4()
    jwks.with_google_identity(subject, "fake-sub-1")
    token = jwks.token(sub=subject)
    settings = settings_of(database_url)
    app = create_app(settings, google=google, supabase_auth=TokenVerifier(
        SUPABASE_URL, fetch_jwks=jwks.serve, secret_key="fake-server-secret", fetch_admin_user=jwks.admin_serve))
    session = {"access_token": token, "refresh_token": "fake-refresh", "token_type": "bearer",
               "expires_at": int(time.time()) + 3600, "expires_in": 3600,
               "user": {"id": str(subject), "aud": "authenticated", "email": "browser@example.invalid"}}
    with serve(app) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.add_init_script("localStorage.setItem('sb-test-project-auth-token', " + json.dumps(json.dumps(session)) + ")")
        result = {"cancel": False}
        counts = {"connect": 0, "disconnect": 0}

        def route_request(route):
            url = route.request.url
            if url.startswith("https://accounts.example.invalid/auth?"):
                state = parse_qs(urlparse(url).query)["state"][0]
                query = {"state": state, "error": "access_denied"} if result["cancel"] else {"state": state, "code": "fake-code"}
                route.fulfill(status=303, headers={"location": base + "/auth/google/callback?" + urlencode(query)})
            elif url.startswith(base + "/"):
                for action in counts:
                    if url == base + "/api/gmail/" + action:
                        counts[action] += 1
                route.continue_()
            else:
                route.abort()

        context.route("**/*", route_request)
        context.route("**/api/trade/settings", lambda route: route.fulfill(status=503,
            json={"error": {"code": "test_unavailable", "message": "가상 회사 설정 조회 실패"}}))
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/app/settings")
        expect(page.get_by_text("가상 회사 설정 조회 실패", exact=True)).to_be_visible()
        nav = page.get_by_role("navigation", name="설정 항목")
        expect(nav.get_by_role("button")).to_have_text(["회사 정보", "거래처", "판매 단가표", "구매 단가표", "은행 계좌", "로고·직인", "연동하기"])
        nav.get_by_role("button", name="연동하기", exact=True).click()
        gmail = page.get_by_role("region", name="Gmail 연동", exact=True)
        calendar = page.get_by_role("region", name="Google 캘린더 연동", exact=True)
        expect(gmail.get_by_text("연결 안 됨", exact=True)).to_be_visible()
        expect(calendar.get_by_role("button")).to_be_disabled()

        def double_connect():
            # 같은 JS 작업 안의 연속 클릭으로 React 렌더 전 중복 요청도 검증한다.
            gmail.get_by_role("button", name="Gmail 연결", exact=True).evaluate("button => { button.click(); button.click() }")

        double_connect()
        expect(gmail.get_by_text("연결됨", exact=True)).to_be_visible()
        expect(gmail.get_by_text("메일 감시 중", exact=True)).to_be_visible()
        assert counts["connect"] == 1 and len(google.called("exchange")) == 1
        expect(nav.get_by_role("button", name="연동하기", exact=True)).to_have_attribute("aria-pressed", "true")
        expect(page).to_have_url(base + "/app/settings")  # 콜백 안내 재생 방지
        page.reload()
        nav.get_by_role("button", name="연동하기", exact=True).click()
        expect(gmail.get_by_text("연결됨", exact=True)).to_be_visible()
        page.screenshot(path=str(tmp_path / "integrations-desktop.png"), full_page=True)

        # 390px에서도 두 카드/버튼이 보이고 가로 넘침이 없다.
        page.set_viewport_size({"width": 390, "height": 844})
        expect(calendar).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "integrations-mobile.png"), full_page=True)
        gmail.get_by_role("button", name="Gmail 연결 해제", exact=True).click()
        expect(gmail.get_by_text("같은 Google 앱에 연결한 다른 서비스도", exact=False)).to_be_visible()
        gmail.get_by_role("button", name="취소", exact=True).click()
        expect(gmail.get_by_role("group", name="Gmail 연결 해제 확인")).to_have_count(0)
        gmail.get_by_role("button", name="Gmail 연결 해제", exact=True).click()
        gmail.get_by_role("button", name="해제 확인", exact=True).evaluate("button => { button.click(); button.click() }")
        expect(gmail.get_by_text("연결 안 됨", exact=True)).to_be_visible()
        assert counts["disconnect"] == 1 and len(google.called("revoke")) == 1
        page.reload()
        nav.get_by_role("button", name="연동하기", exact=True).click()
        expect(gmail.get_by_text("연결 안 됨", exact=True)).to_be_visible()

        result["cancel"] = True
        double_connect()
        expect(page.get_by_text("Gmail 연결을 취소했습니다.", exact=False)).to_be_visible()
        expect(gmail.get_by_text("연결 안 됨", exact=True)).to_be_visible()
        result["cancel"] = False
        google.logins.append(fake_login(scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"]))
        double_connect()
        expect(page.get_by_text("Gmail 필수 권한이 누락되었습니다.", exact=False)).to_be_visible()
        expect(gmail.get_by_text("연결 안 됨", exact=True)).to_be_visible()
        google.logins.append(fake_login(sub="other-google-sub"))
        double_connect()
        expect(page.get_by_text("앱 로그인에 사용한 Google 계정과 다릅니다.", exact=False)).to_be_visible()
        expect(gmail.get_by_text("연결 안 됨", exact=True)).to_be_visible()

        # 누락 서버 설정과 시작 요청의 401은 성공으로 표시하지 않는다.
        app.state.settings = replace(settings, google_oauth_client_secret="")
        double_connect()
        expect(page.get_by_role("alert")).to_contain_text("서버 설정이 끝나지 않아")
        expect(gmail.get_by_text("연결 상태 미확인", exact=True)).to_be_visible()
        app.state.settings = settings
        gmail.get_by_role("button", name="상태 다시 확인", exact=True).click()
        expect(gmail.get_by_text("연결 안 됨", exact=True)).to_be_visible()
        context.route("**/api/gmail/connect", lambda route: route.fulfill(status=401, json={"detail": "가상 만료"}))
        double_connect()
        expect(page.get_by_role("alert")).to_contain_text("로그인이 만료되었거나 유효하지 않습니다.")
        expect(page.get_by_role("button", name="로그인 다시 확인", exact=True)).to_be_visible()
        expect(gmail.get_by_role("button", name="Gmail 연결", exact=True)).to_be_disabled()
        context.unroute("**/api/gmail/connect")
        gmail.get_by_role("button", name="상태 다시 확인", exact=True).click()
        expect(gmail.get_by_text("연결 안 됨", exact=True)).to_be_visible()

        # 감시 실패/중지와 토큰 연결은 서로 다르며 재연결로 회복한다.
        google.watch_error = GoogleUnavailable("가상 감시 실패")
        double_connect()
        expect(gmail.get_by_text("연결됨", exact=True)).to_be_visible()
        expect(gmail.get_by_text("메일 감시 오류", exact=False)).to_be_visible()
        google.watch_error = None
        gmail.get_by_role("button", name="Gmail 다시 연결", exact=True).click()
        expect(gmail.get_by_text("메일 감시 중", exact=True)).to_be_visible()
        with httpx.Client() as client:
            assert client.post(base + "/api/gmail/logout", headers={"Authorization": "Bearer " + token}).status_code == 200
        gmail.get_by_role("button", name="상태 다시 확인", exact=True).click()
        expect(gmail.get_by_text("메일 감시 중지", exact=False)).to_be_visible()
        gmail.get_by_role("button", name="Gmail 다시 연결", exact=True).click()
        expect(gmail.get_by_text("메일 감시 중", exact=True)).to_be_visible()

        google.revoke_error = GoogleUnavailable("가상 해제 실패")
        gmail.get_by_role("button", name="Gmail 연결 해제", exact=True).click()
        gmail.get_by_role("button", name="해제 확인", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("Google 토큰 폐기에 실패했습니다.")
        expect(gmail.get_by_text("연결 상태 미확인", exact=True)).to_be_visible()
        google.revoke_error = None
        gmail.get_by_role("button", name="상태 다시 확인", exact=True).click()
        expect(gmail.get_by_text("연결됨", exact=True)).to_be_visible()
        gmail.get_by_role("button", name="해제 확인", exact=True).click()
        expect(gmail.get_by_text("연결 안 됨", exact=True)).to_be_visible()

        # 위조 성공 쿼리는 상태를 바꾸지 않는다. 상태 조회 실패에도 Calendar 카드는 남는다.
        page.goto(base + "/app/settings?gmail=connected&keep=1")
        expect(gmail.get_by_text("연결 안 됨", exact=True)).to_be_visible()
        expect(page).to_have_url(base + "/app/settings?keep=1")
        page.goto(base + "/app/settings?gmail=__proto__")
        expect(page.get_by_text("Gmail 연결을 완료하지 못했습니다. 다시 시도해 주세요.", exact=True)).to_be_visible()
        expect(gmail.get_by_text("연결 안 됨", exact=True)).to_be_visible()
        context.route("**/api/me", lambda route: route.fulfill(status=401, json={"detail": "가상 만료"}))
        gmail.get_by_role("button", name="상태 다시 확인", exact=True).click()
        expect(gmail.get_by_text("연결 상태 미확인", exact=True)).to_be_visible()
        expect(calendar).to_be_visible()
        expect(page.get_by_role("alert")).to_contain_text("로그인이 만료되었거나 유효하지 않습니다.")
        context.unroute("**/api/me")
        gmail.get_by_role("button", name="상태 다시 확인", exact=True).click()
        expect(gmail.get_by_text("연결 안 됨", exact=True)).to_be_visible()

        # 회사 API 장애 경계를 제거한 뒤 원래 회사 입력/저장이 정상 동작한다.
        context.unroute("**/api/trade/settings")
        nav.get_by_role("button", name="회사 정보", exact=True).click()
        page.get_by_role("button", name="다시 읽기", exact=True).click()
        company = page.get_by_label("회사명 (영문)", exact=True)
        company.fill("Virtual Browser Trading")
        page.get_by_role("button", name="변경 저장", exact=True).click()
        expect(page.get_by_text("저장했습니다. 새 문서·검토부터 적용됩니다.", exact=True)).to_be_visible()
        page.reload()
        expect(company).to_have_value("Virtual Browser Trading")
        nav.get_by_role("button", name="연동하기", exact=True).click()
        expect(gmail.get_by_text("연결 안 됨", exact=True)).to_be_visible()
        context.route("**/api/me", lambda route: route.fulfill(status=401, json={"detail": "가상 만료"}))
        gmail.get_by_role("button", name="상태 다시 확인", exact=True).click()
        page.get_by_role("button", name="로그인 다시 확인", exact=True).click()
        expect(page).to_have_url(base + "/app/login")
        expect(page.get_by_text("로그인이 만료되었거나 유효하지 않습니다. 다시 로그인해 주세요.", exact=True)).to_be_visible()
        assert not errors
        browser.close()
