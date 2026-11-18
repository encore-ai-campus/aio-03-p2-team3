"""실제 React/API/체크포인트와 가짜 모델·Gmail의 사용자 승인 경로."""
import json
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import httpx
from playwright.sync_api import expect, sync_playwright
import pytest

from tests.test_master_agent import Choices, app_for, auth, company
from tests.fakes.storage import FakeStorage
from tests.test_pi_domain import pi_input
from tests.fakes.gmail import FakeGmailGoogle
from tests.fakes.google import fake_login
from tests.test_approval import add_mail
from tests.test_knowledge_browser import serve
from tests.test_supabase_auth import SUPABASE_URL, FakeJwks
from app.web import frontend


pytestmark = pytest.mark.slow


def test_agent_browser_question_reload_approval_once_and_mobile(database_url, tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    dist = tmp_path / 'dist'
    subprocess.run(['npm', 'run', 'build', '--', '--outDir', str(dist)], cwd=root / 'frontend',
        env={**os.environ, 'SUPABASE_URL': SUPABASE_URL, 'SUPABASE_PUBLISHABLE_KEY': 'sb_publishable_fake_for_browser'},
        check=True, capture_output=True, timeout=120, shell=os.name == 'nt')
    monkeypatch.setattr(frontend, 'DIST', dist)
    jwks, google, subject = FakeJwks(), FakeGmailGoogle(), uuid4()
    token = jwks.token(sub=subject)
    choices = Choices([('get_mail', {'thread_id': 'fake-thread'}),
        ('ask_user', {'question': '답장을 진행할까요?'}),
        ('prepare_send', {'candidate_id': 1}), '승인한 답장을 발송했습니다.', '앞선 발송 결과를 확인했습니다.'])
    app = app_for(database_url, jwks, google, choices, storage=FakeStorage())
    session = {'access_token': token, 'refresh_token': 'fake-refresh', 'token_type': 'bearer',
        'expires_at': int(time.time()) + 3600, 'expires_in': 3600,
        'user': {'id': str(subject), 'aud': 'authenticated', 'email': 'browser@example.invalid'}}
    with serve(app) as base, sync_playwright() as p:
        owner = httpx.get(base + '/api/me', headers=auth(token)).json()['user_id']
        with app.state.database.session() as s:
            from app.db.models import User
            from app.services.auth import store_login, utcnow
            store_login(s, app.state.google_access, s.get(User, owner), fake_login(), utcnow())
        ids = add_mail(type('Client', (), {'app': app})(), owner)
        choices.calls[2] = ('prepare_send', {'candidate_id': ids[0]})
        browser = p.chromium.launch()
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(base + '/') else route.abort())
        context.add_init_script("localStorage.setItem('sb-test-project-auth-token', " + json.dumps(json.dumps(session)) + ")")
        page = context.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + '/app/agent')
        expect(page.get_by_role('heading', name='업무 도우미', exact=True)).to_be_visible()
        page.get_by_label('업무 요청', exact=True).fill('가상 메일 확인하고 답장 준비해 줘')
        page.get_by_role('button', name='요청하기', exact=True).click()
        region = page.get_by_role('region', name='추가 정보 입력')
        expect(region).to_be_visible(timeout=20000)
        expect(region).to_be_focused()
        page.reload()
        expect(region).to_be_visible()
        region.get_by_label('답변', exact=True).fill('네')
        region.get_by_role('button', name='답변하고 계속').click()
        expect(region.get_by_label('답장 후보', exact=True)).to_be_visible(timeout=20000)
        region.get_by_label('답장 후보', exact=True).select_option(str(ids[1]))
        region.get_by_role('button', name='답변하고 계속').click()
        approval = page.get_by_role('region', name='작업 최종 확인')
        expect(approval).to_be_visible(timeout=20000)
        expect(approval.get_by_text('받는 사람: sender@example.invalid', exact=True)).to_be_visible()
        expect(approval.get_by_text('가상 답장 본문 2', exact=True)).to_be_visible()
        assert not google.mailbox.called('send')
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        approval.get_by_role('button', name='확인하고 보내기').click()
        expect(page.get_by_text('승인한 답장을 발송했습니다.', exact=True)).to_be_visible(timeout=20000)
        assert len(google.mailbox.called('send')) == 1
        page.get_by_label('업무 요청', exact=True).fill('결과 알려 줘')
        page.get_by_role('button', name='요청하기', exact=True).click()
        expect(page.get_by_text('앞선 발송 결과를 확인했습니다.', exact=True)).to_be_visible(timeout=20000)
        page.reload()
        expect(page.get_by_text('앞선 발송 결과를 확인했습니다.', exact=True)).to_be_visible()
        assert len(google.mailbox.called('send')) == 1 and not errors
        with httpx.Client(base_url=base) as client:
            company(client, token)
        choices.calls.extend([('prepare_document', {'kind': 'PI', 'values': pi_input().model_dump(mode='json')}),
            ('prepare_issue', {'kind': 'PI', 'document_id': 1, 'revision': 1}), 'PI 파일을 발급했습니다.'])
        page.get_by_label('업무 요청', exact=True).fill('PI 작성하고 파일 발급해 줘')
        page.get_by_role('button', name='요청하기', exact=True).click()
        expect(approval).to_be_visible(timeout=20000)
        expect(approval.get_by_text('USD 80.00', exact=True)).to_be_visible()
        page.screenshot(path=str(tmp_path / 'agent-approval-mobile.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        approval.get_by_role('button', name='확인하고 승인').click()
        expect(page.get_by_text('PI 파일을 발급했습니다.', exact=True)).to_be_visible(timeout=20000)
        page.locator('.work-row').first.click()  # 접힌 작업 타임라인을 펼친 뒤 단계를 연다(채팅 UI 개편).
        page.get_by_text('파일 발급 · 완료', exact=True).click()
        with page.expect_download() as download:
            page.get_by_role('button', name='다운로드').filter(has_text='.pdf').click()
        assert download.value.suggested_filename.endswith('.pdf')
        assert len(google.mailbox.called('send')) == 1 and not errors
        page.screenshot(path=str(tmp_path / 'agent-mobile.png'), full_page=True)
        browser.close()
