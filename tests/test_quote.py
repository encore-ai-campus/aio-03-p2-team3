"""계획 11절: 정수 계산·한글 PDF·설정·사용자 격리·견적 그래프. 외부 API는 쓰지 않는다."""

from base64 import b64decode, urlsafe_b64decode
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
from email import message_from_bytes
from email.policy import default as email_policy
from io import BytesIO
from threading import Event

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pypdf import PdfReader
import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.models import (
    Approval, CompanyProfile, CounterpartyHistory, DealTerms, PriceListItem, ProcessedMessage,
    Quote, ReplyCandidate, Run, ThreadMessage, User, UserPreference, utcnow,
)
from app.graph.run import start_run
from app.llm.client import use_backend
from app.main import create_app
from app.quote.calc import build_draft, fill_prices
from app.quote.pdf import render_quote_pdf
from app.runlog.logger import recording
from app.services.approval import send_approved_candidate, send_approved_quote
from app.services.auth import GoogleAccess, TokenCipher, save_login
from app.tools.base import ToolResult
from app.tools.registry import TOOLS
from app.web.deps import current_user_id
from tests.fakes.llm import FakeLLM
from tests.fakes.gmail import FakeGmailGoogle, message
from tests.fakes.google import fake_login

TERMS = {
    "customer_name": "가상상사", "due_date": "2026-11-20",
    "items": [{"item_name": "한글 복사용지", "quantity": 3, "unit": "박스", "unit_price": 101},
              {"item_name": "연필", "quantity": 2, "unit": "개", "unit_price": None},
              {"item_name": "공책", "quantity": 1, "unit": "권", "unit_price": None}],
    "contact_name": None, "contact_phone": None, "delivery_place": None, "note": None, "evidence": {},
}
COMPANY = {"company_name": "가상문구", "business_no": "000-00-00000",
           "ceo_name": "가상대표", "contact": "desk@example.invalid"}
PRICES = [{"item_name": "한글 복사용지", "unit": "박스", "unit_price": 999},
          {"item_name": "연필", "unit": "개", "unit_price": 52}]


def draft():
    return build_draft(TERMS, COMPANY, PRICES, quote_no="Q-20261110-001", quote_date=date(2026, 11, 10))


def test_price_priority_dates_integer_vat_and_missing():
    result = draft()
    assert [line["unit_price"] for line in result["lines"]] == [101, 52, None]
    assert [line["price_source"] for line in result["lines"]] == ["thread", "price_list", None]
    assert result["missing_prices"] == ["공책"] and result["status"] == "needs_price"
    assert result["total"] is None and result["supply_amount"] is None and result["vat"] is None
    assert date.fromisoformat(result["valid_until"]) - date.fromisoformat(result["quote_date"]) == timedelta(days=30)
    filled = fill_prices(result, {2: 50})
    assert (filled["supply_amount"], filled["vat"], filled["total"]) == (457, 45, 502)
    assert filled["status"] == "ready" and filled["lines"][2]["price_source"] == "user"
    assert result["lines"][2]["unit_price"] is None  # 입력 초안을 변형하지 않음
    huge = deepcopy(TERMS)
    huge["items"] = [{"item_name": "큰 정수", "quantity": 3, "unit": None, "unit_price": 2**60 + 1}]
    huge_draft = build_draft(huge, {}, [], quote_no="Q-20261110-002", quote_date=date(2026, 11, 10))
    assert huge_draft["vat"] == ((2**60 + 1) * 3) // 10


@pytest.mark.parametrize("values", [{}, {0: 3, 2: 3}, {2: -1}, {2: 1.5}, {2: True}])
def test_missing_prices_require_valid_whole_won(values):
    with pytest.raises(ValueError):
        fill_prices(draft(), values)


def test_zero_and_different_units():
    result = fill_prices(draft(), {2: 0})
    assert result["lines"][2]["amount"] == 0 and result["status"] == "ready"
    terms = deepcopy(TERMS)
    terms["items"][1]["unit"] = "박스"
    result = build_draft(terms, COMPANY, PRICES, quote_no="Q-test", quote_date=date(2026, 11, 10))
    assert result["missing_prices"] == ["연필", "공책"]


def test_pdf_contains_korean_and_embedded_font_and_multiple_pages():
    result = fill_prices(draft(), {2: 50})
    data = render_quote_pdf(result)
    assert data.startswith(b"%PDF-")
    reader = PdfReader(BytesIO(data))
    content = "".join(page.extract_text() for page in reader.pages)
    for expected in ("견적서", "가상문구", "한글 복사용지", "가상상사", "합계: 502원", "2026-12-10"):
        assert expected in content
    fonts = reader.pages[0]["/Resources"]["/Font"]
    assert any("/FontFile2" in font.get_object()["/DescendantFonts"][0].get_object()["/FontDescriptor"]
               for font in fonts.values() if "/DescendantFonts" in font.get_object())
    result["lines"] *= 35
    assert len(PdfReader(BytesIO(render_quote_pdf(result))).pages) > 1
    incomplete = "".join(p.extract_text() for p in PdfReader(BytesIO(render_quote_pdf(draft()))).pages)
    assert "미완성 견적서" in incomplete and "단가 입력 필요" in incomplete


def test_tool_persists_id_number_and_user_isolation(database):
    with database.session() as session:
        session.add(User(id=2, google_sub="fake-2", email="other@example.invalid"))
    payload = {"user_id": 1, "thread_id": "thread", "deal_terms": TERMS,
               "company": COMPANY, "price_list": PRICES}
    with recording(database, "fake-run"):
        first = TOOLS["create_quote"].invoke(payload)
        second = TOOLS["create_quote"].invoke(payload)
        other = TOOLS["create_quote"].invoke({**payload, "user_id": 2})
    assert first.ok and second.ok and other.ok
    assert first.value["quote_no"].endswith("-001") and second.value["quote_no"].endswith("-002")
    assert other.value["quote_no"] == first.value["quote_no"]
    with database.session() as session:
        stored = session.get(Quote, first.value["quote_id"])
        assert stored.draft == first.value and stored.status == "needs_price"


@pytest.fixture
def web(tmp_path):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path}/quote.sqlite3", session_secret="fake-session"))
    app.dependency_overrides[current_user_id] = lambda: 1
    with TestClient(app) as client:
        db = app.state.database
        with db.session() as session:
            session.add_all([User(id=1, google_sub="one", email="one@example.invalid"),
                             User(id=2, google_sub="two", email="two@example.invalid")])
        with recording(db, "fake-run"):
            result = TOOLS["create_quote"].invoke({"user_id": 1, "thread_id": "thread", "deal_terms": TERMS,
                                                    "company": COMPANY, "price_list": PRICES})
        yield client, app, db, result.value["quote_id"]


def test_company_and_price_settings_upsert_and_isolation(web):
    client, app, db, quote_id = web
    assert client.get("/settings").status_code == 200
    assert client.post("/settings/company", data=COMPANY).status_code == 200
    assert client.post("/settings/prices", data=PRICES[0]).status_code == 200
    assert client.post("/settings/prices", data={**PRICES[0], "unit_price": 500}).status_code == 200
    with db.session() as session:
        assert session.get(CompanyProfile, 1).company_name == "가상문구"
        items = session.scalars(select(PriceListItem).where(PriceListItem.user_id == 1)).all()
        assert len(items) == 1 and items[0].unit_price == 500
    app.dependency_overrides[current_user_id] = lambda: 2
    assert "가상문구" not in client.get("/settings").text
    assert client.get(f"/quotes/{quote_id}").status_code == 404
    assert client.get(f"/quotes/{quote_id}/preview.pdf").status_code == 404
    assert client.post(f"/quotes/{quote_id}/prices", data={"price_2": 50}).status_code == 404
    assert client.post("/settings/prices", data={**PRICES[0], "unit_price": -1}).status_code == 422
    assert client.post("/settings/prices", data={**PRICES[0], "unit_price": "1.5"}).status_code == 422


def test_missing_price_screen_input_and_preview(web):
    client, app, db, quote_id = web
    page = client.get(f"/quotes/{quote_id}")
    assert page.status_code == 200 and "단가를 입력해 주세요" in page.text
    assert 'name="price_2"' in page.text and 'name="price_0"' not in page.text
    for values in ({}, {"price_2": -1}, {"price_2": "1.5"}, {"price_2": 50, "price_0": 999}):
        assert client.post(f"/quotes/{quote_id}/prices", data=values).status_code == 400
    assert client.post(f"/quotes/{quote_id}/prices", data={"price_2": 50}).status_code == 200
    assert "502원" in client.get(f"/quotes/{quote_id}").text
    pdf = client.get(f"/quotes/{quote_id}/preview.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert "합계: 502원" in PdfReader(BytesIO(pdf.content)).pages[0].extract_text()
    assert client.post(f"/quotes/{quote_id}/prices", data={"price_2": 20}).status_code == 409
    app.dependency_overrides.clear()
    assert client.get("/settings", follow_redirects=False).headers["location"] == "/login"
    assert client.get(f"/quotes/{quote_id}", follow_redirects=False).status_code == 303


def test_real_graph_links_quote_and_candidates_with_settings(database, email):
    with database.session() as session:
        session.add(CompanyProfile(user_id=1, **COMPANY))
        session.add_all([PriceListItem(user_id=1, **row) for row in PRICES])
    extracted = {**TERMS, "evidence": []}
    fake = FakeLLM([{"intent": "deal", "reason": "거래 견적 요청"}, extracted,
                    {"candidates": [{"label": "간단 안내", "body": "첨부 견적서를 확인해 주세요."},
                                    {"label": "상세 안내", "body": "요청한 견적서를 첨부드립니다."}]}])
    with use_backend(fake):
        result = start_run(user_id=1, email=email, mode="test", database=database)
    assert result["end_reason"] == "awaiting_approval" and result["reply_mode"] == "quote"
    quote = result["quote_draft"]
    assert quote["supplier"] == COMPANY and quote["lines"][1]["price_source"] == "price_list"
    assert "상대방에게 단가를 묻지" in fake.calls[-1]
    with database.session() as session:
        stored = session.get(Quote, quote["quote_id"])
        assert stored.run_id == result["run_id"] and stored.deal_terms_id is not None
        candidates = session.scalars(select(ReplyCandidate).where(ReplyCandidate.run_id == result["run_id"])).all()
        assert len(candidates) == 2 and all(c.kind == "quote" and c.quote_id == stored.id for c in candidates)


@pytest.fixture
def approval_web(web):
    client, app, db, quote_id = web
    google = FakeGmailGoogle()
    google.mailbox.raw_messages["fake-message"] = message(thread_id="thread")
    google.mailbox.raw_messages["fake-message"]["payload"]["headers"].append(
        {"name": "References", "value": "<older@example.invalid>"})
    access = GoogleAccess(db, google, TokenCipher(Fernet.generate_key().decode()), "fake-topic")
    save_login(access, fake_login(sub="one"))
    app.state.google_access = access
    with db.session() as session:
        session.add(Run(run_id="quote-run", user_id=1, mode="test", message_id="fake-message",
                        thread_id="thread", reflection_enabled=False))
        row = session.get(Quote, quote_id)
        row.run_id = "quote-run"
        session.add(ThreadMessage(user_id=1, thread_id="thread", gmail_message_id="fake-message",
                                  direction="in", from_addr="sender@example.invalid", to_addrs=[],
                                  subject="가상 문의", body_text="가상 원문", sent_at=utcnow()))
        session.add(ProcessedMessage(user_id=1, thread_id="thread", gmail_message_id="fake-message",
                                     status="awaiting_approval"))
        ids = []
        for label in ("짧게", "정중하게"):
            candidate = ReplyCandidate(user_id=1, run_id="quote-run", thread_id="thread",
                                       source_message_id="fake-message", kind="quote", quote_id=quote_id,
                                       label=label, subject="Re: 가상 문의", body="첨부 견적서를 확인해 주세요.")
            session.add(candidate)
            session.flush()
            ids.append(candidate.id)
    yield client, app, db, quote_id, ids, access


class FakeSender:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or ToolResult(ok=True, source="gmail", value={"sent_message_id": "sent-fake"})

    def invoke(self, payload):
        self.calls.append(payload)
        return self.result


def test_approve_requires_prices_then_attaches_current_pdf_once(approval_web, monkeypatch):
    client, app, db, quote_id, ids, access = approval_web
    sender = FakeSender()
    monkeypatch.setitem(TOOLS, "send_email", sender)
    pending = client.post(f"/quotes/{quote_id}/approve", data={"candidate_id": ids[0]})
    assert pending.status_code == 200 and "notice=needs_price" in str(pending.url)
    assert sender.calls == []
    assert "disabled" in client.get(f"/quotes/{quote_id}").text
    client.post(f"/quotes/{quote_id}/prices", data={"price_2": 50})
    assert client.post(f"/quotes/{quote_id}/approve", data={"candidate_id": ids[0]}).status_code == 200
    assert client.post(f"/quotes/{quote_id}/approve", data={"candidate_id": ids[0]}).status_code == 200
    assert client.post(f"/quotes/{quote_id}/approve", data={"candidate_id": ids[1]}).status_code == 200
    assert len(sender.calls) == 1
    payload = sender.calls[0]
    assert payload["user_id"] == 1 and payload["thread_id"] == "thread"
    assert payload["to_addrs"] == ["sender@example.invalid"]
    assert payload["in_reply_to"] == "<fake-message@example.invalid>"
    assert payload["references"] == ["<older@example.invalid>", "<fake-message@example.invalid>"]
    attachment, = payload["attachments"]
    assert attachment["mime_type"] == "application/pdf" and attachment["filename"].startswith("견적서_Q-")
    assert "합계: 502원" in PdfReader(BytesIO(b64decode(attachment["content_b64"]))).pages[0].extract_text()
    with db.session() as session:
        quote = session.get(Quote, quote_id)
        assert quote.status == quote.draft["status"] == "sent" and quote.sent_at is not None
        approvals = session.scalars(select(Approval)).all()
        assert len(approvals) == 1 and approvals[0].sent_message_id == "sent-fake"
        assert session.get(ReplyCandidate, ids[0]).status == "sent"
        assert session.get(ReplyCandidate, ids[1]).status == "superseded"
        assert session.scalar(select(ProcessedMessage)).status == "sent"


def test_concurrent_different_candidates_are_one_approval(approval_web, monkeypatch):
    client, app, db, quote_id, ids, access = approval_web
    client.post(f"/quotes/{quote_id}/prices", data={"price_2": 50})
    entered, release = Event(), Event()
    sender = FakeSender()

    def blocking_send(payload):
        sender.calls.append(payload)
        entered.set()
        assert release.wait(timeout=10)
        return sender.result

    monkeypatch.setitem(TOOLS, "send_email", type("Sender", (), {"invoke": staticmethod(blocking_send)})())
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(send_approved_quote, 1, quote_id, ids[0], access=access)
        assert entered.wait(timeout=10)
        second = pool.submit(send_approved_quote, 1, quote_id, ids[1], access=access)
        release.set()
        assert first.result(timeout=10).outcome == "sent"
        assert second.result(timeout=10).outcome == "already_sent"
    assert len(sender.calls) == 1


def test_approval_failure_tampering_and_explicit_retry(approval_web, monkeypatch):
    client, app, db, quote_id, ids, access = approval_web
    sender = FakeSender(ToolResult(ok=False, source="gmail", error_kind="network", error_message="가짜 실패"))
    monkeypatch.setitem(TOOLS, "send_email", sender)
    client.post(f"/quotes/{quote_id}/prices", data={"price_2": 50})
    app.dependency_overrides[current_user_id] = lambda: 2
    assert client.post(f"/quotes/{quote_id}/approve", data={"candidate_id": ids[0]}).status_code == 404
    app.dependency_overrides[current_user_id] = lambda: 1
    with db.session() as session:
        candidate = session.get(ReplyCandidate, ids[0])
        candidate.kind = "general"
    assert client.post(f"/quotes/{quote_id}/approve", data={"candidate_id": ids[0]}).status_code == 404
    with db.session() as session:
        session.get(ReplyCandidate, ids[0]).kind = "quote"
    assert sender.calls == []
    failed = client.post(f"/quotes/{quote_id}/approve", data={"candidate_id": ids[0]})
    assert failed.status_code == 200 and "notice=failed_unknown" in str(failed.url)
    assert "보낸편지함을 확인" in failed.text
    assert len(sender.calls) == 1
    with db.session() as session:
        assert session.scalar(select(Approval)).send_status == "failed"
        assert session.get(ReplyCandidate, ids[0]).status == "send_failed"
        assert session.get(Quote, quote_id).status == "ready"
    # 일반 승인과 같은 결과 키·명시적 재승인: 자동 재시도는 없고 같은 승인 행을 재사용한다.
    sender.result = ToolResult(ok=True, source="gmail", value={"sent_message_id": "retried-fake"})
    assert "notice=sent" in str(client.post(f"/quotes/{quote_id}/approve", data={"candidate_id": ids[0]}).url)
    assert len(sender.calls) == 2
    with db.session() as session:
        assert len(session.scalars(select(Approval)).all()) == 1
        assert session.scalar(select(Approval)).sent_message_id == "retried-fake"


def test_quote_uses_real_send_email_mime_and_gmail_once(approval_web):
    client, app, db, quote_id, ids, access = approval_web
    client.post(f"/quotes/{quote_id}/prices", data={"price_2": 50})
    result = client.post(f"/quotes/{quote_id}/approve", data={"candidate_id": ids[0]})
    assert "notice=sent" in str(result.url)
    client.post(f"/quotes/{quote_id}/approve", data={"candidate_id": ids[0]})
    sends = access.google.mailbox.called("send")
    assert len(sends) == 1
    _, params, retries = sends[0]
    assert retries == 0 and params["body"]["threadId"] == "thread"
    mime = message_from_bytes(urlsafe_b64decode(params["body"]["raw"]), policy=email_policy)
    assert mime["To"] == "sender@example.invalid" and mime["In-Reply-To"] == "<fake-message@example.invalid>"
    attachment, = list(mime.iter_attachments())
    assert attachment.get_content_type() == "application/pdf"
    assert attachment.get_filename().startswith("견적서_Q-")
    assert "합계: 502원" in PdfReader(BytesIO(attachment.get_payload(decode=True))).pages[0].extract_text()


def test_quote_send_preserves_memory_and_quote_status_together(approval_web):
    """11·13절 통합: 미완성 견적은 기억에 쓰지 않고, 승인 발송 성공 뒤 한 번만 저장한다."""
    client, app, db, quote_id, ids, access = approval_web
    with db.session() as session:
        terms = DealTerms(user_id=1, thread_id="thread", source_message_id="fake-message",
                          run_id="quote-run", terms=TERMS, missing_fields=[], required_source="config")
        session.add(terms)
        session.flush()
        session.get(Quote, quote_id).deal_terms_id = terms.id
    assert "notice=needs_price" in str(client.post(
        f"/quotes/{quote_id}/approve", data={"candidate_id": ids[0]},
    ).url)
    with db.session() as session:
        assert session.scalar(select(CounterpartyHistory)) is None
        assert session.get(UserPreference, (1, "approved_reply_style")) is None
    client.post(f"/quotes/{quote_id}/prices", data={"price_2": 50})
    assert "notice=sent" in str(client.post(
        f"/quotes/{quote_id}/approve", data={"candidate_id": ids[0]},
    ).url)
    client.post(f"/quotes/{quote_id}/approve", data={"candidate_id": ids[0]})
    assert len(access.google.mailbox.called("send")) == 1
    with db.session() as session:
        quote = session.get(Quote, quote_id)
        assert quote.status == quote.draft["status"] == "sent"
        history, = session.scalars(select(CounterpartyHistory).where(CounterpartyHistory.user_id == 1))
        assert history.quote_id == quote_id and history.deal_terms == TERMS
        assert history.counterparty_email == "sender@example.invalid" and history.thread_id == "thread"
        outgoing, = session.scalars(select(ThreadMessage).where(
            ThreadMessage.user_id == 1, ThreadMessage.direction == "out",
        ))
        assert outgoing.gmail_message_id == "fake-sent-1" and outgoing.to_addrs == ["sender@example.invalid"]
        assert outgoing.body_text == "첨부 견적서를 확인해 주세요."
        preference = session.get(UserPreference, (1, "approved_reply_style"))
        assert preference.value["label"] == "짧게"


def test_quote_and_general_approval_share_user_lock(approval_web, monkeypatch):
    client, app, db, quote_id, ids, access = approval_web
    client.post(f"/quotes/{quote_id}/prices", data={"price_2": 50})
    with db.session() as session:
        candidate = session.get(ReplyCandidate, ids[1])
        candidate.kind, candidate.quote_id = "general", None
    entered, release = Event(), Event()
    calls = []

    def blocking_send(payload):
        calls.append(payload)
        entered.set()
        assert release.wait(timeout=10)
        return ToolResult(ok=True, source="gmail", value={"sent_message_id": "sent-fake"})

    monkeypatch.setitem(TOOLS, "send_email", type("Sender", (), {"invoke": staticmethod(blocking_send)})())
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(send_approved_quote, 1, quote_id, ids[0], access=access)
        assert entered.wait(timeout=10)
        second = pool.submit(send_approved_candidate, 1, ids[1], access=access)
        release.set()
        assert first.result(timeout=10).outcome == "sent"
        assert second.result(timeout=10).outcome == "already_replied"
    assert len(calls) == 1


def test_pdf_failure_does_not_claim_or_send(approval_web, monkeypatch):
    client, app, db, quote_id, ids, access = approval_web
    client.post(f"/quotes/{quote_id}/prices", data={"price_2": 50})

    def fail(_):
        raise OSError("가짜 글꼴 읽기 오류")

    monkeypatch.setattr("app.services.approval.render_quote_pdf", fail)
    result = send_approved_quote(1, quote_id, ids[0], access=access)
    assert result.outcome == "failed" and access.google.mailbox.called("send") == []
    with db.session() as session:
        assert session.get(ReplyCandidate, ids[0]).status == "pending"
        assert session.scalars(select(Approval)).all() == []
