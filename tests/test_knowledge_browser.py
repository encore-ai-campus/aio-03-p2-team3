"""빌드한 React + 실제 FastAPI/pgvector + 가짜 외부 공급자의 브라우저 완주."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
from threading import Thread
import time
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright
from sqlalchemy import select
import uvicorn

from app.auth.supabase import TokenVerifier
from app.config import Settings, local_listener
from app.knowledge.repository import KnowledgeParent
from app.main import create_app
from app.web import frontend
from tests.fakes.storage import FakeStorage
from tests.test_knowledge import FakeEmbedder, FakeExtractor, FakeRenderer, png, pdf
from tests.test_supabase_auth import FakeJwks, SUPABASE_URL


@contextmanager
def serve(app):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", ws="none"))
    def run():
        with local_listener(listener):
            server.run(sockets=[listener])
    thread = Thread(target=run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(.01)
    assert server.started, "시험용 FastAPI가 시작되지 않았습니다."
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
        assert not thread.is_alive(), "시험용 FastAPI가 종료되지 않았습니다."


def test_browser_upload_compare_conflict_confirm_chunks_and_mobile(database_url, tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "SUPABASE_URL": SUPABASE_URL,
                   "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_fake_for_browser_test", "FRONTEND_PORT": "5174"}
    output = tmp_path / "frontend-dist"
    subprocess.run(["npm", "run", "build", "--", "--outDir", str(output)], cwd=root / "frontend",
                   env=environment, check=True, capture_output=True, timeout=120, shell=os.name == "nt")
    monkeypatch.setattr(frontend, "DIST", output)
    jwks, extractor, embedder = FakeJwks(), FakeExtractor(uncertain=True), FakeEmbedder()
    subject = uuid4()
    token = jwks.token(sub=subject)
    app = create_app(Settings(database_url=database_url, session_secret="fake-browser-session"),
                     supabase_auth=TokenVerifier(SUPABASE_URL, fetch_jwks=jwks.serve), storage=FakeStorage(),
                     knowledge_adapters=lambda *_: (FakeRenderer(), extractor, embedder))
    session = {"access_token": token, "refresh_token": "fake-refresh", "token_type": "bearer",
               "expires_at": int(time.time()) + 3600, "expires_in": 3600,
               "user": {"id": str(subject), "aud": "authenticated", "email": "browser@example.invalid"}}
    with serve(app) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        # 외부 서비스는 전혀 호출하지 않는다. 검증된 가짜 세션만 로컬 브라우저에 넣는다.
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
        context.add_init_script("localStorage.setItem('sb-test-project-auth-token', " + json.dumps(json.dumps(session)) + ")")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base + "/app/")
        expect(page.get_by_role("heading", name="문서작성", exact=True)).to_be_visible()
        page.locator(".side").get_by_role("link", name="문서함", exact=True).click()
        expect(page).to_have_url(base + "/app/documents")
        expect(page.get_by_role("heading", name="문서함", exact=True)).to_be_visible()
        expect(page.locator('a[href="/app/knowledge"]')).to_have_count(0)
        page.get_by_label("문서 선택").set_input_files({"name": "가상 문서.png", "mimeType": "image/png", "buffer": png()})
        page.get_by_role("button", name="문서 업로드").click()
        detail = page.get_by_role("region", name="문서 상세")
        expect(detail.get_by_text("원문 확인 필요", exact=True)).to_be_visible(timeout=15000)
        expect(detail.get_by_alt_text("원본에서 렌더링한 1페이지")).to_be_visible()
        editor = detail.get_by_label("추출문 · 원본과 비교해 수정하세요")
        final_text = "제1조 가상 최종 확인\n검수가 끝난 뒤 지급한다. 단, 예외 조건도 함께 보존한다."
        editor.fill(final_text)
        document_id = page.url.split("document=")[1]
        path = f"{base}/api/knowledge/documents/{document_id}"
        headers = {"Authorization": "Bearer " + token}
        with httpx.Client() as client:
            current = client.get(path, headers=headers).json()
            other = client.put(path + "/extraction", headers=headers, json={"attempt_id": current["attempt_id"],
                "revision": current["revision"], "confirm": False,
                "pages": [{"number": 1, "text": "다른 창에서 저장한 가상 원문"}]})
            assert other.status_code == 200
        detail.get_by_role("button", name="원문 확정 후 임베딩").click()
        expect(detail.get_by_text("서버의 원문 또는 상태가 바뀌었습니다.", exact=False)).to_be_visible()
        expect(editor).to_have_value(final_text)
        expect(editor).to_have_value(final_text)
        with page.expect_response(lambda response: response.url == path and response.request.method == "GET"):
            detail.get_by_role("button", name="다시 읽기").click()
        detail.get_by_role("button", name="수정 초기화").click()
        expect(editor).to_have_value("다른 창에서 저장한 가상 원문")
        editor.fill(final_text)
        detail.get_by_role("button", name="원문 확정 후 임베딩").click()
        expect(detail.get_by_text("저장 완료", exact=True)).to_be_visible(timeout=15000)
        expect(detail.get_by_role("heading", name="저장한 청크")).to_be_visible()
        detail.get_by_text("연결한 부모 조항 원문 보기").click()
        expect(detail.locator(".knowledge-chunks details pre")).to_have_text(final_text)
        with app.state.database.session() as database_session:
            assert database_session.scalar(select(KnowledgeParent.text).where(KnowledgeParent.document_id == document_id)) == final_text
        screenshot_dir = Path(os.environ.get("KNOWLEDGE_SCREENSHOT_DIR", str(tmp_path)))
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot_dir / "knowledge-desktop.png"), full_page=True)
        page.goto(base + "/app/knowledge?document=" + document_id + "#original")
        expect(page).to_have_url(base + "/app/documents?document=" + document_id + "#original")
        expect(detail.get_by_text("저장 완료", exact=True)).to_be_visible()
        with page.expect_download() as download:
            detail.get_by_role("button", name="원본 다운로드", exact=True).click()
        assert Path(download.value.path()).read_bytes() == png()
        page.reload()
        expect(detail.get_by_text("저장 완료", exact=True)).to_be_visible()
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.get_by_role("heading", name="문서함", exact=True)).to_be_visible()
        expect(detail.get_by_alt_text("원본에서 렌더링한 1페이지")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(screenshot_dir / "knowledge-mobile.png"), full_page=True)
        page.keyboard.press("Tab")
        assert not errors
        assert len(extractor.calls) == 1 and len(embedder.calls) == 1
        page.set_viewport_size({"width": 1440, "height": 1000})
        original_pdf = pdf(2)
        page.get_by_label("문서 선택").set_input_files({"name": "원본.pdf", "mimeType": "application/pdf", "buffer": original_pdf})
        page.get_by_role("button", name="문서 업로드", exact=True).click()
        expect(detail.get_by_role("heading", name="원본.pdf")).to_be_visible()
        detail.get_by_role("button", name="원본 보기", exact=True).click()
        expect(detail.get_by_alt_text("업로드한 원본 1페이지")).to_be_visible()
        expect(detail.get_by_text("원본 1 / 2페이지", exact=True)).to_be_visible()
        detail.get_by_role("button", name="원본 다음 페이지", exact=True).click()
        expect(detail.get_by_alt_text("업로드한 원본 2페이지")).to_be_visible()
        expect(detail.get_by_role("button", name="원본 다음 페이지", exact=True)).to_be_disabled()
        detail.get_by_role("button", name="원본 이전 페이지", exact=True).click()
        expect(detail.get_by_alt_text("업로드한 원본 1페이지")).to_be_visible()
        page.screenshot(path=str(screenshot_dir / "documents-pdf-preview.png"), full_page=True)
        with page.expect_download() as download:
            detail.get_by_role("button", name="원본 다운로드", exact=True).click()
        assert Path(download.value.path()).read_bytes() == original_pdf
        page.locator(".knowledge-list").get_by_role("button", name="가상 문서.png", exact=False).click()
        expect(detail.get_by_role("heading", name="가상 문서.png")).to_be_visible()
        expect(detail.get_by_alt_text("업로드한 원본 1페이지")).to_have_count(0)
        browser.close()


def test_local_browser_missing_key_retry_failure_and_recovery_without_gmail(database_url, tmp_path, monkeypatch):
    from dataclasses import replace
    from threading import Event
    from app.db.models import User
    from app.knowledge.embeddings import OpenAIEmbedder
    from app.knowledge.extract import OpenAIDocumentExtractor
    from app.knowledge.router import make_adapters
    from app.knowledge.schemas import EmbeddingBatch, ExtractionResult, KnowledgeError, PageText
    from tests.test_local_openai import listener

    root = Path(__file__).resolve().parents[1]
    output = tmp_path / 'frontend-dist'
    subprocess.run(['npm', 'run', 'build', '--', '--outDir', str(output)], cwd=root / 'frontend',
                   env={**os.environ, 'SUPABASE_URL': SUPABASE_URL, 'SUPABASE_PUBLISHABLE_KEY': 'sb_publishable_fake_browser'},
                   check=True, capture_output=True, timeout=120, shell=os.name == "nt")
    monkeypatch.setattr(frontend, 'DIST', output)
    mode = {'key': '', 'fail': False}
    release = Event()
    def extract(self, pages):
        assert self.read_key() == 'fake-local-browser-key'
        if mode['fail']:
            assert release.wait(10), '시험용 실패 응답 대기가 끝나지 않았습니다.'
            raise KnowledgeError('provider_unavailable', '가상 연결 실패')
        return ExtractionResult(profile=self.profile, pages=[PageText(number=p.number, source=p.source, text='제1조 가상 원문\n검수 후 지급한다.') for p in pages])
    def embed(self, texts):
        assert self.read_key() == 'fake-local-browser-key'
        return EmbeddingBatch(profile=self.profile, vectors=[[.25] * self.profile.dimensions for _ in texts])
    monkeypatch.setattr(OpenAIDocumentExtractor, 'extract', extract)
    monkeypatch.setattr(OpenAIEmbedder, 'embed_documents', embed)
    jwks, storage = FakeJwks(), FakeStorage()
    subject = uuid4()
    token = jwks.token(sub=subject)
    session = {'access_token': token, 'refresh_token': 'fake-refresh', 'token_type': 'bearer',
               'expires_at': int(time.time()) + 3600, 'expires_in': 3600,
               'user': {'id': str(subject), 'aud': 'authenticated', 'email': 'browser@example.invalid'}}
    settings = Settings(database_url=database_url, ai_runtime='local', knowledge_embedding_dimensions='3')
    def adapters(owner, profile):
        return make_adapters(app.state.database, replace(settings, openai_api_key=mode['key']), owner, profile)
    with listener():
        app = create_app(settings, supabase_auth=TokenVerifier(SUPABASE_URL, fetch_jwks=jwks.serve),
                         storage=storage, knowledge_adapters=adapters)
        with serve(app) as base, sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
            context.add_init_script("localStorage.setItem('sb-test-project-auth-token', " + json.dumps(json.dumps(session)) + ')')
            page = context.new_page()
            page.goto(base + '/app/documents')
            page.get_by_label('문서 선택').set_input_files({'name': 'local-fake.png', 'mimeType': 'image/png', 'buffer': png()})
            page.get_by_role('button', name='문서 업로드').click()
            expect(page.get_by_text('로컬 .env에 OPENAI_API_KEY', exact=False)).to_be_visible()
            assert not storage.objects
            mode['key'] = 'fake-local-browser-key'
            page.get_by_role('button', name='문서 업로드').click()
            detail = page.get_by_role('region', name='문서 상세')
            expect(detail.get_by_text('저장 완료', exact=True)).to_be_visible(timeout=15000)
            with app.state.database.session() as db:
                users = list(db.scalars(select(User)))
                assert len(users) == 1 and users[0].google_sub is None and users[0].last_login_at is None
            mode['key'] = ''
            detail.get_by_role('button', name='다시 추출·임베딩').click()
            expect(detail.get_by_text('로컬 .env에 OPENAI_API_KEY', exact=False)).to_be_visible()
            expect(detail.get_by_text('서버의 원문 또는 상태가 바뀌었습니다.', exact=False)).to_have_count(0)
            expect(detail.get_by_text('저장 완료', exact=True)).to_be_visible()
            mode.update(key='fake-local-browser-key', fail=True)
            detail.get_by_role('button', name='다시 추출·임베딩').click()
            expect(detail.get_by_text('처리를 요청했습니다.', exact=True)).to_be_visible()
            release.set()
            expect(detail.get_by_text('처리 실패', exact=True)).to_be_visible(timeout=15000)
            expect(detail.get_by_text('처리를 요청했습니다.', exact=True)).to_have_count(0)
            expect(page.locator('.knowledge-upload li')).to_have_text('local-fake.png — 처리 실패')
            detail.get_by_role('button', name='원본 보기', exact=True).click()
            expect(detail.get_by_alt_text('업로드한 원본 1페이지')).to_be_visible()
            detail.get_by_role('button', name='원본 미리보기 닫기', exact=True).click()
            expect(detail.get_by_alt_text('업로드한 원본 1페이지')).to_have_count(0)
            expect(detail.get_by_text('이전에 저장한 인덱스를 보존하고 있습니다.', exact=False)).to_be_visible()
            screenshot_dir = Path(os.environ.get('KNOWLEDGE_SCREENSHOT_DIR', str(tmp_path)))
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot_dir / 'knowledge-local-failed.png'), full_page=True)
            mode['fail'] = False
            detail.get_by_role('button', name='다시 추출·임베딩').click()
            expect(detail.get_by_text('저장 완료', exact=True)).to_be_visible(timeout=15000)
            expect(detail.get_by_role('heading', name='저장한 청크')).to_be_visible()
            expect(detail.get_by_text('이전에 저장한 인덱스를 보존하고 있습니다.', exact=False)).to_have_count(0)
            page.screenshot(path=str(screenshot_dir / 'knowledge-local-recovered.png'), full_page=True)
            assert 'fake-local-browser-key' not in page.content()
            browser.close()
