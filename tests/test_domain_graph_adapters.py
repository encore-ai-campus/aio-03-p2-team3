"""새 마스터 → 기존 서비스 → 임시 PostgreSQL/가짜 Gmail·Storage 통합 검증."""

from hashlib import sha256
from base64 import urlsafe_b64decode
from email.parser import BytesParser
from email.policy import default as email_policy

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select
import pytest

from app.db.models import TradeArtifact, TradeDocument, TradeProposal
from app.graph.schemas import InputRef, Plan, Task
from app.graph.wiring import make_workflow
from app.llm.client import use_backend
from tests.fakes.llm import FakeLLM
from tests.test_approval import client, fake, add_mail, add_user
from tests.test_domain_graph import decision
from tests.test_pi_api import pi_client, create_pi
from tests.test_pi_domain import pi_input
from tests.test_trade_domain_api import pl_values, ready_document
from tests.test_trade_flow import put_settings
from tests.fakes.storage import FakeStorage
from tests.test_domain_graph import FakeCalendar, QUERY


def engine(client):
    app = client.app
    return make_workflow(database=app.state.database, storage=app.state.storage,
                         access=app.state.google_access, checkpointer=InMemorySaver())


def start(workflow, task):
    return workflow.start(actor_id=1, thread_id="workflow", plan=Plan(tasks=[task]))


def resume(workflow, response):
    return workflow.resume(actor_id=1, thread_id="workflow", response=response)


def test_mail_uses_existing_atomic_claim_and_records_matching_receipt(client):
    actor = add_user(client)
    candidate_id = add_mail(client, actor)[0]
    workflow = engine(client)
    state = workflow.start(actor_id=actor, thread_id="workflow", plan=Plan(tasks=[
        Task(id="mail", domain="mail", operation="send", inputs={"candidate_id": candidate_id}),
    ]))
    assert state["work"]["status"] == "needs_approval"
    assert not client.app.state.google_access.google.mailbox.called("send")
    approval = decision(state)
    result = workflow.resume(actor_id=actor, thread_id="workflow", response=approval)
    assert result["results"]["mail"]["status"] == "completed", result
    assert result["results"]["mail"]["data"]["sent_message_id"]
    assert len(client.app.state.google_access.google.mailbox.called("send")) == 1
    workflow.resume(actor_id=actor, thread_id="workflow", response=approval)
    assert len(client.app.state.google_access.google.mailbox.called("send")) == 1


def test_changed_reply_to_invalidates_mail_approval(client):
    actor = add_user(client)
    candidate_id = add_mail(client, actor)[0]
    workflow = engine(client)
    state = workflow.start(actor_id=actor, thread_id="workflow", plan=Plan(tasks=[
        Task(id="mail", domain="mail", operation="send", inputs={"candidate_id": candidate_id}),
    ]))
    mailbox = client.app.state.google_access.google.mailbox
    mailbox.raw_messages["fake-message"]["payload"]["headers"].append({"name": "Reply-To", "value": "changed@example.invalid"})
    result = workflow.resume(actor_id=actor, thread_id="workflow", response=decision(state))
    assert result["results"]["mail"]["code"] == "candidate_changed"
    assert not mailbox.called("send")


@pytest.mark.parametrize("kind", ["PI", "PO", "CI", "PL"])
def test_all_trade_documents_issue_real_files_through_new_master(pi_client, kind):
    document = create_pi(pi_client) if kind == "PI" else ready_document(pi_client, kind.lower())
    workflow = engine(pi_client)
    state = start(workflow, Task(id="document", domain="documents", operation="issue",
        inputs={"kind": kind, "document_id": document["document_id"], "revision": document["revision"]}))
    assert state["work"]["status"] == "needs_approval", state
    result = resume(workflow, decision(state))
    assert result["results"]["document"]["status"] == "completed", result
    receipt = result["results"]["document"]["data"]
    assert len(receipt["files"]) == 2
    for file in receipt["files"]:
        response = pi_client.get(file["download_url"])
        assert response.status_code == 200
        assert sha256(response.content).hexdigest() == file["content_hash"]
    repeated = resume(workflow, decision(state))
    assert repeated["results"]["document"] == result["results"]["document"]


def test_document_question_resumes_by_revising_same_document(pi_client):
    workflow = engine(pi_client)
    state = start(workflow, Task(id="document", domain="documents", operation="draft",
        inputs={"kind": "PI", "values": pi_input(payment_terms=None).model_dump(mode="json")}))
    assert state["work"]["status"] == "needs_input", state
    document_id = state["work"]["data"]["document_id"]
    result = resume(workflow, {"task_id": "document", "answers": {"values": pi_input().model_dump(mode="json")}})
    assert result["results"]["document"]["status"] == "completed", result
    assert result["results"]["document"]["data"]["document_id"] == document_id
    assert result["results"]["document"]["data"]["revision"] == 2
    with pi_client.app.state.database.session() as session:
        assert session.scalar(select(func.count()).select_from(TradeDocument)) == 1


def test_document_change_after_approval_prevents_issue(pi_client):
    document = create_pi(pi_client)
    workflow = engine(pi_client)
    state = start(workflow, Task(id="document", domain="documents", operation="issue",
        inputs={"kind": "PI", "document_id": document["document_id"]}))
    changed = pi_client.put(f"/api/trade/pi/{document['document_id']}", json={
        "revision": document["revision"], "document": pi_input(document_number="PI-CHANGED").model_dump(mode="json")})
    assert changed.status_code == 200
    result = resume(workflow, decision(state))
    assert result["results"]["document"]["status"] == "failed", result
    with pi_client.app.state.database.session() as session:
        assert session.scalar(select(func.count()).select_from(TradeArtifact)) == 0


def test_cancel_invalidates_saved_document_proposal_without_issuing(pi_client):
    document = create_pi(pi_client)
    workflow = engine(pi_client)
    state = start(workflow, Task(id="document", domain="documents", operation="issue",
        inputs={"kind": "PI", "document_id": document["document_id"]}))
    proposal_id = state["work"]["action"]["payload"]["proposal_id"]
    result = resume(workflow, decision(state, "cancel"))
    assert result["results"]["document"]["status"] == "cancelled"
    with pi_client.app.state.database.session() as session:
        assert session.get(TradeProposal, proposal_id).status == "cancelled"
        assert session.scalar(select(func.count()).select_from(TradeArtifact)) == 0


def test_pl_draft_packing_approval_and_issue_are_separate_bound_actions(pi_client):
    workflow = engine(pi_client)
    plan = Plan(tasks=[
        Task(id="draft", domain="documents", operation="draft", inputs={"kind": "PL", "values": pl_values()}),
        Task(id="packing", domain="documents", operation="approve_packing", inputs={"kind": "PL"},
             depends_on=["draft"], bindings={"document_id": InputRef(task_id="draft", field="document_id"),
                                          "revision": InputRef(task_id="draft", field="revision")}),
        Task(id="issue", domain="documents", operation="issue", inputs={"kind": "PL"},
             depends_on=["packing"], bindings={"document_id": InputRef(task_id="packing", field="document_id"),
                                            "revision": InputRef(task_id="packing", field="revision")}),
    ])
    state = workflow.start(actor_id=1, thread_id="workflow", plan=plan)
    assert state["current"] == "packing" and state["work"]["status"] == "needs_approval", (
        state.get("work", {}).get("data", {}).get("document", {}).get("blocking_issues"))
    state = resume(workflow, decision(state))
    assert state["results"]["packing"]["status"] == "completed", state
    assert state["current"] == "issue" and state["work"]["status"] == "needs_approval", state
    result = resume(workflow, decision(state))
    assert result["results"]["issue"]["status"] == "completed", result


def test_structured_planner_uses_existing_llm_boundary_and_calendar_is_explicitly_unavailable(database):
    workflow = make_workflow(database=database, checkpointer=InMemorySaver())
    plan = Plan(tasks=[Task(id="calendar", domain="calendar", operation="find_slots", inputs=QUERY)])
    with use_backend(FakeLLM([plan.model_dump(mode="json")])):
        result = workflow.start(actor_id=1, thread_id="natural", request="가상 일정의 가능한 시간 조회")
    assert result["results"]["calendar"]["code"] == "calendar_not_connected", result


@pytest.mark.parametrize("corrupt_file", [False, True])
def test_master_binds_issued_files_to_real_mail_and_continues_calendar_query(client, corrupt_file):
    actor = add_user(client)
    candidate_id = add_mail(client, actor)[0]
    storage = FakeStorage()
    put_settings(client.app.state.database, storage)
    calendar = FakeCalendar()
    workflow = make_workflow(database=client.app.state.database, storage=storage,
        access=client.app.state.google_access, calendar=calendar, checkpointer=InMemorySaver())
    plan = Plan(tasks=[
        Task(id="draft", domain="documents", operation="draft", inputs={"kind": "PI", "values": pi_input().model_dump(mode="json")}),
        Task(id="issue", domain="documents", operation="issue", inputs={"kind": "PI"}, depends_on=["draft"],
             bindings={"document_id": InputRef(task_id="draft", field="document_id"),
                       "revision": InputRef(task_id="draft", field="revision")}),
        Task(id="mail", domain="mail", operation="send", inputs={"candidate_id": candidate_id}, depends_on=["issue"],
             bindings={"file_ids": InputRef(task_id="issue", field="file_ids")}),
        Task(id="calendar", domain="calendar", operation="find_slots", inputs=QUERY),
    ])
    state = workflow.start(actor_id=actor, thread_id="workflow", plan=plan)
    assert state["current"] == "issue", state
    state = workflow.resume(actor_id=actor, thread_id="workflow", response=decision(state))
    assert state["current"] == "mail", state
    files = state["work"]["action"]["payload"]["files"]
    assert len(files) == 2 and state["tasks"][2]["inputs"]["file_ids"] == state["results"]["issue"]["data"]["file_ids"]
    if corrupt_file:
        with client.app.state.database.session() as session:
            file = session.get(TradeArtifact, files[0]["id"])
            storage.objects[file.object_key] = b"corrupted-test-file"
    result = workflow.resume(actor_id=actor, thread_id="workflow", response=decision(state))
    calls = client.app.state.google_access.google.mailbox.called("send")
    assert result["results"]["calendar"]["status"] == "completed" and calendar.reads == 1
    if corrupt_file:
        assert result["results"]["mail"]["status"] == "failed" and not calls
        return
    assert all(value["status"] == "completed" for value in result["results"].values()), result
    assert len(calls) == 1
    raw = calls[0][1]["body"]["raw"]
    sent = BytesParser(policy=email_policy).parsebytes(urlsafe_b64decode(raw))
    attachments = list(sent.iter_attachments())
    assert {sha256(part.get_payload(decode=True)).hexdigest() for part in attachments} == {file["content_hash"] for file in files}
