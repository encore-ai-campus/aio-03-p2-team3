"""기존 DB와 기존 서비스 경로에서 재현된 갱신·가격·발송 회귀를 확인한다."""
from unittest.mock import patch

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.db.engine import Database
from app.db.migrations import upgrade_database
from app.db.models import CompanyProfile, PriceListItem, ReplyCandidate, TradeDocument, User
from app.services.approval import send_approved_trade_document
from app.services.trade_docs import revise_trade_document
from tests.test_trade_flow import (
    approval_access, item, put_settings, run_flow, stored_candidates, trade_email, trade_response,
)


def test_existing_database_preserves_rows_and_replaces_price_constraint():
    db = Database("sqlite://")
    with db.engine.begin() as connection:
        User.__table__.create(connection)
        connection.exec_driver_sql("""CREATE TABLE company_profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id), updated_at DATETIME NOT NULL,
            company_name VARCHAR, business_no VARCHAR, ceo_name VARCHAR, contact VARCHAR)""")
        connection.exec_driver_sql("""CREATE TABLE price_list_items (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), updated_at DATETIME NOT NULL,
            item_name VARCHAR NOT NULL, unit VARCHAR, unit_price BIGINT NOT NULL, UNIQUE(user_id,item_name))""")
        connection.exec_driver_sql("""CREATE TABLE reply_candidates (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created_at DATETIME NOT NULL,
            run_id VARCHAR NOT NULL, thread_id VARCHAR NOT NULL, source_message_id VARCHAR NOT NULL,
            kind VARCHAR NOT NULL, label VARCHAR NOT NULL, subject VARCHAR NOT NULL, body TEXT NOT NULL,
            asks_fields JSON NOT NULL, needs_review BOOLEAN NOT NULL, notice VARCHAR, quote_id INTEGER,
            status VARCHAR NOT NULL)""")
        connection.exec_driver_sql("""INSERT INTO users
            (id,google_sub,email,created_at,reflection_enabled) VALUES
            (1,'legacy-sub','legacy@example.invalid','2026-11-10 00:00:00',1)""")
        connection.exec_driver_sql("""INSERT INTO company_profiles
            (user_id,updated_at,company_name) VALUES (1,'2026-11-10 00:00:00','Legacy Trading')""")
        connection.exec_driver_sql("""INSERT INTO price_list_items
            (id,user_id,updated_at,item_name,unit,unit_price)
            VALUES (1,1,'2026-11-10 00:00:00','Legacy Product','PCS',100)""")
        connection.exec_driver_sql("""INSERT INTO reply_candidates
            (id,user_id,created_at,run_id,thread_id,source_message_id,kind,label,subject,body,
             asks_fields,needs_review,status) VALUES
            (1,1,'2026-11-10 00:00:00','r1','t1','m1','general','reply','test','body','[]',0,'pending')""")
    db.create_tables()
    upgrade_database(db.engine)  # 재시작과 반복 실행에도 같은 데이터·제약을 유지한다.
    with db.session() as session:
        assert session.get(CompanyProfile, 1).company_name == "Legacy Trading"
        assert session.get(ReplyCandidate, 1).trade_doc_id is None
        assert session.get(PriceListItem, 1).unit_price == 100
        session.add(PriceListItem(user_id=1, item_name="Legacy Product", role="sale", currency="USD",
                                  party_key="", unit_price_text="8.00"))
    with pytest.raises(IntegrityError):
        with db.session() as session:
            session.add(PriceListItem(user_id=1, item_name="Legacy Product", unit_price=200))
    with db.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    assert "revision" in {column["name"] for column in inspect(db.engine).get_columns("trade_documents")}
    db.close()


def ready_pi(database):
    put_settings(database)
    response, _ = run_flow(database, trade_email(
        "PI 작성 요청", "PI Virtual Serum 100 PCS at USD 8.00 per PCS. FOB Busan, payment T/T."),
        trade_response("PI", items=[item(unit_price="8.00")]))
    document_id = response["trade_doc_draft"]["trade_doc_id"]
    revised = revise_trade_document(1, document_id, {"document_number": "V-100"}, database=database)
    assert revised["status"] == "ready"
    return response, document_id


def test_currency_revision_invalidates_old_verified_price(database):
    _, document_id = ready_pi(database)
    revised = revise_trade_document(1, document_id, {"currency": "KRW"}, database=database)
    assert revised["status"] == "needs_input"
    assert revised["items"][0].get("master_price") is not True
    assert revised["items"][0]["unit_price"] is None
    assert any("KRW catalog price" in issue for issue in revised["blocking_issues"])


def test_counterparty_price_fallback_is_per_product():
    from app.trade.pricing import apply_verified_catalog_prices, build_trade_catalog
    catalog = build_trade_catalog([
        {"id": 1, "role": "sale", "item_name": "Alpha Cream", "capacity": "50ml", "currency": "USD",
         "unit_price_text": "10", "party_key": "Acme Trading", "price_basis": "PCS"},
        {"id": 2, "role": "sale", "item_name": "Beta Serum", "capacity": "30ml", "currency": "USD",
         "unit_price_text": "20", "party_key": "", "price_basis": "PCS"},
    ])
    draft = {"document_type": "PI", "currency": "USD", "product_family": "cosmetics",
             "buyer": {"legal_name": "Acme Trading"}, "items": [
                 {"product_name": "Alpha Cream", "capacity": "50ml"},
                 {"product_name": "Beta Serum", "capacity": "30ml"}]}
    apply_verified_catalog_prices(draft, catalog)
    assert [line["unit_price"] for line in draft["items"]] == ["10", "20"]
    assert draft["missing_fields"] == []


def test_item_identity_revision_does_not_keep_previous_price(database):
    _, document_id = ready_pi(database)
    revised = revise_trade_document(1, document_id, {"items.0.product_name": "Different Product"}, database=database)
    assert revised["status"] == "needs_input"
    assert revised["items"][0].get("master_price") is not True
    assert revised["items"][0]["unit_price"] is None


def test_stale_revision_and_server_fields_cannot_be_overwritten(database):
    _, document_id = ready_pi(database)
    assert revise_trade_document(1, document_id, {"document_number": "V-STALE"}, database=database,
                                  expected_revision=1) is None
    for key in ("packing_totals.approved", "items.0.master_price", "_ci_from_pi", "revision", "status"):
        with pytest.raises(ValueError):
            revise_trade_document(1, document_id, {key: "true"}, database=database)


def test_edit_between_pdf_snapshot_and_claim_cannot_send_stale_document(database):
    response, document_id = ready_pi(database)
    access = approval_access(database)
    candidate = stored_candidates(database, response)[0]

    def render_and_edit(access, user_id, draft):
        assert draft["document_number"] == "V-100"
        assert revise_trade_document(user_id, document_id, {"document_number": "V-CHANGED"}, database=database)
        return b"%PDF-fake"

    with patch("app.services.approval._trade_pdf", side_effect=render_and_edit):
        outcome = send_approved_trade_document(1, document_id, candidate.id, access=access)
    assert outcome.outcome == "document_changed"
    assert access.google.mailbox.called("send") == []
    with database.session() as session:
        assert session.get(ReplyCandidate, candidate.id).status == "pending"
        document = session.get(TradeDocument, document_id)
        assert document.status == "ready" and document.draft["document_number"] == "V-CHANGED"


def test_sending_document_is_not_editable_and_failed_send_releases_claim(database):
    response, document_id = ready_pi(database)
    access = approval_access(database)
    candidate = stored_candidates(database, response)[0]
    from app.services.approval import _send

    def send_while_editing(access, user_id, claimed, **options):
        assert revise_trade_document(user_id, document_id, {"document_number": "FORBIDDEN"}, database=database) is None
        return _send(access, user_id, claimed, **options)

    with patch("app.services.approval._send", side_effect=send_while_editing):
        outcome = send_approved_trade_document(1, document_id, candidate.id, access=access)
    assert outcome.outcome == "sent"
    with database.session() as session:
        assert session.get(TradeDocument, document_id).draft["document_number"] == "V-100"
