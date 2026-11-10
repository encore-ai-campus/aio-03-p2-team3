"""계획 17절: 시험 시나리오·지표·시험 실행기.

가짜 LLM·가짜 Gmail만 쓴다(실제 API 호출 없음). 같은 입력을 성찰 끔/켬으로 돌려 4개 지표
(태스크 완료율·도구 선택 정확도·응답 일관성 점수·평균 재시행 횟수)가 계산되는지, 준비된 응답·고의 실패가
실행 기록에 `detail.injected`로 표시되는지 확인한다.
"""

from dataclasses import replace
import json
from pathlib import Path

from cryptography.fernet import Fernet
import pytest
from sqlalchemy import select

from app.db.models import Run, RunEvent
from app.evaluation import runner
from app.evaluation.metrics import METRIC_NAMES, consistency, render_markdown
from app.evaluation.scenarios import CLEAN, GENERAL, GENERAL_BODY, SCENARIOS, SCENARIOS_BY_KEY
from app.llm import client
from app.services.auth import GoogleAccess, TokenCipher, save_login
from tests.fakes.gmail import FakeGmailGoogle, message
from tests.fakes.google import fake_login
from tests.fakes.llm import FakeLLM

REPORT = Path(__file__).resolve().parents[1] / "docs" / "TEST_REPORT.md"


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    monkeypatch.setattr(client, "get_backend", lambda: pytest.fail("실제 API 호출"))
    monkeypatch.setattr(client, "sleep", lambda _: None)


class AnyMessage(dict):
    """어떤 메일 ID로 조회해도 지어낸 원본 메일을 돌려주는 가짜 메일함."""

    def __missing__(self, message_id):
        return message(message_id, sender="gmail-case@example.invalid")


@pytest.fixture
def gmail():
    fake = FakeGmailGoogle()
    fake.mailbox.raw_messages = AnyMessage()
    return fake


@pytest.fixture
def access(database, gmail):
    access = GoogleAccess(database, gmail, TokenCipher(Fernet.generate_key().decode()), "projects/fake/topics/fake")
    assert save_login(access, fake_login()) == 1   # conftest의 사용자 1에 가짜 토큰을 붙인다
    return access


def events_of(database, run_id, event=None):
    with database.session() as session:
        query = select(RunEvent).where(RunEvent.run_id == run_id)
        if event:
            query = query.where(RunEvent.event == event)
        return list(session.scalars(query.order_by(RunEvent.seq)))


def by(result, key, enabled):
    return [j for j in result["judgments"] if j["scenario"] == key and j["reflection_enabled"] is enabled]


def test_suite_runs_same_inputs_with_reflection_off_and_on(database, access, gmail, tmp_path):
    result = runner.run_suite(database, 1, repeat=2, access=access, export_dir=tmp_path)
    off, on = result["metrics"]["off"], result["metrics"]["on"]
    assert not result["skipped"] and len(result["judgments"]) == len(SCENARIOS) * 2 * 2
    # 실행 기록으로 센 도구·재시도가 그래프 상태의 tools_called·call_retries·reflection_retries와 같다.
    assert all(j["state_matches"] for j in result["judgments"])

    # 1. 태스크 완료율: 판단 오류 두 시나리오는 성찰을 켜야 완료된다.
    assert off["task_completion"] == {"completed": 10, "total": 14, "rate": round(10 / 14, 4)}
    assert on["task_completion"] == {"completed": 14, "total": 14, "rate": 1.0}
    assert not any(j["completed"] for j in by(result, "wrong_tool", False) + by(result, "hallucination", False))
    assert all(j["checks"]["forbidden"] is False for j in by(result, "hallucination", False))
    # 2. 도구 선택 정확도: 성찰 끔의 잘못 분류는 거래 도구 3개가 누락된다.
    assert off["tool_accuracy"]["hits"] == 12 and off["tool_accuracy"]["missing"] == {
        "extract_deal_terms": 2, "check_required_fields": 2, "create_quote": 2}
    assert on["tool_accuracy"]["rate"] == 1.0 and not on["tool_accuracy"]["unnecessary"]
    # 3. 응답 일관성: 준비된 응답이 같으니 반복 실행의 사실·조건·구조가 모두 같다.
    assert off["consistency"]["score"] == on["consistency"]["score"] == 1.0
    assert on["consistency"]["scenarios_measured"] == len(SCENARIOS)
    # 4. 평균 재시행: 성찰 재실행(켬에서 2개 시나리오 × 2번)과 Gmail 실패 뒤 재승인(실행마다 1번)을 센다.
    assert off["retries"] == {"total": 2, "runs": 14, "average": round(2 / 14, 4),
                              "call_retries": 0, "reflection_retries": 0, "resends": 2}
    assert on["retries"] == {"total": 6, "runs": 14, "average": round(6 / 14, 4),
                             "call_retries": 0, "reflection_retries": 4, "resends": 2}

    with database.session() as session:
        runs = session.scalars(select(Run)).all()
        assert {r.mode for r in runs} == {"test"} and len({r.thread_id for r in runs}) == len(runs)
        for key in SCENARIOS_BY_KEY:
            assert sorted(r.reflection_enabled for r in runs if r.scenario == key) == [False, False, True, True]

    # 준비된 응답·고의 실패는 실행 기록에 표시한다.
    for judgment in result["judgments"]:
        llm = events_of(database, judgment["run_id"], "llm_call")
        assert llm and all(e.detail["injected"] is True for e in llm)
    [rate_limited] = by(result, "gemini_rate_limit", True)[:1]
    assert [e.detail["injection"] for e in events_of(database, rate_limited["run_id"], "llm_call")] == [
        "prepared", "failure"]

    # Gmail 발송 실패 주입 → 자동 재시도 없이 실패 안내 → 다시 승인해 1번만 실제(가짜 Gmail) 발송.
    for judgment in by(result, "gmail_error", False) + by(result, "gmail_error", True):
        assert judgment["approval"] == ["failed_unknown", "sent"] and judgment["completed"]
        sends = events_of(database, judgment["run_id"], "send")
        assert [(e.detail["ok"], e.detail.get("injected")) for e in sends] == [(False, True), (True, None)]
    assert len(gmail.mailbox.called("send")) == 4

    # 실행마다 기록 파일(CONTRACT 8.2절 이름)을 남긴다.
    files = sorted(p.name for p in tmp_path.iterdir())
    assert len(files) == len(result["judgments"])
    assert any("_wrong_tool_refl-off_" in name for name in files)
    assert any("_wrong_tool_refl-on_" in name for name in files)
    lines = [json.loads(line) for line in (tmp_path / files[0]).read_text(encoding="utf-8").splitlines()]
    assert lines[0]["type"] == "run" and lines[0]["mode"] == "test"
    assert any(row.get("detail", {}).get("injected") for row in lines)


def test_results_and_records_hold_no_mail_body(database, access):
    result = runner.run_suite(database, 1, repeat=1, access=access)
    text = json.dumps(result, ensure_ascii=False)
    assert GENERAL_BODY not in text and CLEAN["candidates"][0]["body"] not in text
    assert "500만원" in text     # 사실 비교용 값 조각만 남는다


def test_real_mode_marks_only_injected_calls(database):
    real = FakeLLM([GENERAL, GENERAL])   # '실제 API' 자리에 넣은 대역
    network_once = replace(SCENARIOS_BY_KEY["normal_general"], key="network_once",
                           inject={"DraftOutput": [TimeoutError, CLEAN]})
    result = runner.run_suite(database, 1, scenarios=[network_once], repeat=1, mode="real", real=lambda: real)
    assert len(real.calls) == 2
    for judgment in result["judgments"]:
        assert judgment["completed"] and judgment["llm_calls"] == {"prepared": 1, "failure": 1, "real": 1}
        analysis, draft = events_of(database, judgment["run_id"], "llm_call")
        assert "injected" not in analysis.detail
        assert draft.detail["injected"] is True and draft.detail["injection"] == "mixed"
        [retry] = events_of(database, judgment["run_id"], "retry")
        assert retry.detail["injection"] == "failure"
        assert judgment["call_retries"] == 1 and judgment["retries"] == 1
    assert result["metrics"]["off"]["retries"]["average"] == 1.0


def test_consistency_compares_facts_conditions_and_structure(database):
    two = {"candidates": CLEAN["candidates"]}
    three = {"candidates": CLEAN["candidates"] + [{"label": "짧게", "body": "확인 뒤 연락드리겠습니다."}]}
    varied = replace(SCENARIOS_BY_KEY["normal_general"], key="varied",
                     fake=[{"EmailAnalysis": [GENERAL], "DraftOutput": [two]},
                           {"EmailAnalysis": [GENERAL], "DraftOutput": [three]}])
    result = runner.run_suite(database, 1, scenarios=[varied], repeat=2)
    for label in ("off", "on"):
        score = result["metrics"][label]["consistency"]["by_scenario"]["varied"]
        assert score == {"runs": 2, "facts": 1.0, "conditions": 1.0, "structure": 0.0, "score": round(2 / 3, 4)}


def test_single_run_has_no_consistency_score():
    signature = {"facts": [], "conditions": [], "structure": []}
    summary = consistency([{"scenario": "a", "signature": signature}])
    assert summary == {"score": None, "scenarios_measured": 0, "by_scenario": {"a": {"runs": 1, "score": None}}}


def test_approval_scenario_is_skipped_without_gmail_access(database):
    result = runner.run_suite(database, 1, scenarios=[SCENARIOS_BY_KEY["gmail_error"]], repeat=2)
    assert not result["judgments"] and len(result["skipped"]) == 4
    assert result["metrics"]["on"]["task_completion"]["rate"] is None
    assert "미측정" in render_markdown(result["metrics"])


def test_cli_fake_writes_results(tmp_path, capsys):
    out = tmp_path / "result.json"
    assert runner.main(["--fake", "--repeat", "1", "--scenario", "wrong_tool", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert all(name in printed for name in METRIC_NAMES.values())
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["metrics"]["off"]["task_completion"]["completed"] == 0
    assert saved["metrics"]["on"]["task_completion"]["completed"] == 1


def test_report_defines_criteria_for_every_scenario_before_measurement():
    text = REPORT.read_text(encoding="utf-8")
    for scenario in SCENARIOS:
        assert f"`{scenario.key}`" in text
        assert all(f"`{tool}`" in text for tool in scenario.expect.tools)
    assert all(name in text for name in METRIC_NAMES.values())


# --- 실제 실행 준비: 시험 계정 찾기·승인 발송용 실제 메일 찾기 ------------------------------------------

def gmail_mail(message_id, subject, body, sender="partner@example.invalid"):
    raw = message(message_id, thread_id=f"thread-{message_id}", sender=sender, body=body)
    for header in raw["payload"]["headers"]:
        if header["name"] == "Subject":
            header["value"] = subject
    return raw


def ref(message_id):
    return {"id": message_id, "threadId": f"thread-{message_id}"}


@pytest.fixture
def mailbox(gmail):
    """검색 결과는 최신 순(m5 → m1), 두 페이지. m2는 제목이 다르고 m5는 내가 보낸 메일이다."""
    scenario = SCENARIOS_BY_KEY["gmail_error"]
    body = scenario.body
    gmail.mailbox.raw_messages.update({
        "m1": gmail_mail("m1", scenario.subject, body),
        "m2": gmail_mail("m2", "다른 제목", body),
        "m3": gmail_mail("m3", scenario.subject, body),
        "m4": gmail_mail("m4", scenario.subject, body.replace(" ", "\n  ") + "\n\n-- \n상대방 서명"),
        "m5": gmail_mail("m5", scenario.subject, body, sender="demo@example.invalid"),
    })
    gmail.mailbox.search_pages = {
        None: {"messages": [ref("m5"), ref("m4"), ref("m3")], "nextPageToken": "p2"},
        "p2": {"messages": [ref("m2"), ref("m1")]},
    }
    return gmail.mailbox


def test_gmail_search_picks_unused_matching_mails_oldest_first(database, access, mailbox):
    scenario = SCENARIOS_BY_KEY["gmail_error"]
    with database.session() as session:
        session.add(Run(run_id="old-run", user_id=1, mode="test", message_id="m1", thread_id="thread-m1",
                        reflection_enabled=False, scenario="gmail_error"))
    sources, report = runner.find_gmail_sources(database, access, 1, scenario, limit=2)
    assert sources == [("m3", "thread-m3"), ("m4", "thread-m4")]
    assert report == {"query": runner.DEFAULT_GMAIL_SEARCH, "found": 5, "already_used": 1,
                      "mismatched": 1, "selected": 2, "needed": 2}
    searches = mailbox.called("search")
    assert [call[1]["q"] for call in searches] == [runner.DEFAULT_GMAIL_SEARCH] * 2
    assert [call[1].get("pageToken") for call in searches] == [None, "p2"]

    # 찾은 메일로 실제 실행(실제 Gemini 자리는 대역)을 돌리면 그 메일에 답장하고, 다음 검색에서는 빠진다.
    real = FakeLLM([GENERAL, CLEAN, GENERAL, CLEAN])
    result = runner.run_suite(database, 1, scenarios=[scenario], repeat=1, mode="real", access=access,
                              real=lambda: real, gmail_sources=sources)
    assert [j["completed"] for j in result["judgments"]] == [True, True] and not result["skipped"]
    with database.session() as session:
        used = session.scalars(select(Run.message_id).where(Run.scenario == "gmail_error", Run.run_id != "old-run"))
        assert sorted(used) == ["m3", "m4"]
    sends = mailbox.called("send")
    assert [call[1]["body"]["threadId"] for call in sends] == ["thread-m3", "thread-m4"]
    again, report = runner.find_gmail_sources(database, access, 1, scenario, limit=2)
    assert again == [] and report["already_used"] == 3 and report["mismatched"] == 2


def test_gmail_search_failure_hides_error_text(database, access, gmail):
    gmail.mailbox.search_pages = {}
    with pytest.raises(RuntimeError, match=r"^Gmail 검색 실패 \(KeyError\)$"):
        runner.find_gmail_sources(database, access, 1, SCENARIOS_BY_KEY["gmail_error"], limit=2)


def test_resolve_user_by_email(database):
    assert runner.resolve_user(database, user_email=" Demo@Example.invalid ") == 1
    assert runner.resolve_user(database, user_id=1) == 1
    with pytest.raises(ValueError, match="로그인"):
        runner.resolve_user(database, user_email="nobody@example.invalid")
    with pytest.raises(ValueError):
        runner.resolve_user(database, user_id=99)


def test_cli_real_finds_user_and_gmail_mails(database, access, mailbox, monkeypatch, capsys):
    import app.clients.gmail as gmail_module
    import app.config as config_module
    import app.db.engine as engine_module
    import app.services.auth as auth_module

    monkeypatch.setattr(config_module, "get_settings", lambda: config_module.Settings())
    monkeypatch.setattr(engine_module, "get_database", lambda settings=None: database)
    monkeypatch.setattr(gmail_module, "GoogleClient", lambda settings: access.google)
    monkeypatch.setattr(auth_module, "make_cipher", lambda settings: access.cipher)
    captured = {}

    def fake_suite(database, user_id, **kwargs):
        captured.update(user_id=user_id, **kwargs)
        return {"metrics": runner.compute_metrics([]), "skipped": [], "judgments": []}

    monkeypatch.setattr(runner, "run_suite", fake_suite)
    assert runner.main(["--real", "--user-email", "demo@example.invalid", "--gmail-search",
                        "--scenario", "gmail_error", "--repeat", "2"]) == 0
    assert captured["user_id"] == 1 and captured["mode"] == "real" and captured["access"] is not None
    assert captured["gmail_sources"] == [("m1", "thread-m1"), ("m3", "thread-m3"), ("m4", "thread-m4")]
    assert "3/4통 사용" in capsys.readouterr().out
