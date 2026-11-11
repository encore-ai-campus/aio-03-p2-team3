"""13절 완료 기준·오류 경로. 실제 Gmail·Gemini 없이 기억이 모델 입력에 이어지는지 검사한다."""

from datetime import UTC, datetime, timedelta
import json

from google.genai.errors import ClientError
import pytest
from sqlalchemy import func, select

from app.db.models import (
    Approval, CompanyProfile, CounterpartyHistory, DealTerms, PriceListItem,
    ReplyCandidate, RunEvent, ThreadMemory, ThreadMessage, User, UserPreference,
)
from app.graph.build import build_graph
from app.graph.run import start_run
from app.llm import client
from app.prompts.format import thread_context_text
from app.services.memory import context_for_model, load_memories, save_sent_memory
from tests.fakes.llm import FakeLLM

BASE_TIME = datetime(2026, 11, 9, tzinfo=UTC)
GENERAL = {"intent": "general", "reason": "가상 일반 문의"}
DEAL = {"intent": "deal", "reason": "앞 견적 문의의 후속 답변"}
DRAFTS = {"candidates": [{"label": "간단한 안내", "body": "가상 안내입니다."},
                          {"label": "자세한 안내", "body": "가상 자세한 안내입니다."}]}
TERMS = {"customer_name": "가상상사", "items": [{"item_name": "가상용지", "quantity": 20,
          "unit": "박스", "unit_price": None}], "due_date": None, "contact_name": None,
         "contact_phone": None, "delivery_place": None, "note": None, "evidence": {}}
SUMMARY = {"deal_conditions": ["가상용지 20박스"], "confirmed_fields": ["거래처: 가상상사"],
           "unanswered_questions": ["납기는 언제인가요?"]}


@pytest.fixture(autouse=True)
def no_real_api(monkeypatch):
    monkeypatch.setattr(client, "get_backend", lambda: pytest.fail("실제 LLM 호출 금지"))
    monkeypatch.setattr(client, "sleep", lambda _: None)


def run(database, email, responses, overrides=None):
    fake = FakeLLM(responses)
    with client.use_backend(fake):
        result = start_run(user_id=1, email=email, mode="test", database=database,
                           reflection_enabled=False, graph=build_graph(node_overrides=overrides))
    return result, fake


def seed_messages(database, email, count, body="가상 과거 메일", *, user_id=1, start=0):
    with database.session() as session:
        for i in range(start, start + count):
            session.add(ThreadMessage(
                user_id=user_id, thread_id=email["thread_id"], gmail_message_id=f"old-{i}", direction="in",
                from_addr=email["from_addr"], to_addrs=email["to_addrs"], subject=email["subject"],
                body_text=f"{body} {i}", sent_at=BASE_TIME + timedelta(minutes=i),
            ))


def later_email(email, **changes):
    return {**email, "gmail_message_id": "later", "received_at": "2026-11-10T00:00:00+00:00", **changes}


def test_same_thread_reuses_terms_questions_and_last_result(database, email):
    first = {**email, "body_text": "가상상사 가상용지 20박스 견적 부탁드립니다."}
    first_result, _ = run(database, first, [DEAL, {**TERMS, "evidence": []}, DRAFTS])
    assert first_result["end_reason"] == "followup_question"
    with database.session() as session:
        memory = session.get(ThreadMemory, (1, email["thread_id"]))
        assert memory.confirmed_terms["items"][0]["quantity"] == 20
        assert memory.last_result["missing_fields"] == ["due_date"]
        assert session.scalar(select(func.count()).select_from(UserPreference)) == 0
        assert session.scalar(select(func.count()).select_from(CounterpartyHistory)) == 0
    second = later_email(email, body_text="납기는 2026-11-20입니다. 수량은 30박스로 바꿔 주세요.")
    current_terms = {**TERMS, "items": [{**TERMS["items"][0], "quantity": 30}],
                     "due_date": "2026-11-20", "evidence": []}
    result, fake = run(database, second, [DEAL, current_terms, DRAFTS])
    assert result["end_reason"] == "awaiting_approval" and result["missing_fields"] == []
    assert result["deal_terms"]["customer_name"] == "가상상사"
    assert result["deal_terms"]["items"][0]["quantity"] == 30
    assert result["deal_terms"]["due_date"] == "2026-11-20"
    for prompt in fake.calls[:2]:
        assert "가상상사" in prompt and '"quantity": 20' in prompt
        assert "직전 결과·답 안 된 항목" in prompt and "due_date" in prompt
        assert "현재 메일의 명시 조건을 최우선" in prompt
        assert second["body_text"] in prompt
    assert result["thread_context"]["recent_messages"][0]["gmail_message_id"] == first["gmail_message_id"]
    with database.session() as session:
        assert session.get(ThreadMemory, (1, email["thread_id"])).confirmed_terms["items"][0]["quantity"] == 30


def sent_candidate(database, email, *, status="sent", approval_status="sent"):
    seed_messages(database, email, 1)
    with database.session() as session:
        candidate = ReplyCandidate(
            user_id=1, run_id="approved-run", thread_id=email["thread_id"], source_message_id="old-0",
            kind="followup", label="정중한 목록 안내", subject="Re: 가상 문의",
            body="가상 납기를 알려 주세요.", asks_fields=["due_date"], status=status,
        )
        session.add(candidate)
        session.flush()
        session.add(Approval(user_id=1, candidate_id=candidate.id, send_status=approval_status,
                             sent_message_id="gmail-sent" if approval_status == "sent" else None))
        session.add(DealTerms(user_id=1, run_id=candidate.run_id, thread_id=candidate.thread_id,
                              source_message_id=candidate.source_message_id, terms=TERMS,
                              missing_fields=["due_date"], required_source="config"))
    return candidate.id


def test_successful_approved_send_is_saved_once_and_used_in_another_thread(database, email):
    candidate_id = sent_candidate(database, email)
    for _ in range(2):
        with database.session() as session:
            assert save_sent_memory(session, user_id=1, candidate_id=candidate_id,
                                    sent_at=BASE_TIME + timedelta(hours=1))
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ThreadMessage)) == 2
        assert session.scalar(select(func.count()).select_from(CounterpartyHistory)) == 1
        outgoing = session.scalar(select(ThreadMessage).where(ThreadMessage.direction == "out"))
        assert outgoing.gmail_message_id == "gmail-sent" and outgoing.to_addrs == [email["from_addr"]]
        assert session.get(UserPreference, (1, "approved_reply_style")).value["label"] == "정중한 목록 안내"
    other = later_email(email, thread_id="new-thread", from_addr="가상 발신자 <SENDER@example.invalid>")
    result, fake = run(database, other, [GENERAL, DRAFTS])
    assert result["thread_context"]["confirmed_terms"] == {}  # 이번 거래로 복사하지 않음
    assert result["thread_context"]["recent_messages"] == []
    assert result["long_term"]["counterparty_history"][0]["deal_terms"]["customer_name"] == "가상상사"
    for prompt in fake.calls:
        assert "상대방 과거 거래 기록·발송 시점" in prompt and "가상상사" in prompt
        assert "2026-11-09T01:00:00+00:00" in prompt and "최신 외부 조회 결과가 아님" in prompt
        assert "이번 수량·납기·합의 단가로 옮기지 않는다" in prompt
    assert "정중한 목록 안내" in fake.calls[-1]


@pytest.mark.parametrize("candidate_status,approval_status", [
    ("pending", "sending"), ("approved", "sending"), ("send_failed", "failed"), ("sent", "failed"),
])
def test_no_long_term_learning_before_success(database, email, candidate_status, approval_status):
    candidate_id = sent_candidate(database, email, status=candidate_status, approval_status=approval_status)
    with database.session() as session:
        assert not save_sent_memory(session, user_id=1, candidate_id=candidate_id)
        assert session.scalar(select(func.count()).select_from(CounterpartyHistory)) == 0
        assert session.scalar(select(func.count()).select_from(UserPreference)) == 0
        assert session.scalar(select(func.count()).select_from(ThreadMessage)) == 1


def test_other_user_cannot_save_or_load_memories(database, email):
    candidate_id = sent_candidate(database, email)
    with database.session() as session:
        session.add(User(id=2, google_sub="fake-sub-2", email="other@example.invalid"))
        assert not save_sent_memory(session, user_id=2, candidate_id=candidate_id)
        assert save_sent_memory(session, user_id=1, candidate_id=candidate_id, sent_at=BASE_TIME)
    loaded = load_memories(database, user_id=2, email=later_email(email))
    assert loaded["thread_context"]["recent_messages"] == []
    assert loaded["thread_context"]["confirmed_terms"] == {}
    assert loaded["long_term"]["preferences"] == {} and loaded["long_term"]["counterparty_history"] == []


def test_company_prices_preferences_and_sources_are_loaded_by_owner(database, email):
    old_time = BASE_TIME - timedelta(days=60)
    with database.session() as session:
        session.add_all([
            UserPreference(user_id=1, key="tone", value="정중", updated_at=old_time),
            UserPreference(user_id=1, key="signature", value="가상 서명", updated_at=old_time),
            CompanyProfile(user_id=1, company_name="가상 공급자", updated_at=old_time),
            PriceListItem(user_id=1, item_name="가상용지", unit="박스", unit_price=1000, updated_at=old_time),
        ])
    result, fake = run(database, email, [GENERAL, DRAFTS])
    memory = result["long_term"]
    assert memory["company"]["company_name"] == "가상 공급자"
    assert memory["price_list"] == [{"item_name": "가상용지", "unit": "박스", "unit_price": 1000}]
    assert all(source["fetched_at"] == old_time.isoformat() for source in memory["sources"])
    assert "정중" in fake.calls[-1] and all(c["body"].endswith("가상 서명") for c in result["candidates"])


def test_counterparty_and_thread_are_separate_and_history_is_bounded(database, email):
    with database.session() as session:
        for i in range(7):
            session.add(CounterpartyHistory(
                user_id=1, counterparty_email=email["from_addr"], thread_id=f"prior-{i}", summary=f"과거 {i}",
                deal_terms={}, sent_at=BASE_TIME + timedelta(minutes=i),
            ))
        session.add(CounterpartyHistory(user_id=1, counterparty_email="unrelated@example.invalid",
                    thread_id="unrelated", summary="다른 상대방 비공개 거래", deal_terms={}, sent_at=BASE_TIME))
        session.add(ThreadMemory(user_id=1, thread_id="unrelated", confirmed_terms={"note": "다른 스레드 조건"}))
    loaded = load_memories(database, user_id=1, email=later_email(email))
    assert [h["thread_id"] for h in loaded["long_term"]["counterparty_history"]] == [f"prior-{i}" for i in range(6, 1, -1)]
    assert "비공개" not in json.dumps(loaded, ensure_ascii=False)
    assert loaded["thread_context"]["confirmed_terms"] == {}


def test_long_thread_summary_keeps_recent_originals_and_preserved_fields(database, email):
    seed_messages(database, email, 9)
    with database.session() as session:
        session.add(ThreadMemory(user_id=1, thread_id=email["thread_id"], confirmed_terms=TERMS,
                                 last_result={"missing_fields": ["due_date"], "end_reason": "followup_question"}))
    current = later_email(email)
    result, fake = run(database, current, [SUMMARY, GENERAL, DRAFTS])
    context = result["thread_context"]
    assert json.loads(context["summary"]) == SUMMARY
    assert [m["gmail_message_id"] for m in context["recent_messages"]] == [f"old-{i}" for i in range(5, 9)]
    assert "가상 과거 메일 0" in fake.calls[0] and "가상 과거 메일 5" not in fake.calls[0]
    assert current["body_text"] not in fake.calls[0]  # 현재 메일을 과거 요약에 섞지 않음
    assert "가상상사" in fake.calls[1] and "납기는 언제인가요?" in fake.calls[1]
    assert '"missing_fields": ["due_date"]' in fake.calls[1]
    with database.session() as session:
        memory = session.get(ThreadMemory, (1, email["thread_id"]))
        assert memory.summarized_until == BASE_TIME + timedelta(minutes=4)
        assert session.scalar(select(func.count()).select_from(ThreadMessage)) == 10
        logged = list(session.scalars(select(RunEvent).where(RunEvent.run_id == result["run_id"])))
        assert "summarize_thread.v1" in [e.detail.get("prompt_version") for e in logged]
        assert "가상 과거 메일" not in json.dumps([e.detail for e in logged], ensure_ascii=False)
    # 커서를 넘은 새 메시지만 다시 요약한다. 재조회만으로 같은 원문을 재요약하지 않는다.
    fake_again = FakeLLM([])
    with client.use_backend(fake_again):
        again = load_memories(database, user_id=1, email=current)
    assert fake_again.calls == [] and again["thread_context"]["summary"] == context["summary"]
    seed_messages(database, email, 4, start=10)
    next_summary = {**SUMMARY, "unanswered_questions": ["포장 방법은 무엇인가요?"]}
    with client.use_backend(FakeLLM([next_summary])) as next_fake:
        updated = load_memories(database, user_id=1, email=later_email(email, gmail_message_id="next"))
    assert "기존 요약" in next_fake.calls[0] and "납기는 언제인가요?" in next_fake.calls[0]
    assert "가상 과거 메일 0" not in next_fake.calls[0]
    assert json.loads(updated["thread_context"]["summary"]) == next_summary


@pytest.mark.parametrize("count,body,should_summarize", [(7, "가상", False), (8, "가상", True), (6, "가" * 2100, True)])
def test_message_or_character_threshold(database, email, count, body, should_summarize):
    seed_messages(database, email, count, body)
    with client.use_backend(FakeLLM([SUMMARY])) as fake:
        loaded = load_memories(database, user_id=1, email=later_email(email))
    assert bool(fake.calls) == should_summarize
    assert len(loaded["thread_context"]["recent_messages"]) == (4 if should_summarize else count)
    if not should_summarize:
        assert f"{body} 0" in thread_context_text(loaded["thread_context"])


@pytest.mark.parametrize("total,should_summarize", [(12000, False), (12001, True)])
def test_character_threshold_is_strict(database, email, total, should_summarize):
    seed_messages(database, email, 6, "가상")
    current = later_email(email)
    with database.session() as session:
        rows = list(session.scalars(select(ThreadMessage).order_by(ThreadMessage.id)))
        remaining = total - len(current["body_text"]) - sum(len(row.body_text) for row in rows[1:])
        rows[0].body_text = "가" * remaining
    with client.use_backend(FakeLLM([SUMMARY])) as fake:
        load_memories(database, user_id=1, email=current)
    assert bool(fake.calls) == should_summarize


def test_current_and_future_messages_not_repeated_in_context(database, email):
    seed_messages(database, email, 1)
    current = later_email(email)
    with database.session() as session:
        for message_id, at in [(current["gmail_message_id"], datetime.fromisoformat(current["received_at"])),
                               ("future", BASE_TIME + timedelta(days=2))]:
            session.add(ThreadMessage(user_id=1, thread_id=email["thread_id"], gmail_message_id=message_id,
                        direction="in", from_addr=email["from_addr"], to_addrs=[], subject="가상",
                        body_text="중복·미래 본문", sent_at=at))
    loaded = load_memories(database, user_id=1, email=current)
    assert [m["gmail_message_id"] for m in loaded["thread_context"]["recent_messages"]] == ["old-0"]


def test_equal_timestamp_messages_are_not_lost_at_summary_boundary(database, email):
    seed_messages(database, email, 9)
    with database.session() as session:
        row = session.scalar(select(ThreadMessage).where(ThreadMessage.gmail_message_id == "old-5"))
        row.sent_at = BASE_TIME + timedelta(minutes=4)
    with client.use_backend(FakeLLM([SUMMARY])):
        loaded = load_memories(database, user_id=1, email=later_email(email))
    assert {m["gmail_message_id"] for m in loaded["thread_context"]["recent_messages"]} == {f"old-{i}" for i in range(4, 9)}


@pytest.mark.parametrize("error,responses,end_reason,retries", [
    ("rate_limit", [ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})], "awaiting_approval", 0),
    ("network", [TimeoutError("가상 비밀 본문")] * 3, "failed", 2),
    ("invalid_output", [{"deal_conditions": "형식 오류"}] * 2, "failed", 1),
])
def test_summary_failure_preserves_cursor_and_stops_business_llm(database, email, error, responses, end_reason, retries):
    seed_messages(database, email, 9)
    with database.session() as session:
        session.add(ThreadMemory(user_id=1, thread_id=email["thread_id"], summary="앞 요약", confirmed_terms=TERMS,
                                 last_result={"missing_fields": ["due_date"]}))
    result, fake = run(database, later_email(email), responses)
    assert result["end_reason"] == end_reason and result["call_retries"] == retries
    assert result["errors"][0]["node"] == "load_memory" and result["errors"][0]["kind"] == error
    assert len(fake.calls) == len(responses)
    with database.session() as session:
        memory = session.get(ThreadMemory, (1, email["thread_id"]))
        assert memory.summary == "앞 요약" and memory.summarized_until is None
        assert memory.last_result["missing_fields"] == ["due_date"]
        details = [e.detail for e in session.scalars(select(RunEvent).where(RunEvent.run_id == result["run_id"]))]
    assert "가상 비밀 본문" not in json.dumps(details, ensure_ascii=False)


def test_oversized_summary_is_retried_without_losing_raw_messages(database, email):
    seed_messages(database, email, 9)
    oversized = {**SUMMARY, "deal_conditions": ["가" * 4001]}
    result, _ = run(database, later_email(email), [oversized, SUMMARY, GENERAL, DRAFTS])
    assert result["call_retries"] == 1 and result["end_reason"] == "awaiting_approval"
    assert len(result["thread_context"]["summary"]) <= 4000
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ThreadMessage)) == 10


def test_summary_retry_count_and_last_result_survive_formatting(database, email):
    seed_messages(database, email, 9)
    result, _ = run(database, later_email(email), [TimeoutError("가상"), SUMMARY, GENERAL, DRAFTS])
    assert result["call_retries"] == 1 and result["end_reason"] == "awaiting_approval"
    context = {"summary": "짧은 요약", "recent_messages": [], "confirmed_terms": TERMS,
               "last_result": {"missing_fields": ["due_date"]}}
    rendered = thread_context_text(context_for_model({"thread_context": context, "long_term": None}))
    assert "가상상사" in rendered and "due_date" in rendered
    assert context["summary"] == "짧은 요약"  # 모델용 문맥을 만들 때 상태를 바꾸지 않는다.
