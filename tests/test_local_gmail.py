"""실제 .env·로컬 앱 수명·Google SDK 대역·OpenAI 모의 HTTP로 수집 경계를 검증한다."""

import asyncio
import json
import os
from dataclasses import replace
from datetime import timedelta
from threading import Event
from pathlib import Path
import re
import socket
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from googleapiclient.errors import HttpError
import httplib2
import httpx
import pytest

from app.clients.gmail import GoogleClient, GoogleUnavailable, TokenExpired
from app.config import get_settings
from app.db.local_gmail import SqlMailboxStore
from app.db.models import GmailWatch, GoogleToken, ProcessedMessage, ReplyCandidate, Run, RunEvent, User, UserOpenAIKey
from app.main import create_app
from app.services.auth import missing_login_settings, save_login, utcnow
from app.services.gmail_push import process_notification
from app.services.local_gmail import LOCAL_TOPIC, LocalGmailCollector
from app.services.watch import register_watch, renew_watch_if_due, stop_watch
from tests.fakes.gmail import FakeGmailGoogle, history_page, message
from tests.fakes.google import fake_login
from tests.test_auth import sign_in
from tests.test_gmail_push import rows, watch
from tests.test_local_openai import clean_environment, listener
from tests.test_openai_keys import sdk


def env_file(tmp_path, database_url):
    path = tmp_path / ".env"
    path.write_text("\n".join([
        "AI_RUNTIME=local", "OPENAI_API_KEY=fake-local-private-key",
        f"DATABASE_URL={database_url}", "SESSION_SECRET=fake-local-session",
        f"TOKEN_ENCRYPTION_KEY={Fernet.generate_key().decode()}",
        "GOOGLE_OAUTH_CLIENT_ID=fake-client", "GOOGLE_OAUTH_CLIENT_SECRET=fake-secret",
        "GOOGLE_OAUTH_REDIRECT_URI=http://127.0.0.1:8000/auth/google/callback",
    ]))
    return path


@pytest.fixture
def local(tmp_path, database_url, monkeypatch, sdk):
    settings = get_settings(str(env_file(tmp_path, database_url)))
    fake = FakeGmailGoogle()
    started = Event()
    original = LocalGmailCollector.poll_once

    def first_tick(collector):
        try:
            return original(collector)
        finally:
            started.set()

    monkeypatch.setattr(LocalGmailCollector, "poll_once", first_tick)
    with listener(), TestClient(create_app(settings, google=fake), base_url="http://127.0.0.1") as client:
        assert started.wait(5)  # 로그인 전 시작 주기를 끝내 테스트와 실제 수집이 경합하지 않게 한다.
        assert sign_in(client).headers["location"] == "/inbox"
        yield client, fake, client.app.state.google_access


def poll(local):
    local[0].app.state.local_gmail.poll_once()


def http_error(status):
    return HttpError(httplib2.Response({"status": status}), b'{"error":{"message":"fake-private-data"}}')


def test_login_without_pubsub_starts_at_current_history_and_never_watches(local, sdk):
    client, fake, access = local
    assert missing_login_settings(access.settings) == []
    assert "GMAIL_PUBSUB_TOPIC" in missing_login_settings(replace(access.settings, ai_runtime="server"))
    assert (watch(access).topic, watch(access).history_id, watch(access).status) == (LOCAL_TOPIC, "1000", "active")
    assert fake.called("profile") == [("profile", "fake-access-1")]
    assert not fake.mailbox.called("history") and not rows(access.database, Run) and sdk == []
    assert "로컬 새 메일 수집 켜짐" in client.get("/inbox").text
    assert renew_watch_if_due(access, 1, utcnow() + timedelta(days=8)) is False
    assert not fake.called("watch") and not fake.called("stop")


def test_collection_uses_env_key_and_only_explicit_approval_sends_once(local, sdk):
    client, fake, access = local
    poll(local)
    [processed] = rows(access.database, ProcessedMessage)
    candidates = rows(access.database, ReplyCandidate)
    assert processed.status == "awaiting_approval" and len(candidates) == 2
    assert len(sdk) == 2 and all(auth == "Bearer fake-local-private-key" for auth, _ in sdk)
    assert not fake.mailbox.called("send")
    for candidate in [candidates[0], candidates[0], candidates[1]]:
        assert client.post(f"/candidates/{candidate.id}/approve", follow_redirects=False).status_code == 303
    [sent] = fake.mailbox.called("send")
    assert sent[1]["body"]["threadId"] == "fake-thread" and sent[2] == 0
    assert rows(access.database, ProcessedMessage)[0].status == "sent"
    assert not rows(access.database, UserOpenAIKey)
    assert "fake-local-private-key" not in repr([row.detail for row in rows(access.database, RunEvent)])
    assert not fake.called("watch") and not fake.called("stop")


def test_repeated_history_and_all_pages_do_not_duplicate(local, sdk):
    _, fake, access = local
    fake.mailbox.pages = {
        None: history_page("fake-message", history_id="1002", next_page="page2"),
        "page2": history_page("fake-message", "second", history_id="1002"),
    }
    fake.mailbox.raw_messages["second"] = message("second", "thread2")
    poll(local)
    poll(local)
    assert len(rows(access.database, Run)) == 2 and len(sdk) == 4
    assert len(fake.mailbox.called("message")) == 2 and watch(access).history_id == "1002"
    calls = fake.mailbox.called("history")
    assert [c[1]["pageToken"] for c in calls] == [None, "page2", None, "page2"]
    assert [c[1]["startHistoryId"] for c in calls] == ["1000", "1000", "1002", "1002"]


@pytest.mark.parametrize("failure", ["page", "message"])
def test_failed_page_or_message_keeps_cursor_then_resumes(local, sdk, failure):
    _, fake, access = local
    fake.mailbox.raw_messages["second"] = message("second", "thread2")
    if failure == "page":
        fake.mailbox.pages = {None: history_page("fake-message", next_page="page2"), "page2": http_error(503)}
    else:
        fake.mailbox.pages = {None: history_page("fake-message", "second", history_id="1002")}
        fake.mailbox.raw_messages["second"] = http_error(503)
    poll(local)
    assert watch(access).history_id == "1000" and watch(access).last_error == "local_poll: google_unavailable"
    assert len(rows(access.database, Run)) == 1
    fake.mailbox.pages = {None: history_page("fake-message", "second", history_id="1002")}
    fake.mailbox.raw_messages["second"] = message("second", "thread2")
    poll(local)
    assert watch(access).history_id == "1002" and watch(access).status == "active"
    assert len(rows(access.database, Run)) == 2 and len(sdk) == 4


def test_expired_history_stops_until_explicit_reconnect_at_current_position(local):
    client, fake, access = local
    fake.mailbox.pages[None] = http_error(404)
    poll(local)
    assert watch(access).last_error == "history_expired" and watch(access).history_id == "1000"
    before = len(fake.mailbox.calls)
    poll(local)
    assert len(fake.mailbox.calls) == before
    page = client.get("/inbox")
    assert "Gmail 기록 조회 기간이 만료" in page.text and "다시 로그인" in page.text
    assert not rows(access.database, Run)
    assert sign_in(client).status_code == 303
    assert watch(access).history_id == "1001" and watch(access).last_error is None
    fake.mailbox.pages[None] = {"historyId": "1001"}
    poll(local)
    assert not rows(access.database, Run) and not fake.mailbox.called("search")
    assert not fake.called("watch") and not fake.called("stop")


@pytest.mark.parametrize("failure", ["refresh", "401", "403"])
def test_revoked_or_expired_connection_stops_and_does_not_retry(local, failure):
    client, fake, access = local
    if failure == "refresh":
        with access.database.session() as session:
            session.get(GoogleToken, 1).expires_at = utcnow() - timedelta(seconds=1)
        fake.refresh_error = TokenExpired("fake-private-data")
    else:
        fake.mailbox.pages[None] = http_error(int(failure))
    poll(local)
    assert watch(access).last_error == "token_expired"
    [token] = rows(access.database, GoogleToken)
    assert token.refresh_token_enc is None and token.access_token_enc is None
    calls = len(fake.calls), len(fake.mailbox.calls)
    poll(local)
    assert calls == (len(fake.calls), len(fake.mailbox.calls))
    assert "다시 로그인" in client.get("/inbox").text


def test_normal_access_token_refresh_continues_collection(local, sdk):
    _, fake, access = local
    with access.database.session() as session:
        session.get(GoogleToken, 1).expires_at = utcnow() - timedelta(seconds=1)
    poll(local)
    assert len(fake.called("refresh")) == 1 and len(sdk) == 2
    assert watch(access).history_id == "1001"


@pytest.mark.parametrize("reason", ["rateLimitExceeded", "userRateLimitExceeded"])
def test_gmail_403_quota_error_keeps_token_and_resumes(local, reason):
    _, fake, access = local
    fake.mailbox.pages[None] = HttpError(httplib2.Response({"status": 403}), json.dumps({
        "error": {"errors": [{"reason": reason}], "message": "fake-private-data"},
    }).encode())
    poll(local)
    assert watch(access).last_error == "local_poll: google_unavailable" and watch(access).history_id == "1000"
    assert rows(access.database, GoogleToken)[0].refresh_token_enc is not None
    fake.mailbox.pages[None] = history_page("fake-message")
    poll(local)
    assert watch(access).status == "active" and watch(access).history_id == "1001"


def test_logout_stops_without_google_stop_and_relogin_skips_logged_out_mail(local):
    client, fake, access = local
    client.post("/logout")
    before = len(fake.calls), len(fake.mailbox.calls)
    poll(local)
    assert watch(access).status == "stopped" and before == (len(fake.calls), len(fake.mailbox.calls))
    assert sign_in(client).status_code == 303
    assert watch(access).history_id == "1001"
    assert not fake.called("stop") and not fake.called("watch")


def test_cancel_reconnection_stops_local_collection(local):
    client, fake, access = local
    response = client.get("/auth/google/start", follow_redirects=False)
    state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
    client.get("/auth/google/callback", params={"state": state, "error": "access_denied"}, follow_redirects=False)
    poll(local)
    assert watch(access).status == "stopped" and not fake.mailbox.called("history")


@pytest.mark.parametrize("stop_at", ["page", "message"])
def test_logout_during_read_does_not_start_more_runs_or_revive_cursor(local, monkeypatch, stop_at):
    _, fake, access = local
    method = "list_history" if stop_at == "page" else "get_message"
    original = getattr(fake, method)

    def stopped(*args, **kwargs):
        result = original(*args, **kwargs)
        stop_watch(access, 1)
        return result

    monkeypatch.setattr(fake, method, stopped)
    poll(local)
    assert watch(access).status == "stopped" and watch(access).history_id == "1000"
    assert not rows(access.database, Run) and not rows(access.database, ProcessedMessage)


@pytest.mark.parametrize("first_fails", [False, True])
def test_connected_users_are_polled_separately_with_same_message_id(local, sdk, monkeypatch, first_fails):
    from tests.fakes.gmail import Mailbox
    client, fake, access = local
    other_id = save_login(access, fake_login(sub="fake-other", email="other@example.invalid", access_token="fake-access-2"))
    register_watch(access, other_id)
    other = Mailbox()
    other.pages[None] = history_page("fake-message", history_id="2000")
    first = fake.mailbox
    if first_fails:
        first.pages[None] = http_error(503)
    monkeypatch.setattr(fake, "gmail", lambda token: other if token == "fake-access-2" else first)
    with access.database.session() as session:
        session.get(User, 1).last_login_at = None
        session.get(User, other_id).last_login_at = None
    client.cookies.clear()  # 브라우저 세션 없이 저장된 연결로 수집한다.
    process_notification(access, "other@example.invalid", "3000")
    assert not rows(access.database, Run)  # Pub/Sub는 로컬 작업을 시작하지 않는다.
    poll(local)
    expected = {other_id} if first_fails else {1, other_id}
    assert {r.user_id for r in rows(access.database, Run)} == expected
    assert {r.user_id for r in rows(access.database, ProcessedMessage)} == expected
    assert {r.user_id for r in rows(access.database, ReplyCandidate)} == expected
    assert watch(access, other_id).history_id == "2000"
    assert watch(access).history_id == ("1000" if first_fails else "1001")
    assert len(sdk) == len(expected) * 2 and all(auth == "Bearer fake-local-private-key" for auth, _ in sdk)
    LocalGmailCollector(access, SqlMailboxStore(access.database)).poll_once()  # 재시작·중복 조회
    assert len(rows(access.database, Run)) == len(expected)
    assert not fake.called("watch") and not fake.called("stop")


@pytest.mark.parametrize("owner", ["", "fake-other"])
def test_owner_configuration_does_not_change_collection(local, owner, monkeypatch):
    _, _, access = local
    monkeypatch.setenv("LOCAL_OWNER_GOOGLE_SUB", owner)
    collector = LocalGmailCollector(access, SqlMailboxStore(access.database))
    collector.poll_once()
    assert len(rows(access.database, Run)) == 1


@pytest.mark.parametrize("sender,labels,reason", [
    ("demo@example.invalid", ["INBOX"], "self"),
    ("no-reply@example.invalid", ["INBOX"], "no_reply"),
    ("sender@example.invalid", ["INBOX", "CATEGORY_PROMOTIONS"], "promotion"),
    ("sender@example.invalid", ["INBOX", "CATEGORY_SOCIAL"], "social"),
    ("sender@example.invalid", [], "not_inbox"),
])
def test_shared_filters_skip_mail_without_ai(local, sdk, sender, labels, reason):
    _, fake, access = local
    fake.mailbox.raw_messages["fake-message"] = message(sender=sender, labels=labels)
    poll(local)
    [processed] = rows(access.database, ProcessedMessage)
    assert processed.status == "ignored" and processed.skip_reason == reason and sdk == []


def test_failed_initial_profile_read_retries_without_watch(local, monkeypatch):
    _, fake, access = local
    original = fake.get_history_id
    monkeypatch.setattr(fake, "get_history_id", lambda token: (_ for _ in ()).throw(GoogleUnavailable()))
    register_watch(access, 1)
    assert watch(access).history_id is None and watch(access).last_error == "local_connect: google_unavailable"
    monkeypatch.setattr(fake, "get_history_id", original)
    poll(local)
    assert watch(access).history_id == "1001" and not rows(access.database, Run)
    assert not fake.called("watch")


def test_profile_response_cannot_reactivate_logged_out_collection(local, monkeypatch):
    _, fake, access = local

    def profile(token):
        stop_watch(access, 1)
        return "9999"

    monkeypatch.setattr(fake, "get_history_id", profile)
    register_watch(access, 1)
    assert watch(access).status == "stopped" and watch(access).history_id is None


def test_process_stop_wakes_idle_loop_and_prevents_more_reads(local):
    client, fake, access = local
    collector = client.app.state.local_gmail
    collector.stop()
    before = len(fake.calls), len(fake.mailbox.calls)
    collector.poll_once()
    asyncio.run(collector.run())
    assert before == (len(fake.calls), len(fake.mailbox.calls))


def test_new_collector_resumes_persisted_cursor_after_process_restart(local, sdk):
    _, fake, access = local
    poll(local)
    fake.mailbox.pages[None] = history_page("fake-message", "second", history_id="1002")
    fake.mailbox.raw_messages["second"] = message("second", "second-thread")
    LocalGmailCollector(access, SqlMailboxStore(access.database)).poll_once()
    assert fake.mailbox.called("history")[-1][1]["startHistoryId"] == "1001"
    assert watch(access).history_id == "1002" and len(sdk) == 4
    assert len(rows(access.database, Run)) == 2


def test_server_mode_keeps_pubsub_login_watch_and_stop_without_collector(tmp_path, database_url):
    settings = replace(get_settings(str(env_file(tmp_path, database_url))), ai_runtime="server",
                       gmail_pubsub_topic="projects/fake/topics/unchanged")
    fake = FakeGmailGoogle()
    with TestClient(create_app(settings, google=fake)) as client:
        assert client.app.state.local_gmail is None
        assert sign_in(client).status_code == 303
        assert fake.called("watch")[0][2] == "projects/fake/topics/unchanged"
        assert "새 메일 알림 켜짐" in client.get("/inbox").text
        client.post("/logout")
        assert len(fake.called("stop")) == 1 and not fake.called("profile")


def test_real_google_profile_request_reads_position_without_watch(local):
    _, _, access = local
    calls = []

    def execute(**kwargs):
        calls.append(kwargs)
        return {"historyId": "12345"}

    def profile(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(execute=execute)

    google = GoogleClient(access.settings)
    google.gmail = lambda token: SimpleNamespace(users=lambda: SimpleNamespace(getProfile=profile))
    assert google.get_history_id("fake-access") == "12345"
    assert calls == [{"userId": "me"}, {"num_retries": 2}]


def test_actual_local_launcher_collects_while_browser_idle_then_sends_once(tmp_path, database_url):
    path = env_file(tmp_path, database_url)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (tmp_path / "server.log").open("w+") as logfile:
        process = subprocess.Popen(
            [sys.executable, "-m", "tests.fakes.local_server", "--env", str(path), "--port", str(port)],
            cwd=Path(__file__).resolve().parents[1], stdout=logfile, stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5) as client:
                deadline = time.monotonic() + 15
                while True:
                    try:
                        if client.get("/healthz").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    assert process.poll() is None and time.monotonic() < deadline
                    time.sleep(0.05)
                assert "이 PC에서 본인 Gmail" in client.get("/login").text
                assert client.get("/healthz", headers={"Host": "public.example.invalid"}).status_code == 400
                start = client.get("/auth/google/start")
                state = parse_qs(urlsplit(start.headers["location"]).query)["state"][0]
                assert client.get("/auth/google/callback", params={"state": state, "code": "fake-code"}).status_code == 303
                # 상태 확인 경로는 업무/수집을 시작하지 않는다. 백그라운드 주기만으로 후보가 생겨야 한다.
                deadline = time.monotonic() + 15
                while (result := client.get("/test/state").json())["candidates"] < 2:
                    assert time.monotonic() < deadline
                    time.sleep(0.05)
                assert result["local_key_only"] and result["sends"] == 0
                thread = client.get("/threads/fake-thread")
                candidate = re.search(r'/candidates/(\d+)/approve', thread.text)[1]
                for _ in range(2):
                    assert client.post(f"/candidates/{candidate}/approve").status_code == 303
                assert client.get("/test/state").json()["sends"] == 1
                client.post("/logout")
                before = client.get("/test/state").json()
                time.sleep(0.15)
                after = client.get("/test/state").json()
                assert before == after and after["watches"] == after["stops"] == 0
            process.terminate()
            # Uvicorn은 정상 lifespan 종료 뒤 원래 SIGTERM을 다시 발생시킬 수 있다.
            return_code = process.wait(timeout=10)
            if os.name == "nt":
                assert return_code == 1
            else:
                assert return_code in {0, -signal.SIGTERM}
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            logfile.seek(0)
            logs = logfile.read()
            assert "fake-local-private-key" not in logs and "fake-refresh-1" not in logs
            if os.name != "nt":
                assert "Application shutdown complete" in logs


def test_sql_store_selects_only_connected_local_retryable_users(local):
    _, _, access = local
    store = SqlMailboxStore(access.database)
    cases = [
        ('no_token', 'active', None, LOCAL_TOPIC),
        ('empty_token', 'active', None, LOCAL_TOPIC),
        ('no_watch', 'active', None, LOCAL_TOPIC),
        ('stopped', 'stopped', None, LOCAL_TOPIC),
        ('expired_token', 'error', 'token_expired', LOCAL_TOPIC),
        ('expired_history', 'error', 'history_expired', LOCAL_TOPIC),
        ('public', 'active', None, 'projects/fake/topics/server'),
        ('unknown_status', 'unknown', None, LOCAL_TOPIC),
        ('retryable', 'error', 'local_poll: google_unavailable', LOCAL_TOPIC),
        ('initial_cursor', 'error', 'local_connect', LOCAL_TOPIC),
    ]
    included = [1]
    with access.database.session() as session:
        for index, (name, status, error, topic) in enumerate(cases, 2):
            session.add(User(id=index, email=f'{name}@example.invalid'))
            session.flush()
            if name != 'no_token':
                session.add(GoogleToken(user_id=index, refresh_token_enc='' if name == 'empty_token' else 'fake-ciphertext'))
            if name != 'no_watch':
                session.add(GmailWatch(user_id=index, topic=topic, status=status, last_error=error,
                                       history_id=None if name == 'initial_cursor' else '1000', last_renewed_at=utcnow()))
            if name in {'retryable', 'initial_cursor'}:
                included.append(index)
    assert [m.id for m in store.list()] == included
    for index in range(1, len(cases) + 2):
        assert (store.current(index) is not None) == (index in included)


@pytest.mark.parametrize('change', ['disconnect', 'stop', 'reconnect', 'public', 'terminal'])
def test_sql_store_rejects_old_generation_or_ineligible_results(local, change):
    _, _, access = local
    store = SqlMailboxStore(access.database)
    old = store.current(1)
    with access.database.session() as session:
        current = session.get(GmailWatch, 1)
        if change == 'disconnect': session.delete(session.get(GoogleToken, 1))
        if change == 'stop': current.status = 'stopped'
        if change == 'reconnect': current.last_renewed_at = utcnow() + timedelta(seconds=1)
        if change == 'public': current.topic = 'projects/fake/topics/server'
        if change == 'terminal': current.status, current.last_error = 'error', 'history_expired'
    assert not store.advance(old, '99999')
    assert not store.fail(old, 'local_poll: fake')
    assert watch(access).history_id == old.cursor


@pytest.mark.parametrize('change', ['disconnect', 'reconnect', 'process_stop'])
def test_connection_change_during_page_prevents_message_reads_and_late_cursor(local, monkeypatch, change):
    client, fake, access = local
    original = fake.list_history
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        if change == 'disconnect':
            with access.database.session() as session:
                session.delete(session.get(GoogleToken, 1))
        elif change == 'reconnect':
            with access.database.session() as session:
                watch_row = session.get(GmailWatch, 1)
                watch_row.last_renewed_at = utcnow() + timedelta(seconds=1)
                watch_row.history_id = '8000'
        else:
            client.app.state.local_gmail.stop()
        return result
    monkeypatch.setattr(fake, 'list_history', changed)
    poll(local)
    assert not fake.mailbox.called('message') and not rows(access.database, Run)
    assert watch(access).history_id == ('8000' if change == 'reconnect' else '1000')


def test_stop_between_separate_body_attachments_prevents_next_read(local, monkeypatch):
    from tests.fakes.gmail import encoded
    _, fake, access = local
    raw = fake.mailbox.raw_messages['fake-message']
    raw['payload']['mimeType'] = 'multipart/alternative'
    raw['payload']['body'] = {}
    raw['payload']['parts'] = [dict(mimeType='text/plain', body={'attachmentId': value}) for value in ['a', 'b']]
    read = []
    def attachment(*args):
        read.append(args[-1])
        stop_watch(access, 1)
        return encoded('가상 본문')
    monkeypatch.setattr(fake, 'get_attachment', attachment)
    poll(local)
    assert read == ['a'] and not rows(access.database, Run)
    assert watch(access).status == 'stopped' and watch(access).history_id == '1000'


def test_collector_continues_after_one_store_read_fails():
    from app.config import Settings
    from app.services.local_gmail import Mailbox
    class DummyDatabase: pass
    access = SimpleNamespace(local_mode=True, settings=Settings(ai_runtime='local'), database=DummyDatabase())
    mailboxes = [Mailbox(1, 'a@example.invalid', '1000', utcnow()), Mailbox(2, 'b@example.invalid', '1000', utcnow())]
    class Store:
        def list(self): return mailboxes
        def current(self, user_id):
            if user_id == 1: raise RuntimeError('fake-private-data')
            return mailboxes[1]
    collector = LocalGmailCollector(access, Store())
    seen = []
    collector._poll_user = lambda mailbox: seen.append(mailbox.id)
    with listener(): collector.poll_once()
    assert seen == [2]
