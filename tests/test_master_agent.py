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


def app_for(url, jwks, google, choices, settings=None, storage=None, knowledge_adapters=None, calendar=None):
    return create_app(settings or settings_of(url), google=google, calendar=calendar, agent_choose=choices, storage=storage,
        knowledge_adapters=knowledge_adapters,
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
    progress = result.json()["progress"]
    assert progress["started_at"] >= state["progress"]["finished_at"] and progress["steps"] == []
    state = read(client, token, key)
    assert state["progress"]["started_at"] == progress["started_at"]
    assert state["progress"]["finished_at"] >= progress["started_at"]
    return state


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
        accepted = response.json()
        key = accepted['id']
        state = read(client, token, key)
        assert state['status'] == 'needs_input' and state['waiting']['task_id'] == 'agent', state
        assert accepted['progress']['steps'] == []
        progress = state['progress']
        assert progress['started_at'] == accepted['progress']['started_at']
        assert progress['finished_at'] >= progress['started_at']
        assert {'label': '메일 검색', 'status': 'completed'} in progress['steps']
        assert all(set(step) == {'label', 'status'} for step in progress['steps'])
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
        assert {'label': '답장 발송 준비', 'status': 'completed'} in state['progress']['steps']
        assert not google.mailbox.called('send')
        waiting, revision = state['waiting'], state['revision']
        decision = {"action_id": waiting['action']['id'], "content_hash": waiting['content_hash'], "decision": "approve"}
        state = resume(client, token, key, state, decision)
        assert state['status'] == 'completed', state
        assert {'label': '답장 발송', 'status': 'completed'} in state['progress']['steps']
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
        assert state['progress']['finished_at'] >= state['progress']['started_at']
        assert state['progress']['steps'][-1] == {'label': '다음 작업 판단', 'status': 'failed'}
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
    incomplete = pi_input(document_number=None, payment_terms=None).model_dump(mode='json')
    incomplete['items'][0]['discount_percent'] = None
    choices = Choices([('document_schema', {'kind': 'PI'}),
        ('prepare_document', {'kind': 'PI', 'values': incomplete}),
        ('prepare_issue', {'kind': 'PI', 'document_id': 2, 'revision': 4}), '문서를 발급했습니다.'])
    with TestClient(app_for(database_url, jwks, google, choices, storage=storage)) as client:
        company(client, token)
        duplicate = client.post('/api/trade/pi', headers=auth(token),
                                json=pi_input(document_number='PI-TAKEN').model_dump(mode='json'))
        assert duplicate.status_code < 300, duplicate.text
        response = client.post('/api/agent/conversations', headers=auth(token), json={'message': 'PI를 작성해 줘'})
        key = response.json()['id']
        state = read(client, token, key)

        def complete(state, changes):
            return resume(client, token, key, state, {'task_id': state['waiting']['task_id'],
                          'answers': {'pi_changes': changes}})

        assert state['waiting']['fields'] == ['pi_changes']
        card = state['working']['data']['pi_completion']
        assert card['document_id'] == 2 and card['revision'] == 1
        assert set(card['fields']) == {'payment_terms', 'items.0.discount_percent'}
        state = complete(state, {'buyer.legal_name': 'Unexpected Change'})
        card = state['working']['data']['pi_completion']
        assert card['error'] == 'PI_COMPLETION_INVALID' and card['revision'] == 1
        state = complete(state, {'items.0.discount_percent': '101'})
        assert state['working']['data']['pi_completion']['error'] == 'PI_COMPLETION_INVALID'
        saved = client.get('/api/trade/pi/2', headers=auth(token)).json()
        externally_revised = client.put('/api/trade/pi/2', headers=auth(token),
            json={'revision': 1, 'document': {**saved['input'], 'remarks': 'External edit'}})
        assert externally_revised.status_code == 200, externally_revised.text
        state = complete(state, {'payment_terms': 'Stale T/T'})
        card = state['working']['data']['pi_completion']
        assert card['error'] == 'document_changed' and card['revision'] == 2
        assert state['working']['data']['input']['document_number'] is None
        state = complete(state, {'payment_terms': 'T/T'})
        card = state['working']['data']['pi_completion']
        assert card['revision'] == 3
        assert set(card['fields']) == {'items.0.discount_percent'}
        state = complete(state, {'items.0.discount_percent': '0'})
        assert state['status'] == 'needs_approval', state
        assert state['waiting']['action']['payload']['revision'] == 4
        saved = client.get('/api/trade/pi/2', headers=auth(token)).json()
        assert saved['input']['document_number'] is None
        assert saved['input']['remarks'] == 'External edit'
        assert saved['input']['items'][0]['discount_percent'] == '0'
        with client.app.state.database.session() as s:
            assert s.scalar(select(func.count()).select_from(TradeDocument)) == 2
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


def test_issued_search_finds_the_original_files_for_the_authenticated_owner(database_url):
    from datetime import datetime, timezone

    from app.db.models import TradeArtifact, TradeProposal
    from app.trade.review.repository import SQLReviews
    from tests.fakes.storage import FakeStorage
    from tests.test_pi_domain import pi_input

    jwks = FakeJwks()
    token, other_token = jwks.token(), jwks.token(sub=uuid4())
    filters = {"kind": "PI", "counterparty": "acme", "issued_from": "2026-10-01", "issued_to": "2026-10-31"}
    choices = Choices([("search_trade_documents", filters), "지난달 발급본입니다."])
    with TestClient(app_for(database_url, jwks, FakeGmailGoogle(), choices, storage=FakeStorage())) as client:
        database = client.app.state.database
        account = client.get("/api/me", headers=auth(token)).json()["user_id"]
        for member_token in (token, other_token):
            company(client, member_token)

        def create_pi(headers, number):
            response = client.post("/api/trade/pi", headers=headers, json=pi_input(document_number=number).model_dump(mode="json"))
            assert response.status_code == 201, response.text
            return response.json()["document_id"]

        def issue_pi(headers, document_id, date):
            url = f"/api/trade/pi/{document_id}/reviews"
            response = client.post(url, headers=headers, json={"revision": 1, "formats": ["pdf"]})
            assert response.status_code == 201, response.text
            proposal = response.json()
            response = client.post(f"{url}/{proposal['id']}/decisions", headers=headers, json={
                "action": "approve", "revision": 1, "content_hash": proposal["content_hash"]})
            assert response.status_code == 200, response.text
            with database.session() as session:
                session.get(TradeProposal, proposal["id"]).decided_at = datetime.fromisoformat(date)
            return response.json()

        headers = auth(token)
        first = create_pi(headers, "PI-ORIGINAL")
        original = issue_pi(headers, first, "2026-09-30T15:00:00+00:00")
        last = issue_pi(headers, create_pi(headers, "PI-LATEST"), "2026-10-31T14:59:59+00:00")
        issue_pi(headers, create_pi(headers, "PI-NOV"), "2026-10-31T15:00:00+00:00")
        issue_pi(auth(other_token), create_pi(auth(other_token), "PI-OTHER"), "2026-10-28T00:00:00+00:00")
        create_pi(headers, "PI-UNISSUED")
        change = pi_input(document_number="PI-EDITED").model_dump(mode="json")
        response = client.put(f"/api/trade/pi/{first}", headers=headers, json={"revision": 1, "document": change})
        assert response.status_code == 200 and response.json()["revision"] == 2, response.text

        repo = SQLReviews(database, account, "PI")
        assert len(repo.search_issued(document_number=None, counterparty="acme",
                                      issued_from=None, issued_to=None)["issued_documents"]) == 3

        response = client.post("/api/agent/conversations", headers=headers, json={"message": "지난달 Acme에 발급한 PI를 찾아줘"})
        assert response.status_code == 202, response.text
        state = read(client, token, response.json()["id"])
        assert state["status"] == "completed"
        matches = state["results"][0]["data"]["issued_documents"]
        assert [(hit["document_number"], hit["revision"], hit["issued_on"]) for hit in matches] == [
            (last["issued_document_number"], 1, "2026-10-31"),
            (original["issued_document_number"], 1, "2026-10-01")]
        assert [hit["files"] for hit in matches] == [last["files"], original["files"]]
        assert client.get(matches[1]["files"][0]["download_url"], headers=headers).content.startswith(b"%PDF")
        assert client.get(matches[1]["files"][0]["download_url"], headers=auth(other_token)).status_code == 404
        assert any(original["issued_document_number"] in message.content for message in choices.observed if message.type == "tool")
        assert {"label": "발급 문서 검색", "status": "completed"} in state["progress"]["steps"]

        repo = SQLReviews(database, account, None)
        assert repo.search_issued(document_number="%", counterparty=None, issued_from=None,
                                  issued_to=None) == {"issued_documents": []}
        # 실제 승인 흐름과 별개로 검색 상한을 검사할 승인 기록을 준비한다.
        with database.session() as session:
            snapshot = session.get(TradeProposal, original["id"])
            for day in range(2, 13):
                proposal_id = uuid4().hex
                session.add(TradeProposal(id=proposal_id, user_id=account, document_id=first, revision=1,
                    payload=snapshot.payload, content_hash=snapshot.content_hash, status="approved", decision="approve",
                    decided_at=datetime(2026, 10, day, tzinfo=timezone.utc)))
                session.flush()
                file = original["files"][0]
                session.add(TradeArtifact(id=uuid4().hex, user_id=account, proposal_id=proposal_id,
                    filename=file["filename"], file_format="pdf", media_type=file["media_type"], content_hash=file["content_hash"]))
        limited = repo.search_issued(document_number=original["issued_document_number"], counterparty=None, issued_from=None, issued_to=None)
        assert [match["issued_on"] for match in limited["issued_documents"]] == [
            f"2026-10-{day:02}" for day in range(12, 2, -1)]


def test_knowledge_chat_opens_uploads_and_answers_from_the_published_owner_profile(database_url):
    from app.knowledge.chunking import build_chunks
    from app.knowledge.operations import upload
    from app.knowledge.repository import KnowledgeChild, KnowledgeParent, SqlRepository
    from app.knowledge.schemas import EmbeddingBatch, PageText
    from tests.fakes.storage import FakeStorage
    from tests.test_knowledge import FakeEmbedder, FakeExtractor, FakeRenderer, pdf, run

    class QueryEmbedder(FakeEmbedder):
        def embed_documents(self, texts):
            batch = super().embed_documents(texts)
            if texts == ["근거 없는 질문"]:
                return EmbeddingBatch(profile=self.profile, vectors=[[-1.0, 0.0, 0.0]])
            return batch

    jwks, storage, embedder = FakeJwks(), FakeStorage(), QueryEmbedder()
    token, outsider = jwks.token(), jwks.token(sub=uuid4())
    choices = Choices([])
    adapters = lambda *_: (FakeRenderer(), FakeExtractor(), embedder)
    with TestClient(app_for(database_url, jwks, FakeGmailGoogle(), choices, knowledge_adapters=adapters)) as client:
        database = client.app.state.database
        repository = SqlRepository(database)
        owner = client.get("/api/me", headers=auth(token)).json()["user_id"]
        other_owner = client.get("/api/me", headers=auth(outsider)).json()["user_id"]

        def publish(owner_id, filename, pages, text, indexing_embedder=None):
            document = upload(repository, storage, owner_id, filename, pdf(pages))
            assert run(repository, storage, FakeExtractor(content=text), indexing_embedder) == "ready"
            return document

        original_text = "제1조 대금\n검수 후 지급한다. 단, 반품 건은 정산에서 제외한다."
        contract = publish(owner, "테이블오더.pdf", 1, original_text)
        publish(other_owner, "테이블오더.pdf", 2, "다른 회사의 비공개 문구")
        publish(owner, "이전 모델 계약.pdf", 3, "이전 모델의 근거", FakeEmbedder(dimensions=2))

        def ask(text, **inputs):
            choices.calls.extend([("search_knowledge_documents", inputs), "문서함 검색을 확인했습니다."])
            response = client.post("/api/agent/conversations", headers=auth(token), json={"message": text})
            assert response.status_code == 202, response.text
            return read(client, token, response.json()["id"])["results"][0]

        found = ask("문서함에 있는 테이블오더 문서 볼 수 있어?", filename="테이블오더")["data"]
        assert found["knowledge_status"] == "found" and not embedder.calls
        assert [document["url"] for document in found["knowledge_documents"]] == [
            f"/documents?document={contract['id']}"]

        retry = repository.retry(owner, contract["id"], contract["attempt_id"])
        parents, children = build_chunks([PageText(number=1, text="게시 전의 후보 문구")])
        scope = {"document_id": contract["id"], "user_id": owner, "attempt_id": retry["attempt_id"]}
        with database.session() as session:
            session.add(KnowledgeParent(**scope, **parents[0].model_dump()))
            session.flush()
            session.add(KnowledgeChild(**scope, **children[0].model_dump(), embedding=[0.25] * 3,
                profile_id=embedder.profile.fingerprint, dimensions=embedder.profile.dimensions))

        result = ask("결제 조건과 예외를 인용해 줘", query="결제 조건과 예외")["data"]
        assert [source["text"] for source in result["knowledge_clauses"]] == [original_text]
        assert result["knowledge_clauses"][0]["sources"][0]["source"] == "원본 페이지 1"
        assert any(original_text.split("\n")[1] in message.content for message in choices.observed if message.type == "tool")
        assert ask("없는 파일 열어줘", filename="없는 파일")["data"]["knowledge_status"] == "not_found"
        assert ask("초안의 결제 조건", query="근거 없는 질문")["data"]["knowledge_status"] == "no_evidence"

        upload(repository, storage, owner, "테이블오더_수정.pdf", pdf(4))
        calls = len(embedder.calls)
        ambiguous = ask("테이블오더 결제 조건은?", filename="테이블오더", query="결제 조건")["data"]
        assert ambiguous["knowledge_status"] == "choose_document"
        assert len(ambiguous["knowledge_documents"]) == 2 and len(embedder.calls) == calls
        assert ask("수정 문서의 내용", filename="테이블오더_수정", query="결제 조건")["data"]["knowledge_status"] == "not_indexed"
        embedder.fail_after = calls
        failure = ask("계약서 오류 확인", document_id=contract["id"], query="결제 조건")
        assert failure["status"] == "failed" and failure["code"] == "provider_unavailable"


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


def test_mail_search_filters_body_date_and_sent_reply_before_paging(database):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from app.db.models import Counterparty, ProcessedMessage, ReplyCandidate, ThreadMessage, User
    from app.graph.mail.adapters import ExistingMail
    from app.graph.mail.schemas import SearchInput
    from app.graph.master.tools import AGENT_TOOLS

    start = datetime(2026, 11, 19, tzinfo=ZoneInfo("Asia/Seoul"))
    end = start + timedelta(days=1)
    sender = "alpha@fiction.example.invalid"
    keyword = "코발트독수리%_"

    with database.session() as session:
        outsider = User(email="second@example.invalid", google_sub="second")
        session.add(outsider)
        session.flush()
        session.add(Counterparty(user_id=1, company_key="fiction-alpha", legal_name="Fiction Alpha",
                                 aliases=["알파"], email=sender))

        def receive(key, thread_id, at, *, subject="발주 요청", body=keyword, owner=1):
            session.add(ThreadMessage(user_id=owner, thread_id=thread_id, gmail_message_id=key, direction="in",
                from_addr=sender, subject=subject, body_text=body, to_addrs=[], sent_at=at))
            session.add(ProcessedMessage(user_id=owner, thread_id=thread_id, gmail_message_id=key,
                                          received_at=at, status="awaiting_approval"))

        def send(key, thread_id, at, owner=1):
            session.add(ThreadMessage(user_id=owner, thread_id=thread_id, gmail_message_id=key, direction="out",
                from_addr="tester@example.invalid", subject="Re: 발주 요청", body_text="확인했습니다.",
                to_addrs=[sender], sent_at=at))

        receive("early", "early", start - timedelta(seconds=1))
        receive("replied", "replied", start + timedelta(minutes=15))
        send("sent-reply", "replied", start + timedelta(minutes=30))
        receive("first", "followup", start)
        send("sent-first", "followup", start + timedelta(hours=1))
        receive("other", "other", start + timedelta(hours=2), owner=outsider.id)
        receive("subject-only", "subject-only", start + timedelta(hours=3), subject=keyword, body="본문에 없음")
        receive("literal", "literal", start, body="코발트독수리AB")
        receive("older-only", "older", start)
        receive("older-new", "older", end, body="다음 날 메일")
        receive("boundary", "boundary", end)
        receive("followup", "followup", start + timedelta(hours=4), body="가상 본문 " * 50 + keyword)
        send("other-sent", "followup", start + timedelta(hours=5), owner=outsider.id)
        session.add(ReplyCandidate(user_id=1, thread_id="followup", run_id="fixture-run", source_message_id="followup",
                                   label="초안", kind="general", subject="Re: 발주", body="아직 보내지 않은 초안"))

    options = dict(query=keyword, field="body", received_from=start, received_before=end, reply_status="unanswered")
    task = AGENT_TOOLS["search_mail"].invoke(options)
    assert task["inputs"]["received_before"] == end.isoformat()
    mail = ExistingMail(database=database)
    result = mail.search(1, SearchInput.model_validate(task["inputs"]))
    assert [row["thread_id"] for row in result["threads"]] == ["followup", "older"]
    assert keyword in result["threads"][0]["preview"] and result["threads"][0]["preview"].startswith("…")
    assert all(row["reply_status"] == "unanswered" for row in result["threads"])
    assert result["search_scope"]["field"] == "body"
    replied = mail.search(1, SearchInput(**{**options, "reply_status": "replied"}))
    assert [row["thread_id"] for row in replied["threads"]] == ["followup", "replied"]
    assert all(row["reply_status"] == "replied" for row in replied["threads"])
    for field in ("sender", "all"):
        alias = mail.search(1, SearchInput(query="알파", field=field, received_from=start, received_before=end))
        assert {row["thread_id"] for row in alias["threads"]} == {"followup", "older", "literal", "subject-only", "replied"}

    from app.db.mailbox import MailStore

    store = MailStore(database)
    page_one = store.search_threads(1, **options, cursor=None, limit=1)
    page_two = store.search_threads(1, **options, cursor=page_one["next_cursor"], limit=1)
    assert [row["thread_id"] for row in page_one["items"] + page_two["items"]] == ["followup", "older"]
    assert page_two["next_cursor"] is None
    with pytest.raises(ValueError, match="invalid_mail_search_window"):
        SearchInput(received_from=end, received_before=start)


def test_registered_trade_directory_resolves_code_currency_and_party_scope(database):
    from app.db.models import Counterparty, PriceListItem, User
    from app.graph.documents.adapters import ExistingDocuments
    from app.graph.documents.schemas import CounterpartySearch, TradePriceSearch
    from app.graph.master.tools import AGENT_TOOLS

    with database.session() as session:
        other = User(email="other-dir@example.invalid", google_sub="other-dir")
        session.add(other)
        session.flush()
        session.add_all([
            Counterparty(user_id=1, company_key="fictionalpha", legal_name="Fiction Alpha",
                         aliases=["알파", "공동 별칭"], email="alpha@example.invalid", phone="010-0000-0001"),
            Counterparty(user_id=1, company_key="fictionbeta", legal_name="Fiction Beta",
                         aliases=["공동 별칭"], email="beta@example.invalid"),
            Counterparty(user_id=other.id, company_key="secret", legal_name="Private Other",
                         aliases=["알파"], email="private@example.invalid"),
        ])

        def price(amount, *, party="", currency="USD", role="sale", code="SC-110",
                  name="V-Cera Serum", owner=1):
            session.add(PriceListItem(user_id=owner, item_name=name, product_code=code, party_key=party,
                role=role, currency=currency, unit_price_text=amount, unit="each", price_basis="FOB"))

        price("15.50")
        price("12.50", party="fictionalpha")
        price("11.00", party="fictionbeta")
        price("1300", currency="KRW")
        price("8.01", role="purchase")
        price("27.00", currency="EUR", code="SC-111", name="SC110 misleading listing")
        price("0.01", owner=other.id)

    documents = ExistingDocuments(database=database)
    task = AGENT_TOOLS["search_trade_prices"].invoke({
        "product": "sc110", "currency": "usd", "role": "sale", "counterparty": "알파",
    })
    result = documents.search_trade_prices(1, TradePriceSearch.model_validate(task["inputs"]))
    row, = result["prices"]
    assert row["unit_price"] == "12.50" and row["currency"] == "USD"
    assert row["scope"] == "counterparty" and row["counterparty"] == "Fiction Alpha"
    assert row["unit"] == "each" and row["price_basis"] == "FOB"

    def lookup(**overrides):
        return documents.search_trade_prices(1, TradePriceSearch(
            **{**task["inputs"], **overrides}))

    assert lookup(currency="KRW")["prices"][0]["scope"] == "common"
    assert lookup(role="purchase")["prices"][0]["unit_price"] == "8.01"
    assert lookup(currency="EUR")["price_status"] == "not_found"
    conflict = lookup(counterparty="공동 별칭")
    assert conflict["price_status"] == "choose_counterparty" and conflict["prices"] == []
    assert {card["legal_name"] for card in conflict["counterparties"]} == {"Fiction Alpha", "Fiction Beta"}
    assert documents.search_counterparties(1, CounterpartySearch(query="알파"))["counterparties"][0]["email"] == "alpha@example.invalid"
    assert documents.search_counterparties(1, CounterpartySearch(query="private@example.invalid"))["total"] == 0
