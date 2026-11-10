"""계획 12절: 자가 성찰 루프(감지 → 원인 분석 → 수정 전략 → 재실행 → 재검증)와 켜기/끄기.

가짜 LLM만 쓴다(실제 API 호출 없음). 오류 유형마다 1건씩 감지·수정·재검증 성공, 한도 초과 대체 경로,
스위치 끔, 실행 기록의 감지 근거·수정 전략·재실행 결과를 확인한다.
"""

from datetime import date
import json

from fastapi.testclient import TestClient
from google.genai.errors import ClientError
import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.models import ReplyCandidate, RunEvent, User
from app.graph.build import build_graph
from app.graph.nodes import reflect as reflect_module
from app.graph.nodes.reflect import detect, reflect
from app.graph.run import start_run
from app.graph.state import initial_state
from app.llm import client
from app.main import create_app
from app.quote.calc import build_draft
from app.quote.required_fields import get_required_fields
from app.tools.fallback import NOTICE_MESSAGES
from app.web.deps import current_user_id
from tests.fakes.llm import FakeLLM

GENERAL = {"intent": "general", "reason": "일반 문의"}
DEAL = {"intent": "deal", "reason": "견적 요청"}
FIX = {"cause": "근거 없는 값을 지어냄", "feedback": "원문에 없는 숫자를 쓰지 마세요"}
CLEAN = {"candidates": [{"label": "안내", "body": "문의 감사합니다. 확인 뒤 다시 안내드리겠습니다."},
                        {"label": "확인", "body": "자세한 내용을 확인해 연락드리겠습니다."}]}
INVENTED = {"candidates": [{"label": "안내", "body": "총 500만원에 11월 30일까지 드릴 수 있습니다."},
                           {"label": "확인", "body": "확인 뒤 다시 안내드리겠습니다."}]}
QUOTE_REPLY = {"candidates": [{"label": "간단 안내", "body": "첨부 견적서를 확인해 주세요."},
                              {"label": "상세 안내", "body": "요청하신 견적서를 첨부드립니다."}]}
TERMS = {
    "customer_name": "가상상사", "due_date": "2026-11-20",
    "items": [{"item_name": "가상 복사용지", "quantity": 100, "unit": "박스", "unit_price": None}],
    "contact_name": None, "contact_phone": None, "delivery_place": None, "note": None,
    "evidence": [{"field": "quantity", "excerpt": "100박스"}],
}
NO_DUE = {**TERMS, "due_date": None}


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    monkeypatch.setattr(client, "get_backend", lambda: pytest.fail("실제 API 호출"))
    monkeypatch.setattr(client, "sleep", lambda _: None)


@pytest.fixture
def deal_email(email):
    return {**email, "subject": "가상 견적 문의",
            "body_text": "가상상사입니다. 가상 복사용지 100박스 견적 부탁드립니다. 11월 20일까지 필요합니다."}


def run(database, email, responses, overrides=None, reflection_enabled=True):
    fake = FakeLLM(responses)
    with client.use_backend(fake):
        result = start_run(user_id=1, email=email, mode="test", database=database,
                           reflection_enabled=reflection_enabled,
                           graph=build_graph(node_overrides=overrides or {}))
    return result, fake


def events(database, run_id):
    with database.session() as session:
        return list(session.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)))


def reflection_events(database, run_id):
    return [e.detail for e in events(database, run_id) if e.event == "reflection"]


def started(database, run_id):
    return [e.node for e in events(database, run_id) if e.event == "node_start"]


def saved(database, run_id):
    with database.session() as session:
        return session.scalars(select(ReplyCandidate).where(ReplyCandidate.run_id == run_id)).all()


def assert_fixed_once(database, result, kind, target):
    """감지 → 수정 전략 → 재실행 → 재검증 성공이 상태와 실행 기록에 모두 남았는지 본다."""
    first, last = result["reflection_history"]
    assert [i["type"] for i in first["issues"]][0] == kind and not first["passed"]
    assert first["retry_target"] == target and first["cause"] and first["feedback"]
    assert last["passed"] and last["verified"] is True
    assert result["reflection_retries"] == 1 and result["reflection_retries_by_type"] == {kind: 1}
    stages = reflection_events(database, result["run_id"])
    assert [s["stage"] for s in stages] == ["detect", "analyze", "strategy", "detect", "verify"]
    assert stages[0]["issues"][0]["type"] == kind and stages[0]["issues"][0]["evidence"]   # 감지 근거
    assert stages[2]["strategy"] == first["strategy"] and stages[2]["retry_target"] == target  # 수정 전략
    assert stages[4]["verified"] is True and stages[4]["retried"] == target                  # 재실행 결과
    nodes = started(database, result["run_id"])
    assert nodes.count("reflect") == 2 and target in nodes[nodes.index("reflect"):]
    llm_versions = [e.detail["prompt_version"] for e in events(database, result["run_id"]) if e.event == "llm_call"]
    assert "reflect_fix.v1" in llm_versions


# --- 오류 유형마다 1건: 감지 → 수정 → 재검증 성공 -------------------------------------------------

def test_hallucination_is_fixed_by_reprompt(database, email):
    result, fake = run(database, email, [GENERAL, INVENTED, FIX, CLEAN])
    assert result["end_reason"] == "awaiting_approval" and not result["needs_review"]
    assert_fixed_once(database, result, "hallucination", "draft_replies")
    assert "500만원" in result["reflection_history"][0]["issues"][0]["evidence"]
    assert "원문에 없는 숫자를 쓰지 마세요" in fake.calls[3] and "500만원" in fake.calls[3]
    assert [c.body for c in saved(database, result["run_id"])] == [c["body"] for c in result["candidates"]]
    assert all("500만원" not in c.body for c in saved(database, result["run_id"]))
    assert result["call_retries"] == 0   # 성찰 재실행은 통신 재시도와 따로 센다


def test_wrong_tool_reroutes_general_reply_to_deal_path(database, deal_email):
    result, _ = run(database, deal_email, [GENERAL, CLEAN, FIX, TERMS, QUOTE_REPLY])
    assert_fixed_once(database, result, "wrong_tool", "extract_deal")
    assert result["reflection_history"][0]["strategy"] == "reroute"
    assert result["intent"] == "deal" and result["reply_mode"] == "quote" and result["quote_draft"]
    nodes = started(database, result["run_id"])
    assert nodes[nodes.index("reflect"):][:5] == ["reflect", "extract_deal", "check_required", "make_quote", "draft_replies"]
    reselect = [e for e in events(database, result["run_id"]) if e.event == "tool_select" and e.node == "reflect"]
    assert reselect[0].tool == "extract_deal_terms" and reselect[0].detail["reason"]
    assert {c.kind for c in saved(database, result["run_id"])} == {"quote"}


def test_missing_param_reruns_previous_node(database, deal_email):
    calls = []

    def make_quote(state):
        calls.append(True)
        if len(calls) == 1:   # 첫 실행은 견적서 초안을 비운 채로 넘긴다
            return {"reply_mode": "quote", "step_status": "ok"}
        quote = build_draft(TERMS, None, [], quote_no="Q-20261110-001", quote_date=date(2026, 11, 10))
        return {"reply_mode": "quote", "quote_draft": quote, "step_status": "ok"}

    result, _ = run(database, deal_email, [DEAL, TERMS, QUOTE_REPLY, FIX, QUOTE_REPLY],
                    {"make_quote": make_quote})
    assert_fixed_once(database, result, "missing_param", "make_quote")
    assert len(calls) == 2 and result["quote_draft"]["quote_no"] == "Q-20261110-001"


def test_inconsistent_followup_is_fixed(database, deal_email):
    vague = {"candidates": [{"label": "짧게", "body": "몇 가지 더 알려 주시겠어요?"},
                            {"label": "길게", "body": "추가 정보가 필요합니다."}]}
    asks = {"candidates": [{"label": "짧게", "body": "희망 납기를 알려 주시겠어요?"},
                           {"label": "길게", "body": "견적을 위해 납기를 알려 주세요."}]}
    result, fake = run(database, deal_email, [DEAL, NO_DUE, vague, FIX, asks])
    assert result["end_reason"] == "followup_question"
    assert_fixed_once(database, result, "inconsistent", "draft_followup")
    assert "납기" in result["reflection_history"][0]["issues"][0]["evidence"]
    assert "원문에 없는 숫자를 쓰지 마세요" in fake.calls[4]


# --- 한도 초과 → 대체 경로 ----------------------------------------------------------------------

def test_type_limit_falls_back_to_needs_review(database, email):
    responses = [GENERAL, INVENTED, FIX, INVENTED, FIX, INVENTED]
    result, fake = run(database, email, responses)
    assert len(fake.calls) == len(responses)    # 대체 경로에서는 LLM을 더 부르지 않는다
    assert result["end_reason"] == "awaiting_approval"
    assert result["needs_review"] and result["notice"] == "reflection_limit"
    assert result["reflection_retries"] == 2 and result["reflection_retries_by_type"] == {"hallucination": 2}
    last = result["reflection_history"][-1]
    assert last["strategy"] == "fallback" and last["verified"] is False and last["retry_target"] is None
    assert reflection_events(database, result["run_id"])[-1].items() >= {
        "stage": "strategy", "strategy": "fallback", "reason": "limit"}.items()
    rows = saved(database, result["run_id"])
    assert len(rows) == 2 and all(r.needs_review and r.notice == "reflection_limit" for r in rows)
    assert "reflection_limit" in NOTICE_MESSAGES
    assert started(database, result["run_id"]).count("draft_replies") == 3


def test_total_limit_and_empty_candidates_use_safe_template(email):
    state = initial_state(run_id="r", user_id=1, mode="test", email=email, reflection_enabled=True)
    state.update(reply_mode="general", reflection_retries=3,
                 reflection_retries_by_type={"hallucination": 1, "inconsistent": 1, "wrong_tool": 1})
    update = reflect(state)
    assert update["reflection"]["strategy"] == "fallback" and update["notice"] == "reflection_limit"
    [candidate] = update["candidates"]
    assert candidate["needs_review"] and candidate["notice"] == "reflection_limit"
    assert candidate["subject"] == "Re: 가상 문의"


def test_reflection_error_ends_with_needs_review(database, email, monkeypatch):
    monkeypatch.setattr(reflect_module, "detect", lambda state: 1 / 0)
    result, _ = run(database, email, [GENERAL, CLEAN])
    assert result["end_reason"] == "awaiting_approval" and result["notice"] == "reflection_limit"
    assert [e["kind"] for e in result["errors"]] == ["internal"]
    assert "ZeroDivisionError" in result["errors"][0]["message"]


def test_reflect_fix_failure_uses_rule_feedback(database, email):
    rate_limit = ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})
    result, fake = run(database, email, [GENERAL, INVENTED, rate_limit, CLEAN])
    first = result["reflection_history"][0]
    assert first["cause"].startswith("규칙 검사") and "500만원" in first["feedback"]
    assert "500만원" in fake.calls[3] and result["reflection_history"][-1]["verified"] is True
    analyze = [s for s in reflection_events(database, result["run_id"]) if s["stage"] == "analyze"][0]
    assert analyze["llm_ok"] is False and analyze["error_kind"] == "rate_limit"


# --- 스위치 끔 → 성찰 건너뜀, 우선순위 -------------------------------------------------------------

def test_switch_off_skips_reflection(database, email):
    result, fake = run(database, email, [GENERAL, INVENTED], reflection_enabled=False)
    assert len(fake.calls) == 2 and "reflect" not in started(database, result["run_id"])
    assert result["reflection_history"] == [] and result["reflection_retries"] == 0
    assert any("500만원" in r.body for r in saved(database, result["run_id"]))   # 성찰 전 결과 그대로


def test_switch_priority_option_then_user_then_env(database, email, monkeypatch):
    graph = build_graph(node_overrides={"analyze_email": lambda s: {"intent": "ignore"}})
    with database.session() as session:
        session.get(User, 1).reflection_enabled = True
    assert start_run(user_id=1, email=email, mode="test", database=database, graph=graph)["reflection_enabled"]
    assert not start_run(user_id=1, email=email, mode="test", database=database, graph=graph,
                         reflection_enabled=False)["reflection_enabled"]
    from app import config
    monkeypatch.setattr(config, "get_settings", lambda: Settings(reflection_enabled_default=True))
    with database.session() as session:
        session.add(User(id=2, google_sub="fake-sub-2", email="two@example.invalid"))
    with database.session() as session:
        assert session.get(User, 2).reflection_enabled is True


def test_settings_toggle_updates_user_switch(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path}/reflect.sqlite3", session_secret="fake-session"))
    app.dependency_overrides[current_user_id] = lambda: 1
    with TestClient(app) as web:
        db = app.state.database
        with db.session() as session:
            session.add_all([User(id=1, google_sub="one", email="one@example.invalid", reflection_enabled=False),
                             User(id=2, google_sub="two", email="two@example.invalid", reflection_enabled=False)])
        page = web.get("/settings")
        assert page.status_code == 200 and 'action="/settings/reflection"' in page.text and "지금: 끔" in page.text
        assert web.post("/settings/reflection", data={"enabled": "on"}).status_code == 200
        assert "지금: 켬" in web.get("/settings").text
        with db.session() as session:
            assert session.get(User, 1).reflection_enabled and not session.get(User, 2).reflection_enabled
        web.post("/settings/reflection", data={})
        with db.session() as session:
            assert not session.get(User, 1).reflection_enabled
        app.dependency_overrides.clear()
        response = web.post("/settings/reflection", data={"enabled": "on"}, follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/login"


# --- 감지 규칙(LLM 없음) -------------------------------------------------------------------------

def state_with(email, **values):
    state = initial_state(run_id="r", user_id=1, mode="test", email=email, reflection_enabled=True)
    state.update(values)
    return state


def candidate(body, kind="general", subject="Re: 가상 문의", asks=()):
    return {"label": "후보", "subject": subject, "body": body, "kind": kind,
            "asks_fields": list(asks), "needs_review": False, "notice": None}


def kinds(findings):
    return [(f.issue["type"], f.strategy, f.target) for f in findings]


def test_detect_supported_values_and_plain_numbers_pass(email):
    email = {**email, "body_text": "가상 복사용지 3박스를 12월 1일까지 받을 수 있을까요? 지난번처럼 2,000원이면 좋겠습니다."}
    state = state_with(email, reply_mode="general", candidates=[
        candidate("3박스를 12/1까지 2,000원에 맞춰 보겠습니다. 1번 안입니다."),
        candidate("확인 뒤 연락드리겠습니다.")])
    assert detect(state) == []


def test_detect_does_not_use_past_deals_as_evidence(email):
    state = state_with(email, reply_mode="general", long_term={
        "preferences": {}, "company": None, "price_list": [], "sources": [],
        "counterparty_history": [{"deal_terms": {"items": [{"quantity": 70}]}}]},
        candidates=[candidate("지난번처럼 70개 보내 드리겠습니다."), candidate("확인하겠습니다.")])
    assert kinds(detect(state)) == [("hallucination", "reprompt", "draft_replies")]


def test_detect_inconsistent_shape_subject_and_recipient(email):
    state = state_with(email, reply_mode="general", candidates=[
        candidate("확인하겠습니다. other@example.invalid 로 회신 주세요.", subject="다른 제목")])
    found = kinds(detect(state))
    assert found.count(("inconsistent", "reprompt", "draft_replies")) == 3   # 개수·제목·받는 사람


def test_detect_quote_with_missing_fields_switches_to_followup(email):
    state = state_with(email, reply_mode="quote", deal_terms=NO_DUE, missing_fields=["due_date"],
                       required_fields=get_required_fields(1), quote_draft={"quote_no": "Q"},
                       candidates=[candidate("첨부 확인", "quote"), candidate("첨부 드립니다", "quote")])
    [finding] = [f for f in detect(state) if f.issue["type"] == "wrong_tool"]
    assert (finding.strategy, finding.target) == ("followup", "draft_followup")
    assert finding.update["reply_mode"] == "followup"


def test_run_records_have_no_mail_body(database, email):
    result, _ = run(database, email, [GENERAL, INVENTED, FIX, CLEAN])
    details = json.dumps([e.detail for e in events(database, result["run_id"])], ensure_ascii=False)
    assert email["body_text"] not in details and "총 500만원에 11월 30일까지" not in details
