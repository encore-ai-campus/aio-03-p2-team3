"""채팅 업무 경로와 PostgreSQL 기록을 가짜 Gmail에서 검증한다."""
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.clients.gmail import GoogleUnavailable
from app.db.models import ThreadMessage, User, utcnow
from app.mail.followups import refresh_due
from app.services.auth import store_login
from tests.fakes.gmail import FakeGmailGoogle, encoded
from tests.fakes.google import fake_login
from tests.fakes.storage import FakeStorage
from tests.test_approval import add_mail
from tests.test_master_agent import Choices, app_for, auth, company, read, resume
from tests.test_pi_domain import pi_input
from tests.test_supabase_auth import FakeJwks


def turn(client, token, text):
    response = client.post("/api/agent/conversations", headers=auth(token), json={"message": text})
    assert response.status_code == 202, response.text
    key = response.json()["id"]
    return key, read(client, token, key)


def user(client, token):
    return client.get("/api/me", headers=auth(token)).json()["user_id"]


def connect(client, owner):
    with client.app.state.database.session() as session:
        store_login(session, client.app.state.google_access, session.get(User, owner), fake_login(), utcnow())


def append_mail(database, owner, thread, message_id, at, direction, sender="sender@example.invalid"):
    with database.session() as session:
        session.add(ThreadMessage(user_id=owner, thread_id=thread, gmail_message_id=message_id,
            direction=direction, from_addr=sender if direction == "in" else "demo@example.invalid",
            to_addrs=["Sender@Example.Invalid"] if direction == "out" else ["demo@example.invalid"],
            subject=f"발송 조건 {thread}", body_text="파일명 언급 only.pdf", sent_at=at))


def test_new_compose_and_reply_edit_api_ownership_approval_and_stale_revision(database_url):
    jwks, google = FakeJwks(), FakeGmailGoogle()
    token, outsider = jwks.token(), jwks.token(sub=uuid4())
    values = {"recipients": ["recipient@example.invalid"], "subject": "새 인사", "body": "안녕하세요."}
    choices = Choices([("prepare_new_mail", values), "새 초안을 저장했습니다."])
    with TestClient(app_for(database_url, jwks, google, choices)) as client:
        owner = user(client, token)
        user(client, outsider)
        _, state = turn(client, token, "새 인사 메일 초안")
        original = state["results"][0]["data"]["compose_draft"]
        url = "/api/mail/compose-drafts/" + original["id"]
        assert client.get(url, headers=auth(outsider)).status_code == 404
        assert client.put(url, headers=auth(outsider), json={**values, "revision": 1}).status_code == 404
        revised = client.put(url, headers=auth(token), json={**values, "body": "수정 본문", "revision": 1})
        assert revised.json()["revision"] == 2
        assert client.put(url, headers=auth(token), json={**values, "revision": 1}).status_code == 409
        assert client.get(url, headers=auth(token)).json()["body"] == "수정 본문"
        assert client.put(url, headers=auth(token), json={**values, "recipients": ["broken"], "revision": 2}).status_code == 422

        first, second = add_mail(client, owner)
        choices.calls.extend([("get_mail", {"thread_id": "fake-thread"}),
            ("prepare_edit_reply", {"candidate_id": first, "body": "첫 후보 수정"}),
            ("prepare_edit_reply", {"candidate_id": second, "body": "둘째 후보 수정"}), "수정했습니다."])
        key, state = turn(client, token, "기존 답변을 수정해 줘")
        assert state["status"] == "needs_input", state
        state = resume(client, token, key, state, {"task_id": state["waiting"]["task_id"], "answers": {"candidate_id": second}})
        assert state["status"] == "needs_approval", state
        action = state["waiting"]["action"]
        assert action["payload"]["original"]["id"] == second
        assert client.get("/api/mail/threads/fake-thread", headers=auth(token)).json()["candidates"][1]["body"] == "가상 답장 본문 2"
        state = resume(client, token, key, state, {"action_id": action["id"], "content_hash": state["waiting"]["content_hash"], "decision": "approve"})
        assert state["results"][-1]["data"]["edited_reply"]["body"] == "둘째 후보 수정", state
        assert not google.mailbox.called("send")

        (single,) = add_mail(client, owner, message_id="edit-source", thread_id="edit-thread", kinds=("general",))
        choices.calls.extend([("get_mail", {"thread_id": "edit-thread"}),
            ("prepare_edit_reply", {"candidate_id": single, "subject": "채팅의 변경 제목"}), "최신 내용을 확인해 주세요."])
        key, state = turn(client, token, "이 답장의 제목을 바꿔 줘")
        assert state["status"] == "needs_approval", state
        action = state["waiting"]["action"]
        edit = client.put(f"/api/mail/candidates/{single}", headers=auth(token), json={
            "expected_subject": "Re: 가상 문의", "expected_body": "가상 답장 본문 1",
            "subject": "별도 화면에서 바꾼 제목", "body": "가상 답장 본문 1",
        })
        assert edit.status_code == 200, edit.text
        state = resume(client, token, key, state, {"action_id": action["id"],
            "content_hash": state["waiting"]["content_hash"], "decision": "approve"})
        assert state["results"][-1]["code"] == "candidate_changed", state
        [latest] = client.get("/api/mail/threads/edit-thread", headers=auth(token)).json()["candidates"]
        assert latest["subject"] == "별도 화면에서 바꾼 제목"
        assert not google.mailbox.called("send")


def test_trade_drafts_tool_current_revision_issued_and_owner_filter(database_url):
    jwks, google = FakeJwks(), FakeGmailGoogle()
    token, outsider = jwks.token(), jwks.token(sub=uuid4())
    values = pi_input(payment_terms=None).model_dump(mode="json")
    ready = pi_input(document_number="PI-ISSUED-002").model_dump(mode="json")
    choices = Choices([("prepare_document", {"kind": "PI", "values": values}), "초안을 저장했습니다."])
    with TestClient(app_for(database_url, jwks, google, choices, storage=FakeStorage())) as client:
        company(client, token)
        company(client, outsider)
        _, state = turn(client, token, "PI 작성")
        target = state["results"][0]["data"]["document_id"]
        choices.calls.extend([("prepare_document", {"kind": "PI", "document_id": target, "revision": 1, "values": values}), "초안 수정"])
        turn(client, token, "PI 수정")
        choices.calls.extend([("prepare_document", {"kind": "PI", "values": ready}), "초안 준비"])
        _, state = turn(client, token, "발급할 PI 작성")
        assert "document_id" in state["results"][0]["data"], state
        issued = state["results"][0]["data"]["document_id"]
        choices.calls.extend([("prepare_issue", {"kind": "PI", "document_id": issued, "revision": 1}), "발급"])
        key, state = turn(client, token, "PI 발급")
        action = state["waiting"]["action"]
        resume(client, token, key, state, {"action_id": action["id"], "content_hash": state["waiting"]["content_hash"], "decision": "approve"})
        choices.calls.extend([("list_trade_drafts", {"kind": "PI"}), "미완성 문서 조회"])
        _, state = turn(client, token, "작성하다 만 PI")
        [draft] = state["results"][0]["data"]["draft_documents"]
        assert draft["document_id"] == target and draft["revision"] == 2
        assert "payment_terms" in draft["missing_fields"] and draft["url"].endswith(f"/pi/{target}")
        for actor, kind in ((outsider, "PI"), (token, "PO")):
            choices.calls.extend([("list_trade_drafts", {"kind": kind}), "조회"])
            _, state = turn(client, actor, "작성하다 만 문서")
            assert not state["results"][0]["data"]["draft_documents"]


def test_actual_attachment_metadata_download_account_and_gateway_failure(database_url):
    jwks, google = FakeJwks(), FakeGmailGoogle()
    token, outsider = jwks.token(), jwks.token(sub=uuid4())
    key = {"thread_id": "fake-thread", "message_id": "fake-message"}
    lookup = ("get_mail", {"thread_id": key["thread_id"]})
    tool = ("list_mail_attachments", key)
    choices = Choices([lookup, tool, "첨부 확인"])
    with TestClient(app_for(database_url, jwks, google, choices)) as client:
        owner = user(client, token)
        user(client, outsider)
        add_mail(client, owner)
        _, state = turn(client, token, "원본 첨부 확인")
        assert state["results"][-1]["code"] == "gmail_not_connected"
        connect(client, owner)
        raw = google.mailbox.raw_messages["fake-message"]
        raw["payload"]["body"]["data"] = encoded("요청하신 only-mention.pdf")
        choices.calls.extend([lookup, tool, "첨부 없음"])
        _, state = turn(client, token, "본문에 들어 있는 파일도 첨부야?")
        assert state["results"][-1]["data"]["mail_attachments"] == []
        raw["payload"]["parts"] = [{"mimeType": "multipart/mixed", "parts": [
            {"filename": "선적서.pdf", "mimeType": "application/pdf", "body": {"attachmentId": "one", "size": 5}},
            {"filename": "메모.txt", "mimeType": "text/plain", "body": {"data": encoded("draft"), "size": 5}},
        ]}]
        google.mailbox.attachment_data[("fake-message", "one")] = {"data": encoded("tests")}
        choices.calls.extend([lookup, tool, "파일 두 개"])
        _, state = turn(client, token, "첨부 원본 줘")
        files = state["results"][-1]["data"]["mail_attachments"]
        assert [file["filename"] for file in files] == ["선적서.pdf", "메모.txt"]
        assert not google.mailbox.called("attachment")
        for file, content in zip(files, (b"tests", b"draft"), strict=True):
            url = file["download_url"]
            assert client.get(url).status_code == 401
            before = len(google.mailbox.called("message"))
            assert client.get(url, headers=auth(outsider)).status_code == 404
            assert client.get(url.replace("fake-thread", "wrong-thread"), headers=auth(token)).status_code == 404
            assert len(google.mailbox.called("message")) == before
            response = client.get(url, headers=auth(token))
            assert response.content == content and response.headers["content-disposition"].startswith("attachment;")
            assert response.headers["x-content-type-options"] == "nosniff"
        url = files[0]["download_url"]
        assert client.get(url.rsplit("/", 1)[0] + "/0.5", headers=auth(token)).status_code == 404
        google.mailbox.attachment_data[("fake-message", "one")] = GoogleUnavailable()
        assert client.get(url, headers=auth(token)).status_code == 502
        raw["threadId"] = "wrong"
        assert client.get(url, headers=auth(token)).status_code == 404


def test_reply_followups_deadline_repeat_restart_cancel_and_account(database_url):
    jwks, google = FakeJwks(), FakeGmailGoogle()
    token, outsider = jwks.token(), jwks.token(sub=uuid4())
    now = utcnow()
    due = now + timedelta(days=3)
    choices = Choices([("search_sent_mail", {"query": "sender@example.invalid"}),
        ("register_mail_followup", {"thread_id": "quiet", "due_at": due.isoformat()}), "알림을 등록했습니다."])
    with TestClient(app_for(database_url, jwks, google, choices)) as client:
        owner, other = user(client, token), user(client, outsider)
        database = client.app.state.database
        for thread in ("quiet", "answered", "cancelled"):
            append_mail(database, owner, thread, "out-" + thread, now, "out")
        append_mail(database, other, "foreign", "out-foreign", now, "out")
        _, state = turn(client, token, "사흘 동안 답 없으면 알려줘")
        assert {row["thread_id"] for row in state["results"][0]["data"]["sent_threads"]} == {"quiet", "answered", "cancelled"}
        saved = state["results"][1]["data"]["followups"][0]
        assert saved["status"] == "pending"
        for thread in ("quiet", "answered", "cancelled"):
            choices.calls.extend([("search_sent_mail", {"query": thread}),
                ("register_mail_followup", {"thread_id": thread, "due_at": due.isoformat()}), "등록 확인"])
            _, state = turn(client, token, "알림 등록")
            if thread == "quiet":
                assert state["results"][1]["data"]["followups"][0]["id"] == saved["id"]
        rows = client.get("/api/mail/followups", headers=auth(token)).json()["followups"]
        cancelled = next(item["id"] for item in rows if item["thread_id"] == "cancelled")
        assert client.delete(f"/api/mail/followups/{cancelled}", headers=auth(outsider)).status_code == 404
        choices.calls.extend([("list_mail_followups", {}), ("cancel_mail_followup", {"followup_id": cancelled}), "취소"])
        _, state = turn(client, token, "세 번째 알림 취소")
        assert state["results"][-1]["data"]["followups"][0]["status"] == "cancelled"
        append_mail(database, owner, "answered", "in-early", due - timedelta(seconds=1), "in")
        append_mail(database, owner, "quiet", "in-late", due + timedelta(seconds=1), "in")
        append_mail(database, owner, "quiet", "in-unrelated", due - timedelta(seconds=1), "in", "other@example.invalid")
        refresh_due(database, now=due - timedelta(seconds=1))
        assert client.get("/api/mail/followups?due_only=true", headers=auth(token)).json()["followups"] == []
    with TestClient(app_for(database_url, jwks, google, Choices([]))) as client:
        database = client.app.state.database
        for _ in range(2):
            refresh_due(database, now=due + timedelta(seconds=2))
        rows = client.get("/api/mail/followups", headers=auth(token)).json()["followups"]
        assert {item["thread_id"]: item["status"] for item in rows} == {
            "quiet": "due", "answered": "replied", "cancelled": "cancelled",
        }
        assert client.get("/api/mail/followups", headers=auth(outsider)).json()["followups"] == []
        assert not google.mailbox.called("send")
