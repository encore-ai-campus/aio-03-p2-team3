"""#208·#209·#210: 실제 FastAPI/임시 PostgreSQL, 가짜 인증·추출·Storage의 PI/PO/CI/PL 모바일 회귀."""
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


def ci_issue_download(page, context, client, base, tmp_path, name):
    """모바일 검토/발급과 실패 후 같은 파일 재다운로드를 실제 bytes로 확인한다."""
    page.get_by_role("button", name="최종 검토 만들기", exact=True).click()
    expect(page.get_by_role("heading", name="최종 검토 · 버전", exact=False)).to_be_focused()
    page.get_by_text("고정된 버전·파일 정보", exact=True).click()
    layout(page)
    keyboard_reachable(page)
    page.screenshot(path=str(tmp_path / (name + "-review.png")), full_page=True)
    button = page.get_by_role("button", name="승인하고 파일 발급", exact=True)
    button.focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("button", name="PDF 다운로드", exact=True)).to_be_enabled()
    path = "/api/trade/ci/" + page.url.rsplit("/", 1)[1]
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
    return path


@pytest.fixture
def ci_browser(database_url, mobile_frontend, monkeypatch):
    monkeypatch.setattr(frontend, "DIST", mobile_frontend)
    jwks, subject = FakeJwks(), uuid4()
    token = jwks.token(sub=subject)
    headers = {"Authorization": "Bearer " + token}
    app = create_app(Settings(database_url=database_url, session_secret="fake-ci-mobile-session"),
                     supabase_auth=TokenVerifier(SUPABASE_URL, fetch_jwks=jwks.serve), storage=FakeStorage())
    session = {"access_token": token, "refresh_token": "fake-refresh", "token_type": "bearer",
               "expires_at": int(time.time()) + 3600, "expires_in": 3600,
               "user": {"id": str(subject), "aud": "authenticated", "email": "mobile@example.invalid"}}
    with serve(app) as base, httpx.Client(base_url=base, headers=headers) as client, sync_playwright() as pw:
        write_settings(client, headers)
        assert client.post("/api/trade/settings/branding/seal", files={"image": ("seal.png", seal_png(), "image/png")}).status_code == 200
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 390, "height": 844})
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
        context.add_init_script("if (location.origin === " + json.dumps(base) + ") localStorage.setItem('sb-test-project-auth-token', " + json.dumps(json.dumps(session)) + ")")
        page = context.new_page()
        errors = []
        context.on("page", lambda tab: tab.on("pageerror", lambda error: errors.append(str(error))))
        page.on("pageerror", lambda error: errors.append(str(error)))
        yield page, context, client, base
        assert not errors
        browser.close()


def test_ci_linked_mobile_source_reselect_preserves_shipment(ci_browser, tmp_path):
    from tests.test_trade_domain_api import post, review, choice

    page, context, client, base = ci_browser
    page.goto(base + "/app/trade/ci")
    page.get_by_role("button", name="PI 문서 불러오기", exact=False).click()
    expect(page.get_by_text("저장된 PI가 없습니다.", exact=False)).to_be_visible()
    url = base + "/api/trade/ci/source-pis"
    context.route(url, lambda route: route.abort())
    page.get_by_role("button", name="목록 새로고침", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("목록 다시 읽기")
    expect(page.get_by_role("alert")).to_be_focused()
    context.unroute(url)
    incomplete_values = pi_input(document_number="PI-INCOMPLETE").model_dump(mode="json")
    incomplete_values["buyer"]["address"] = None
    incomplete_values["items"][0]["free_quantity"] = "5"
    incomplete = post(client, "/api/trade/pi", incomplete_values)
    ready = post(client, "/api/trade/pi", pi_input(document_number="PI-READY").model_dump(mode="json"))
    approved = post(client, "/api/trade/pi", pi_input(document_number="PI-APPROVED").model_dump(mode="json"))
    assert choice(client, "pi", review(client, "pi", approved), "approve").status_code == 200
    # 최신 revision만 목록에 표시한다. 오래된 승인 버전은 자동 선택하지 않는다.
    assert client.put(f"/api/trade/pi/{ready['document_id']}", json={"revision": 1, "document": ready["input"]}).status_code == 200
    for number in range(52):
        post(client, "/api/trade/pi", pi_input(document_number=f"PI-{number}-" + "LONG" * 30).model_dump(mode="json"))
    page.get_by_role("button", name="목록 다시 읽기", exact=True).click()
    expect(page.get_by_role("radio")).to_have_count(50)
    expect(page.get_by_role("radio", checked=True)).to_have_count(0)
    layout(page)
    more_url = url + "?cursor=*"
    context.route(more_url, lambda route: route.abort())
    page.get_by_role("button", name="PI 더 보기", exact=True).click()
    expect(page.get_by_role("alert")).to_be_visible()
    expect(page.get_by_role("radio")).to_have_count(50)
    context.unroute(more_url)
    page.get_by_role("button", name="PI 더 보기", exact=True).click()
    expect(page.get_by_role("radio")).to_have_count(55)
    expect(page.get_by_role("button", name="PI 더 보기", exact=True)).to_have_count(0)
    for number, status, revision in (("PI-APPROVED", "승인 완료", 1), ("PI-READY", "PI 승인 필요", 2), ("PI-INCOMPLETE", "정보 보완 필요", 1)):
        radio = page.get_by_role("radio", name=number, exact=False)
        if number == "PI-READY":
            previous = page.get_by_role("radio", name="PI-APPROVED", exact=False)
            previous.focus()
            page.keyboard.press("ArrowDown")
        else:
            radio.click()
        expect(radio).to_be_checked()
        expect(radio).to_be_enabled()
        expect(page.get_by_label("원본 PI 남은 작업")).to_contain_text(f"버전 {revision} · {status}")
    page.get_by_role("button", name="선적 정보 입력", exact=True).click()
    shipment = {"CI 문서번호": "CI-" + "LONG" * 30, "선적 참조": "SHIP-" + "LONG" * 30,
                "원산지": "Republic of Korea", "납품 조건": "FOB Busan", "배송지": "1 Fiction Avenue " * 20,
                "청구지": "2 Fiction Avenue " * 20, "비고": "Virtual shipment notes " * 10}
    for label, value in shipment.items():
        page.get_by_label(label, exact=True).fill(value)
    expect(page.get_by_role("button", name="CI 생성", exact=True)).to_be_disabled()
    assert client.get("/api/trade/ci").json() == []
    assert client.post("/api/trade/ci", json={"source_pi_id": incomplete["document_id"], "source_revision": 1}).status_code == 409
    page.get_by_role("button", name="작성 내용 보기", exact=True).click()
    reference = page.get_by_label("선적 참조", exact=True)
    reference.focus()
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 844})
        expect(reference).to_be_focused()
        expect(page.locator('[aria-current="step"]')).to_have_text("선적 정보")
        expect(page.locator(".pi-summary-toggle")).to_have_attribute("aria-expanded", "true")
        for label, value in shipment.items():
            expect(page.get_by_label(label, exact=True)).to_have_value(value)
    layout(page)
    keyboard_reachable(page)
    # 실제 별도 PI 탭에서 보완/발급한다. CI 준비 화면은 서버 생성 없이 유지한다.
    with page.expect_popup() as popup:
        page.get_by_role("link", name="PI 보완·승인하기", exact=False).click()
    pi_tab = popup.value
    pi_tab.get_by_label("주소 (영문)", exact=True).fill("3 Fiction Ave, Seoul")
    pi_tab.get_by_role("button", name="임시 저장", exact=True).click()
    pi_tab.get_by_role("button", name="최종 검토 만들기", exact=True).click()
    pi_tab.get_by_role("button", name="승인하고 파일 발급", exact=True).click()
    expect(pi_tab.get_by_role("button", name="PDF 다운로드", exact=True)).to_be_enabled()
    pi_tab.close()
    page.get_by_role("button", name="PI 상태 다시 확인", exact=True).click()
    expect(page.get_by_label("원본 PI 남은 작업")).to_contain_text("현재 PI는 버전 2")
    expect(page.get_by_role("button", name="CI 생성", exact=True)).to_be_disabled()
    page.get_by_role("button", name="이전", exact=True).click()
    page.get_by_role("button", name="PI 더 보기", exact=True).click()
    page.get_by_role("radio", name="PI-INCOMPLETE · 버전 2", exact=False).click()
    page.get_by_role("button", name="선적 정보 입력", exact=True).click()
    for label, value in shipment.items():
        expect(page.get_by_label(label, exact=True)).to_have_value(value)
    # 선택 뒤 PI·단가표가 바뀌어도 선택한 승인 버전의 가격/FOC로 발급한다.
    original = client.get(f"/api/trade/pi/{incomplete['document_id']}").json()
    new_values = deepcopy(original["input"])
    new_values["items"][0].update(unit_price="25", confirm_price_override=True)
    assert client.put(f"/api/trade/pi/{incomplete['document_id']}", json={"revision": 2, "document": new_values}).status_code == 200
    assert client.put("/api/trade/settings/prices", json={"item_name": "Virtual Serum", "capacity": "50ml", "role": "sale", "currency": "USD", "unit_price": "99", "price_basis": "PCS"}).status_code == 200
    page.get_by_role("button", name="CI 생성", exact=True).click()
    expect(page.get_by_role("button", name="최종 검토 만들기", exact=True)).to_be_enabled()
    path = "/api/trade/ci/" + page.url.rsplit("/", 1)[1]
    saved = client.get(path).json()
    assert saved["input"]["source_revision"] == 2
    assert saved["document"]["total"] == original["document"]["total"] == "80.00"
    for field in ("unit_price", "paid_quantity", "free_quantity"):
        assert saved["document"]["items"][0][field] == original["document"]["items"][0][field]
    assert not saved["document"].get("bank") and saved["document"].get("payment_terms") in (None, "N/A")
    page.get_by_role("navigation", name="CI 작성 단계").get_by_role("button", name="원본 PI", exact=True).click()
    expect(page.get_by_role("radio")).to_have_count(0)
    expect(page.get_by_text("저장된 CI의 원본은 고정됩니다.", exact=False)).to_be_visible()
    page.get_by_role("navigation", name="CI 작성 단계").get_by_role("button", name="전체 확인", exact=True).click()
    ci_issue_download(page, context, client, base, tmp_path, "ci-linked")
    page.get_by_role("navigation", name="CI 작성 단계").get_by_role("button", name="선적 정보", exact=True).click()
    page.get_by_label("선적 참조", exact=True).fill("UNSAVED LINKED SHIPMENT")
    current = client.get(path).json()
    assert client.put(path, json={"revision": current["revision"], "document": current["input"]}).status_code == 200
    page.get_by_role("button", name="저장하고 전체 확인", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("입력은 보존")
    expect(page.get_by_role("alert")).to_be_focused()
    expect(page.get_by_label("선적 참조", exact=True)).to_have_value("UNSAVED LINKED SHIPMENT")
    page.get_by_role("button", name="최신본 다시 읽기", exact=True).click()
    expect(page.get_by_role("button", name="최종 검토 만들기", exact=True)).to_be_enabled()
    page.get_by_role("navigation", name="CI 작성 단계").get_by_role("button", name="선적 정보", exact=True).click()
    expect(page.get_by_label("선적 참조", exact=True)).to_have_value(shipment["선적 참조"])


@pytest.mark.parametrize("method", ["direct", "extract"])
def test_ci_standalone_mobile_complete_price_conflict(ci_browser, monkeypatch, tmp_path, method):
    from app.trade.ci import agent as ci_agent

    page, context, client, base = ci_browser
    values = pi_input(document_number="CI-EXTRACT").model_dump(mode="json")
    values.pop("payment_terms")
    values["items"][0].pop("is_sample")
    values["items"][0].update(unit_price="9", source="Virtual Serum 50ml 10 PCS USD 9 discount 0")
    values["buyer"]["address"] = None
    values.update(mode="standalone", document_type="CI", shipment_reference="SHIP", country_of_origin="Korea")
    monkeypatch.setattr(ci_agent, "extract_facts", lambda *_: deepcopy(values))
    monkeypatch.setattr(trade_router, "user_openai", lambda *_args, **_kwargs: nullcontext(SimpleNamespace(issue=None)))
    page.goto(base + "/app/trade/ci")
    page.get_by_role("button", name="원문 붙여넣기" if method == "extract" else "직접 작성", exact=False).click()
    if method == "extract":
        source = "CI-EXTRACT Acme Trading FOB Busan SHIP Korea Virtual Serum 50ml 10 PCS USD 9 discount 0"
        page.get_by_label("거래 원문", exact=True).fill(source)
        layout(page)
        expect(page.get_by_label("거래 원문", exact=True)).to_have_value(source)
        extract_url = base + "/api/trade/ci/extract-standalone"
        context.route(extract_url, lambda route: route.abort())
        page.get_by_role("button", name="원문에서 정보 가져오기", exact=True).click()
        expect(page.get_by_role("alert")).to_be_focused()
        expect(page.get_by_label("거래 원문", exact=True)).to_have_value(source)
        context.unroute(extract_url)
        page.get_by_role("button", name="원문에서 정보 가져오기", exact=True).click()
        expect(page.get_by_role("heading", name="거래처 입력", exact=True)).to_be_focused()
        expect(page.get_by_label("회사명 (영문)", exact=True)).to_have_count(0)
    else:
        page.get_by_label("회사명 (영문)", exact=True).fill("VirtualCounterparty" * 10)
        page.get_by_role("button", name="임시 저장", exact=True).click()
        expect(page.get_by_role("button", name="최종 검토 만들기", exact=True)).to_be_disabled()
        page.get_by_role("button", name="거래처 보완", exact=True).click()
    page.get_by_label("주소 (영문)", exact=True).fill("1 Fiction Avenue " * 20)
    page.get_by_role("navigation", name="CI 작성 단계").get_by_role("button", name="품목", exact=True).click()
    if method == "direct":
        page.get_by_label("품목명 (영문) · 품목 1", exact=True).fill("Virtual Serum")
        page.get_by_label("유상 수량 · 품목 1", exact=True).fill("10")
        page.get_by_text("품목 1 상세", exact=False).click()
        page.get_by_label("용량·규격 · 품목 1", exact=True).fill("50ml")
    else:
        page.get_by_role("button", name="임시 저장", exact=True).click()
        expect(page.get_by_role("button", name="최종 검토 만들기", exact=True)).to_be_disabled()
        page.get_by_role("button", name="품목 보완", exact=True).click()
        page.get_by_label("품목 1 · 단가표 대신 입력한 단가 사용", exact=True).check()
    page.get_by_role("button", name="작성 내용 보기", exact=True).click()
    field = page.get_by_label("유상 수량 · 품목 1", exact=True)
    field.focus()
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 844})
        expect(field).to_have_value("10")
        expect(field).to_be_focused()
        expect(page.locator('[aria-current="step"]')).to_have_text("품목")
        expect(page.locator(".pi-summary-toggle")).to_have_attribute("aria-expanded", "true")
    layout(page)
    keyboard_reachable(page)
    page.get_by_role("navigation", name="CI 작성 단계").get_by_role("button", name="거래·선적 조건", exact=True).click()
    page.get_by_label("CI 문서번호", exact=True).fill("CI-" + method + "-LONG" * 30)
    page.get_by_label("선적 참조", exact=True).fill("SHIP-MOBILE")
    page.get_by_label("원산지", exact=True).fill("Republic of Korea")
    page.get_by_label("납품 조건", exact=True).fill("FOB Busan")
    layout(page)
    page.get_by_role("button", name="저장하고 전체 확인", exact=True).click()
    expect(page.get_by_role("button", name="최종 검토 만들기", exact=True)).to_be_enabled()
    path = "/api/trade/ci/" + page.url.rsplit("/", 1)[1]
    saved = client.get(path).json()
    assert saved["document"]["total"] == ("80.00" if method == "direct" else "90.00")
    assert saved["input"]["mode"] == "standalone" and not saved["document"].get("bank")
    assert saved["document"].get("payment_terms") in (None, "N/A")
    ci_issue_download(page, context, client, base, tmp_path, "ci-" + method)
    page.get_by_role("navigation", name="CI 작성 단계").get_by_role("button", name="거래·선적 조건", exact=True).click()
    page.get_by_label("선적 참조", exact=True).fill("UNSAVED STANDALONE SHIPMENT")
    current = client.get(path).json()
    assert client.put(path, json={"revision": current["revision"], "document": current["input"]}).status_code == 200
    page.get_by_role("button", name="임시 저장", exact=True).click()
    expect(page.get_by_role("alert")).to_be_focused()
    expect(page.get_by_label("선적 참조", exact=True)).to_have_value("UNSAVED STANDALONE SHIPMENT")
    expect(page.locator('[aria-current="step"]')).to_have_text("거래·선적 조건")
    page.get_by_role("button", name="최신본 다시 읽기", exact=True).click()
    expect(page.get_by_role("button", name="최종 검토 만들기", exact=True)).to_be_enabled()
    page.get_by_role("navigation", name="CI 작성 단계").get_by_role("button", name="거래·선적 조건", exact=True).click()
    expect(page.get_by_label("선적 참조", exact=True)).to_have_value("SHIP-MOBILE")


@pytest.mark.parametrize("method", ["direct", "extract"])
def test_pl_mobile_two_approvals_conflict_and_download(ci_browser, monkeypatch, tmp_path, method):
    from app.trade.pl import agent
    from tests.test_trade_domain_api import pl_values

    page, context, client, base = ci_browser
    values = pl_values()
    values.update(document_number="PL-MOBILE", container_count="2 x 40FT" if method == "extract" else None)
    values["buyer"]["address"] = None
    monkeypatch.setattr(agent, "extract_facts", lambda *_: deepcopy(values))
    monkeypatch.setattr(trade_router, "user_openai", lambda *_args, **_kwargs: nullcontext(SimpleNamespace(issue=None)))
    page.goto(base + "/app/trade/pl")
    page.get_by_role("button", name="원문 붙여넣기" if method == "extract" else "직접 작성", exact=False).click()
    if method == "extract":
        page.get_by_label("거래 원문", exact=True).fill("Virtual packing source")
        page.get_by_role("button", name="← 작성 방법 선택", exact=True).click()
        page.get_by_role("button", name="원문 붙여넣기", exact=False).click()
        expect(page.get_by_label("거래 원문", exact=True)).to_have_value("Virtual packing source")
        page.get_by_role("button", name="원문에서 정보 가져오기", exact=True).click()
    else:
        page.get_by_label("회사명 (영문)", exact=True).fill("Virtual Buyer")
    page.get_by_label("주소 (영문)", exact=True).fill("1 Fiction Avenue " * 20)
    nav = page.get_by_role("navigation", name="PL 작성 단계")
    nav.get_by_role("button", name="품목·포장", exact=True).click()
    if method == "direct":
        page.get_by_label("품목명 (영문) · 품목 1", exact=True).fill("Virtual Item")
        page.get_by_label("수량 · 품목 1", exact=True).fill("10")
        page.get_by_label("포장 수 · 품목 1", exact=True).fill("2")
        page.get_by_label("포장 종류 · 품목 1", exact=True).fill("BOX")
    page.get_by_text("별도 포장 행 ·", exact=False).click()
    page.get_by_role("button", name="포장 행 추가", exact=True).click()
    for label, value in [("포장 종류", "PALLET"), ("포장 수", "3"), ("순중량 (kg)", "10"), ("총중량 (kg)", "12")]:
        page.get_by_label(label + " · 포장 1", exact=True).fill(value)
    field = page.get_by_label("포장 수 · 포장 1", exact=True)
    page.get_by_role("button", name="작성 내용 보기", exact=True).click()
    field.focus()
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 844})
        expect(field).to_have_value("3")
        expect(field).to_be_focused()
        expect(page.locator(".pi-summary-toggle")).to_have_attribute("aria-expanded", "true")
    layout(page)
    keyboard_reachable(page)
    nav.get_by_role("button", name="선적 조건·합계", exact=True).click()
    page.get_by_label("PL 문서번호", exact=True).fill("PL-" + method)
    page.get_by_label("선적 참조", exact=True).fill("SHIP-MOBILE")
    page.get_by_label("납품 조건", exact=True).fill("FOB Busan")
    page.get_by_label("원본 포장 수", exact=True).fill("99")
    page.get_by_role("button", name="저장하고 전체 확인", exact=True).click()
    approve = page.get_by_role("button", name="합계 승인", exact=True)
    expect(approve).to_be_enabled()
    path = "/api/trade/pl/" + page.url.rsplit("/", 1)[1]
    original = client.get(path).json()
    comparison = client.get(path + "/packing-review").json()
    assert original["document"]["packing_totals"]["packages_total"]["net_weight_kg"] == "10"
    if method == "extract":
        assert original["document"]["packing_totals"]["quantities"] == {"PCS": "616001", "KG": "2399.48"}
    layout(page)
    region = page.get_by_role("region", name="원본과 서버 계산 합계 · 가로 스크롤", exact=True)
    region.focus()
    page.keyboard.press("ArrowRight")
    page.wait_for_function("document.querySelector('.packing-review .table-scroll').scrollLeft > 0")
    keyboard_reachable(page)
    # 해시 불일치와 오래된 revision은 서버에서 거부한다.
    assert client.post(path + "/packing-review/decisions", json={"action": "approve", "revision": comparison["revision"], "content_hash": "0" * 64}).status_code == 409
    nav.get_by_role("button", name="품목·포장", exact=True).click()
    page.get_by_label("수량 · 품목 1", exact=True).fill("11")
    nav.get_by_role("button", name="거래처", exact=True).click()
    page.get_by_role("button", name="이전", exact=True).click()
    expect(approve).to_be_disabled()
    page.get_by_role("button", name="변경사항 저장", exact=True).click()
    expect(approve).to_be_enabled()
    approve.click()
    expect(page.get_by_role("button", name="최종 검토 만들기", exact=True)).to_be_enabled()
    approved = client.get(path).json()
    assert approved["proposal_id"] is None
    assert client.post(path + "/packing-review/decisions", json={"action": "approve", "revision": comparison["revision"], "content_hash": comparison["content_hash"]}).status_code == 409
    page.get_by_role("button", name="합계 취소", exact=True).click()
    expect(approve).to_be_enabled()
    assert client.get(path).json()["document"]["actual_package_count"] == "99"
    approve.click()
    page.get_by_role("button", name="최종 검토 만들기", exact=True).click()
    expect(page.get_by_role("heading", name="최종 검토 · 버전", exact=False)).to_be_focused()
    page.get_by_role("button", name="수정", exact=True).click()
    page.get_by_label("주소 (영문)", exact=True).fill("2 Fiction Avenue")
    page.get_by_role("button", name="임시 저장", exact=True).click()
    expect(approve).to_be_enabled()
    expect(page.get_by_role("button", name="최종 검토 만들기", exact=True)).to_be_disabled()
    approve.click()
    page.get_by_role("button", name="최종 검토 만들기", exact=True).click()
    layout(page)
    page.screenshot(path=str(tmp_path / ("pl-" + method + ".png")), full_page=True)
    page.get_by_role("button", name="승인하고 파일 발급", exact=True).click()
    expect(page.get_by_role("button", name="PDF 다운로드", exact=True)).to_be_enabled()
    document = client.get(path).json()
    proposal = client.get(path + "/reviews/" + str(document["proposal_id"])).json()
    for file in proposal["files"]:
        url = base + file["download_url"]
        button = page.get_by_role("button", name=file["file_format"].upper() + " 다운로드", exact=True)
        context.route(url, lambda route: route.abort())
        button.click()
        expect(page.get_by_role("alert")).to_be_focused()
        context.unroute(url)
        with page.expect_download() as download:
            button.click()
        assert sha256(Path(download.value.path()).read_bytes()).hexdigest() == file["content_hash"]
    nav.get_by_role("button", name="선적 조건·합계", exact=True).click()
    page.get_by_label("선적 참조", exact=True).fill("UNSAVED SHIPMENT")
    current = client.get(path).json()
    assert client.put(path, json={"revision": current["revision"], "document": current["input"]}).status_code == 200
    page.get_by_role("button", name="임시 저장", exact=True).click()
    expect(page.get_by_role("alert")).to_be_focused()
    expect(page.get_by_label("선적 참조", exact=True)).to_have_value("UNSAVED SHIPMENT")
