"""계획 8절 완료 기준: 메일 분석·답장 후보(가짜 LLM, 실제 API 호출 없음)."""

import json

from google.genai.errors import ClientError
import pytest
from sqlalchemy import select

from app.db.models import ReplyCandidate as ReplyCandidateRow, RunEvent
from app.graph.build import build_graph
from app.graph.run import start_run
from app.llm import client
from app.tools.fallback import NOTICE_MESSAGES, fallback_candidates
from app.tools.registry import TOOLS
from tests.fakes.llm import FakeLLM

RATE_LIMIT = ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})
GENERAL = {"intent": "general", "reason": "제품 사용법을 묻는 일반 문의다."}
DEAL = {"intent": "deal", "reason": "품목과 수량, 납기가 들어 있다."}
IGNORE = {"intent": "ignore", "reason": "답장이 필요 없는 뉴스레터다."}


def drafts(count):
    labels = ["바로 안내", "추가 확인 요청", "정중한 보류", "네 번째"]
    return {"candidates": [{"label": labels[i], "body": f"가상 답장 {i + 1}"} for i in range(count)]}


@pytest.fixture(autouse=True)
def no_real_llm_or_wait(monkeypatch):
    monkeypatch.setattr(client, "get_backend", lambda *a: pytest.fail("실제 LLM은 호출하면 안 됩니다"))
    monkeypatch.setattr(client, "sleep", lambda _: None)


def run(database, email, responses, overrides=None, reflection_enabled=False):
    fake = FakeLLM(responses)
    with client.use_backend(fake):
        result = start_run(user_id=1, email=email, mode="test", database=database,
                           reflection_enabled=reflection_enabled,
                           graph=build_graph(node_overrides=overrides))
    return result, fake


def events(database, run_id):
    with database.session() as session:
        return list(session.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)))


def saved(database, run_id):
    with database.session() as session:
        return list(session.scalars(select(ReplyCandidateRow).where(
            ReplyCandidateRow.user_id == 1, ReplyCandidateRow.run_id == run_id,
        ).order_by(ReplyCandidateRow.id)))


@pytest.mark.parametrize("count", [2, 3])
def test_general_inquiry_saves_two_or_three_candidates(database, email, count):
    result, fake = run(database, email, [GENERAL, drafts(count)])
    assert result["end_reason"] == "awaiting_approval"
    assert result["intent"] == "general" and result["selected_tool"] == "draft_replies"
    assert result["tool_reason"] == GENERAL["reason"]
    assert len(result["candidates"]) == count and not result["needs_review"]
    rows = saved(database, result["run_id"])
    assert [r.label for r in rows] == [c["label"] for c in result["candidates"]]
    assert all(r.kind == "general" and r.status == "pending" and r.subject == "Re: 가상 문의"
               and r.thread_id == "fake-thread" and r.source_message_id == "fake-message" for r in rows)
    assert result["tools_called"] == [{"tool": "draft_replies", "ok": True, "error_kind": None,
                                       "attempts": 1, "duration_ms": result["tools_called"][0]["duration_ms"]}]
    logged = events(database, result["run_id"])
    select_event = next(e for e in logged if e.event == "tool_select")
    assert select_event.node == "analyze_email" and select_event.tool == "draft_replies"
    assert select_event.detail["reason"] == GENERAL["reason"]
    assert {"tool_call", "tool_result"} <= {e.event for e in logged if e.tool == "draft_replies"}
    assert [e.detail["prompt_version"] for e in logged if e.event == "llm_call"] == ["analyze_email.v1", "draft_replies.v1"]
    assert email["body_text"] in fake.calls[0] and email["body_text"] in fake.calls[1]
    assert email["body_text"] not in json.dumps([e.detail for e in logged], ensure_ascii=False)


def test_candidate_count_outside_contract_is_retried_as_invalid_output(database, email):
    result, _ = run(database, email, [GENERAL, drafts(4), drafts(2)])
    assert result["end_reason"] == "awaiting_approval" and len(saved(database, result["run_id"])) == 2
    assert result["call_retries"] == 1


def test_deal_email_takes_deal_path(database, email):
    reached = []

    def extract(state):
        reached.append(state["selected_tool"])
        return {"step_status": "failed"}

    result, fake = run(database, email, [DEAL], {"extract_deal": extract})
    assert reached == ["extract_deal_terms"]
    assert result["intent"] == "deal" and result["selected_tool"] == "extract_deal_terms"
    nodes = [e.node for e in events(database, result["run_id"]) if e.event == "node_start"]
    assert nodes[:3] == ["load_memory", "analyze_email", "extract_deal"]
    assert "draft_replies" not in nodes and len(fake.calls) == 1


def test_ignore_ends_without_candidates(database, email):
    result, _ = run(database, email, [IGNORE])
    assert result["end_reason"] == "ignored" and result["selected_tool"] is None
    assert saved(database, result["run_id"]) == []


@pytest.mark.parametrize("responses, llm_calls", [
    ([RATE_LIMIT], 1),                  # 메일 분석에서 한도 오류
    ([GENERAL, RATE_LIMIT], 2),         # 답장 후보에서 한도 오류
])
def test_rate_limit_saves_fallback_candidate_with_notice(database, email, responses, llm_calls):
    result, fake = run(database, email, responses, reflection_enabled=True)
    assert len(fake.calls) == llm_calls  # 한도 오류는 재시도하지 않는다
    assert result["end_reason"] == "awaiting_approval"
    assert result["needs_review"] and result["notice"] == "rate_limit" and result["call_retries"] == 0
    assert [e["kind"] for e in result["errors"]] == ["rate_limit"]
    rows = saved(database, result["run_id"])
    assert len(rows) == 1 and rows[0].needs_review and rows[0].notice == "rate_limit"
    assert "rate_limit" in NOTICE_MESSAGES
    nodes = [e.node for e in events(database, result["run_id"]) if e.event == "node_start"]
    assert "reflect" not in nodes


def test_network_failure_retries_then_succeeds(database, email):
    result, _ = run(database, email, [GENERAL, TimeoutError("가상"), TimeoutError("가상"), drafts(2)])
    assert result["end_reason"] == "awaiting_approval" and len(saved(database, result["run_id"])) == 2
    assert result["call_retries"] == 2 and result["tools_called"][0]["attempts"] == 3
    assert len([e for e in events(database, result["run_id"]) if e.event == "retry"]) == 2


@pytest.mark.parametrize("responses", [
    [TimeoutError("가상")] * 3,                    # 메일 분석에서 재시도를 다 씀
    [GENERAL] + [TimeoutError("가상")] * 3,        # 답장 후보에서 재시도를 다 씀
])
def test_network_failure_after_retries_ends_failed(database, email, responses):
    result, _ = run(database, email, responses)
    assert result["end_reason"] == "failed" and result["call_retries"] == 2
    assert [e["kind"] for e in result["errors"]] == ["network"]
    assert saved(database, result["run_id"]) == []


def test_reflection_feedback_reaches_prompt(database, email):
    reflection = {"passed": False, "issues": [], "cause": None, "strategy": "reprompt",
                  "retry_target": "draft_replies", "feedback": "가격을 지어내지 마세요", "verified": None}
    result, fake = run(database, email, [GENERAL, drafts(2)], {
        "load_memory": lambda s: {"reflection": reflection},
    })
    assert result["end_reason"] == "awaiting_approval"
    assert "가격을 지어내지 마세요" in fake.calls[1]


def test_tool_returns_result_and_fallback_shape(email):
    with client.use_backend(FakeLLM([drafts(3)])):
        result = TOOLS["draft_replies"].invoke({
            "email": email, "reply_mode": "general", "preferences": {"signature": "가상 서명"},
        })
    assert result.ok and result.source == "gemini:gemini-3.8-flash"
    assert all(c["body"].endswith("가상 서명") for c in result.value["candidates"])
    fallback = fallback_candidates({**email, "subject": "RE: 가상"}, kind="followup", asks_fields=["due_date"])
    assert fallback == [{
        "label": fallback[0]["label"], "subject": "RE: 가상", "body": fallback[0]["body"],
        "kind": "followup", "asks_fields": ["due_date"], "needs_review": True, "notice": "rate_limit",
    }]
