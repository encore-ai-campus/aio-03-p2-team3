"""계획 10절: 거래 항목 추출 → 필수 항목 검토 → 재질문/견적서 경로. 가짜 LLM만 쓴다."""

import json

from google.genai.errors import ClientError
import pytest
from sqlalchemy import select

from app.db.models import DealTerms as DealTermsRow, RunEvent
from app.graph.build import build_graph
from app.graph.run import start_run
from app.llm import client
from app.quote.required_fields import get_required_fields
from app.tools.check_required_fields import find_missing
from app.tools.extract_deal_terms import ExtractedDealTerms, to_deal_terms
from app.tools.registry import TOOLS
from tests.fakes.llm import FakeLLM

COMPLETE = {
    "customer_name": "가상상사",
    "items": [{"item_name": "가상 복사용지", "quantity": 100, "unit": "박스", "unit_price": None}],
    "due_date": "2026-11-20", "contact_name": None, "contact_phone": None,
    "delivery_place": None, "note": None,
    "evidence": [{"field": "customer_name", "excerpt": "가상상사"},
                 {"field": "quantity", "excerpt": "100박스"},
                 {"field": "due_date", "excerpt": "11월 20일까지"}],
}
NO_DUE_DATE = {**COMPLETE, "due_date": None,
               "evidence": [e for e in COMPLETE["evidence"] if e["field"] != "due_date"]}
FOLLOWUP = {"candidates": [
    {"label": "간단히 묻기", "subject": "Re: 가상 견적 문의", "body": "희망 납기를 알려 주시겠어요?"},
    {"label": "목록으로 묻기", "subject": "", "body": "아래 항목을 알려 주세요.\n- 납기"},
]}


@pytest.fixture
def deal_email(email):
    return {**email, "subject": "가상 견적 문의",
            "body_text": "가상상사입니다. 가상 복사용지 100박스 견적 부탁드립니다."}


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    monkeypatch.setattr(client, "get_backend", lambda: pytest.fail("실제 API 호출"))
    monkeypatch.setattr(client, "sleep", lambda _: None)


def run(database, email, responses, overrides=None, **kwargs):
    # 거래 경로만 본다: 메일 분석(8)은 의도만 정하고, 견적서 동봉 답장(11의 draft_replies quote)은 빈 틀로 둔다.
    nodes = {"analyze_email": lambda s: {"intent": "deal"}, "draft_replies": lambda s: {},
             "make_quote": lambda s: {}, **(overrides or {})}
    fake = FakeLLM(responses)
    with client.use_backend(fake):
        result = start_run(user_id=1, email=email, mode="test", database=database,
                           graph=build_graph(node_overrides=nodes), **kwargs)
    return result, fake


def events_for(database, run_id):
    with database.session() as session:
        return list(session.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)))


def started_nodes(database, run_id):
    return [e.node for e in events_for(database, run_id) if e.event == "node_start"]


def saved_row(database, run_id):
    with database.session() as session:
        return session.scalar(select(DealTermsRow).where(DealTermsRow.run_id == run_id))


def test_all_required_fields_go_to_quote_path(database, deal_email):
    result, fake = run(database, deal_email, [COMPLETE])
    nodes = started_nodes(database, result["run_id"])
    assert nodes[:5] == ["load_memory", "analyze_email", "extract_deal", "check_required", "make_quote"]
    assert "draft_followup" not in nodes
    assert result["missing_fields"] == [] and result["end_reason"] == "awaiting_approval"
    assert result["deal_terms"]["customer_name"] == "가상상사"
    assert result["deal_terms"]["evidence"] == {
        "customer_name": "가상상사", "quantity": "100박스", "due_date": "11월 20일까지"}
    assert result["required_fields"]["source"] == "config"
    assert [c["tool"] for c in result["tools_called"]] == ["extract_deal_terms", "check_required_fields"]
    assert len(fake.calls) == 1  # 필수 항목 검토는 LLM을 부르지 않는다
    row = saved_row(database, result["run_id"])
    assert row.missing_fields == [] and row.required_source == "config"
    assert row.thread_id == "fake-thread" and row.source_message_id == "fake-message"


def test_missing_due_date_asks_for_due_date(database, deal_email):
    result, fake = run(database, deal_email, [NO_DUE_DATE, FOLLOWUP])
    assert result["end_reason"] == "followup_question"
    assert result["missing_fields"] == ["due_date"] and result["reply_mode"] == "followup"
    candidates = result["candidates"]
    assert 2 <= len(candidates) <= 3
    assert all(c["kind"] == "followup" and c["asks_fields"] == ["due_date"] for c in candidates)
    assert candidates[1]["subject"] == "Re: 가상 견적 문의"  # 빈 제목은 원래 제목으로 채움
    assert "납기" in fake.calls[1]  # 재질문 프롬프트에 빠진 항목 이름이 들어감
    assert "make_quote" not in started_nodes(database, result["run_id"])
    assert saved_row(database, result["run_id"]).missing_fields == ["due_date"]


@pytest.mark.parametrize("response, attempts, kind", [
    (TimeoutError("가상 통신 실패"), 3, "network"),          # 통신 재시도 2번을 다 씀
    ({"items": "목록 아님"}, 2, "invalid_output"),          # 형식 재시도 1번을 다 씀
])
def test_extraction_failure_ends_failed(database, deal_email, response, attempts, kind):
    responses = [response] * attempts
    result, _ = run(database, deal_email, responses)
    assert result["end_reason"] == "failed"
    assert result["deal_terms"] is None and result["call_retries"] == attempts - 1
    assert result["errors"][0]["node"] == "extract_deal" and result["errors"][0]["kind"] == kind
    nodes = started_nodes(database, result["run_id"])
    assert nodes[-1] == "finish_failed" and "check_required" not in nodes
    assert saved_row(database, result["run_id"]) is None


@pytest.mark.parametrize("responses, end_reason, kind", [
    ([ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})], "awaiting_approval", "general"),
    ([NO_DUE_DATE, ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})], "followup_question", "followup"),
])
def test_rate_limit_uses_fallback_and_skips_reflection(database, deal_email, responses, end_reason, kind):
    result, _ = run(database, deal_email, responses, reflection_enabled=True)
    assert result["end_reason"] == end_reason
    assert result["needs_review"] and result["notice"] == "rate_limit"
    assert len(result["candidates"]) == 1 and result["candidates"][0]["kind"] == kind
    assert result["candidates"][0]["asks_fields"] == (["due_date"] if kind == "followup" else [])
    assert result["errors"][-1]["kind"] == "rate_limit"
    assert "reflect" not in started_nodes(database, result["run_id"])


def test_followup_wrong_candidate_count_is_retried(database, deal_email):
    one = {"candidates": FOLLOWUP["candidates"][:1]}
    result, _ = run(database, deal_email, [NO_DUE_DATE, one, FOLLOWUP])
    assert result["end_reason"] == "followup_question" and len(result["candidates"]) == 2
    assert result["call_retries"] == 1


def test_reflection_feedback_reaches_extract_prompt(database, deal_email):
    def reflect(state):
        if state["reflection_history"]:
            done = {"passed": True, "issues": [], "cause": None, "strategy": None,
                    "retry_target": None, "feedback": None, "verified": True}
            return {"reflection": done, "reflection_history": [done]}
        retry = {"passed": False, "issues": [], "cause": "가상 원인", "strategy": "reprompt",
                 "retry_target": "extract_deal", "feedback": "가상 피드백: 수량을 다시 확인", "verified": None}
        return {"reflection": retry, "reflection_history": [retry]}

    result, fake = run(database, deal_email, [COMPLETE, COMPLETE], {"reflect": reflect}, reflection_enabled=True)
    assert result["end_reason"] == "awaiting_approval"
    assert "가상 피드백" not in fake.calls[0] and "가상 피드백: 수량을 다시 확인" in fake.calls[1]
    with database.session() as session:  # 다시 검토해도 실행마다 한 줄
        assert len(list(session.scalars(select(DealTermsRow).where(
            DealTermsRow.run_id == result["run_id"])))) == 1


def test_logs_tool_choice_and_required_source_without_body(database, deal_email):
    result, _ = run(database, deal_email, [NO_DUE_DATE, FOLLOWUP])
    events = events_for(database, result["run_id"])
    names = [(e.event, e.node, e.tool) for e in events if e.event.startswith("tool_")]
    assert ("tool_select", "check_required", "draft_followup_replies") in names
    assert ("tool_result", "extract_deal_terms") in [(n[0], n[2]) for n in names]
    assert ("tool_result", "draft_followup_replies") in [(n[0], n[2]) for n in names]
    source = next(e for e in events if e.event == "required_source")
    assert source.node == "check_required" and source.detail["fields"] == [
        "customer_name", "item_name", "quantity", "due_date"]
    details = json.dumps([e.detail for e in events], ensure_ascii=False)
    assert deal_email["body_text"] not in details and "희망 납기를 알려" not in details


@pytest.mark.parametrize("terms, missing", [
    ({"customer_name": "가상", "items": [], "due_date": "2026-11-20"}, ["item_name", "quantity"]),
    ({"customer_name": "가상", "items": [{"item_name": "A", "quantity": None}], "due_date": "x"}, ["quantity"]),
    ({"customer_name": "  ", "items": [{"item_name": "A", "quantity": 1}, {"item_name": None, "quantity": 2}],
      "due_date": None}, ["customer_name", "item_name", "due_date"]),
    ({"customer_name": "가상", "items": [{"item_name": "A", "quantity": 1, "unit_price": None}],
      "due_date": "x"}, []),
])
def test_find_missing_rules(terms, missing):
    assert find_missing(terms, get_required_fields(1)) == missing


def test_extracted_values_are_cleaned():
    raw = ExtractedDealTerms.model_validate({
        "customer_name": " ", "items": [{"item_name": "A", "quantity": 0}, {}],
        "due_date": "다음 주 금요일",
        "evidence": [{"field": "customer_name", "excerpt": "지어낸 근거"},
                     {"field": "due_date", "excerpt": "다음 주 금요일"}],
    })
    terms = to_deal_terms(raw)
    assert terms["customer_name"] is None and terms["due_date"] == "다음 주 금요일"
    assert terms["items"] == [{"item_name": "A", "quantity": None, "unit": None, "unit_price": None}]
    assert terms["evidence"] == {"due_date": "다음 주 금요일"}


def test_tools_return_results_instead_of_raising(deal_email):
    terms = to_deal_terms(ExtractedDealTerms.model_validate(COMPLETE))
    result = TOOLS["draft_followup_replies"].invoke({
        "email": deal_email, "deal_terms": terms, "missing_fields": [], "field_labels": {}})
    assert not result.ok and result.error_kind == "invalid_input"
    assert TOOLS["check_required_fields"].invoke({"deal_terms": terms}).error_kind == "invalid_input"
