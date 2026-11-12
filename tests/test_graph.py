import json
from typing import Literal

from pydantic import BaseModel
import pytest
from sqlalchemy import select

from app.db.models import Run, RunEvent
from app.graph.build import build_graph
from app.graph.run import start_run
from app.llm import client
from app.prompts import Prompt
from tests.fakes.llm import FakeLLM, openai_error


class Decision(BaseModel):
    intent: Literal["general", "deal", "ignore"]


def events_for(database, run_id):
    with database.session() as session:
        return list(session.scalars(select(RunEvent).where(
            RunEvent.run_id == run_id,
        ).order_by(RunEvent.seq)))


def stub_drafts(state):
    # 흐름 시험용. 실제 답장 후보 노드는 tests/test_mail_analysis.py가 시험한다.
    return {"candidates": [], "step_status": "ok"}


# 이 파일은 그래프 연결(전이)만 본다. 업무 본문을 채운 거래 노드도 빈 틀로 바꿔 끼운다
# (거래 노드 본문 시험은 tests/test_deal.py).
BLANK_NODES = {name: (lambda s: {}) for name in ("extract_deal", "check_required", "draft_followup", "make_quote")}


def pass_reflect(state):
    # 흐름 시험용 통과 성찰. 실제 성찰(감지·수정·재검증)은 tests/test_reflect.py가 시험한다.
    passed = {"passed": True, "issues": [], "cause": None, "strategy": None,
              "retry_target": None, "feedback": None, "verified": None}
    return {"reflection": passed, "reflection_history": [passed]}


def run(database, email, overrides=None, **kwargs):
    overrides = {"draft_replies": stub_drafts, "reflect": pass_reflect, **BLANK_NODES, **(overrides or {})}
    return start_run(user_id=1, email=email, mode="test", database=database,
                     graph=build_graph(node_overrides=overrides), **kwargs)


def test_fake_llm_graph_completes_and_records_node_times(database, email, monkeypatch):
    monkeypatch.setattr(client, "get_backend", lambda: pytest.fail("실제 API 호출"))

    def analyze(state):
        result = client.call_structured(Prompt("test_analyze", "v1", "{input}"), Decision,
                                        {"input": state["email"]["body_text"]})
        return {"intent": result.value.intent, "reply_mode": "general", "call_retries": result.attempts - 1}

    fake = FakeLLM([{"intent": "general"}])
    with client.use_backend(fake):
        result = run(database, email, {"analyze_email": analyze}, reflection_enabled=True)
    assert result["end_reason"] == "awaiting_approval"
    events = events_for(database, result["run_id"])
    node_ends = [e for e in events if e.event == "node_end"]
    assert [e.node for e in node_ends] == ["load_memory", "analyze_email", "draft_replies", "reflect", "save_pending"]
    assert all(isinstance(e.duration_ms, int) and e.duration_ms >= 0 for e in node_ends)
    assert [e.seq for e in events] == list(range(len(events)))
    assert events[0].event == "run_start" and events[-1].event == "run_end"
    assert all(e.at.utcoffset().total_seconds() == 0 for e in events)
    llm_event = next(e for e in events if e.event == "llm_call")
    assert llm_event.detail["prompt_version"] == "test_analyze.v1"
    with database.session() as session:
        persisted = session.scalar(select(Run).where(Run.run_id == result["run_id"], Run.user_id == 1))
        assert persisted.end_reason == result["end_reason"]
        assert persisted.ended_at >= persisted.started_at and persisted.duration_ms >= 0
    assert email["body_text"] not in json.dumps([e.detail for e in events], ensure_ascii=False)


@pytest.mark.parametrize("intent, missing, reflection, expected, middle", [
    ("general", [], False, "awaiting_approval", "draft_replies"),
    ("deal", ["quantity"], True, "followup_question", "draft_followup"),
    ("deal", [], True, "awaiting_approval", "make_quote"),
    ("ignore", [], True, "ignored", None),
])
def test_graph_paths(database, email, intent, missing, reflection, expected, middle):
    overrides = {
        "analyze_email": lambda s: {"intent": intent, "reply_mode": "general"},
        "check_required": lambda s: {"missing_fields": missing, "reply_mode": "followup" if missing else "quote"},
    }
    result = run(database, email, overrides, reflection_enabled=reflection)
    assert result["end_reason"] == expected
    nodes = [e.node for e in events_for(database, result["run_id"]) if e.event == "node_start"]
    if middle:
        assert middle in nodes
    else:
        assert nodes == ["load_memory", "analyze_email"]
    assert "send_email" not in nodes


@pytest.mark.parametrize("node, intent, missing, status, expected", [
    ("analyze_email", "general", [], "rate_limit", "awaiting_approval"),
    ("extract_deal", "deal", [], "rate_limit", "awaiting_approval"),
    ("draft_replies", "general", [], "rate_limit", "awaiting_approval"),
    ("draft_followup", "deal", ["quantity"], "rate_limit", "followup_question"),
    ("analyze_email", "general", [], "failed", "failed"),
    ("extract_deal", "deal", [], "failed", "failed"),
    ("check_required", "deal", [], "failed", "failed"),
    ("make_quote", "deal", [], "failed", "failed"),
    ("draft_replies", "general", [], "failed", "failed"),
    ("draft_followup", "deal", ["quantity"], "failed", "failed"),
])
def test_error_transitions(database, email, node, intent, missing, status, expected):
    overrides = {
        "analyze_email": lambda s: {"intent": intent},
        "check_required": lambda s: {"missing_fields": missing, "reply_mode": "followup" if missing else "quote"},
    }
    overrides[node] = lambda s: {"step_status": status}
    result = run(database, email, overrides, reflection_enabled=True)
    assert result["end_reason"] == expected
    nodes = [e.node for e in events_for(database, result["run_id"]) if e.event == "node_start"]
    assert "reflect" not in nodes


@pytest.mark.parametrize("target", ["extract_deal", "draft_replies", "draft_followup", "make_quote"])
def test_reflection_reexecution_and_accumulating_fields(database, email, target):
    def reflect(state):
        passed = bool(state["reflection_history"])
        reflection = {
            "passed": passed, "issues": [], "cause": None,
            "strategy": None if passed else "reprompt", "retry_target": None if passed else target,
            "feedback": None, "verified": passed,
        }
        return {"reflection": reflection, "reflection_history": [reflection],
                "reflection_retries": 1, "call_retries": 1}

    result = run(database, email, {"analyze_email": lambda s: {"intent": "general"}, "reflect": reflect}, reflection_enabled=True)
    assert result["end_reason"] == "awaiting_approval"
    assert len(result["reflection_history"]) == 2 and result["call_retries"] == 2
    assert result["reflection_retries"] == 1
    assert any(e.node == target and e.event == "node_start" for e in events_for(database, result["run_id"]))


def test_reflection_fallback_finishes_without_retry(database, email):
    result = run(database, email, {
        "analyze_email": lambda s: {"intent": "general"},
        "reflect": lambda s: {"reflection": {
            "passed": False, "issues": [], "cause": None, "strategy": "fallback",
            "retry_target": "draft_replies", "feedback": None, "verified": False,
        }, "needs_review": True, "notice": "reflection_limit"},
    }, reflection_enabled=True)
    assert result["end_reason"] == "awaiting_approval" and result["needs_review"]
    nodes = [e.node for e in events_for(database, result["run_id"]) if e.event == "node_start"]
    assert nodes.count("draft_replies") == 1


def test_node_exception_is_timed_and_message_is_not_logged(database, email):
    def broken(state):
        raise RuntimeError("이 가상 비밀 문구는 저장되면 안 됩니다")

    result = run(database, email, {"analyze_email": broken})
    assert result["end_reason"] == "failed"
    events = events_for(database, result["run_id"])
    assert any(e.event == "error" and e.node == "analyze_email" for e in events)
    assert any(e.event == "node_end" and e.node == "analyze_email" and e.duration_ms >= 0 for e in events)
    assert "가상 비밀 문구" not in json.dumps([e.detail for e in events], ensure_ascii=False)


@pytest.mark.parametrize("failure, expected, attempts", [
    (openai_error(429), "awaiting_approval", 1),
    (TimeoutError("가상 통신 실패"), "failed", 3),
])
def test_llm_error_kind_controls_graph_exit(database, email, monkeypatch, failure, expected, attempts):
    monkeypatch.setattr(client, "sleep", lambda _: None)

    def analyze(state):
        result = client.call_structured(Prompt("test_analyze", "v1", "{input}"), Decision, {"input": "가상 입력"})
        return {"step_status": "rate_limit" if result.error_kind == "rate_limit" else "failed",
                "call_retries": result.attempts - 1}

    with client.use_backend(FakeLLM([failure] * attempts)):
        result = run(database, email, {"analyze_email": analyze}, reflection_enabled=True)
    assert result["end_reason"] == expected
    assert result["call_retries"] == attempts - 1 and result["reflection_retries"] == 0
    retry_events = [e for e in events_for(database, result["run_id"]) if e.event == "retry"]
    assert len(retry_events) == attempts - 1


def test_blank_nodes_do_not_claim_success(database, email):
    # 실제 키가 있어도 외부 호출 없이 실패가 전파되는지만 본다(환경과 무관한 검증).
    with client.use_backend(FakeLLM([openai_error(400)])):
        assert run(database, email)["end_reason"] == "failed"


def test_unknown_user_is_rejected_without_run(database, email):
    with pytest.raises(ValueError, match="사용자"):
        start_run(user_id=999, email=email, mode="test", database=database)
