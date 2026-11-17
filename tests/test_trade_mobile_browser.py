"""#208: 실제 FastAPI/임시 PostgreSQL, 가짜 인증·추출·Storage의 PI/PO 모바일 회귀."""
from contextlib import nullcontext
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright
import pytest

from app.auth.supabase import TokenVerifier
from app.config import Settings
from app.main import create_app
from app.trade.common import router as trade_router
from app.trade.pi import agent as pi_agent
from app.trade.po import agent as po_agent
from app.web import frontend
from tests.fakes.storage import FakeStorage
from tests.test_knowledge_browser import serve
from tests.test_pi_domain import pi_input
from tests.test_supabase_auth import FakeJwks, SUPABASE_URL, write_settings
from tests.test_trade_flow import seal_png


@pytest.fixture(scope="module")
def mobile_frontend(tmp_path_factory):
    output = tmp_path_factory.mktemp("trade-mobile") / "dist"
    subprocess.run(["npm", "run", "build", "--", "--outDir", str(output)],
                   cwd=Path(__file__).resolve().parents[1] / "frontend", check=True,
                   capture_output=True, timeout=120, shell=os.name == "nt", env={**os.environ,
                   "SUPABASE_URL": SUPABASE_URL, "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_fake_for_browser_test"})
    return output


def layout(page, widths=(320, 768, 1440, 390)):
    for width in widths:
        page.set_viewport_size({"width": width, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"overflow at {width}"
        for button in page.locator(".pi-step-actions button, .review-panel .form-actions button").all():
            button.scroll_into_view_if_needed()
            box = button.bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1
            if width <= 800:
                nav = page.locator(".bottom-nav").bounding_box()
                assert box["y"] + box["height"] <= nav["y"] + 1


def keyboard_reachable(page):
    """현재 펼쳐진 화면의 모든 동작에 Tab으로 접근하고 포커스를 확인한다."""
    count = page.evaluate("""() => {
      const controls = [...document.querySelectorAll('button,a[href],input,textarea,select,summary,[tabindex="0"]')]
        .filter(el => el.checkVisibility() && !el.matches(':disabled') && getComputedStyle(el).visibility !== 'hidden');
      controls.forEach((el, index) => el.dataset.mobileFocus = String(index));
      return controls.length;
    }""")
    seen = set()
    for _ in range(count + 3):
        page.keyboard.press("Tab")
        active = page.evaluate("""() => ({ id: document.activeElement.dataset.mobileFocus,
          outline: getComputedStyle(document.activeElement).outlineStyle })""")
        if active.get("id") is not None:
            seen.add(active["id"])
            assert active["outline"] != "none", active
    assert len(seen) == count, (seen, count)


@pytest.mark.parametrize("kind", ["pi", "po"])
def test_pi_po_mobile_complete_resize_conflict_retry(database_url, mobile_frontend, monkeypatch, tmp_path, kind):
    monkeypatch.setattr(frontend, "DIST", mobile_frontend)
    jwks, storage, subject = FakeJwks(), FakeStorage(), uuid4()
    token = jwks.token(sub=subject)
    headers = {"Authorization": "Bearer " + token}
    app = create_app(Settings(database_url=database_url, session_secret="fake-mobile-session"),
                     supabase_auth=TokenVerifier(SUPABASE_URL, fetch_jwks=jwks.serve), storage=storage)
    extracted = pi_input(document_number=kind.upper() + "-SOURCE").model_dump(mode="json")
    role = "buyer" if kind == "pi" else "seller"
    if kind == "po":
        extracted["seller"], extracted["buyer"] = extracted["buyer"], {}
        extracted["items"][0].pop("is_sample")
    extracted[role]["address"] = None
    monkeypatch.setattr(pi_agent if kind == "pi" else po_agent, "extract_facts", lambda *_: deepcopy(extracted))
    monkeypatch.setattr(trade_router, "user_openai", lambda *_args, **_kwargs: nullcontext(SimpleNamespace(issue=None)))
    session = {"access_token": token, "refresh_token": "fake-refresh", "token_type": "bearer",
               "expires_at": int(time.time()) + 3600, "expires_in": 3600,
               "user": {"id": str(subject), "aud": "authenticated", "email": "mobile@example.invalid"}}
    with serve(app) as base, httpx.Client(base_url=base, headers=headers) as client, sync_playwright() as pw:
        write_settings(client, headers)
        assert client.put("/api/trade/settings/prices", json={"item_name": "Virtual Serum", "capacity": "50ml",
            "role": "purchase", "currency": "USD", "unit_price": "3", "price_basis": "PCS"}).status_code == 200
        assert client.post("/api/trade/settings/branding/seal", files={"image": ("seal.png", seal_png(), "image/png")}).status_code == 200
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 390, "height": 844})
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
        context.add_init_script("localStorage.setItem('sb-test-project-auth-token', " + json.dumps(json.dumps(session)) + ")")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/app/trade/" + kind)
        page.get_by_role("button", name="직접 작성", exact=False).click()
        form = page.get_by_role("form", name=kind.upper() + " 입력")
        form.get_by_label("회사명 (영문)", exact=True).fill("VirtualCounterparty" * 10)
        # 주소 누락 초안을 저장하고 필요한 입력만 보완한다.
        page.get_by_role("button", name="임시 저장", exact=True).click()
        expect(form.get_by_label("주소 (영문)", exact=True)).to_be_visible()
        form.get_by_label("주소 (영문)", exact=True).fill("1 Fiction Avenue " * 20)
        page.get_by_role("button", name="이 단계 전체 수정").click()
        page.get_by_role("navigation", name=kind.upper() + " 작성 단계").get_by_role("button", name="품목", exact=True).click()
        expect(page.get_by_role("button", name="품목 추가", exact=True)).to_be_visible()
        page.get_by_label("품목명 (영문) · 품목 1", exact=True).fill("Virtual Serum")
        page.get_by_label("유상 수량 · 품목 1", exact=True).fill("10")
        page.get_by_role("button", name="품목 추가", exact=True).click()
        page.get_by_role("button", name="품목 2 삭제", exact=True).click()
        page.get_by_text("품목 1 상세", exact=False).click()
        page.get_by_label("용량·규격 · 품목 1", exact=True).fill("50ml")
        page.get_by_label("할인율 (%) · 품목 1", exact=True).fill("10")
        if kind == "po":
            page.get_by_label("무상 수량 · 품목 1", exact=True).fill("2")
        else:
            page.get_by_label("샘플 품목 (0원 포함)").check()
            expect(page.get_by_label("할인율 (%) · 품목 1", exact=True)).to_be_disabled()
            page.get_by_label("샘플 품목 (0원 포함)").uncheck()
        page.get_by_role("button", name="작성 내용 보기", exact=True).click()
        quantity = page.get_by_label("유상 수량 · 품목 1", exact=True)
        quantity.focus()
        for width in (1440, 390):
            page.set_viewport_size({"width": width, "height": 844})
            expect(quantity).to_have_value("10")
            expect(quantity).to_be_focused()
            expect(page.locator('[aria-current="step"]')).to_have_text("품목")
            expect(page.locator(".pi-summary-toggle")).to_have_attribute("aria-expanded", "true")
            expect(page.locator(".pi-item-detail details")).to_have_attribute("open", "")
        layout(page)
        keyboard_reachable(page)
        # 실제 기기 inset 대신 같은 공통 높이에 34px을 주입해 탐색/작업 배치를 확인한다.
        inset = page.add_style_tag(content=":root{--mobile-nav-height:97px}.bottom-nav{padding-bottom:34px}")
        layout(page, (320, 390, 768))
        assert page.locator(".bottom-nav").bounding_box()["height"] == 97
        inset.evaluate("el => el.remove()")
        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("button", name="다음", exact=True).click()
        page.get_by_label(kind.upper() + " 문서번호", exact=True).fill(kind.upper() + "-" + "LONG" * 30)
        page.get_by_label("납품 조건 (Incoterms·장소)", exact=True).fill("FOB Busan")
        page.get_by_label("지급 조건", exact=True).fill("T/T")
        page.get_by_role("button", name="저장하고 전체 확인", exact=True).click()
        expect(page.get_by_role("button", name="최종 검토 만들기", exact=True)).to_be_enabled()
        path = "/api/trade/" + kind + "/" + page.url.rsplit("/", 1)[1]
        saved = client.get(path).json()
        assert saved["document"]["total"] == ("72.00" if kind == "pi" else "27.00")
        assert bool(saved["document"].get("bank")) == (kind == "pi")
        layout(page)
        amounts = page.get_by_role("region", name="품목별 금액 · 가로 스크롤")
        amounts.focus()
        page.keyboard.press("ArrowRight")
        page.wait_for_function("document.querySelector('.table-scroll').scrollLeft > 0")
        assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
        page.get_by_role("button", name="최종 검토 만들기", exact=True).click()
        page.get_by_role("button", name="검토 취소", exact=True).click()
        page.get_by_role("button", name="최종 검토 만들기", exact=True).click()
        page.get_by_role("button", name="수정", exact=True).click()
        form.get_by_label("주소 (영문)", exact=True).fill("2 Fiction Ave, Seoul")
        page.get_by_role("button", name="임시 저장", exact=True).click()
        expect(page.get_by_role("button", name="승인하고 파일 발급", exact=True)).to_be_enabled()
        page.get_by_text("고정된 버전·파일 정보", exact=True).click()
        layout(page)
        keyboard_reachable(page)
        page.screenshot(path=str(tmp_path / (kind + "-review.png")), full_page=True)
        # 검토·발급·다운로드를 키보드로 실행한다.
        approve = page.get_by_role("button", name="승인하고 파일 발급", exact=True)
        approve.focus()
        page.keyboard.press("Shift+Tab")
        page.keyboard.press("Tab")
        expect(approve).to_be_focused()
        assert approve.evaluate("el => getComputedStyle(el).outlineStyle") != "none"
        page.keyboard.press("Enter")
        expect(page.get_by_role("button", name="PDF 다운로드", exact=True)).to_be_enabled()
        document = client.get(path).json()
        proposal = client.get(path + "/reviews/" + str(document["proposal_id"])).json()
        for file in proposal["files"]:
            url = base + file["download_url"]
            context.route(url, lambda route: route.abort())
            button = page.get_by_role("button", name=file["file_format"].upper() + " 다운로드", exact=True)
            button.click()
            expect(page.get_by_role("alert")).to_contain_text("다시 시도")
            expect(page.get_by_role("alert")).to_be_focused()
            expect(button).to_be_enabled()
            context.unroute(url)
            with page.expect_download() as download:
                button.focus()
                page.keyboard.press("Enter")
            assert sha256(Path(download.value.path()).read_bytes()).hexdigest() == file["content_hash"]
        layout(page)
        page.reload()
        expect(page.get_by_role("button", name="PDF 다운로드", exact=True)).to_be_enabled()
        # 실제 다른 창 저장으로 revision 충돌을 만들고 입력·단계를 보존한다.
        page.get_by_role("navigation", name=kind.upper() + " 작성 단계").get_by_role("button", name="거래 조건", exact=True).click()
        page.get_by_label("지급 조건", exact=True).fill("UNSAVED MOBILE TERMS")
        current = client.get(path).json()
        assert client.put(path, json={"revision": current["revision"], "document": current["input"]}).status_code == 200
        page.get_by_role("button", name="임시 저장", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("최신")
        expect(page.get_by_label("지급 조건", exact=True)).to_have_value("UNSAVED MOBILE TERMS")
        expect(page.locator('[aria-current="step"]')).to_have_text("거래 조건")
        # 원문 작성 방법을 왕복해도 입력을 보존하고 가짜 추출의 누락을 보완한다.
        page.goto(base + "/app/trade/" + kind)
        page.get_by_role("button", name="원문 붙여넣기", exact=False).click()
        page.get_by_label("거래 원문", exact=True).fill("Virtual source for " + kind)
        layout(page)
        keyboard_reachable(page)
        expect(page.get_by_label("거래 원문", exact=True)).to_have_value("Virtual source for " + kind)
        page.get_by_role("button", name="← 작성 방법 선택", exact=True).click()
        page.get_by_role("button", name="원문 붙여넣기", exact=False).click()
        expect(page.get_by_label("거래 원문", exact=True)).to_have_value("Virtual source for " + kind)
        page.get_by_role("button", name="원문에서 정보 가져오기", exact=True).click()
        expect(form.get_by_label("주소 (영문)", exact=True)).to_be_visible()
        expect(form.get_by_label("회사명 (영문)", exact=True)).to_have_count(0)
        form.get_by_label("주소 (영문)", exact=True).fill("3 Fiction Ave, Seoul")
        page.get_by_role("button", name="임시 저장", exact=True).click()
        expect(page.get_by_role("heading", name="전체 내용을 확인해 주세요", exact=True)).to_be_visible()
        if kind == "pi":
            for route in ("settings", "documents"):
                page.goto(base + "/app/" + route)
                expect(page.get_by_role("heading", name="설정" if route == "settings" else "문서함", exact=True)).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not errors
        browser.close()
