"""작업현황 API: 소스별 상태 정규화·본인 범위·runlog 마스킹 재사용(계획 17절)."""
from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth.supabase import TokenVerifier
from app.db.agent import AgentConversation
from app.db.models import RunEvent, TradeDocument
from app.main import create_app
from tests.fakes.gmail import FakeGmailGoogle
from tests.test_approval import add_mail
from tests.test_gmail_connect import settings_of
from tests.test_supabase_auth import SUPABASE_URL, FakeJwks


def auth(token):
    return {"Authorization": "Bearer " + token}


def make_client(database_url, jwks):
    return TestClient(create_app(settings_of(database_url), google=FakeGmailGoogle(),
                                  supabase_auth=TokenVerifier(SUPABASE_URL, fetch_jwks=jwks.serve)))


def seed(client, owner):
    add_mail(client, owner, message_id="m1", thread_id="t1", status="awaiting_approval", subject="가상전자 견적")
    add_mail(client, owner, message_id="m2", thread_id="t2", status="ignored", subject="뉴스레터")
    with client.app.state.database.session() as session:
        session.add(RunEvent(run_id="run-m1", seq=1, event="node_end", node="analyze",
                             detail={"from": "sender@example.invalid", "step_status": "ok"}))
        session.add(AgentConversation(id=uuid4().hex, user_id=owner, title="PO 목록 요청", status="needs_input",
                                      view={"messages": [], "results": [], "waiting": None, "error": None}))
        session.add(AgentConversation(id=uuid4().hex, user_id=owner, title="실패한 요청", status="error",
                                      view={"messages": [], "results": [], "waiting": None, "error": None}))
        session.add(TradeDocument(user_id=owner, thread_id="t1", run_id="run-m1", doc_kind="PI",
                                  doc_no="PI-20261118-001", draft={}, status="ready"))
        session.add(TradeDocument(user_id=owner, thread_id="t1", run_id="run-m1", doc_kind="CI",
                                  doc_no="CI-20261118-002", draft={}, status="sent"))


def test_tasks_merge_sources_and_normalize_states(database_url):
    jwks = FakeJwks()
    token = jwks.token()
    with make_client(database_url, jwks) as client:
        owner = client.get("/api/me", headers=auth(token)).json()["user_id"]
        seed(client, owner)
        tasks = client.get("/api/status/tasks", headers=auth(token)).json()["tasks"]
        states = {(task["kind"], task["title"]): task["state"] for task in tasks}
        assert states[("mail", "가상전자 견적")] == "needs_approval"
        assert states[("mail", "뉴스레터")] == "skipped"
        assert states[("chat", "PO 목록 요청")] == "needs_input"
        assert states[("chat", "실패한 요청")] == "attention"
        assert states[("doc", "PI-20261118-001")] == "needs_approval"
        assert states[("doc", "CI-20261118-002")] == "completed"
        mail = next(task for task in tasks if task["kind"] == "mail" and task["title"] == "가상전자 견적")
        assert mail["run_id"] == "run-m1" and mail["sub"] == "sender@example.invalid"
        assert [task["at"] or "" for task in tasks] == sorted((task["at"] or "" for task in tasks), reverse=True)


def test_tasks_show_only_own_rows(database_url):
    jwks = FakeJwks()
    token, outsider = jwks.token(), jwks.token(sub=uuid4())
    with make_client(database_url, jwks) as client:
        owner = client.get("/api/me", headers=auth(token)).json()["user_id"]
        seed(client, owner)
        assert client.get("/api/status/tasks", headers=auth(outsider)).json()["tasks"] == []


def test_run_detail_reuses_masking_and_owner_scope(database_url):
    jwks = FakeJwks()
    token, outsider = jwks.token(), jwks.token(sub=uuid4())
    with make_client(database_url, jwks) as client:
        owner = client.get("/api/me", headers=auth(token)).json()["user_id"]
        seed(client, owner)
        response = client.get("/api/status/runs/run-m1", headers=auth(token))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["counts"]["nodes"] == 1
        assert body["events"][0]["label"] == "노드 끝"
        assert "sender@example.invalid" not in str(body)  # runlog와 같은 마스킹이 그대로 적용된다
        assert client.get("/api/status/runs/run-m1", headers=auth(outsider)).status_code == 404
        assert client.get("/api/status/runs/없는실행", headers=auth(token)).status_code == 404
