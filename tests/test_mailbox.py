"""새 메일함: 제외 판정·원문 보존·Bearer 소유권·명시적 발송. 실제 API 없음."""
import json
from types import SimpleNamespace

import httpx
import pytest
from openai import OpenAI, APITimeoutError

from app.db.mailbox import MailStore
from app.db.models import ProcessedMessage, Quote, ReplyCandidate, Run
from app.llm import mail_gate
from app.services.gmail_push import process_notification
from app.services.mail_processing import resume_pending
from tests.fakes.gmail import FakeGmailGoogle, message
from tests.test_approval import add_mail
from tests.test_gmail_connect import make_client, bearer, start_connect, complete, me
from tests.test_gmail_push import access, fake, graph, settings, rows, notify, watch  # noqa: F401
from tests.test_supabase_auth import FakeJwks


def add_quote(client, owner, candidate_ids, *, message_id="fake-message", thread_id="fake-thread"):
    from tests.test_quote import draft
    value = draft()
    with client.app.state.database.session() as session:
        quote = Quote(user_id=owner, thread_id=thread_id, run_id=f"run-{message_id}",
                      quote_no=value["quote_no"], draft=value, status="needs_price")
        session.add(quote); session.flush()
        for candidate_id in candidate_ids:
            row = session.get(ReplyCandidate, candidate_id)
            row.kind, row.quote_id = "quote", quote.id
        return quote.id


@pytest.mark.parametrize("choice,confidence,excluded", [("exclude", .99, True), ("exclude", .5, False), ("keep", .99, False)])
def test_native_decisions_adapter(isolated_mail_decisions, choice, confidence, excluded):
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "fake-decision", "object": "decision", "model": "gpt-6-luna",
                   "answers": [{"type": "choice", "name": "mail_exclusion", "choice": choice,
                                "confidence": confidence, "probabilities": []}]})
    def client(**kwargs):
        return OpenAI(**kwargs, http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    result = isolated_mail_decisions(SimpleNamespace(read=lambda: "fake-key"), {"subject": "가상 문의"}, {}, client_factory=client)
    assert result.exclude is excluded
    assert requests[0]["model"] == mail_gate.MODEL
    assert len(requests[0]["questions"]) == 1


def test_excluded_mail_preserves_original_and_never_enters_graph(access, fake, monkeypatch):
    monkeypatch.setattr(mail_gate, "classify_email", lambda *a: mail_gate.GateResult(True, .99))
    notify(access, None)
    [row] = rows(access.database, ProcessedMessage)
    assert row.status == "ignored" and row.triage["phase"] == "excluded" and row.run_id is None
    assert not rows(access.database, Run)
    store = MailStore(access.database)
    assert store.thread(1, "fake-thread")["messages"][0]["body"]
    assert watch(access).history_id == "1001"


@pytest.mark.parametrize("sender,labels", [("no-reply@example.invalid", ["INBOX"]),
    ("sender@example.invalid", ["INBOX", "CATEGORY_PROMOTIONS"]),
    ("sender@example.invalid", ["INBOX", "CATEGORY_SOCIAL"])])
def test_automatic_sender_and_category_can_be_company_work(access, fake, graph, sender, labels):
    fake.mailbox.raw_messages["fake-message"] = message(sender=sender, labels=labels)
    notify(access, graph)
    assert len(rows(access.database, Run)) == 1


@pytest.mark.parametrize("error", [httpx.ReadTimeout("fake-timeout"),
    APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/decisions"))])
def test_gate_error_does_not_block_history_and_manual_retry_uses_graph(access, fake, graph, monkeypatch, error):
    from app.services.mailbox import process_manually
    def fail(*args):
        raise error
    monkeypatch.setattr(mail_gate, "classify_email", fail)
    notify(access, graph)
    store = MailStore(access.database)
    row = store.get(1, "fake-message")
    assert row["status"] == "needs_review" and row["email"]["body_text"]
    assert not rows(access.database, Run) and watch(access).history_id == "1001"
    process_manually(access, store, 1, row["id"], graph=graph)
    process_manually(access, store, 1, row["id"], graph=graph)
    assert len(rows(access.database, Run)) == 1


def test_disconnect_while_classifying_does_not_enter_graph(access, monkeypatch, graph):
    from app.services.watch import stop_watch
    def classify(*args):
        stop_watch(access, 1)
        return mail_gate.GateResult(False, .99)
    monkeypatch.setattr(mail_gate, "classify_email", classify)
    notify(access, graph)
    assert not rows(access.database, Run)
    assert MailStore(access.database).get(1, "fake-message")["status"] == "needs_review"


def test_local_worker_decisions_is_held_without_server_key_fallback(access, settings, graph, monkeypatch, isolated_mail_decisions):
    from dataclasses import replace
    from app.db.models import User
    with access.database.session() as session:
        session.get(User, 1).ai_execution_mode = "local_worker"
    monkeypatch.setattr(mail_gate, "classify_email", isolated_mail_decisions)
    access = replace(access, settings=settings)
    notify(access, graph)
    row = MailStore(access.database).get(1, "fake-message")
    assert row["status"] == "needs_review" and row["notice"] == "local_worker_key_forbidden"
    assert not rows(access.database, Run)


@pytest.mark.parametrize("phase,expected", [("pending", "awaiting_approval"), ("graph_started", "needs_review")])
def test_restart_resumes_pending_but_does_not_replay_started_graph(access, fake, graph, phase, expected):
    from app.clients.gmail import decode_message
    from app.services.gmail_push import _claim_message
    email = decode_message(fake.mailbox.raw_messages["fake-message"], "demo@example.invalid")
    assert _claim_message(access, 1, email, "1001", None)
    store = MailStore(access.database)
    store.mark(1, "fake-message", "processing", {"phase": phase})
    resume_pending(access, store, graph=graph)
    assert store.get(1, "fake-message")["status"] == expected
    assert len(rows(access.database, Run)) == (1 if phase == "pending" else 0)


def test_restart_reuses_saved_candidates_without_another_graph(mailbox_client):
    client, _, owner, candidates, _, _ = mailbox_client
    store = MailStore(client.app.state.database)
    store.mark(owner, "fake-message", "processing", {"phase": "graph_started"})
    resume_pending(client.app.state.google_access, store, graph=client.app.state.graph)
    assert store.get(owner, "fake-message")["status"] == "awaiting_approval"
    assert [c["id"] for c in store.thread(owner, "fake-thread")["candidates"]] == candidates
    assert len(rows(client.app.state.database, Run)) == 1


@pytest.fixture
def mailbox_client(database_url, graph):
    jwks, google = FakeJwks(), FakeGmailGoogle()
    with make_client(database_url, jwks, google) as client:
        client.app.state.graph = graph
        token = jwks.token()
        owner = me(client, token)["user_id"]
        complete(client, start_connect(client, token))
        candidates = add_mail(client, owner)
        yield client, token, owner, candidates, google, jwks


def test_mailbox_api_reads_original_and_sends_selected_candidate_once(mailbox_client):
    client, token, owner, candidates, google, _ = mailbox_client
    headers = bearer(token)
    listing = client.get("/api/mail/threads", headers=headers)
    assert listing.status_code == 200 and listing.json()["items"][0]["thread_id"] == "fake-thread"
    # 상태 탭 건수: 스레드별 최신 처리 상태만 센다.
    assert listing.json()["status_counts"] == {"awaiting_approval": 1}
    assert "no-store" in listing.headers["cache-control"]
    detail = client.get("/api/mail/threads/fake-thread", headers=headers).json()
    assert detail["messages"][0]["body"] and len(detail["candidates"]) == 2
    preview = client.get(f"/api/mail/candidates/{candidates[0]}/preview", headers=headers)
    assert preview.status_code == 200 and preview.json()["to_addrs"] == ["sender@example.invalid"]
    for _ in range(2):
        result = client.post(f"/api/mail/candidates/{candidates[0]}/send", headers=headers, json={})
        assert result.json()["outcome"] in {"sent", "already_sent"}
    assert len(google.mailbox.called("send")) == 1


def test_mailbox_other_user_and_invalid_bearer_cannot_read_or_send(mailbox_client):
    client, _, _, candidates, google, jwks = mailbox_client
    other = bearer(jwks.token())
    assert client.get("/api/mail/threads", headers=other).json()["items"] == []
    assert client.get("/api/mail/threads/fake-thread", headers=other).status_code == 404
    assert client.post(f"/api/mail/candidates/{candidates[0]}/send", headers=other, json={}).status_code == 404
    assert client.post("/api/mail/messages/1/process", headers=other).status_code == 404
    assert client.get("/api/mail/threads", headers=bearer("invalid")).status_code == 401
    assert not google.mailbox.called("send")


def test_mailbox_rejects_injected_recipient_and_filters_search(mailbox_client):
    client, token, _, candidates, google, _ = mailbox_client
    headers = bearer(token)
    assert client.get("/api/mail/threads?q=가상", headers=headers).json()["items"]
    assert client.get("/api/mail/threads?q=%25", headers=headers).json()["items"] == []
    result = client.post(f"/api/mail/candidates/{candidates[0]}/send", headers=headers,
                         json={"to_addrs": ["untrusted@example.invalid"]})
    assert result.status_code == 422 and not google.mailbox.called("send")


@pytest.mark.parametrize("price", ["50", str(2**60 + 1)])
def test_mailbox_quote_price_completion_pdf_and_selected_send(mailbox_client, price):
    client, token, owner, candidates, google, jwks = mailbox_client
    quote_id = add_quote(client, owner, candidates)
    url = f"/api/mail/quotes/{quote_id}"
    headers = bearer(token)
    assert client.get(url + "/preview.pdf", headers=bearer(jwks.token())).status_code == 404
    assert client.post(url + "/prices", headers=bearer(jwks.token()), json={"prices": {"2": "50"}}).status_code == 404
    blocked = client.post(f"/api/mail/candidates/{candidates[0]}/send", headers=headers, json={})
    assert blocked.json()["outcome"] == "needs_price" and not google.mailbox.called("send")
    for values in ({}, {"0": "50"}, {"2": "-1"}, {"2": "1.5"}, {"2": "50", "bad": "5"}):
        assert client.post(url + "/prices", headers=headers, json={"prices": values}).status_code == 400
    assert client.post(url + "/prices", headers=headers, json={"prices": {"2": price}}).json() == {"status": "ready"}
    assert client.post(url + "/prices", headers=headers, json={"prices": {"2": "51"}}).status_code == 409
    detail = client.get("/api/mail/threads/fake-thread", headers=headers).json()
    value = detail["candidates"][0]["document"]["draft"]
    assert value["lines"][2]["unit_price"] == price
    if price == "50":
        assert value["total"] == "502"
    pdf = client.get(url + "/preview.pdf", headers=headers)
    assert pdf.content.startswith(b"%PDF") and "no-store" in pdf.headers["cache-control"]
    result = client.post(f"/api/mail/candidates/{candidates[0]}/send", headers=headers, json={})
    assert result.json()["outcome"] == "sent" and len(google.mailbox.called("send")) == 1
