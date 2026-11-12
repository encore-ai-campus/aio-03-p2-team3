"""일회성 데이터 복사·대조 명령(app.db.copy_data) 검증(계획 4절).

대상은 conftest의 pgserver PostgreSQL, 원본은 가상 데이터를 넣은 SQLite 파일이다.
사용자·후보·기억·문서 버전·승인 관계·금액·timestamp·JSON·바이너리·PK/시퀀스가 보존되는지 본다.
"""
import sqlite3
from datetime import UTC, datetime

from sqlalchemy import func, select, text

from app.db.copy_data import main
from app.db.engine import Database
from app.db.migrations import upgrade_database
from app.db.models import (Approval, CompanyProfile, DealTerms, GoogleToken, PriceListItem, Quote,
                           ReplyCandidate, Run, RunEvent, ThreadMemory, ThreadMessage, TradeArtifact,
                           TradeDocument, TradeDocumentVersion, TradeProposal, User, UserPreference)

WHEN = datetime(2026, 11, 1, 9, 30, tzinfo=UTC)


def fill_source(path):
    """현재 스키마의 SQLite 원본에 소유자·외래 키로 이어진 대표 데이터를 넣는다."""
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    with db.session() as session:
        session.add(User(id=7, google_sub="copy-sub", email="copy@example.invalid", created_at=WHEN))
        session.flush()  # 나머지 행의 소유자 외래 키가 먼저 저장돼 있게 한다.
        session.add(GoogleToken(user_id=7, refresh_token_enc="enc-refresh", updated_at=WHEN))
        session.add(ThreadMessage(id=11, user_id=7, thread_id="t-1", gmail_message_id="gm-1",
                                  direction="in", from_addr="buyer@example.invalid",
                                  to_addrs=["copy@example.invalid"], subject="PO 요청", body_text="본문",
                                  sent_at=WHEN))
        session.add(ThreadMemory(user_id=7, thread_id="t-1", counterparty_email="buyer@example.invalid",
                                 summary="요약", confirmed_terms={"납기": "11/30"}, updated_at=WHEN))
        session.add(UserPreference(user_id=7, key="signature", value={"text": "감사합니다"}, updated_at=WHEN))
        session.add(CompanyProfile(user_id=7, company_name="가상 상사", legal_name_en="Virtual Trading Co",
                                   updated_at=WHEN))
        session.add(PriceListItem(id=31, user_id=7, item_name="세럼", unit="PCS", unit_price=1000,
                                  updated_at=WHEN))
        session.add(PriceListItem(id=32, user_id=7, item_name="세럼", unit="PCS", role="sale",
                                  currency="USD", unit_price_text="8.00", party_key="", updated_at=WHEN))
        session.add(DealTerms(id=41, user_id=7, thread_id="t-1", source_message_id="gm-1", run_id="run-1",
                              terms={"doc_kind": "PI", "items": [{"product_name": "세럼", "quantity": "100"}]},
                              missing_fields=[], required_source="code", created_at=WHEN))
        session.add(Quote(id=51, user_id=7, thread_id="t-1", run_id="run-1", quote_no="Q-20261101-1",
                          deal_terms_id=41, draft={"total": 800000, "items": [{"name": "세럼"}]},
                          status="ready", created_at=WHEN))
        session.add(ReplyCandidate(id=61, user_id=7, run_id="run-1", thread_id="t-1",
                                   source_message_id="gm-1", kind="quote", label="초안", subject="Re: PO 요청",
                                   body="본문", asks_fields=[], quote_id=51, status="approved",
                                   created_at=WHEN))
        session.flush()  # 승인 행의 외래 키가 가리키는 후보를 먼저 저장한다.
        session.add(Approval(id=71, user_id=7, candidate_id=61, approved_at=WHEN, send_status="sent"))
        session.add(TradeDocument(id=81, user_id=7, thread_id="t-1", run_id="run-1", doc_kind="PI",
                                  doc_no="PI-20261101-001", draft={"document_number": "PI-20261101-001"},
                                  revision=3, status="issued", sent_at=WHEN, created_at=WHEN))
        session.add(TradeDocumentVersion(document_id=81, revision=3, user_id=7,
                                         payload={"document_number": "PI-20261101-001"}, created_at=WHEN))
        session.flush()  # 제안·발급 파일의 외래 키가 가리키는 버전을 먼저 저장한다.
        session.add(TradeProposal(id="prop-0001", user_id=7, document_id=81, revision=3,
                                  payload={"document_number": "PI-20261101-001"}, content_hash="a" * 64,
                                  status="approved", decided_at=WHEN, logo=b"LOGO", seal=b"SEAL",
                                  created_at=WHEN))
        session.flush()  # 발급 파일의 외래 키가 가리키는 제안을 먼저 저장한다.
        session.add(TradeArtifact(id="file-0001", user_id=7, proposal_id="prop-0001", file_format="pdf",
                                  filename="PI.pdf", media_type="application/pdf", content_hash="b" * 64,
                                  content=b"%PDF-fake", created_at=WHEN))
        session.add(Run(run_id="run-1", user_id=7, mode="live", message_id="gm-1", thread_id="t-1",
                        reflection_enabled=True, started_at=WHEN, ended_at=WHEN,
                        end_reason="awaiting_approval", duration_ms=1200))
        session.add(RunEvent(id=72, run_id="run-1", seq=0, at=WHEN, event="run_start",
                             detail={"mode": "live"}, duration_ms=None))
    db.close()


def make_old_source(path):
    """스키마가 앱보다 오래된 SQLite 원본(역사적 국내 견적 스키마)."""
    db = Database(f"sqlite:///{path}")
    with db.engine.begin() as connection:
        User.__table__.create(connection)
        connection.exec_driver_sql("""CREATE TABLE price_list_items (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), updated_at DATETIME NOT NULL,
            item_name VARCHAR NOT NULL, unit VARCHAR, unit_price BIGINT NOT NULL, UNIQUE(user_id,item_name))""")
        connection.exec_driver_sql(
            "INSERT INTO users (id,google_sub,email,created_at,reflection_enabled) VALUES"
            " (1,'legacy-sub','legacy@example.invalid','2026-11-10 00:00:00',1)")
        connection.exec_driver_sql(
            "INSERT INTO price_list_items (id,user_id,updated_at,item_name,unit,unit_price) VALUES"
            " (5,1,'2026-11-10 00:00:00','Old Product','PCS',100)")
    db.close()


def count(database, table):
    with database.engine.connect() as connection:
        return connection.execute(select(func.count()).select_from(table)).scalar_one()


def test_copy_needs_confirmation_and_dry_run_writes_nothing(tmp_path, database_url, capsys):
    source = tmp_path / "legacy.sqlite3"
    fill_source(source)
    target = Database(database_url)
    upgrade_database(target.engine)  # 대상 스키마는 서버 시작 migration으로 이미 만들어져 있다.
    assert main(["--source", str(source), "--target", database_url]) == 2
    assert "--yes" in capsys.readouterr().out
    assert main(["--source", str(source), "--target", database_url, "--dry-run"]) == 0
    assert "dry-run" in capsys.readouterr().out
    assert count(target, User.__table__) == 0
    assert count(target, Quote.__table__) == 0


def test_copy_preserves_data_and_is_repeatable(tmp_path, database_url, capsys):
    source = tmp_path / "legacy.sqlite3"
    fill_source(source)
    assert main(["--source", str(source), "--target", database_url, "--yes"]) == 0
    assert "대조 통과" in capsys.readouterr().out
    target = Database(database_url)
    with target.session() as session:
        user = session.get(User, 7)
        assert user.email == "copy@example.invalid" and user.created_at == WHEN
        assert session.get(GoogleToken, 7).refresh_token_enc == "enc-refresh"
        assert session.get(ThreadMessage, 11).to_addrs == ["copy@example.invalid"]
        assert session.get(ThreadMemory, (7, "t-1")).confirmed_terms == {"납기": "11/30"}
        assert session.get(UserPreference, (7, "signature")).value == {"text": "감사합니다"}
        assert session.get(CompanyProfile, 7).legal_name_en == "Virtual Trading Co"
        domestic, trade = session.get(PriceListItem, 31), session.get(PriceListItem, 32)
        assert (domestic.unit_price, domestic.unit_price_text) == (1000, None)
        assert (trade.unit_price, trade.unit_price_text) == (None, "8.00")
        assert session.get(DealTerms, 41).terms["items"][0]["quantity"] == "100"
        assert session.get(Quote, 51).draft["total"] == 800000
        candidate = session.get(ReplyCandidate, 61)
        assert candidate.quote_id == 51 and candidate.status == "approved"
        assert session.get(Approval, 71).candidate_id == 61
        document = session.get(TradeDocument, 81)
        assert document.revision == 3 and document.draft["document_number"] == "PI-20261101-001"
        assert session.get(TradeDocumentVersion, (81, 3)) is not None
        proposal = session.get(TradeProposal, "prop-0001")
        assert proposal.seal == b"SEAL" and proposal.status == "approved"
        assert session.get(TradeArtifact, "file-0001").content == b"%PDF-fake"
        assert session.get(Run, "run-1").duration_ms == 1200
        assert session.get(RunEvent, 72).detail == {"mode": "live"}
    with target.engine.connect() as connection:  # PK/sequence
        for table, column, maximum in (("users", "id", 7), ("quotes", "id", 51), ("run_events", "id", 72)):
            sequence = connection.execute(text("SELECT pg_get_serial_sequence(:t, :c)"),
                                          {"t": table, "c": column}).scalar_one()
            assert connection.execute(text(f"SELECT last_value, is_called FROM {sequence}")).one() == (maximum, True)
    assert main(["--source", str(source), "--target", database_url, "--yes"]) == 0
    assert "이미 복사됨" in capsys.readouterr().out
    assert count(target, User.__table__) == 1
    target.close()


def test_copy_failure_rolls_back_and_rerun_succeeds(tmp_path, database_url, monkeypatch, capsys):
    from app.db import copy_data

    source = tmp_path / "legacy.sqlite3"
    fill_source(source)
    real_insert = copy_data._insert_rows

    def failing_insert(connection, table, rows):
        if table.name == "quotes":  # users·단가표를 지난 뒤 실패한다.
            raise RuntimeError("가짜 복사 실패")
        real_insert(connection, table, rows)

    monkeypatch.setattr(copy_data, "_insert_rows", failing_insert)
    assert main(["--source", str(source), "--target", database_url, "--yes"]) == 1
    assert "롤백" in capsys.readouterr().out
    target = Database(database_url)
    assert count(target, User.__table__) == 0
    assert count(target, PriceListItem.__table__) == 0
    assert count(target, Quote.__table__) == 0
    monkeypatch.undo()
    assert main(["--source", str(source), "--target", database_url, "--yes"]) == 0
    assert "대조 통과" in capsys.readouterr().out
    assert count(target, User.__table__) == 1
    target.close()


def test_copy_refuses_to_merge_into_used_target(tmp_path, database_url, capsys):
    source = tmp_path / "legacy.sqlite3"
    fill_source(source)
    assert main(["--source", str(source), "--target", database_url, "--yes"]) == 0
    capsys.readouterr()
    target = Database(database_url)
    with target.session() as session:
        session.add(User(id=99, google_sub="other-sub", email="other@example.invalid"))
    assert main(["--source", str(source), "--target", database_url, "--yes"]) == 1
    out = capsys.readouterr().out
    assert "합쳐 쓰지" in out and "users" in out
    assert count(target, User.__table__) == 2  # 대상은 그대로다(합침 없음).
    target.close()


def test_copy_upgrades_old_sqlite_file_on_temporary_copy(tmp_path, database_url, capsys):
    source = tmp_path / "old.sqlite3"
    make_old_source(source)
    assert main(["--source", str(source), "--target", database_url, "--yes"]) == 0
    out = capsys.readouterr().out
    assert "임시 사본" in out and "대조 통과" in out
    target = Database(database_url)
    with target.session() as session:
        assert session.get(User, 1).email == "legacy@example.invalid"
        assert session.get(PriceListItem, 5).unit_price == 100
    # 원본 파일은 갱신되지 않았다(스키마가 그대로 옛 모양).
    connection = sqlite3.connect(source)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    columns = {row[1] for row in connection.execute("PRAGMA table_info(price_list_items)")}
    connection.close()
    assert "alembic_version" not in tables and "role" not in columns
    target.close()


def test_old_sqlite_url_source_is_rejected_with_gap_report(tmp_path, database_url, capsys):
    source = tmp_path / "old.sqlite3"
    make_old_source(source)
    assert main(["--source", f"sqlite:///{source}", "--target", database_url, "--yes"]) == 2
    out = capsys.readouterr().out
    assert "스키마가 앱보다 오래" in out and "price_list_items" in out


def test_non_postgres_target_is_rejected(tmp_path, database_url, capsys):
    source = tmp_path / "legacy.sqlite3"
    fill_source(source)
    assert main(["--source", str(source), "--target", "sqlite:///tmp/x.db", "--yes"]) == 2
    assert "대상 오류" in capsys.readouterr().out
