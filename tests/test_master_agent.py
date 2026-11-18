"""실제 마스터·PostgreSQL saver·API와 가짜 모델/Gmail. 유료 API/실제 발송은 없다."""
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, messages_from_dict
import pytest

from app.auth.supabase import TokenVerifier
from app.main import create_app
from app.services.auth import save_login
from tests.fakes.gmail import FakeGmailGoogle
from tests.fakes.google import fake_login
from tests.test_approval import add_mail
from tests.test_gmail_connect import settings_of
from tests.test_supabase_auth import SUPABASE_URL, FakeJwks


class Choices:
    def __init__(self, calls):
        self.calls, self.observed = list(calls), []

    def __call__(self, messages, context):
        self.observed = messages_from_dict(messages)
        item = self.calls.pop(0)
        if isinstance(item, str):
            return AIMessage(item).model_dump()
        name, args = item
        return AIMessage("", tool_calls=[{"id": f"call_{len(self.calls)}", "name": name,
                                        "args": args}]).model_dump()


def app_for(url, jwks, google, choices, settings=None, storage=None):
    return create_app(settings or settings_of(url), google=google, agent_choose=choices, storage=storage,
        supabase_auth=TokenVerifier(SUPABASE_URL, fetch_jwks=jwks.serve))


def auth(token):
    return {"Authorization": "Bearer " + token}


def read(client, token, key):
    response = client.get(f"/api/agent/conversations/{key}", headers=auth(token))
    assert response.status_code == 200, response.text
    return response.json()


def resume(client, token, key, state, response):
    result = client.post(f"/api/agent/conversations/{key}/resume", headers=auth(token),
                         json={"revision": state["revision"], "response": response})
    assert result.status_code == 202, result.text
    return read(client, token, key)


def test_api_real_tools_persist_question_choose_candidate_approve_once(database_url):
    jwks, google = FakeJwks(), FakeGmailGoogle()
    token, outsider = jwks.token(), jwks.token(sub=uuid4())
    choices = Choices([("search_mail", {"query": "가상"}), ("get_mail", {"thread_id": "fake-thread"}),
        ("ask_user", {"question": "답장을 준비할까요?"}),
        ("prepare_send", {"candidate_id": 1}), "승인한 답장을 발송했습니다."])
    config = settings_of(database_url)
    with TestClient(app_for(database_url, jwks, google, choices, config)) as client:
        owner = client.get('/api/me', headers=auth(token)).json()['user_id']
        # 검증된 앱 사용자에게 테스트 Google 연결/수신 자료를 공급한다.
        with client.app.state.database.session() as s:
            from app.db.models import User
            from app.services.auth import store_login, utcnow
            store_login(s, client.app.state.google_access, s.get(User, owner), fake_login(), utcnow())
        ids = add_mail(client, owner)
        choices.calls[3] = ("prepare_send", {"candidate_id": ids[0]})
        response = client.post('/api/agent/conversations', headers=auth(token), json={"message": "가상 메일 확인"})
        assert response.status_code == 202, response.text
        key = response.json()['id']
        state = read(client, token, key)
        assert state['status'] == 'needs_input' and state['waiting']['task_id'] == 'agent', state
        assert state['results'][0]['data']['threads'][0]['thread_id'] == 'fake-thread'
        assert state['results'][1]['data']['messages'][0]['body_text'] == '테스트용 가상 문의입니다.'
        assert not google.mailbox.called('send')
        assert client.get(f'/api/agent/conversations/{key}', headers=auth(outsider)).status_code == 404
        assert client.post(f'/api/agent/conversations/{key}/resume', headers=auth(outsider),
            json={"revision": state['revision'], "response": {}}).status_code == 404
        assert client.get('/api/agent/conversations').status_code == 401

    # 새 앱/새 saver 인스턴스로 재시작해도 동일 질문에서 재개한다.
    with TestClient(app_for(database_url, jwks, google, choices, config)) as client:
        state = read(client, token, key)
        state = resume(client, token, key, state, {"task_id": "agent", "answers": {"response": "네"}})
        assert {"role": "user", "text": "네"} in state['messages']
        assert state['status'] == 'needs_input' and state['waiting']['fields'] == ['candidate_id']
        state = resume(client, token, key, state, {"task_id": state['waiting']['task_id'],
                                                "answers": {"candidate_id": ids[1]}})
        assert state['status'] == 'needs_approval' and state['waiting']['action']['payload']['candidate_id'] == ids[1]
        assert not google.mailbox.called('send')
        waiting, revision = state['waiting'], state['revision']
        decision = {"action_id": waiting['action']['id'], "content_hash": waiting['content_hash'], "decision": "approve"}
        state = resume(client, token, key, state, decision)
        assert state['status'] == 'completed', state
        assert len(google.mailbox.called('send')) == 1
        assert state['results'][-1]['data']['sent_message_id']
        again = client.post(f'/api/agent/conversations/{key}/resume', headers=auth(token),
                            json={"revision": revision, "response": decision})
        assert again.status_code == 409 and len(google.mailbox.called('send')) == 1
        assert client.get('/api/agent/conversations', headers=auth(token)).json()[0]['id'] == key
        assert any(message.type == 'tool' and 'sent_message_id' in message.content for message in choices.observed)


def test_model_loop_is_bounded_and_owner_cannot_be_tool_input(database_url):
    jwks, google = FakeJwks(), FakeGmailGoogle()
    token = jwks.token()
    choices = Choices([('get_mail', {'user_id': 2, 'thread_id': 'missing'})] * 12)
    with TestClient(app_for(database_url, jwks, google, choices)) as client:
        response = client.post('/api/agent/conversations', headers=auth(token), json={'message': '메일 확인'})
        state = read(client, token, response.json()['id'])
        assert state['status'] == 'error' and state['error'] == 'agent_step_limit'
        assert not google.mailbox.called('send')


def company(client, token):
    from tests.test_trade_flow import seal_png
    headers = auth(token)
    assert client.put('/api/trade/settings/company', headers=headers, json={
        'company_name': 'Testworks Trading', 'legal_name_en': 'Testworks Trading Co',
        'address': '7 Test-ro, Seoul', 'ceo_name': 'Example Signer'}).status_code == 200
    assert client.put('/api/trade/settings/banks/USD', headers=headers, json={
        'beneficiary': 'Testworks Trading', 'bank_name': 'Example Bank', 'branch': 'Example Branch',
        'swift': 'EXAMPLE', 'account_number': '000-0000', 'bank_address': '1 Bank-ro, Seoul'}).status_code == 200
    assert client.put('/api/trade/settings/prices', headers=headers, json={
        'item_name': 'Virtual Serum', 'capacity': '50ml', 'role': 'sale', 'currency': 'USD',
        'unit_price': '8', 'price_basis': 'PCS'}).status_code == 200
    assert client.post('/api/trade/settings/branding/seal', headers=headers,
                      files={'image': ('seal.png', seal_png(), 'image/png')}).status_code == 200


def test_document_tool_missing_facts_revises_same_document_and_issues_real_files(database_url):
    from tests.test_pi_domain import pi_input
    from tests.fakes.storage import FakeStorage
    from app.db.models import TradeDocument
    from sqlalchemy import select, func
    jwks, google, storage = FakeJwks(), FakeGmailGoogle(), FakeStorage()
    token = jwks.token()
    choices = Choices([('document_schema', {'kind': 'PI'}),
        ('prepare_document', {'kind': 'PI', 'values': pi_input(payment_terms=None).model_dump(mode='json')}),
        ('ask_user', {'question': '결제 조건을 알려 주세요.'}),
        ('prepare_document', {'kind': 'PI', 'document_id': 1, 'revision': 1, 'values': pi_input().model_dump(mode='json')}),
        ('prepare_issue', {'kind': 'PI', 'document_id': 1, 'revision': 2}), '문서를 발급했습니다.'])
    with TestClient(app_for(database_url, jwks, google, choices, storage=storage)) as client:
        company(client, token)
        response = client.post('/api/agent/conversations', headers=auth(token), json={'message': 'PI를 작성해 줘'})
        key = response.json()['id']
        state = read(client, token, key)
        assert state['waiting']['message'] == '결제 조건을 알려 주세요.', state
        state = resume(client, token, key, state, {'task_id': 'agent', 'answers': {'response': 'T/T'}})
        assert state['status'] == 'needs_approval', state
        assert state['waiting']['action']['payload']['revision'] == 2
        with client.app.state.database.session() as s:
            assert s.scalar(select(func.count()).select_from(TradeDocument)) == 1
        waiting = state['waiting']
        state = resume(client, token, key, state, {'action_id': waiting['action']['id'],
            'content_hash': waiting['content_hash'], 'decision': 'approve'})
        assert state['status'] == 'completed', state
        files = state['results'][-1]['data']['files']
        assert len(files) == 2
        for file in files:
            downloaded = client.get(file['download_url'], headers=auth(token))
            assert downloaded.status_code == 200 and downloaded.content
        assert not google.mailbox.called('send')


def test_native_tool_binding_uses_owner_key_and_refuses_worker_fallback(database, monkeypatch):
    import json
    import httpx
    from langchain_openai import ChatOpenAI
    from langgraph.checkpoint.memory import InMemorySaver
    from app.llm import client as llm
    from app.graph.wiring import make_workflow
    from app.services.auth import make_cipher
    from app.services.openai_keys import save_key
    from app.db.models import User
    config = settings_of(str(database.engine.url))
    cipher = make_cipher(config)
    save_key(database, 1, 'fake-native-owner-key', cipher, settings=config)
    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append((request.headers['authorization'], body))
        output = ([{'type': 'function_call', 'id': 'fc_fake', 'call_id': 'call_fake',
                    'name': 'search_mail', 'arguments': '{"query":"가상"}'}] if len(requests) == 1 else
                  [{'type': 'message', 'id': 'msg_fake', 'status': 'completed', 'role': 'assistant',
                    'content': [{'type': 'output_text', 'text': '일치하는 수집 메일이 없습니다.', 'annotations': []}]}])
        return httpx.Response(200, json={'id': 'resp_fake', 'object': 'response', 'created_at': 1,
            'model': 'gpt-6-luna', 'status': 'completed', 'error': None, 'incomplete_details': None,
            'output': output, 'parallel_tool_calls': False, 'tools': body['tools'],
            'usage': {'input_tokens': 5, 'output_tokens': 5, 'total_tokens': 10}})
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        def build(settings):
            return ChatOpenAI(model=llm.model_name(settings), api_key=settings.openai_api_key,
                use_responses_api=True, http_client=http, http_socket_options=(), max_retries=0)
        monkeypatch.setattr(llm, '_backend_for_settings', build)
        runtime = make_workflow(database=database, checkpointer=InMemorySaver(), key_cipher=cipher, interactive=True)
        state = runtime.start(actor_id=1, thread_id='native-tools', request='가상 메일 검색')
        assert state['error'] is None and state['results']['turn_1_tool_1']['data']['threads'] == []
        assert len(requests) == 2 and all(key == 'Bearer fake-native-owner-key' for key, _ in requests)
        assert all('user_id' not in tool['parameters'].get('properties', {}) for tool in requests[0][1]['tools'])
        assert 'function_call_output' in json.dumps(requests[1][1]['input'])
        with database.session() as s:
            s.get(User, 1).ai_execution_mode = 'local_worker'
        result = runtime.start(actor_id=1, thread_id='no-worker-fallback', request='메일 검색')
        assert result['error'] == 'LOCAL_WORKER_KEY_FORBIDDEN' and len(requests) == 2
