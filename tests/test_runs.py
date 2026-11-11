"""실행 기록 화면·내보내기(계획 14절, R-12). 실제 API 호출 없이 가짜 실행으로 시험한다."""
import json
import re

import pytest
from fastapi.testclient import TestClient
import httpx

from app.config import Settings
from app.db.models import User
from app.graph.build import build_graph
from app.graph.run import start_run
from app.main import create_app
from app.llm import client as llm_client
from app.runlog.export import export_jsonl
from app.runlog.logger import current_event
from app.runlog.mask import Masker
from app.web.deps import current_user_id
from tests.fakes.llm import FakeLLM, openai_error

# 지어낸 값이다(실제 개인정보 아님).
PII = {
    "email": "sender@example.invalid", "other": "buyer@example.invalid",
    "phone": "010-1234-5678", "biz": "123-45-67890", "name": "홍길동",
}


def analyze(state):
    current_event("tool_select", tool="draft_replies", detail={"reason": "일반 문의 메일"})
    return {"intent": "general", "reply_mode": "general", "selected_tool": "draft_replies"}


def draft(state):
    # 기록에 개인정보가 섞이는 최악의 경우를 일부러 만든다.
    current_event("tool_call", tool="draft_replies", detail={
        "body_chars": 20, "from_name": PII["name"], "to": [PII["email"], PII["other"]],
    })
    current_event("retry", tool="draft_replies", detail={"error_kind": "network", "attempt": 1})
    current_event("error", tool="draft_replies", detail={
        "kind": "network", "message": f"{PII['email']} 연락처 {PII['phone']} 사업자 {PII['biz']}",
    })
    current_event("tool_result", tool="draft_replies", detail={
        "ok": True, "error_kind": None, "attempts": 2, "source": "llm",
        "candidates": [{"label": "수락", "body": f"{PII['name']}님 {PII['email']}로 답장드립니다."}],
    })
    return {"candidates": []}


def fake_run(database, email, mode="test", user_id=1):
    return start_run(user_id=user_id, email=email, mode=mode, database=database, scenario="normal-1",
                     reflection_enabled=False,
                     graph=build_graph(node_overrides={"analyze_email": analyze, "draft_replies": draft}))


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'runs.sqlite3'}"))
    with TestClient(app) as test_client:
        with app.state.database.session() as session:
            session.add_all([
                User(id=1, google_sub="fake-sub-1", email="demo@example.invalid"),
                User(id=2, google_sub="fake-sub-2", email="other@example.invalid"),
            ])
        app.dependency_overrides[current_user_id] = lambda: 1
        yield test_client


@pytest.mark.parametrize("code, attempts, end_reason", [
    ("HTTP 503", 3, "failed"), ("HTTP 429", 1, "awaiting_approval"), ("ReadTimeout", 3, "failed"),
])
def test_sdk_failure_codes_reach_run_page_and_export(client, email, monkeypatch, code, attempts, end_reason):
    private = "private-mail-body fake-api-key sender@example.invalid 가상비밀이름 010-1234-5678"
    error = {
        "HTTP 503": openai_error(503, message=private),
        "HTTP 429": openai_error(429, message=private),
        "ReadTimeout": httpx.ReadTimeout(private),
    }[code]
    monkeypatch.setattr(llm_client, "sleep", lambda _: None)
    monkeypatch.setattr(llm_client, "get_backend", lambda: pytest.fail("실제 LLM은 호출하면 안 됩니다"))
    database = client.app.state.database
    with llm_client.use_backend(FakeLLM([error] * attempts)):
        result = start_run(user_id=1, email=email, database=database, reflection_enabled=False)
    assert result["end_reason"] == end_reason and result["call_retries"] == attempts - 1

    run_id = result["run_id"]
    page = client.get(f"/runs/{run_id}")
    exported = client.get(f"/runs/{run_id}/export")
    assert page.status_code == exported.status_code == 200
    assert code in page.text
    rows = [json.loads(line) for line in exported.text.splitlines()]
    failures = [row for row in rows if row.get("event") in {"retry", "llm_call"}]
    assert len(failures) == attempts
    assert all(row["detail"]["error_code"] == code for row in failures)
    for value in private.split():
        assert value not in page.text and value not in exported.text


def test_masker_rules():
    masker = Masker("live")
    masked = masker.value({
        "message": f"{PII['email']}, {PII['other']}, {PII['email'].upper()} / 전화{PII['phone']} / "
                   f"+82-10-1234-5678 / 02-123-4567 / {PII['biz']}",
        "from_name": PII["name"], "contact_name": PII["name"], "body_text": "가" * 412,
        "run_id": "0101234567890abc", "at": "2026-11-10T00:28:30.415674+00:00",
        "fields": ["customer_name", "quantity"],
    })
    assert masked["message"] == "<이메일1>, <이메일2>, <이메일1> / 전화<전화> / <전화> / <전화> / <사업자번호>"
    assert masked["from_name"] == masked["contact_name"] == "<이름1>"
    assert masked["body_text"] == "<본문 412자>"
    assert masked["run_id"] == "0101234567890abc" and masked["at"].startswith("2026-11-10T00:28")
    assert masked["fields"] == ["customer_name", "quantity"]
    # 이름 키에서 모은 이름은 다른 글에 섞여 있어도 가린다.
    rows = [{"detail": {"message": f"{PII['name']} 고객 응답 없음"}}, {"detail": {"from_name": PII["name"]}}]
    learned = Masker("test")
    learned.learn(rows)
    assert learned.value(rows)[0]["detail"]["message"] == "<이름1> 고객 응답 없음"
    # 지어낸 시험 메일은 본문을 남기되 주소·전화 모양은 가린다.
    assert Masker("test").value({"body": f"안녕하세요 {PII['email']}"}) == {"body": "안녕하세요 <이메일1>"}


@pytest.mark.parametrize("mode", ["test", "live"])
def test_export_file_follows_contract_and_masks(database, email, mode):
    email = {**email, "from_addr": PII["email"], "from_name": PII["name"]}
    result = fake_run(database, email, mode=mode)
    filename, content = export_jsonl(database, 1, result["run_id"])
    label = "normal-1" if mode == "test" else "live"
    assert re.fullmatch(rf"\d{{8}}-\d{{4}}_{label}_refl-off_{result['run_id'][:8]}\.jsonl", filename)
    rows = [json.loads(line) for line in content.splitlines()]
    assert rows[0]["type"] == "run" and rows[0]["run_id"] == result["run_id"] and rows[0]["mode"] == mode
    events = rows[1:]
    assert all(row["type"] == "event" for row in events)
    assert [row["seq"] for row in events] == list(range(len(events)))
    assert events[0]["event"] == "run_start" and events[-1]["event"] == "run_end"
    for value in PII.values():
        assert value not in content
    assert "<이메일1>" in content and "<이메일2>" in content and "<이름1>" in content
    assert "<전화>" in content and "<사업자번호>" in content
    body = next(r for r in events if r["event"] == "tool_result")["detail"]["candidates"][0]["body"]
    original = f"{PII['name']}님 {PII['email']}로 답장드립니다."
    assert body == (f"<본문 {len(original)}자>" if mode == "live" else "<이름1>님 <이메일1>로 답장드립니다.")
    # 남의 실행은 내보낼 수 없다.
    assert export_jsonl(database, 2, result["run_id"]) is None


def test_run_screens_show_own_records_in_order(client, email):
    app = client.app
    result = fake_run(app.state.database, email)
    other = fake_run(app.state.database, email, user_id=2)

    listing = client.get("/runs")
    assert listing.status_code == 200 and result["run_id"][:8] in listing.text
    assert other["run_id"][:8] not in listing.text

    page = client.get(f"/runs/{result['run_id']}")
    assert page.status_code == 200
    seqs = [int(s) for s in re.findall(r'data-seq="(\d+)"', page.text)]
    assert seqs == list(range(len(seqs))) and len(seqs) > 10
    order = ["실행 시작", "load_memory", "도구 선택", "일반 문의 메일", "도구 호출",
             "재시도", "오류", "도구 결과", "save_pending", "실행 끝"]
    table = page.text[page.text.index("<tbody>"):]
    positions = [table.index(text) for text in order]
    assert positions == sorted(positions)
    assert "row-warn" in page.text and "ms" in page.text
    for value in PII.values():
        assert value not in page.text

    assert client.get(f"/runs/{other['run_id']}").status_code == 404
    assert client.get(f"/runs/{other['run_id']}/export").status_code == 404

    exported = client.get(f"/runs/{result['run_id']}/export")
    assert exported.status_code == 200
    assert "attachment" in exported.headers["content-disposition"]
    assert f"_normal-1_refl-off_{result['run_id'][:8]}.jsonl" in exported.headers["content-disposition"]
    assert all(value not in exported.text for value in PII.values())


def test_run_screens_require_login(client):
    client.app.dependency_overrides.clear()
    for path in ["/runs", "/runs/anything", "/runs/anything/export"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303 and response.headers["location"] == "/login"
