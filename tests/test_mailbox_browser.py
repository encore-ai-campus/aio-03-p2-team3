"""실제 React/FastAPI/임시 DB와 가짜 Gmail로 원문→초안→발송·모바일을 확인한다."""
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright

from app.auth.supabase import TokenVerifier
from app.main import create_app
from app.services.watch import register_watch
from app.web import frontend
from tests.fakes.gmail import FakeGmailGoogle
from tests.fakes.google import fake_login
from tests.test_approval import add_mail
from tests.test_gmail_connect import settings_of
from tests.test_knowledge_browser import serve
from tests.test_supabase_auth import FakeJwks, SUPABASE_URL
from tests.test_mailbox import add_quote
from tests.fakes.gmail import message


def test_browser_mailbox_original_preview_send_and_mobile(database_url, tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    dist = tmp_path / "dist"
    environment = {**os.environ, "SUPABASE_URL": SUPABASE_URL,
                   "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_fake_for_browser", "FRONTEND_PORT": "5174"}
    subprocess.run(["npm", "run", "build", "--", "--outDir", str(dist)], cwd=root / "frontend",
                   env=environment, check=True, capture_output=True, timeout=120, shell=os.name == "nt")
    monkeypatch.setattr(frontend, "DIST", dist)
    jwks, google, subject = FakeJwks(), FakeGmailGoogle(), uuid4()
    token = jwks.token(sub=subject)
    app = create_app(settings_of(database_url), google=google,
                     supabase_auth=TokenVerifier(SUPABASE_URL, fetch_jwks=jwks.serve))
    session = {"access_token": token, "refresh_token": "fake-refresh", "token_type": "bearer",
               "expires_at": int(time.time()) + 3600, "expires_in": 3600,
               "user": {"id": str(subject), "aud": "authenticated", "email": "browser@example.invalid"}}
    with serve(app) as base, sync_playwright() as playwright:
        owner = httpx.get(base + "/api/me", headers={"Authorization": "Bearer " + token}).json()["user_id"]
        with app.state.database.session() as s:
            from app.db.models import User
            user = s.get(User, owner)
            # 사용자 UUID 매핑을 보존한 채 같은 Google 계정에 연결한 상태를 만든다.
            from app.services.auth import store_login, utcnow
            store_login(s, app.state.google_access, user, fake_login(), utcnow())
        register_watch(app.state.google_access, owner)
        add_mail(type("Client", (), {"app": app})(), owner)
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
        context.add_init_script("localStorage.setItem('sb-test-project-auth-token', " + json.dumps(json.dumps(session)) + ")")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/app/inbox")
        expect(page.get_by_role("heading", name="받은 메일", exact=True)).to_be_visible()
        page.locator(".mail-row").first.click()
        expect(page.get_by_text("테스트용 가상 문의입니다.", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="AI 답장 초안", exact=True)).to_be_visible()
        page.get_by_role("button", name="발송 내용 확인").first.click()
        preview = page.get_by_role("region", name="발송 최종 확인")
        expect(preview).to_be_visible()
        expect(preview).to_be_focused()
        expect(preview.get_by_text("받는 사람: sender@example.invalid", exact=True)).to_be_visible()
        page.get_by_role("button", name="확인하고 보내기").click()
        expect(page.get_by_text("메일을 보냈습니다.", exact=True)).to_be_visible()
        assert len(google.mailbox.called("send")) == 1
        # 국내 견적도 같은 화면에서 빈 단가→기존 합계/PDF 확인→승인 발송한다.
        client = type("Client", (), {"app": app})()
        quote_candidates = add_mail(client, owner, "quote-message", "quote-thread", subject="가상 견적 문의")
        add_quote(client, owner, quote_candidates, message_id="quote-message", thread_id="quote-thread")
        google.mailbox.raw_messages["quote-message"] = message("quote-message", "quote-thread")
        page.get_by_role("button", name="새로고침", exact=True).click()
        page.locator(".mail-row").filter(has_text="가상 견적 문의").click()
        panel = page.locator(".mail-candidate").first
        panel.get_by_text("관련 국내 견적서", exact=False).click()
        panel.get_by_label("공책 단가(원)").fill("50")
        panel.get_by_role("button", name="단가 저장 · 합계 계산").click()
        expect(panel.get_by_label("공책 단가(원)")).to_have_count(0)
        panel.get_by_text("관련 국내 견적서", exact=False).click()
        expect(panel.get_by_text("합계 502원", exact=False)).to_be_visible()
        with page.expect_download() as downloaded:
            panel.get_by_role("button", name="견적서 PDF 확인").click()
        assert downloaded.value.suggested_filename.endswith(".pdf")
        panel.get_by_role("button", name="발송 내용 확인").click()
        page.get_by_role("button", name="확인하고 보내기").click()
        expect(page.get_by_text("메일을 보냈습니다.", exact=True)).to_be_visible()
        assert len(google.mailbox.called("send")) == 2
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.get_by_role("button", name="목록으로", exact=True)).to_be_visible()
        page.get_by_role("button", name="목록으로", exact=True).click()
        expect(page.locator(".mail-row").first).to_be_visible()
        page.locator(".mail-row").first.click()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(tmp_path / "mailbox-mobile.png"), full_page=True)
        assert errors == []
        browser.close()
