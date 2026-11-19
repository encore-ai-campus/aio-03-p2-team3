"""실제 수신 마스터, PostgreSQL 검색과 모의 캘린더를 통과하는 초안 검증."""
from datetime import UTC, datetime, timedelta
from functools import partial
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from app.db.mailbox import MailStore
from app.db.models import CalendarToken, Counterparty, ProcessedMessage, User, utcnow
from app.graph.build import build_graph
from app.graph.mail.retrieval_adapter import analyze_with_knowledge
from app.graph.run import start_run
from app.graph.schemas import WorkflowError
from app.knowledge.operations import search, upload
from app.knowledge.query_rewrite import QueryPlan
from app.knowledge.repository import SqlRepository
from app.knowledge.schemas import EmbeddingBatch, KnowledgeError
from app.llm.client import use_backend
from app.main import create_app
from tests.fakes.gmail import FakeGmailGoogle, message
from tests.fakes.llm import FakeLLM
from tests.fakes.storage import FakeStorage
from tests.test_gmail_push import push_payload, setup_user, settings  # noqa: F401
from tests.test_knowledge import FakeEmbedder, FakeExtractor, pdf, run
from tests.test_mail_analysis import drafts

KST = ZoneInfo("Asia/Seoul")


class QueryEmbedder(FakeEmbedder):
    def embed_documents(self, texts):
        self.calls.append(texts)
        return EmbeddingBatch(profile=self.profile, vectors=[[0.25, -0.25, 0] for _ in texts])


@pytest.fixture
def contracts(database):
    repository, storage = SqlRepository(database), FakeStorage()
    with database.session() as session:
        other = User(google_sub="fake-other", email="other@example.invalid")
        session.add(other)
        session.flush()
        parties = [
            Counterparty(user_id=1, company_key="alpha", legal_name="Fiction Alpha", email=" Sender@Example.Invalid "),
            Counterparty(user_id=1, company_key="beta", legal_name="Fiction Beta", email="beta@example.invalid"),
            Counterparty(user_id=other.id, company_key="other", legal_name="Fiction Other", email="sender@example.invalid"),
            Counterparty(user_id=1, company_key="empty", legal_name="Fiction Empty", email="empty@example.invalid"),
        ]
        session.add_all(parties)
        session.flush()
        pairs = [(party.user_id, party.id) for party in parties[:3]]
    documents = []
    for index, ((owner, party), content) in enumerate(zip(pairs, (
        "Payment due after inspection.", "Payment due before shipment.", "Payment due immediately.",
    ), strict=True), 1):
        doc = upload(repository, storage, owner, f"contract-{index}.pdf", pdf(index))
        assert run(repository, storage, extractor=FakeExtractor(content=content)) == "ready"
        repository.assign_counterparty(owner, doc["id"], party)
        documents.append(doc["id"])
    with pytest.raises(KnowledgeError, match="등록한 거래처"):
        repository.assign_counterparty(1, documents[0], pairs[2][1])
    return repository, documents


@pytest.mark.parametrize(("sender", "scope", "indexes"), [
    ("Sender <sender@example.invalid>", "counterparty", [0]),
    ("new@example.invalid", "personal", [0, 1]),
    ("empty@example.invalid", "counterparty", []),
])
def test_contract_mail_search_scope_drafting_and_persisted_sources(database, email, contracts, sender, scope, indexes):
    repository, documents = contracts
    email = {**email, "from_addr": sender, "body_text": "서명한 계약서상 물건 보구 나서 내면 돼요? 주문 100개 건입니다."}
    with database.session() as session:
        session.add(ProcessedMessage(user_id=1, gmail_message_id=email["gmail_message_id"], thread_id=email["thread_id"]))
    analysis = {"intent": "deal", "reason": "기존 계약 지급 조건", "contract_question": True}
    fake = FakeLLM([analysis, drafts(2)])
    embedder = QueryEmbedder()
    seen = []

    def rank(owner, query, clauses):
        assert owner == 1 and "보구 나서" in query
        seen.extend(clause["document_id"] for clause in clauses)
        return [clause["clause_id"] for clause in clauses]

    graph = build_graph(node_overrides={"analyze_email": partial(
        analyze_with_knowledge, repository=repository, get_embedder=lambda _: embedder,
        plan_query=lambda *_: QueryPlan(korean="검수 후 대금 지급", english="payment inspection"), rerank=rank,
    )})
    with use_backend(fake):
        result = start_run(user_id=1, email=email, database=database, graph=graph, reflection_enabled=True)
    assert result["end_reason"] == "awaiting_approval" and result["intent"] == "general"
    assert set(seen) == {documents[i] for i in indexes}
    assert embedder.calls == ([["검수 후 대금 지급", "payment inspection"]] if indexes else [])
    if indexes == [0]:
        assert "Payment due after inspection." in fake.calls[1]
        assert "before shipment" not in fake.calls[1]
    else:
        assert len(fake.calls) == 1
        assert all("계약" in candidate["body"] and "Payment" not in candidate["body"] for candidate in result["candidates"])
    [saved] = MailStore(database).thread(1, email["thread_id"])["processing"]
    evidence = saved["inbound_context"]["knowledge"]
    assert evidence["scope"] == scope
    assert {item["document_id"] for item in evidence["clauses"]} == {documents[i] for i in indexes}
    assert all("text" not in item and item["sources"] for item in evidence["clauses"])


def test_shared_search_keeps_english_candidate_and_explicit_document(contracts):
    repository, documents = contracts
    embedder = QueryEmbedder()
    result = search(repository, 1, filename=None, document_id=documents[0],
        query="물건 보구 나서 내면 돼?", get_embedder=lambda: embedder,
        plan_query=lambda _: QueryPlan(korean="물건 확인 후 지급", english="inspection"))
    assert embedder.calls == [["물건 확인 후 지급", "inspection"]]
    [selected] = result["knowledge_clauses"]
    assert selected["document_id"] == documents[0]
    assert selected["sources"][0]["source"] == "원본 페이지 1"


@pytest.mark.parametrize(("mode", "expected"), [
    ("busy", "busy"), ("free", "available"), ("no_length", "duration_required"),
    ("unspecified", "unspecified"), ("disconnected", "unavailable"),
    ("quoted", "unspecified"), ("outside", "outside_window"),
])
def test_inbound_schedule_free_busy_before_draft(database, email, mode, expected):
    start = (utcnow().astimezone(KST) + timedelta(days=3)).replace(hour=15, minute=30, second=0, microsecond=0)
    received = start - timedelta(days=2)
    if mode == "outside":
        received += timedelta(days=35)
    text = "내일모레 오후 3시 30분"
    body = f"{text}에 30분간 미팅 가능한가요?"
    meeting = {
        "selected_start": start.replace(minute=0).isoformat(), "timezone": KST.key, "duration_minutes": 30,
        "evidence": text, "duration_evidence": "30분간",
    }
    if mode == "no_length":
        body = f"{text}에 미팅 가능한가요?"
        meeting["duration_evidence"] = "30분"
    if mode in ("unspecified", "quoted"):
        body = "미팅할 수 있는 시간이 있나요?" + (f"\n> {text}에 미팅" if mode == "quoted" else "")
        if mode == "unspecified":
            meeting = None
    email = {**email, "body_text": body, "received_at": received.astimezone(UTC).isoformat()}
    calls = []

    class Calendar:
        def read_busy(self, owner, query):
            assert owner == 1 and query.calendar_ids == ["primary"]
            assert query.end - query.start == timedelta(days=30)
            calls.append(query)
            if mode == "disconnected":
                raise WorkflowError("calendar_not_connected")
            return {"calendars": {"primary": [{"start": start, "end": start + timedelta(minutes=40)}]
                                  if mode == "busy" else []},
                    "observed_at": utcnow(), "version": "fake"}

    fake = FakeLLM([{"intent": "general", "reason": "미팅 조율", "calendar_related": True,
                    "schedule_only": True, "meeting": meeting}])
    graph = build_graph(node_overrides={"analyze_email": partial(
        analyze_with_knowledge, repository=SqlRepository(database),
        get_embedder=lambda _: pytest.fail("빈 문서함을 임베딩함"), calendar=Calendar(),
    )})
    with use_backend(fake):
        result = start_run(user_id=1, email=email, database=database, graph=graph, reflection_enabled=True)
    assert result["end_reason"] == "awaiting_approval", result
    assert len(calls) == 1
    availability = result["calendar_availability"]
    assert availability["status"] == expected
    if mode in ("busy", "free", "no_length"):
        assert datetime.fromisoformat(availability["start"]) == start
        assert all("15:30" in candidate["body"] for candidate in result["candidates"])
    if mode == "busy":
        assert len(availability["alternatives"]) == 2
        assert all("일정이 겹칩니다" in candidate["body"] for candidate in result["candidates"])
    if mode == "quoted":
        assert text not in fake.calls[0]


def test_gmail_push_composition_uses_calendar_before_storing_draft(settings):
    class Google:
        def free_busy(self, access_token, ids, start, end):
            assert access_token == "calendar-access" and ids == ["primary"]
            calls.append((start, end))
            return {"primary": {"busy": []}}

    calls = []
    gmail = FakeGmailGoogle()
    raw = message(body="미팅 날짜가 아직 미정입니다. 가능 시간 확인 부탁드립니다.")
    gmail.mailbox.raw_messages["fake-message"] = raw
    fake = FakeLLM([{"intent": "general", "reason": "미팅 조율", "calendar_related": True, "schedule_only": True}])
    with TestClient(create_app(settings, google=gmail, calendar=Google())) as client:
        owner = setup_user(client.app.state.google_access)
        db = client.app.state.database
        access = client.app.state.calendar_access
        with db.session() as session:
            session.add(CalendarToken(user_id=owner, google_sub="calendar-fixture",
                scopes=["openid", "email", "https://www.googleapis.com/auth/calendar.readonly"],
                access_token_enc=access.cipher.encrypt("calendar-access"),
                refresh_token_enc=access.cipher.encrypt("calendar-refresh"), expires_at=utcnow() + timedelta(hours=1)))
        with use_backend(fake):
            response = client.post("/gmail/push?token=fake-push-token", json=push_payload())
        assert response.status_code == 204
        state = MailStore(db).thread(owner, "fake-thread")
        assert state["processing"][0]["inbound_context"]["calendar"]["status"] == "unspecified"
        assert len(calls) == 1 and calls[0][1] - calls[0][0] == timedelta(days=30)
        assert all("시작 시각" in candidate["body"] for candidate in state["candidates"])
        assert len(state["candidates"]) == 2 and not gmail.mailbox.called("send")
