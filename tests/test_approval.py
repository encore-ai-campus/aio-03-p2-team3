"""계획 9절: 가짜 Gmail로 승인·발송 경로와 받은 메일·스레드 화면을 시험한다(실제 Gmail 호출 없음)."""

from base64 import b64encode, urlsafe_b64decode
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from email import message_from_bytes
from email.policy import default as email_policy
import json
from threading import Event
import time

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from googleapiclient.errors import HttpError
import httplib2
from itsdangerous import TimestampSigner
import pytest
from sqlalchemy import select

from app.config import LIMITS, Settings
from app.db.models import (
    Approval, CounterpartyHistory, DealTerms, ProcessedMessage, ReplyCandidate, Run, RunEvent,
    ThreadMessage, UserPreference, utcnow,
)
from app.graph.run import start_run
from app.llm.client import use_backend
from app.main import create_app
from app.services.approval import send_approved_candidate
from app.services.auth import save_login
from app.services.watch import register_watch
from app.tools.registry import TOOLS
from app.web.routes.candidates import APPROVAL_NOTICES
from tests.fakes.gmail import FakeGmailGoogle, message
from tests.fakes.google import fake_login
from tests.fakes.llm import FakeLLM

SECRET = "fake-session-secret"


@pytest.fixture
def fake():
    return FakeGmailGoogle()


@pytest.fixture
def client(fake, database_url):
    settings = Settings(
        database_url=database_url, token_encryption_key=Fernet.generate_key().decode(),
        session_secret=SECRET, gmail_pubsub_topic="projects/fake/topics/fake",
    )
    with TestClient(create_app(settings, google=fake)) as client:
        yield client


def add_user(client, sub="fake-sub-1", address="demo@example.invalid") -> int:
    access = client.app.state.google_access
    user_id = save_login(access, fake_login(sub=sub, email=address))
    register_watch(access, user_id)
    return user_id


def log_in(client, user_id):
    payload = b64encode(json.dumps({"user_id": user_id}).encode())
    client.cookies.set("gq_session", TimestampSigner(SECRET).sign(payload).decode())


def add_mail(client, user_id, message_id="fake-message", thread_id="fake-thread", *, kinds=("general", "general"),
             status="awaiting_approval", notice=None, subject="가상 문의") -> list[int]:
    """그래프가 끝난 뒤의 모습(처리한 메일·스레드 메일·실행·후보)을 만든다. 후보 id 목록을 돌려준다."""
    run_id = f"run-{message_id}"
    with client.app.state.database.session() as session:
        session.add(Run(run_id=run_id, user_id=user_id, mode="live", message_id=message_id,
                        thread_id=thread_id, reflection_enabled=False))
        session.add(ProcessedMessage(user_id=user_id, gmail_message_id=message_id, thread_id=thread_id,
                                     status=status, notice=notice, run_id=run_id, received_at=utcnow()))
        session.add(ThreadMessage(user_id=user_id, thread_id=thread_id, gmail_message_id=message_id,
                                  direction="in", from_addr="sender@example.invalid", to_addrs=["demo@example.invalid"],
                                  subject=subject, body_text="테스트용 가상 문의입니다.", sent_at=utcnow()))
        rows = [ReplyCandidate(
            user_id=user_id, run_id=run_id, thread_id=thread_id, source_message_id=message_id, kind=kind,
            label=f"후보 {n}", subject=f"Re: {subject}", body=f"가상 답장 본문 {n}", notice=notice,
            needs_review=notice is not None,
        ) for n, kind in enumerate(kinds, 1)]
        session.add_all(rows)
        session.flush()
        return [row.id for row in rows]


def rows(client, model):
    with client.app.state.database.session() as session:
        return list(session.scalars(select(model).order_by(model.id)))


def candidate(client, candidate_id):
    with client.app.state.database.session() as session:
        return session.get(ReplyCandidate, candidate_id)


def approve(client, candidate_id):
    response = client.post(f"/candidates/{candidate_id}/approve", follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"]


def sent_mail(fake, index=-1):
    _, params, num_retries = fake.mailbox.called("send")[index]
    raw = params["body"]["raw"]
    return params, num_retries, message_from_bytes(urlsafe_b64decode(raw + "=" * (-len(raw) % 4)), policy=email_policy)


@pytest.fixture
def mailbox(client, fake):
    user_id = add_user(client)
    log_in(client, user_id)
    fake.mailbox.raw_messages["fake-message"] = message()
    ids = add_mail(client, user_id, kinds=("general", "general", "quote"))
    return user_id, ids


def test_approval_sends_once_to_same_thread_and_records(client, fake, mailbox):
    user_id, (first, second, quote) = mailbox
    # 승인 전에는 화면을 열어도 아무것도 보내지 않는다
    page = client.get("/threads/fake-thread")
    assert page.status_code == 200
    assert "후보 1" in page.text and "후보 2" in page.text
    assert f'action="/candidates/{first}/approve"' in page.text
    assert f'action="/candidates/{quote}/approve"' not in page.text  # 견적서 후보는 견적서 화면에서만 승인
    client.get("/inbox")
    client.get("/inbox/list")
    assert fake.mailbox.called("send") == [] and rows(client, Approval) == []

    assert approve(client, first) == "/threads/fake-thread?notice=sent"
    params, num_retries, mail = sent_mail(fake)
    assert len(fake.mailbox.called("send")) == 1
    assert params["body"]["threadId"] == "fake-thread" and num_retries == 0  # 발송은 자동 재시도 없음
    assert mail["To"] == "sender@example.invalid" and mail["Subject"] == "Re: 가상 문의"
    assert mail["In-Reply-To"] == "<fake-message@example.invalid>"
    assert mail["References"] == "<fake-message@example.invalid>"
    assert mail.get_content().strip() == "가상 답장 본문 1"

    [approval] = rows(client, Approval)
    assert (approval.user_id, approval.candidate_id, approval.send_status) == (user_id, first, "sent")
    assert approval.sent_message_id == "fake-sent-1" and approval.approved_at is not None
    # 같은 원본 메일의 나머지 대기 후보는 종류와 관계없이 보내지 않음으로 바꾼다
    assert [candidate(client, i).status for i in (first, second, quote)] == ["sent", "superseded", "superseded"]
    assert rows(client, ProcessedMessage)[0].status == "sent"
    events = [(e.event, e.tool, e.detail) for e in rows(client, RunEvent) if e.run_id == "run-fake-message"]
    assert events == [
        ("approval", "send_email", {"candidate_id": first, "quote_id": None, "trade_doc_id": None, "ok": True, "error_kind": None}),
        ("send", "send_email", {"candidate_id": first, "quote_id": None, "trade_doc_id": None, "ok": True, "error_kind": None}),
    ]
    page = client.get("/threads/fake-thread?notice=sent")
    assert APPROVAL_NOTICES["sent"][0] in page.text and "다른 답장을 보냄" in page.text
    assert "approve" not in page.text.split("후보 3")[0]  # 보낸 뒤에는 일반 후보 승인 버튼이 없다
    assert "보냄" in client.get("/inbox/list").text


def test_double_click_and_other_candidates_send_only_once(client, fake, mailbox):
    _, (first, second, quote) = mailbox
    assert approve(client, first).endswith("notice=sent")
    assert approve(client, first).endswith("notice=already_sent")
    assert approve(client, second).endswith("notice=already_replied")
    assert approve(client, quote).endswith("notice=quote_only")
    assert len(fake.mailbox.called("send")) == 1 and len(rows(client, Approval)) == 1


def test_concurrent_approvals_send_once(client, fake, mailbox):
    user_id, (first, second, _) = mailbox
    entered, release = Event(), Event()
    original = fake.send_message

    def slow_send(gmail, raw, thread_id):
        entered.set()
        release.wait(5)
        return original(gmail, raw, thread_id)

    fake.send_message = slow_send
    access = client.app.state.google_access
    with ThreadPoolExecutor(3) as pool:
        first_click = pool.submit(send_approved_candidate, user_id, first, access=access)
        assert entered.wait(5)
        # 보내는 중에 같은 후보를 다시 누르거나 다른 후보를 눌러도 보내지 않는다
        again = pool.submit(send_approved_candidate, user_id, first, access=access)
        other = pool.submit(send_approved_candidate, user_id, second, access=access)
        time.sleep(0.1)
        release.set()
        outcomes = [first_click.result().outcome, again.result().outcome, other.result().outcome]
    assert outcomes == ["sent", "already_sent", "already_replied"]
    assert len(fake.mailbox.called("send")) == 1


def test_in_progress_candidate_is_not_sent_again(client, fake, mailbox):
    _, (first, _, _) = mailbox
    with client.app.state.database.session() as session:
        session.get(ReplyCandidate, first).status = "approved"  # 다른 요청이 보내는 중
    assert approve(client, first).endswith("notice=already_sent")
    assert fake.mailbox.called("send") == []


def test_other_users_candidates_and_threads_are_denied(client, fake, mailbox):
    other = add_user(client, sub="fake-sub-2", address="other@example.invalid")
    [theirs] = add_mail(client, other, "other-message", "other-thread", kinds=("general",), subject="다른 사용자 메일")
    assert client.post(f"/candidates/{theirs}/approve", follow_redirects=False).status_code == 404
    assert client.get("/threads/other-thread").status_code == 404
    assert "다른 사용자 메일" not in client.get("/inbox/list").text
    assert fake.mailbox.called("send") == [] and rows(client, Approval) == []
    assert candidate(client, theirs).status == "pending"

    client.cookies.clear()  # 로그인하지 않으면 로그인 화면으로
    denied = client.post(f"/candidates/{theirs}/approve", follow_redirects=False)
    assert denied.status_code == 303 and denied.headers["location"] == "/login"


@pytest.mark.parametrize("error, outcome", [
    (TimeoutError(), "failed_unknown"),
    (HttpError(httplib2.Response({"status": "500"}), b'{"error":{"message":"private-body-marker"}}'), "failed_unknown"),
    (HttpError(httplib2.Response({"status": "401"}), b""), "failed_auth"),
    (HttpError(httplib2.Response({"status": "400"}), b""), "failed"),
    (HttpError(httplib2.Response({"status": "429"}), b""), "failed"),
])
def test_send_failure_shows_notice_and_same_candidate_can_be_approved_again(client, fake, mailbox, error, outcome):
    _, (first, second, _) = mailbox
    fake.mailbox.send_results.append(error)
    assert approve(client, first) == f"/threads/fake-thread?notice={outcome}"
    assert len(fake.mailbox.called("send")) == 1  # 실패해도 자동으로 다시 보내지 않는다
    [approval] = rows(client, Approval)
    assert approval.send_status == "failed" and approval.sent_message_id is None
    assert "private-body-marker" not in (approval.error or "")
    assert [candidate(client, i).status for i in (first, second)] == ["send_failed", "pending"]
    assert rows(client, ProcessedMessage)[0].status == "awaiting_approval"
    page = client.get(f"/threads/fake-thread?notice={outcome}")
    assert APPROVAL_NOTICES[outcome][0] in page.text and "보내기 실패" in page.text
    assert f'action="/candidates/{first}/approve"' in page.text  # 같은 후보로 다시 승인
    sends = [e.detail for e in rows(client, RunEvent) if e.event == "send"]
    assert sends[-1]["ok"] is False

    assert approve(client, first).endswith("notice=sent")
    [approval] = rows(client, Approval)  # 승인 기록은 후보마다 하나(같은 줄을 다시 씀)
    assert approval.send_status == "sent" and approval.error is None
    assert [candidate(client, i).status for i in (first, second)] == ["sent", "superseded"]
    assert len(fake.mailbox.called("send")) == 2


def test_failure_before_sending_is_not_ambiguous(client, fake, mailbox):
    _, (first, _, _) = mailbox
    # 원본 머리글을 못 읽으면 보내기 전에 멈춘다: 보내지 않은 것이 확실하므로 '보냈을 수도' 안내를 쓰지 않는다
    fake.mailbox.raw_messages["fake-message"] = HttpError(httplib2.Response({"status": "503"}), b"")
    assert approve(client, first).endswith("notice=failed")
    assert fake.mailbox.called("send") == []
    assert candidate(client, first).status == "send_failed"
    _, params, _ = fake.mailbox.called("message")[-1]
    assert params["format"] == "metadata"


def test_inbox_lists_own_mail_with_status_and_polls(client, fake):
    user_id = add_user(client)
    other = add_user(client, sub="fake-sub-2", address="other@example.invalid")
    add_mail(client, user_id, "m-wait", "t-wait", subject="견적 문의")
    add_mail(client, user_id, "m-limit", "t-limit", subject="한도 메일", notice="rate_limit", kinds=("general",))
    add_mail(client, user_id, "m-proc", "t-proc", status="processing", kinds=(), subject="처리 중 메일")
    add_mail(client, user_id, "m-err", "t-err", status="error", kinds=(), subject="실패 메일")
    add_mail(client, user_id, "m-skip", "t-skip", status="ignored", kinds=(), subject="광고 메일")
    add_mail(client, other, "m-other", "t-other", subject="남의 메일")

    unauth = client.get("/inbox/list", headers={"HX-Request": "true"}, follow_redirects=False)
    assert unauth.status_code == 303 and unauth.headers["HX-Redirect"] == "/login"
    log_in(client, user_id)
    page = client.get("/inbox")
    assert 'hx-get="/inbox/list"' in page.text
    assert f'hx-trigger="every {LIMITS["INBOX_POLL_SECONDS"]}s"' in page.text
    fragment = client.get("/inbox/list").text
    assert "<html" not in fragment
    for text in ["견적 문의", "승인 대기", "후보 2개", "한도 메일", "한도 초과", "처리 중 메일", "처리 중",
                 "실패 메일", "오류", 'href="/threads/t-wait"']:
        assert text in fragment
    assert "광고 메일" not in fragment and "남의 메일" not in fragment
    assert fake.mailbox.called("send") == []

    limited = client.get("/threads/t-limit").text  # 한도 초과 대체 후보에는 안내 띠
    assert "한도 초과로 AI 후보를 만들지 못했습니다" in limited and "확인 필요" in limited


@pytest.mark.parametrize("status", ["processing", "error", "awaiting_approval"])
def test_thread_shows_processing_error_or_pending_candidates(client, fake, status):
    user_id = add_user(client)
    log_in(client, user_id)
    ids = add_mail(client, user_id, status=status, kinds=("general", "general") if status == "awaiting_approval" else ())

    page = client.get("/threads/fake-thread")
    assert page.status_code == 200
    assert "테스트용 가상 문의입니다." in page.text
    assert ("답장 후보를 만드는 중입니다" in page.text) == (status == "processing")
    assert ("후보를 만들지 못했습니다" in page.text) == (status == "error")
    assert ('href="/runs/run-fake-message"' in page.text) == (status == "error")
    assert ('hx-get="/threads/fake-thread"' in page.text) == (status == "processing")
    if status == "processing":
        assert f'hx-trigger="every {LIMITS["INBOX_POLL_SECONDS"]}s"' in page.text
        assert 'hx-select="#thread-content"' in page.text and 'hx-swap="outerHTML"' in page.text
    if status == "awaiting_approval":
        assert "승인 대기" in page.text and "후보 1" in page.text and "후보 2" in page.text
        assert all(f'action="/candidates/{candidate_id}/approve"' in page.text for candidate_id in ids)
    assert fake.mailbox.called("send") == [] and rows(client, Approval) == []
    assert rows(client, ProcessedMessage)[0].status == status


@pytest.mark.parametrize("finished", ["awaiting_approval", "error"])
def test_thread_refresh_replaces_processing_and_stops_polling(client, fake, finished):
    user_id = add_user(client)
    log_in(client, user_id)
    add_mail(client, user_id, status="processing", kinds=())
    assert 'hx-get="/threads/fake-thread"' in client.get("/threads/fake-thread").text

    with client.app.state.database.session() as session:
        session.scalar(select(ProcessedMessage)).status = finished
        if finished == "awaiting_approval":
            session.add(ReplyCandidate(user_id=user_id, run_id="run-fake-message", thread_id="fake-thread",
                                       source_message_id="fake-message", kind="general", label="새 답장 후보",
                                       subject="Re: 가상 문의", body="가상 답장"))

    refreshed = client.get("/threads/fake-thread", headers={"HX-Request": "true"})
    assert refreshed.status_code == 200 and 'id="thread-content"' in refreshed.text
    assert "답장 후보를 만드는 중입니다" not in refreshed.text
    assert "hx-trigger" not in refreshed.text
    if finished == "awaiting_approval":
        assert "새 답장 후보" in refreshed.text and 'action="/candidates/' in refreshed.text
    else:
        assert "후보를 만들지 못했습니다" in refreshed.text
        assert 'href="/runs/run-fake-message"' in refreshed.text
    assert fake.mailbox.called("send") == [] and rows(client, Approval) == []


def test_thread_matches_each_messages_status_and_run(client):
    user_id = add_user(client)
    log_in(client, user_id)
    add_mail(client, user_id, "failed-message", status="error", kinds=(), subject="실패한 문의")
    add_mail(client, user_id, "pending-message", subject="후보가 준비된 문의")
    add_mail(client, user_id, "processing-message", status="processing", kinds=(), subject="처리 중인 문의")

    page = client.get("/threads/fake-thread")
    assert page.status_code == 200
    failed = page.text.index("실패한 문의")
    pending = page.text.index("후보가 준비된 문의")
    processing = page.text.index("처리 중인 문의")
    assert failed < page.text.index("후보를 만들지 못했습니다") < pending
    assert failed < page.text.index('href="/runs/run-failed-message"') < pending
    assert pending < page.text.index("후보 1") < processing
    assert processing < page.text.index("답장 후보를 만드는 중입니다")
    assert page.text.count("후보를 만들지 못했습니다") == 1
    assert page.text.count("답장 후보를 만드는 중입니다") == 1


@pytest.mark.parametrize("status", ["processing", "error"])
def test_thread_with_only_processed_row_shows_status_without_run_link(client, status):
    user_id = add_user(client)
    log_in(client, user_id)
    with client.app.state.database.session() as session:
        session.add(ProcessedMessage(user_id=user_id, gmail_message_id="fake-message", thread_id="fake-thread",
                                     status=status))
    page = client.get("/threads/fake-thread")
    assert page.status_code == 200
    assert ("답장 후보를 만드는 중입니다" in page.text) == (status == "processing")
    assert ("후보를 만들지 못했습니다" in page.text) == (status == "error")
    assert 'href="/runs/' not in page.text


@pytest.mark.parametrize("status", ["processing", "error"])
def test_thread_does_not_read_other_users_status_with_same_ids(client, status):
    user_id = add_user(client)
    other = add_user(client, sub="fake-sub-2", address="other@example.invalid")
    log_in(client, user_id)
    add_mail(client, user_id)
    add_mail(client, other, "other-message", "fake-thread", status=status, kinds=(), subject="다른 사용자의 원문")
    with client.app.state.database.session() as session:
        session.add(ProcessedMessage(user_id=other, gmail_message_id="fake-message", thread_id="fake-thread",
                                     status=status, run_id="private-run-marker"))

    for headers in ({}, {"HX-Request": "true"}):
        page = client.get("/threads/fake-thread", headers=headers)
        assert page.status_code == 200 and "승인 대기" in page.text
        assert "다른 사용자의 원문" not in page.text and "private-run-marker" not in page.text
        assert "답장 후보를 만드는 중입니다" not in page.text and "후보를 만들지 못했습니다" not in page.text
        assert "hx-trigger" not in page.text


@pytest.mark.parametrize("status", ["processing", "error"])
def test_other_users_processing_or_error_thread_is_denied(client, status):
    user_id = add_user(client)
    other = add_user(client, sub="fake-sub-2", address="other@example.invalid")
    log_in(client, user_id)
    add_mail(client, other, "other-message", "other-thread", status=status, kinds=())
    for headers in ({}, {"HX-Request": "true"}):
        denied = client.get("/threads/other-thread", headers=headers)
        assert denied.status_code == 404
        assert "run-other-message" not in denied.text


def test_send_email_tool_requires_approval_path():
    result = TOOLS["send_email"].invoke({
        "user_id": 1, "thread_id": "fake-thread", "to_addrs": ["sender@example.invalid"],
        "subject": "Re: 가상 문의", "body": "가상 답장",
    })
    assert result.ok is False and result.error_kind == "internal"


def test_approved_send_saves_memory_used_in_later_thread(client, fake, mailbox):
    """13절: 실제 승인 진입점 → 가짜 Gmail → 기억 저장 → 새 스레드 모델 입력."""
    user_id, (first, _, _) = mailbox
    database = client.app.state.database
    terms = {"customer_name": "가상상사", "items": [{"item_name": "가상용지", "quantity": 20}],
             "due_date": "2026-11-20"}
    with database.session() as session:
        session.add(DealTerms(user_id=user_id, thread_id="fake-thread", source_message_id="fake-message",
                             run_id="run-fake-message", terms=terms, missing_fields=[], required_source="config"))
        session.add(UserPreference(user_id=user_id, key="tone", value="정중"))
        assert session.get(UserPreference, (user_id, "approved_reply_style")) is None
    assert rows(client, CounterpartyHistory) == [] and len(rows(client, ThreadMessage)) == 1
    fake.mailbox.raw_messages["fake-message"]["payload"]["headers"].append(
        {"name": "Reply-To", "value": "reply@example.invalid"},
    )
    assert approve(client, first).endswith("notice=sent")
    assert approve(client, first).endswith("notice=already_sent")
    assert len(fake.mailbox.called("send")) == 1
    outgoing = [row for row in rows(client, ThreadMessage) if row.direction == "out"]
    assert len(outgoing) == 1 and outgoing[0].gmail_message_id == "fake-sent-1"
    assert outgoing[0].to_addrs == ["reply@example.invalid"]
    assert outgoing[0].body_text == "가상 답장 본문 1"
    history = rows(client, CounterpartyHistory)
    assert len(history) == 1 and history[0].deal_terms == terms
    with database.session() as session:
        assert session.get(UserPreference, (user_id, "approved_reply_style")).value["label"] == "후보 1"
        assert session.get(UserPreference, (user_id, "tone")).value == "정중"
    email = {
        "gmail_message_id": "new-thread-message", "thread_id": "new-thread", "rfc_message_id": None,
        "from_addr": "sender@example.invalid", "from_name": None, "to_addrs": ["demo@example.invalid"],
        "subject": "가상 재문의", "body_text": "지난 거래에 이어 문의합니다.",
        "received_at": (utcnow() + timedelta(seconds=1)).isoformat(), "direction": "in",
    }
    llm = FakeLLM([
        {"intent": "general", "reason": "가상 후속 문의"},
        {"candidates": [{"label": "간단히 안내", "body": "가상 안내"},
                        {"label": "자세히 안내", "body": "가상 상세 안내"}]},
    ])
    with use_backend(llm):
        result = start_run(user_id=user_id, email=email, mode="test", database=database,
                           reflection_enabled=False)
    assert result["end_reason"] == "awaiting_approval"
    assert result["thread_context"]["confirmed_terms"] == {}
    assert result["long_term"]["counterparty_history"][0]["deal_terms"] == terms
    assert all("가상상사" in prompt and "과거 거래 기록·발송 시점" in prompt for prompt in llm.calls)
    assert "정중" in llm.calls[-1] and "가상 답장 본문 1" in llm.calls[-1]


def test_send_failure_saves_no_memory_until_successful_retry(client, fake, mailbox):
    user_id, (first, _, _) = mailbox
    fake.mailbox.send_results.append(TimeoutError())
    assert approve(client, first).endswith("notice=failed_unknown")
    assert len(rows(client, ThreadMessage)) == 1 and rows(client, CounterpartyHistory) == []
    with client.app.state.database.session() as session:
        assert session.get(UserPreference, (user_id, "approved_reply_style")) is None
    assert approve(client, first).endswith("notice=sent")
    assert len(rows(client, ThreadMessage)) == 2
    with client.app.state.database.session() as session:
        assert session.get(UserPreference, (user_id, "approved_reply_style")) is not None


def test_memory_error_does_not_undo_sent_status_or_send_again(client, fake, mailbox, monkeypatch, caplog):
    from app.services import approval as service

    user_id, (first, _, _) = mailbox

    def broken_memory(session, **kwargs):
        session.add(UserPreference(user_id=user_id, key="partial-memory", value="가상"))
        session.flush()
        raise RuntimeError("private-memory-body-marker")

    monkeypatch.setattr(service, "save_sent_memory", broken_memory)
    assert approve(client, first).endswith("notice=sent")
    assert candidate(client, first).status == "sent" and rows(client, Approval)[0].send_status == "sent"
    assert rows(client, ProcessedMessage)[0].status == "sent"
    with client.app.state.database.session() as session:
        assert session.get(UserPreference, (user_id, "partial-memory")) is None
    assert approve(client, first).endswith("notice=already_sent")
    assert len(fake.mailbox.called("send")) == 1
    assert "발송 뒤 기억 저장 실패 (RuntimeError)" in caplog.text
    assert "private-memory-body-marker" not in caplog.text
