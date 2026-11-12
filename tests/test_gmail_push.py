"""계획 7절: 인증·중복·무시·오류 후 이어 읽기·실제 ASGI 응답 시점을 가짜로 시험한다."""

import asyncio
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from threading import Event

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from google.oauth2 import id_token
from googleapiclient.errors import HttpError
import httplib2
import pytest
from sqlalchemy import select

from app.clients.gmail import GoogleClient, TokenExpired, decode_message
from app.config import LIMITS, Settings
from app.db.engine import Database
from app.db.models import GmailWatch, GoogleToken, ProcessedMessage, ReplyCandidate, Run, RunEvent, ThreadMessage, User
from app.graph.build import build_graph
from app.llm import client as llm
from app.main import create_app
from app.services.auth import GoogleAccess, TokenCipher, save_login
from app.services.gmail_push import process_notification
from app.services.watch import register_watch
from tests.fakes.gmail import FakeGmailGoogle, encoded, history_page, message
from tests.fakes.google import fake_login
from tests.fakes.llm import FakeLLM


@pytest.fixture(autouse=True)
def no_real_llm(monkeypatch):
    monkeypatch.setattr(llm, "get_backend", lambda *a: pytest.fail("실제 LLM 호출 금지"))


@pytest.fixture
def settings(database_url):
    return Settings(
        database_url=database_url, token_encryption_key=Fernet.generate_key().decode(),
        session_secret="fake-session-secret", gmail_pubsub_topic="projects/fake/topics/fake",
        pubsub_push_token="fake-push-token",
    )


@pytest.fixture
def fake():
    return FakeGmailGoogle()


def setup_user(access, sub="fake-sub-1", address="demo@example.invalid"):
    user_id = save_login(access, fake_login(sub=sub, email=address))
    register_watch(access, user_id)
    return user_id


@pytest.fixture
def access(database, settings, fake):
    access = GoogleAccess(database, fake, TokenCipher(settings.token_encryption_key), settings.gmail_pubsub_topic)
    setup_user(access)
    return access


@pytest.fixture
def graph():
    return build_graph(node_overrides={
        "analyze_email": lambda state: {"intent": "general", "reply_mode": "general"},
        "draft_replies": lambda state: {"candidates": []},
    })


@pytest.fixture
def client(settings, fake, graph):
    with TestClient(create_app(settings, google=fake)) as client:
        setup_user(client.app.state.google_access)
        client.app.state.graph = graph
        yield client


def rows(database, model):
    with database.session() as session:
        return list(session.scalars(select(model)))


def watch(access, user_id=1):
    with access.database.session() as session:
        return session.get(GmailWatch, user_id)


def push_payload(history_id="1001", address="demo@example.invalid"):
    data = json.dumps({"emailAddress": address, "historyId": history_id}).encode()
    return {"message": {"data": b64encode(data).decode(), "messageId": "fake-pubsub-id"}}


def notify(access, graph, history_id="1001", address="demo@example.invalid"):
    process_notification(access, address, history_id, graph=graph)


def test_fake_push_runs_actual_graph_and_persists_candidates(client, fake):
    database = client.app.state.database
    client.app.state.graph = build_graph()
    with database.session() as session:
        session.scalar(select(User)).reflection_enabled = True
    backend = FakeLLM([
        {"intent": "general", "reason": "일반 문의"},
        {"candidates": [{"label": "안내", "body": "가상 답장 1"}, {"label": "확인", "body": "가상 답장 2"}]},
    ])
    with llm.use_backend(backend):
        response = client.post("/gmail/push?token=fake-push-token", json=push_payload())
    assert response.status_code == 204 and response.content == b""
    [processed], [thread], [run] = (rows(database, model) for model in (ProcessedMessage, ThreadMessage, Run))
    assert processed.status == "awaiting_approval" and processed.run_id == run.run_id
    assert processed.history_id == "1001" and processed.received_at.utcoffset().total_seconds() == 0
    assert (thread.gmail_message_id, thread.thread_id, thread.direction) == ("fake-message", "fake-thread", "in")
    assert (run.user_id, run.mode, run.message_id, run.thread_id, run.reflection_enabled) == (
        processed.user_id, "live", "fake-message", "fake-thread", True,
    )
    candidates = rows(database, ReplyCandidate)
    assert len(candidates) == 2 and all(c.run_id == run.run_id and c.status == "pending" for c in candidates)
    assert any(e.event == "run_end" for e in rows(database, RunEvent))
    assert watch(client.app.state.google_access, run.user_id).history_id == "1001"
    assert fake.mailbox.calls[0][1]["historyTypes"] == ["messageAdded"]
    assert all(call[2] == LIMITS["GMAIL_MAX_RETRIES"] for call in fake.mailbox.calls)


def test_repeated_notification_and_same_message_in_later_history_run_once(access, fake, graph):
    notify(access, graph)
    notify(access, graph)
    fake.mailbox.pages[None] = history_page("fake-message", history_id="1002")
    notify(access, graph, "1002")
    for model in (ProcessedMessage, ThreadMessage, Run):
        assert len(rows(access.database, model)) == 1
    assert len([c for c in fake.mailbox.calls if c[0] == "message"]) == 1
    assert watch(access).history_id == "1002"


def test_overlapping_notifications_are_serialized(access, graph, database_url):
    # 서로 다른 엔진·연결에서도 DB 잠금으로 중복 처리가 직렬화된다.
    database = Database(database_url)
    database.create_tables()
    access = replace(access, database=database, google=FakeGmailGoogle())
    setup_user(access)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(notify, access, graph) for _ in range(2)]
            for future in futures:
                future.result(timeout=5)
        assert len(rows(database, Run)) == len(rows(database, ThreadMessage)) == 1
        assert watch(access).history_id == "1001"
    finally:
        database.close()


@pytest.mark.parametrize("sender,labels,reason", [
    ("Demo <DEMO@example.invalid>", ["INBOX"], "self"),
    ("alias@example.invalid", ["SENT", "INBOX"], "self"),
    ("no-reply@example.invalid", ["INBOX"], "no_reply"),
    ("No_Reply@example.invalid", ["INBOX"], "no_reply"),
    ("noreply@example.invalid", ["INBOX"], "no_reply"),
    ("do-not-reply@example.invalid", ["INBOX"], "no_reply"),
    ("sender@example.invalid", ["INBOX", "CATEGORY_PROMOTIONS"], "promotion"),
    ("sender@example.invalid", ["INBOX", "CATEGORY_SOCIAL"], "social"),
    ("sender@example.invalid", ["SENT"], "self"),
    ("sender@example.invalid", [], "not_inbox"),
    ("sender@example.invalid", ["INBOX", "SPAM"], "not_inbox"),
])
def test_ignored_mail_never_starts_graph(access, fake, sender, labels, reason):
    fake.mailbox.raw_messages["fake-message"] = message(sender=sender, labels=labels)
    notify(access, None)
    [processed] = rows(access.database, ProcessedMessage)
    assert (processed.status, processed.skip_reason, processed.run_id) == ("ignored", reason, None)
    assert rows(access.database, Run) == rows(access.database, ThreadMessage) == []
    assert watch(access).history_id == "1001"


def test_paginated_history_deduplicates_messages_and_keeps_thread(access, fake, graph):
    fake.mailbox.pages = {
        None: history_page("fake-message", next_page="page-2"),
        "page-2": history_page("fake-message", "second", history_id="1003"),
    }
    fake.mailbox.raw_messages["second"] = message("second")
    notify(access, graph, "1003")
    assert len(rows(access.database, Run)) == 2
    assert {r.thread_id for r in rows(access.database, ThreadMessage)} == {"fake-thread"}
    assert [c[1]["pageToken"] for c in fake.mailbox.calls if c[0] == "history"] == [None, "page-2"]
    assert watch(access).history_id == "1003"


@pytest.mark.parametrize("failure_at", ["history", "message", "page-2", "attachment"])
def test_gmail_failure_keeps_cursor_and_next_notification_resumes(access, fake, graph, failure_at, caplog):
    mailbox = fake.mailbox
    error = HttpError(httplib2.Response({"status": "503"}), b'{"error":{"message":"private-body-marker"}}')
    mailbox.pages[None] = history_page("fake-message", "second", history_id="1003")
    mailbox.raw_messages["second"] = message("second")
    if failure_at == "history":
        mailbox.pages[None] = error
    elif failure_at == "message":
        mailbox.raw_messages["second"] = error
    elif failure_at == "page-2":
        mailbox.pages[None] = history_page("fake-message", next_page="page-2")
        mailbox.pages["page-2"] = error
    else:
        mailbox.raw_messages["second"]["payload"]["body"] = {"attachmentId": "large-body"}
        mailbox.attachment_data[("second", "large-body")] = error
    notify(access, graph, "1003")
    failed_watch = watch(access)
    assert failed_watch.history_id == "1000" and failed_watch.status == "error"
    assert failed_watch.last_error == "gmail_push: google_unavailable"
    assert "private-body-marker" not in caplog.text
    assert len(rows(access.database, Run)) == (0 if failure_at == "history" else 1)
    mailbox.pages = {None: history_page("fake-message", "second", history_id="1004")}
    mailbox.raw_messages["second"] = message("second")
    notify(access, graph, "1004")
    assert len(rows(access.database, Run)) == len(rows(access.database, ThreadMessage)) == 2
    assert watch(access).history_id == "1004" and watch(access).last_error is None


def test_history_labels_changed_do_not_count_as_new_messages(access, fake, graph):
    fake.mailbox.pages[None] = {"historyId": "1004", "history": [
        {"id": "1004", "messages": [{"id": "fake-message"}],
         "labelsAdded": [{"message": {"id": "fake-message"}, "labelIds": ["INBOX"]}]},
    ]}
    notify(access, graph, "1004")
    assert rows(access.database, Run) == [] and watch(access).history_id == "1004"


def test_unknown_or_stopped_user_and_old_notifications_do_not_read_gmail(access, fake, graph):
    notify(access, graph, address="unknown@example.invalid")
    notify(access, graph, "999")
    with access.database.session() as session:
        session.get(GmailWatch, 1).status = "stopped"
    notify(access, graph)
    assert fake.called("gmail") == [] and watch(access).history_id == "1000"


def test_same_gmail_message_id_is_scoped_to_user(access, graph):
    other = setup_user(access, sub="fake-sub-2", address="other@example.invalid")
    # FakeGoogle의 두 번째 watch 기준점은 1001이다.
    notify(access, graph)
    notify(access, graph, "1002", "other@example.invalid")
    assert {r.user_id for r in rows(access.database, ProcessedMessage)} == {1, other}
    assert len(rows(access.database, ThreadMessage)) == 2


def test_due_watch_renews_without_skipping_cursor_and_refreshes_token(access, fake, graph):
    with access.database.session() as session:
        session.get(GmailWatch, 1).last_renewed_at -= timedelta(hours=25)
        session.get(GoogleToken, 1).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    notify(access, graph)
    assert fake.refreshed == 1
    assert fake.called("gmail") == [("gmail", "fake-access-refreshed-1")]
    assert fake.mailbox.calls[0][1]["startHistoryId"] == "1000"
    assert watch(access).history_id == "1001"


def test_expired_refresh_token_preserves_reauthentication_state(access, fake, graph):
    with access.database.session() as session:
        session.get(GoogleToken, 1).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    fake.refresh_error = TokenExpired("invalid_grant")
    notify(access, graph)
    notify(access, graph, "1002")
    assert watch(access).last_error == "token_expired" and watch(access).history_id == "1000"
    assert rows(access.database, Run) == [] and len(fake.called("refresh")) == 1


@pytest.mark.parametrize("end_reason,status,notice", [
    ("followup_question", "awaiting_approval", None),
    ("ignored", "ignored", None), ("failed", "error", None),
    ("awaiting_approval", "awaiting_approval", "rate_limit"),
])
def test_graph_result_updates_processed_state(access, end_reason, status, notice):
    class Graph:
        def invoke(self, state, config):
            return {**state, "end_reason": end_reason, "notice": notice}
    notify(access, Graph())
    [processed] = rows(access.database, ProcessedMessage)
    [run] = rows(access.database, Run)
    assert (processed.status, processed.notice, processed.run_id) == (status, notice, run.run_id)
    assert run.end_reason == end_reason and run.ended_at is not None


def test_graph_exception_is_recorded_and_later_mail_still_runs(access, fake, graph):
    class BrokenGraph:
        def invoke(self, state, config):
            raise RuntimeError("private-body-marker")
    notify(access, BrokenGraph())
    assert rows(access.database, ProcessedMessage)[0].status == "error"
    assert rows(access.database, Run)[0].end_reason == "failed"
    fake.mailbox.pages[None] = history_page("second", history_id="1002")
    fake.mailbox.raw_messages["second"] = message("second")
    notify(access, graph, "1002")
    assert [r.status for r in rows(access.database, ProcessedMessage)] == ["error", "awaiting_approval"]


@pytest.mark.parametrize("query", ["", "?token=wrong"])
def test_invalid_push_auth_returns_403_without_run(client, fake, query):
    response = client.post("/gmail/push" + query, json=push_payload())
    assert response.status_code == 403
    assert rows(client.app.state.database, Run) == fake.called("gmail") == []


def test_missing_push_auth_configuration_is_closed(client):
    client.app.state.settings = replace(client.app.state.settings, pubsub_push_token="")
    assert client.post("/gmail/push?token=fake-push-token", json=push_payload()).status_code == 403


def test_oidc_takes_precedence_and_rejects_wrong_service_identity(client, fake):
    client.app.state.settings = replace(client.app.state.settings,
        pubsub_push_audience="https://app.example.invalid/gmail/push",
        pubsub_push_service_account="push@example.invalid",
    )
    assert client.post("/gmail/push?token=fake-push-token", json=push_payload()).status_code == 403
    headers = {"Authorization": "Bearer fake-oidc-token"}
    assert client.post("/gmail/push", headers=headers, json=push_payload()).status_code == 204
    assert fake.called("verify") == [(
        "verify", "fake-oidc-token", "https://app.example.invalid/gmail/push", "push@example.invalid",
    )]
    fake.verify_error = ValueError("private-token-marker")
    assert client.post("/gmail/push", headers=headers, json=push_payload()).status_code == 403
    client.app.state.settings = replace(client.app.state.settings, pubsub_push_service_account="")
    assert client.post("/gmail/push?token=fake-push-token", json=push_payload()).status_code == 403


@pytest.mark.parametrize("data", [None, [], {}, {"emailAddress": "no-address", "historyId": "1001"},
    {"emailAddress": "demo@example.invalid", "historyId": True},
    {"emailAddress": "demo@example.invalid", "historyId": "0"},
    {"emailAddress": "demo@example.invalid", "historyId": "1.2"},
    {"emailAddress": "demo@example.invalid", "historyId": "１２３"},
])
def test_malformed_notification_is_400_without_work(client, fake, data):
    payload = {"message": {"data": encoded(json.dumps(data))}}
    assert client.post("/gmail/push?token=fake-push-token", json=payload).status_code == 400
    assert fake.called("gmail") == []


@pytest.mark.parametrize("payload", [{}, {"message": {}}, {"message": {"data": "%%%"}},
                                     {"message": {"data": 1}}])
def test_invalid_envelope_is_400(client, payload):
    assert client.post("/gmail/push?token=fake-push-token", json=payload).status_code == 400


def test_asgi_response_finishes_while_graph_is_still_blocked(client):
    entered, release, completed, sent = Event(), Event(), Event(), Event()
    messages = []

    class SlowGraph:
        def invoke(self, state, config):
            entered.set()
            assert release.wait(5), "시험 그래프 해제 시간 초과"
            completed.set()
            return {**state, "end_reason": "awaiting_approval"}

    client.app.state.graph = SlowGraph()
    body = json.dumps(push_payload()).encode()

    async def invoke():
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)
            if message["type"] == "http.response.body" and not message.get("more_body"):
                assert not completed.is_set()
                sent.set()

        await client.app({
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "POST", "scheme": "http", "path": "/gmail/push", "raw_path": b"/gmail/push",
            "query_string": b"token=fake-push-token", "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 12345), "server": ("testserver", 80), "root_path": "",
        }, receive, send)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, invoke())
        try:
            assert sent.wait(5) and entered.wait(5)
            assert not completed.is_set() and not future.done()
            assert messages[0]["status"] == 204
            assert messages[-1] == {"type": "http.response.body", "body": b""}
        finally:
            release.set()
        future.result(timeout=5)
    assert completed.is_set()


def test_mime_decoding_prefers_plain_and_skips_attachments():
    raw = message(sender="=?utf-8?b?7YWM7Iqk7Yq4?= <sender@example.invalid>")
    raw["payload"]["mimeType"] = "multipart/mixed"
    raw["payload"].pop("body")
    raw["payload"]["parts"] = [
        {"mimeType": "multipart/alternative", "parts": [
            {"mimeType": "text/html", "body": {"data": encoded("<p>중복 HTML</p>")}},
            {"mimeType": "text/plain", "body": {"data": encoded("가상 본문")}},
        ]},
        {"mimeType": "text/plain", "filename": "attachment.txt", "body": {"data": encoded("제외할 첨부")}},
    ]
    decoded = decode_message(raw, "demo@example.invalid")
    assert decoded["body_text"] == "가상 본문" and decoded["from_name"] == "테스트"
    assert decoded["rfc_message_id"] == "<fake-message@example.invalid>"


def test_html_only_and_large_text_body_are_read_as_text():
    raw = message()
    raw["payload"]["mimeType"] = "text/html"
    raw["payload"]["body"] = {"attachmentId": "large-body"}
    decoded = decode_message(raw, "demo@example.invalid", lambda value: encoded(
        "<style>숨김</style><p>가상 &amp; 본문<br>둘째 줄</p><script>제외</script>"))
    assert decoded["body_text"] == "가상 & 본문\n둘째 줄"


@pytest.mark.parametrize("claims,valid", [
    ({"email": "push@example.invalid", "email_verified": True}, True),
    ({"email": "wrong@example.invalid", "email_verified": True}, False),
    ({"email": "push@example.invalid", "email_verified": False}, False),
    ({"email": "push@example.invalid", "email_verified": "true"}, False),
])
def test_google_oidc_validates_verified_service_email(settings, monkeypatch, claims, valid):
    def verify(token, request, audience):
        assert token == "fake-token" and audience == "fake-audience" and callable(request)
        return claims
    monkeypatch.setattr(id_token, "verify_oauth2_token", verify)
    google = GoogleClient(settings)
    if valid:
        google.verify_push_token("fake-token", "fake-audience", "push@example.invalid")
    else:
        with pytest.raises(ValueError):
            google.verify_push_token("fake-token", "fake-audience", "push@example.invalid")


def test_oidc_public_keys_are_cached_and_refetched_after_five_minutes(monkeypatch):
    from google.auth.transport import requests
    from app.clients import gmail

    calls = []
    now = [3000]
    response = object()

    class Request:
        def __call__(self, url, **kwargs):
            calls.append((url, kwargs))
            return response

    monkeypatch.setattr(requests, "Request", Request)
    monkeypatch.setattr(gmail, "monotonic", lambda: now[0])
    gmail._certificate_response.cache_clear()
    try:
        for _ in range(2):
            assert gmail._certificate_request("https://certs.example.invalid", method="GET") is response
        assert len(calls) == 1
        now[0] += 300
        assert gmail._certificate_request("https://certs.example.invalid", method="GET") is response
        assert len(calls) == 2
    finally:
        gmail._certificate_response.cache_clear()
