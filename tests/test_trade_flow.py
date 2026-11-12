"""kekorea-port 6절: PI → PO → CI·PL 대표 흐름 백엔드 연결 시험(그래프 → 저장 → 승인 → 발송).

가짜 LLM(tests/fakes/llm.py)·가짜 Gmail(tests/fakes/gmail.py)만 쓰고 실제 API는 부르지 않는다.
- 그래프: 무역 메일 → 무역 추출 → 필수 항목 검토 → make_quote 무역 분기(create_trade_document)
  → draft_replies v3(무역 문서 요약) → save_pending(후보 trade_doc_id 연결).
- 승인: 문서 확정(검토 입력 revise·PL 합계 승인 approve_packing_totals)과 메일 발송 승인
  (send_approved_trade_document)을 구분해 시험한다(계약 15.5·15.6절).
- 회사 고유 값은 쓰지 않는다(가상 발행 회사 Testworks Trading Co, 가상 거래처 Acme Trading,
  가상 상품 Virtual Serum, 가상 직인 1×1 PNG).
"""

import hashlib
import struct
import zlib
from base64 import urlsafe_b64decode
from email import message_from_bytes

from cryptography.fernet import Fernet
from sqlalchemy import select

from app.db.models import (
    Approval, CompanyBankAccount, CompanyBranding, CompanyProfile, FileAsset, PriceListItem,
    ReplyCandidate, TradeDocument, utcnow,
)
from app.graph.run import start_run
from app.llm.client import use_backend
from app.files.storage import StorageError
from app.services.approval import send_approved_candidate, send_approved_trade_document
from app.services.auth import GoogleAccess, TokenCipher, save_login
from app.services.trade_docs import approve_packing_totals, revise_trade_document
from tests.fakes.gmail import FakeGmailGoogle, message
from tests.fakes.google import fake_login
from tests.fakes.llm import FakeLLM
from tests.fakes.storage import FakeStorage

ISSUER_NAME = "Testworks Trading Co"  # 가상 발행 회사(영문)
BANK_KEYS = ("BENEFICIARY", "BANK_NAME", "BRANCH", "SWIFT", "ACCOUNT_NUMBER", "BANK_ADDRESS")

CANDIDATES = {"candidates": [
    {"label": "간단 안내", "body": "요청하신 문서를 첨부해 보내드립니다. 확인 후 회신해 주세요."},
    {"label": "상세 안내", "body": "요청하신 문서를 준비해 첨부했습니다. 검토 후 필요한 조정을 말씀해 주세요."},
]}


def seal_png(width=1, height=1):
    """테스트 전용 1×1 RGB PNG(회사 자산이 아님)."""

    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    pixels = (b"\0" + b"\xff" * (width * 3)) * height
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


def put_settings(database, storage):
    """무역서류에 필요한 본인 설정: 발행 회사·계좌·무역 단가표(가상)·직인.

    직인은 9절 저장 경로와 같은 모양(file_assets 행 + Storage 객체)으로 심는다."""
    seal = seal_png()
    with database.session() as session:
        session.add(CompanyProfile(
            user_id=1, company_name="테스트상사", legal_name_en=ISSUER_NAME,
            address="7 Test-ro, Seoul", contact="sales@testworks.example",
            phone="+82-2-000-0000", email="sales@testworks.example"))
        session.add(CompanyBankAccount(
            user_id=1, currency="USD", beneficiary="TESTWORKS TRADING CO", bank_name="Test Bank",
            branch="Seoul Branch", swift="TESTUS33", account_number="000-0000-0000",
            bank_address="1 Bank-ro, Seoul"))
        session.add_all([
            PriceListItem(user_id=1, item_name="Virtual Serum", capacity="50ml", role="sale",
                          currency="USD", unit_price_text="8.00", party_key="", price_basis="per PCS"),
            PriceListItem(user_id=1, item_name="Virtual Serum", capacity="50ml", role="purchase",
                          currency="KRW", unit_price_text="8000", party_key="", price_basis="per PCS"),
        ])
        asset = FileAsset(user_id=1, original_filename="seal.png", content_type="image/png",
                          size_bytes=len(seal), sha256=hashlib.sha256(seal).hexdigest(),
                          object_key="1/branding/seed")
        session.add(asset)
        session.flush()
        session.add(CompanyBranding(user_id=1, seal=seal, seal_sha256=hashlib.sha256(seal).hexdigest(),
                                    seal_file_id=asset.id))
    storage.objects[asset.object_key] = seal


def trade_email(subject, body, message_id="fake-message", thread_id="fake-thread"):
    return {
        "gmail_message_id": message_id, "thread_id": thread_id, "rfc_message_id": None,
        "from_addr": "buyer@example.invalid", "from_name": None,
        "to_addrs": ["demo@example.invalid"], "subject": subject, "body_text": body,
        "received_at": "2026-11-10T00:00:00+00:00", "direction": "in",
    }


def party(legal_name=None, address=None):
    return {"legal_name": legal_name, "address": address, "contact": None, "phone": None,
            "email": None, "registration_details": None}


def item(**overrides):
    base = {"product_name": "Virtual Serum", "product_code": None, "capacity": "50ml",
            "quantity": "100", "unit": "PCS", "unit_price": None, "price_basis": "per PCS",
            "discount_percent": None, "paid_quantity": "100", "free_quantity": None,
            "shipped_quantity": None, "promotion": None, "price_source": None,
            # 근거 조각은 원문 인용이라 단가까지 담아야 근거 검증(verify_item_quotes)을 통과한다.
            "source": "Virtual Serum 100 PCS at USD 8.00 per PCS", "package_type": None,
            "package_count": None, "net_weight_kg": None, "gross_weight_kg": None,
            "volume_cbm": None, "hs_code": None}
    base.update(overrides)
    return base


def trade_response(document_type, **updates):
    base = {
        "document_type": document_type, "product_family": "cosmetics", "currency": "USD",
        "buyer": party("Acme Trading", "1 Fiction Ave, Seoul"),
        "seller": party(None, None),
        "items": [item()],
        "incoterms": "FOB Busan", "payment_terms": "T/T", "remarks": None,
        "document_number": None, "issue_date": None, "ship_to": None, "ship_to_source": None,
        "bill_to": None, "shipment_reference": None, "country_of_origin": None, "hs_code": None,
        "actual_package_count": None, "container_count": None,
        "declared_total_quantity": None, "declared_total_quantity_unit": None,
        "declared_net_weight_kg": None, "declared_gross_weight_kg": None,
        "declared_volume_cbm": None, "packages": [],
        "missing_fields": [], "conflicts": [], "source_notes": ["Virtual Serum 100 PCS"],
    }
    base.update(updates)
    return base


def run_flow(database, email, extracted, *, reflection_enabled=False):
    """무역 대표 흐름의 그래프 실행(분석 → 추출 → 문서 → 답장 후보)."""
    fake = FakeLLM([{"intent": "deal", "reason": "무역서류 작성 요청"}, extracted, CANDIDATES])
    with use_backend(fake):
        result = start_run(user_id=1, email=email, mode="test", reflection_enabled=reflection_enabled,
                           database=database)
    return result, fake


def approval_access(database):
    """가짜 Gmail 승인 경로. 그래프가 저장한 후보·문서를 그대로 쓴다."""
    google = FakeGmailGoogle()
    access = GoogleAccess(database, google, TokenCipher(Fernet.generate_key().decode()), "fake-topic")
    save_login(access, fake_login(sub="fake-sub-1"))
    return access


def stored_document(database, result):
    with database.session() as session:
        return session.scalar(select(TradeDocument).where(
            TradeDocument.id == result["trade_doc_draft"]["trade_doc_id"],
            TradeDocument.user_id == 1))


def stored_candidates(database, result):
    with database.session() as session:
        return session.scalars(select(ReplyCandidate).where(
            ReplyCandidate.run_id == result["run_id"], ReplyCandidate.user_id == 1)).all()


# ── PI: 그래프 → 검토 입력(문서번호) → 승인 발송(PI 계좌·직인 PDF 첨부) ────────────

def test_pi_flow_from_graph_to_sent(database):
    storage = FakeStorage()
    put_settings(database, storage)
    email = trade_email(
        "PI 작성 요청",
        "Hello, this is Acme Trading. Please create a PI for Virtual Serum 100 PCS "
        "at USD 8.00 per PCS. Incoterms FOB Busan, payment T/T.")
    result, fake = run_flow(database, email, trade_response("PI", items=[item(unit_price="8.00")]),
                            reflection_enabled=True)  # 성찰 켬: 무역 초안이 규칙 검사를 통과하는지도 본다
    assert result["end_reason"] == "awaiting_approval" and result["reply_mode"] == "quote"
    draft = result["trade_doc_draft"]
    assert draft["doc_kind"] == "PI" and draft["trade_doc_id"] is not None
    assert draft["status"] == "needs_input"  # 문서번호는 검토 입력(계약 15.5절)
    assert any("Document number" in issue for issue in draft["blocking_issues"])
    assert draft["issuer"]["legal_name_en"] == ISSUER_NAME  # 발행 회사 스냅숏
    assert draft["bank"]["SWIFT"] == "TESTUS33"  # PI 계좌 스냅숏(대문자 6키)
    assert draft["items"][0]["unit_price"] == "8.00"  # 카탈로그 판매가(공통 행)
    assert result["quote_draft"] is None
    # draft_replies.v3: 무역 문서 요약이 프롬프트에 들어간다.
    last_prompt = fake.calls[-1]
    assert "PI" in last_prompt and draft["doc_no"] in last_prompt and "USD" in last_prompt
    row = stored_document(database, result)
    assert row.run_id == result["run_id"] and row.deal_terms_id is not None
    candidates = stored_candidates(database, result)
    assert len(candidates) == 2 and all(
        c.kind == "quote" and c.trade_doc_id == row.id and c.quote_id is None for c in candidates)

    # 문서 확정(문서번호 입력) 뒤에만 발송 승인이 가능하다.
    access = approval_access(database)
    assert send_approved_trade_document(1, row.id, candidates[0].id, access=access, storage=storage).outcome == "needs_input"
    finalized = revise_trade_document(1, row.id, {"document_number": "V-100"}, database=database)
    assert finalized["status"] == "ready" and finalized["ready_for_issue"] is True

    outcome = send_approved_trade_document(1, row.id, candidates[0].id, access=access, storage=storage)
    assert outcome.outcome == "sent" and outcome.thread_id == "fake-thread"
    sends = access.google.mailbox.called("send")
    assert len(sends) == 1  # 재시도 없이 1회(승인 경로 규칙)
    assert sends[0][2] == 0
    raw_b64 = sends[0][1]["body"]["raw"]
    raw = urlsafe_b64decode(raw_b64 + "=" * (-len(raw_b64) % 4))
    mime = message_from_bytes(raw)
    assert mime["In-Reply-To"] == "<fake-message@example.invalid>"  # 같은 스레드 답장
    attached = [part for part in mime.walk() if part.get_filename()]
    assert [part.get_filename() for part in attached] == [f"{finalized['doc_no']}.pdf"]
    pdf = attached[0].get_payload(decode=True)
    assert pdf.startswith(b"%PDF-")
    with database.session() as session:
        document = session.get(TradeDocument, row.id)
        assert document.status == "sent" and document.sent_at is not None
        assert document.draft["status"] == "sent"
        sent_candidate = session.get(ReplyCandidate, candidates[0].id)
        assert sent_candidate.status == "sent"
        assert session.get(ReplyCandidate, candidates[1].id).status == "superseded"
        assert session.scalar(select(Approval).where(
            Approval.candidate_id == candidates[0].id)).send_status == "sent"
    # 이미 보낸 문서는 다시 보내지 않는다.
    assert send_approved_trade_document(1, row.id, candidates[0].id, access=access, storage=storage).outcome == "already_sent"


# ── PO: 매입가 적용·발행사(구매자) 검사 ───────────────────────────────────────

def test_po_flow_applies_purchase_price_and_issuer_buyer(database):
    storage = FakeStorage()
    put_settings(database, storage)
    email = trade_email(
        "PO 작성 요청",
        "Hello, we order Virtual Serum 100 PCS, currency KRW. Please create a PO. "
        "Incoterms FOB Busan, payment T/T.")
    # PO는 상대방(공급처)이 seller, 발행 회사가 buyer다(추출은 buyer를 비워 발행사 기본값으로 채운다).
    # 단가는 메일에 없고 카탈로그 매입가로 채운다(빈 값 추측 금지).
    extracted = trade_response(
        "PO", currency="KRW",
        buyer=party(None, None), seller=party("Acme Trading", "1 Fiction Ave, Seoul"),
        items=[item(unit_price=None, price_basis="per PCS",
                    source="Virtual Serum 100 PCS")])
    result, _ = run_flow(database, email, extracted)
    assert result["end_reason"] == "awaiting_approval"
    draft = result["trade_doc_draft"]
    assert draft["doc_kind"] == "PO"
    assert draft["buyer"]["legal_name"] == ISSUER_NAME  # PO 구매자는 발행 회사(발행사 기본값)
    assert draft["items"][0]["unit_price"] == "8000"  # 카탈로그 매입가
    assert draft["items"][0]["master_price"] is True
    assert not any("must be the issuing company" in issue for issue in draft["blocking_issues"])
    row = stored_document(database, result)
    finalized = revise_trade_document(1, row.id, {"document_number": "P-100"}, database=database)
    assert finalized["status"] == "ready" and finalized["total"] == "800000"
    access = approval_access(database)
    candidates = stored_candidates(database, result)
    assert send_approved_trade_document(1, row.id, candidates[0].id, access=access, storage=storage).outcome == "sent"
    with database.session() as session:
        assert session.get(TradeDocument, row.id).status == "sent"


# ── CI: 첨부 PI 가격 그대로·렌더 직전 ci_render_data ─────────────────────────────

def test_ci_flow_uses_pi_prices_without_catalog_substitution(database):
    storage = FakeStorage()
    put_settings(database, storage)
    email = trade_email(
        "CI 작성 요청",
        "Shipment S-1 cleared customs. Quoted from the received document: "
        "PI No. V-100, Virtual Serum 100 PCS at USD 8.00 per PCS, total USD 800.00.")
    extracted = trade_response(
        "CI", payment_terms=None, shipment_reference="S-1", country_of_origin="KR",
        source_document_type="PI", source_total="800.00",
        items=[item(unit_price="8.00", discount_percent="0", source_line_total="800.00")])
    result, _ = run_flow(database, email, extracted)
    assert result["end_reason"] == "awaiting_approval"
    draft = result["trade_doc_draft"]
    assert draft["doc_kind"] == "CI" and draft["_ci_from_pi"] is True  # PI 원문 근거
    assert draft["items"][0]["unit_price"] == "8.00"  # PI 거래가격 그대로(카탈로그 대체 금지)
    assert draft["total"] == "800.00"
    row = stored_document(database, result)
    finalized = revise_trade_document(1, row.id, {"document_number": "C-100"}, database=database)
    assert finalized["status"] == "ready"  # PI 근거·금액 일치로 생성 차단이 풀린다
    access = approval_access(database)
    candidates = stored_candidates(database, result)
    assert send_approved_trade_document(1, row.id, candidates[0].id, access=access, storage=storage).outcome == "sent"


def test_ci_without_pi_source_is_blocked_from_sending(database):
    storage = FakeStorage()
    put_settings(database, storage)
    email = trade_email(
        "CI 작성 요청",
        "Please prepare a CI for Virtual Serum 100 PCS at USD 8.00 per PCS. "
        "Incoterms FOB Busan, shipment S-2, origin KR.")
    extracted = trade_response(
        "CI", payment_terms=None, shipment_reference="S-2", country_of_origin="KR",
        items=[item(unit_price="8.00", discount_percent="0")])
    result, _ = run_flow(database, email, extracted)
    draft = result["trade_doc_draft"]
    assert draft.get("_ci_from_pi") is not True  # PI 원문 근거 없음
    assert any("attached PI" in issue for issue in draft["blocking_issues"])  # 생성 차단(계약 15.5절)
    row = stored_document(database, result)
    access = approval_access(database)
    candidates = stored_candidates(database, result)
    assert send_approved_trade_document(1, row.id, candidates[0].id, access=access, storage=storage).outcome == "needs_pi_source"
    assert access.google.mailbox.called("send") == []  # 보내지 않는다


# ── PL: 합계 승인(문서 확정)과 발송 승인 구분 ───────────────────────────────────

def test_pl_flow_requires_packing_approval_then_send(database):
    storage = FakeStorage()
    put_settings(database, storage)
    email = trade_email(
        "PL 작성 요청",
        "Please prepare a PL for shipment S-9. Virtual Serum 100 PCS in 10 cartons, "
        "net 50 kg, gross 60 kg, 1 CBM. Incoterms FOB Busan.")
    extracted = trade_response(
        "PL", currency=None, payment_terms=None, shipment_reference="S-9",
        container_count="1", actual_package_count="10",
        declared_total_quantity="100", declared_total_quantity_unit="PCS",
        declared_net_weight_kg="50", declared_gross_weight_kg="60", declared_volume_cbm="1",
        items=[item(source="Virtual Serum 100 PCS in 10 cartons",
                    package_type="CARTON", package_count="10", net_weight_kg="50",
                    gross_weight_kg="60", volume_cbm="1")])
    result, _ = run_flow(database, email, extracted)
    assert result["end_reason"] == "awaiting_approval"
    draft = result["trade_doc_draft"]
    assert draft["doc_kind"] == "PL" and draft["packing_totals"] is not None
    assert draft["packing_totals"]["approved"] is False  # 발송 전 합계 승인 필요(계약 15.6절)
    row = stored_document(database, result)
    access = approval_access(database)
    candidates = stored_candidates(database, result)
    # 문서번호(검토 입력) → PL 합계 승인 → 발송 승인 순서로만 갈 수 있다.
    assert send_approved_trade_document(1, row.id, candidates[0].id, access=access, storage=storage).outcome == "needs_input"
    finalized = revise_trade_document(1, row.id, {"document_number": "L-100"}, database=database)
    assert finalized["status"] == "ready"  # 차이가 없는 PL: 승인 없이 ready
    assert send_approved_trade_document(1, row.id, candidates[0].id, access=access, storage=storage).outcome == "needs_input"
    approved = approve_packing_totals(1, row.id, database=database)
    assert approved["packing_totals"]["approved"] is True  # 문서 확정 승인(원본 합계 보존)
    assert send_approved_trade_document(1, row.id, candidates[0].id, access=access, storage=storage).outcome == "sent"
    with database.session() as session:
        assert session.get(TradeDocument, row.id).status == "sent"


# ── 경로 보호: 무역 문서 후보는 일반 승인 경로로 보내지 않는다 ─────────────────────

def test_trade_candidate_cannot_be_sent_by_general_approval(database):
    storage = FakeStorage()
    put_settings(database, storage)
    email = trade_email(
        "PI 작성 요청",
        "Hello, this is Acme Trading. Please create a PI for Virtual Serum 100 PCS "
        "at USD 8.00 per PCS. Incoterms FOB Busan, payment T/T.")
    result, _ = run_flow(database, email, trade_response("PI", items=[item(unit_price="8.00")]))
    access = approval_access(database)
    candidates = stored_candidates(database, result)
    outcome = send_approved_candidate(1, candidates[0].id, access=access)
    assert outcome.outcome == "quote_only"  # 문서 확인 화면의 승인으로만 보낸다
    assert access.google.mailbox.called("send") == []


# ── 직인 없으면 발송 승인이 PDF 생성을 차단한다(원본 동작) ───────────────────────

def test_missing_seal_blocks_trade_send(database):
    storage = FakeStorage()
    put_settings(database, storage)
    with database.session() as session:  # 직인 연결만 지운다
        branding = session.get(CompanyBranding, 1)
        branding.seal_file_id = None
    email = trade_email(
        "PI 작성 요청",
        "Hello, this is Acme Trading. Please create a PI for Virtual Serum 100 PCS "
        "at USD 8.00 per PCS. Incoterms FOB Busan, payment T/T.")
    result, _ = run_flow(database, email, trade_response("PI", items=[item(unit_price="8.00")]))
    row = stored_document(database, result)
    revise_trade_document(1, row.id, {"document_number": "V-101"}, database=database)
    access = approval_access(database)
    candidates = stored_candidates(database, result)
    assert send_approved_trade_document(1, row.id, candidates[0].id, access=access, storage=storage).outcome == "needs_seal"
    assert access.google.mailbox.called("send") == []
    with database.session() as session:
        assert session.get(TradeDocument, row.id).status == "ready"  # 문서 상태는 그대로
        assert session.get(ReplyCandidate, candidates[0].id).status == "pending"


def test_seal_storage_failure_blocks_trade_send_without_fake_success(database):
    # 9절: Gmail 렌더 경로의 직인도 Storage에서 읽는다. 저장소를 못 읽으면 발송하지 않는다.
    storage = FakeStorage()
    put_settings(database, storage)
    email = trade_email(
        "PI 작성 요청",
        "Hello, this is Acme Trading. Please create a PI for Virtual Serum 100 PCS "
        "at USD 8.00 per PCS. Incoterms FOB Busan, payment T/T.")
    result, _ = run_flow(database, email, trade_response("PI", items=[item(unit_price="8.00")]))
    row = stored_document(database, result)
    revise_trade_document(1, row.id, {"document_number": "V-102"}, database=database)
    access = approval_access(database)
    candidates = stored_candidates(database, result)
    storage.download_error = StorageError("storage_unavailable", "파일 저장소에 연결하지 못했습니다.")
    outcome = send_approved_trade_document(1, row.id, candidates[0].id, access=access, storage=storage)
    assert outcome.outcome == "failed"
    assert access.google.mailbox.called("send") == []
    with database.session() as session:
        assert session.get(TradeDocument, row.id).status == "ready"  # 아직 claim하지 않았다
        assert session.get(ReplyCandidate, candidates[0].id).status == "pending"
    storage.download_error = None
    assert send_approved_trade_document(1, row.id, candidates[0].id, access=access, storage=storage).outcome == "sent"
