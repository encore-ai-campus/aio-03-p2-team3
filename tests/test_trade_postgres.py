"""실제 PostgreSQL 검사. pgserver가 개발 의존성이라 `uv run pytest`에 항상 포함된다(3절).

발급 파일 Storage 전환(계획 10절)의 실패 행렬도 여기서 검증한다: 일부 형식 업로드 실패,
업로드 뒤 revision 변경, SQL 확정 실패, 존재하는 key의 해시 불일치, 다운로드 장애, backfill.
"""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Barrier, Event

import pytest
from sqlalchemy import func, inspect, select, update
from sqlalchemy.exc import IntegrityError

from app.db.engine import Database
from app.db.migrations import upgrade_database
from app.db.models import (CompanyProfile, PriceListItem, ReplyCandidate, TradeArtifact, TradeDocument,
                           TradeProposal, User, utcnow)
from app.files import cleanup
from app.trade.review.backfill import backfill as issued_backfill
from app.trade.review.repository import SQLReviews, issued_object_key
from tests.fakes.storage import FakeStorage, storage_error
from tests.test_pi_api import configured_client, create_pi, decide, propose


def test_existing_postgres_data_and_constraints_are_upgraded(database_url):
    db = Database(database_url)
    try:
        with db.engine.begin() as connection:
            User.__table__.create(connection)
            connection.exec_driver_sql("""CREATE TABLE company_profiles (
                user_id INTEGER PRIMARY KEY REFERENCES users(id), updated_at TIMESTAMPTZ NOT NULL,
                company_name VARCHAR, business_no VARCHAR, ceo_name VARCHAR, contact VARCHAR)""")
            connection.exec_driver_sql("""CREATE TABLE price_list_items (
                id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), updated_at TIMESTAMPTZ NOT NULL,
                item_name VARCHAR NOT NULL, unit VARCHAR, unit_price BIGINT NOT NULL, UNIQUE(user_id,item_name))""")
            connection.exec_driver_sql("""CREATE TABLE reply_candidates (
                id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL,
                run_id VARCHAR NOT NULL, thread_id VARCHAR NOT NULL, source_message_id VARCHAR NOT NULL,
                kind VARCHAR NOT NULL, label VARCHAR NOT NULL, subject VARCHAR NOT NULL, body TEXT NOT NULL,
                asks_fields JSONB NOT NULL, needs_review BOOLEAN NOT NULL, notice VARCHAR, quote_id INTEGER,
                status VARCHAR NOT NULL)""")
            connection.execute(User.__table__.insert().values(
                id=1, google_sub="legacy-sub", email="legacy@example.invalid"))
            connection.exec_driver_sql("""INSERT INTO company_profiles
                (user_id,updated_at,company_name) VALUES (1,now(),'Legacy Trading')""")
            connection.exec_driver_sql("""INSERT INTO price_list_items
                (user_id,updated_at,item_name,unit_price) VALUES (1,now(),'Legacy Product',100)""")
            connection.exec_driver_sql("""INSERT INTO reply_candidates
                (user_id,created_at,run_id,thread_id,source_message_id,kind,label,subject,body,
                 asks_fields,needs_review,status) VALUES
                (1,now(),'r1','t1','m1','general','reply','test','body','[]',false,'pending')""")
        db.create_tables()
        upgrade_database(db.engine)
        with db.session() as session:
            assert session.get(CompanyProfile, 1).company_name == "Legacy Trading"
            assert session.get(PriceListItem, 1).unit_price == 100
            assert session.get(ReplyCandidate, 1).trade_doc_id is None
            session.add(PriceListItem(user_id=1, item_name="Legacy Product", role="sale", currency="USD",
                                      party_key="", unit_price_text="8.00"))
        assert "revision" in {column["name"] for column in inspect(db.engine).get_columns("trade_documents")}
    finally:
        db.close()


def test_postgres_pi_api_and_concurrent_approval_without_shared_python_lock(database_url):
    from app.trade.pi.operations import check_pi_for_review
    from app.trade.pi.rendering import render_pi_files
    from app.trade.review.models import Decision, ReviewRequest
    from app.trade.review.operations import decide, propose
    from app.trade.review.repository import SQLReviews
    from tests.test_pi_api import configured_client, create_pi, test_pi_http_end_to_end_approval_and_idempotent_download

    with configured_client(database_url) as client:
        test_pi_http_end_to_end_approval_and_idempotent_download(client)
        database = client.app.state.database
        document = create_pi(client)
        first_repository = SQLReviews(database, 1, "PI", storage=client.app.state.storage)
        proposal = propose(document["document_id"], ReviewRequest(revision=1), repository=first_repository,
                           check_document=check_pi_for_review)
        second_database = Database(database_url)
        second_database.create_tables()
        second_repository = SQLReviews(second_database, 1, "PI", storage=client.app.state.storage)
        barrier = Barrier(2)
        choice = Decision(action="approve", revision=1, content_hash=proposal["content_hash"])

        def render_together(payload, branding):
            barrier.wait(timeout=10)
            return render_pi_files(payload, branding)

        def approve(repository):
            return decide(proposal["id"], document["document_id"], choice,
                          repository=repository, renderer=render_together)

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(approve, repository) for repository in (first_repository, second_repository)]
                results = [future.result(timeout=15) for future in futures]
            assert all(result["status"] == "approved" for result in results)
            assert results[0]["files"] == results[1]["files"]
            storage = client.app.state.storage
            with database.session() as session:
                rows = session.scalars(select(TradeArtifact)).all()
                assert len(rows) == 4  # 두 문서 × 두 형식, 한 제안/형식당 한 파일 참조
                assert all(row.content is None for row in rows)  # 새 승인은 DB에 bytes를 두지 않는다(10절)
                assert len({row.object_key for row in rows}) == 4
                for row in rows:
                    assert row.object_key.startswith("1/issued/") and row.size_bytes == len(storage.objects[row.object_key])
                    assert sha256(storage.objects[row.object_key]).hexdigest() == row.content_hash
        finally:
            second_database.close()


def test_postgres_po_ci_pl_full_http_flows(database_url):
    from app.auth.deps import current_user_id
    from tests.test_pi_api import configured_client
    from tests.test_trade_domain_api import test_each_domain_cancel_modify_approve_download_and_version_history

    with configured_client(database_url) as client:
        for kind in ("po", "ci", "pl"):
            client.app.dependency_overrides[current_user_id] = lambda: 1
            test_each_domain_cancel_modify_approve_download_and_version_history(client, kind)


def issued_uploads(storage) -> list[str]:
    return [key for method, key in storage.calls
            if method == "upload" and "/issued/" in key]


@pytest.mark.parametrize("corrupted", [False, True])
def test_concurrent_storage_upload_reuses_only_matching_bytes(database_url, corrupted):
    """다른 서버가 먼저 올린 객체는 해시가 같은 경우에만 재사용한다."""
    from app.files.storage import StorageError

    with configured_client(database_url) as client:
        created = create_pi(client)
        proposal = propose(client, created)
        storage = client.app.state.storage
        upload = storage.upload

        def another_server_uploads_first(key, data, content_type):
            if "/issued/" in key:
                upload(key, b"changed" if corrupted else data, content_type)
                raise StorageError("object_exists", "이미 저장된 객체", status_code=409)
            upload(key, data, content_type)

        storage.upload = another_server_uploads_first
        response = decide(client, proposal, "approve")
        assert response.status_code == (503 if corrupted else 200)
        if corrupted:
            assert response.json()["error"]["code"] == "ARTIFACT_CORRUPTED"
        else:
            assert len(response.json()["files"]) == 2


def test_postgres_partial_format_upload_failure_keeps_pending_and_retry_reuses_object(database_url):
    """PDF 업로드만 성공하고 XLSX가 실패하면 승인은 안 된다. 재시도는 PDF 객체를 재사용한다."""
    with configured_client(database_url) as client:
        database, storage = client.app.state.database, client.app.state.storage
        created = create_pi(client)
        proposal = propose(client, created)
        original_upload = storage.upload

        def fail_xlsx(object_key, data, content_type):
            if "/xlsx/" in object_key:
                raise storage_error("가짜 XLSX 업로드 실패")
            return original_upload(object_key, data, content_type)

        storage.upload = fail_xlsx
        try:
            failed = decide(client, proposal, "approve")
        finally:
            storage.upload = original_upload
        assert failed.status_code == 503 and failed.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
        with database.session() as session:
            assert session.get(TradeProposal, proposal["id"]).status == "pending"
            assert session.get(TradeDocument, created["document_id"]).status == "ready"
            assert session.scalar(select(func.count()).select_from(TradeArtifact)) == 0

        approved = decide(client, proposal, "approve")  # Storage가 회복되면 같은 제안으로 재시도
        assert approved.status_code == 200, approved.text
        assert len(approved.json()["files"]) == 2
        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(TradeArtifact)) == 2
        assert sorted(issued_uploads(storage)) == sorted(set(issued_uploads(storage)))  # 재시도는 새 업로드 없이 재사용
        assert len(set(issued_uploads(storage))) == 2


def test_postgres_upload_then_revision_change_keeps_pending_and_leaves_orphan(database_url):
    """모든 형식을 올린 뒤 문서 revision이 바뀌면 확정은 실패한다. SQL에 기록되지 않은 객체는
    발급 파일로 노출하지 않고 미참조로 남는다."""
    with configured_client(database_url) as client:
        database, storage = client.app.state.database, client.app.state.storage
        created = create_pi(client)
        proposal = propose(client, created)
        original_upload = storage.upload
        bumped = False

        def upload_and_bump_revision(object_key, data, content_type):
            nonlocal bumped
            if not bumped and "/issued/" in object_key:  # 업로드와 SQL 확정 사이에 다른 연결이 수정한다
                bumped = True
                with Database(database_url).session() as session:
                    session.execute(update(TradeDocument).where(
                        TradeDocument.id == created["document_id"]).values(revision=2))
            return original_upload(object_key, data, content_type)

        storage.upload = upload_and_bump_revision
        try:
            conflict = decide(client, proposal, "approve")
        finally:
            storage.upload = original_upload
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "REVISION_CONFLICT"
        with database.session() as session:
            assert session.get(TradeProposal, proposal["id"]).status == "pending"
            document = session.get(TradeDocument, created["document_id"])
            assert document.status == "ready" and document.revision == 2
            assert session.scalar(select(func.count()).select_from(TradeArtifact)) == 0
        orphans = {row["key"] for row in cleanup.unreferenced_objects(database, storage)}
        assert orphans == {key for key in storage.objects if "/issued/" in key} and orphans


def test_postgres_approval_sql_failure_rolls_back_and_retry_reuses_objects(database_url):
    """SQL 확정 단계 실패(유일 제약 충돌)는 롤백해 ready/pending을 유지한다. 재시도는 올려둔
    객체를 그대로 재사용해 확정한다."""
    from app.trade.pi.rendering import render_pi_files

    with configured_client(database_url) as client:
        database, storage = client.app.state.database, client.app.state.storage
        created = create_pi(client)
        proposal = propose(client, created)
        with database.session() as session:  # 확정을 실패시킬 같은 (제안, 형식) 행을 미리 둔다
            session.add(TradeArtifact(id="conflicting", user_id=1, proposal_id=proposal["id"],
                                      file_format="pdf", filename="PI.pdf", media_type="application/pdf",
                                      content_hash="c" * 64, content=b"%PDF-fake"))
        repository = SQLReviews(database, 1, "PI", storage=storage)
        files = render_pi_files(proposal["payload"],
                                repository.proposal_branding(repository.get(proposal["id"])))
        with pytest.raises(IntegrityError):
            repository.approve(proposal["id"], proposal["revision"], proposal["content_hash"], files)
        with database.session() as session:
            assert session.get(TradeProposal, proposal["id"]).status == "pending"
            assert session.get(TradeDocument, created["document_id"]).status == "ready"
            assert session.scalars(select(TradeArtifact.id)).all() == ["conflicting"]  # 승인 행은 롤백
        with database.session() as session:
            session.delete(session.get(TradeArtifact, "conflicting"))

        uploads_before = set(issued_uploads(storage))
        approved = decide(client, proposal, "approve")
        assert approved.status_code == 200, approved.text
        assert set(issued_uploads(storage)) == uploads_before  # 재시도는 새 업로드 없이 재사용
        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(TradeArtifact)) == 2


def test_postgres_existing_issued_key_with_different_bytes_fails(database_url):
    """결정적 key에 서로 다른 bytes가 있으면 승인을 실패시킨다(덮어쓰지 않는다)."""
    from app.trade.pi.rendering import render_pi_files

    with configured_client(database_url) as client:
        database, storage = client.app.state.database, client.app.state.storage
        created = create_pi(client)
        proposal = propose(client, created)
        repository = SQLReviews(database, 1, "PI", storage=storage)
        files = render_pi_files(proposal["payload"],
                                repository.proposal_branding(repository.get(proposal["id"])))
        pdf = next(file for file in files if file.file_format == "pdf")
        key = issued_object_key(1, proposal["id"], "pdf", sha256(pdf.content).hexdigest())
        storage.objects[key] = b"tampered issued bytes"
        response = decide(client, proposal, "approve")
        assert response.status_code == 503 and response.json()["error"]["code"] == "ARTIFACT_CORRUPTED"
        assert storage.objects[key] == b"tampered issued bytes"  # 있던 bytes를 덮어쓰지 않는다
        with database.session() as session:
            assert session.get(TradeProposal, proposal["id"]).status == "pending"
            assert session.scalar(select(func.count()).select_from(TradeArtifact)) == 0


def test_postgres_issued_download_storage_failures_and_idempotent_retry(database_url):
    """다운로드 장애·변조는 성공으로 돌려주지 않고, 재승인은 Storage를 읽지 않고 같은 파일을 돌려준다."""
    with configured_client(database_url) as client:
        database, storage = client.app.state.database, client.app.state.storage
        created = create_pi(client)
        approved = decide(client, propose(client, created), "approve").json()
        [pdf] = [file for file in approved["files"] if file["file_format"] == "pdf"]
        with database.session() as session:
            key = session.get(TradeArtifact, pdf["id"]).object_key

        storage.download_error = storage_error()
        unavailable = client.get(pdf["download_url"])
        assert unavailable.status_code == 503 and unavailable.json()["error"]["code"] == "STORAGE_UNAVAILABLE"

        storage.download_error = None
        original, storage.objects[key] = storage.objects[key], b"tampered"
        corrupted = client.get(pdf["download_url"])
        assert corrupted.status_code == 503 and corrupted.json()["error"]["code"] == "ARTIFACT_CORRUPTED"

        storage.objects[key] = original
        download = client.get(pdf["download_url"])
        assert download.status_code == 200 and sha256(download.content).hexdigest() == pdf["content_hash"]

        downloads_before = [call for call in storage.calls if call[0] == "download"]
        repeated = decide(client, approved, "approve")  # 응답 유실 재요청
        assert repeated.status_code == 200 and repeated.json()["files"] == approved["files"]
        assert [call for call in storage.calls if call[0] == "download"] == downloads_before


def test_postgres_issued_backfill_moves_legacy_bytes_and_rerun_verifies(database_url):
    """10절 이전 옛 발급 파일을 결정적 key로 옮기고 byte 해시를 검증한다. 반복 실행은 안전하다."""
    with configured_client(database_url) as client:
        database = client.app.state.database
        created = create_pi(client)
        proposal = propose(client, created)
        legacy = b"%PDF-legacy"
        digest = sha256(legacy).hexdigest()
        with database.session() as session:  # 10절 이전 상태: bytes가 DB에만 있고 제안은 승인
            session.execute(update(TradeProposal).where(TradeProposal.id == proposal["id"]).values(
                status="approved", decision="approve", decided_at=utcnow()))
            session.execute(update(TradeDocument).where(TradeDocument.id == created["document_id"]).values(
                status="issued"))
            session.add(TradeArtifact(id="legacyfile", user_id=1, proposal_id=proposal["id"], file_format="pdf",
                                      filename="PI.pdf", media_type="application/pdf",
                                      content_hash=digest, content=legacy))
            session.add(TradeArtifact(id="brokenfile", user_id=1, proposal_id=proposal["id"], file_format="xlsx",
                                      filename="PI.xlsx", media_type="spreadsheetml", content_hash="0" * 64,
                                      content=b"broken"))

        storage = FakeStorage()
        legacy_repository = SQLReviews(database, 1, "PI", storage=storage)
        assert legacy_repository.file("legacyfile")["content"] == legacy  # backfill 전엔 DB bytes로 내려받는다

        plan = issued_backfill(database, storage)  # dry-run은 계획만 보고 상태를 바꾸지 않는다
        assert plan["linked"] == 1 and plan["uploaded"] == 0 and plan["verified"] == 0
        assert plan["skipped"] == ["TradeArtifact brokenfile: bytes 해시가 기록과 다릅니다"]
        with database.session() as session:
            assert session.get(TradeArtifact, "legacyfile").object_key is None
        assert storage.objects == {}

        done = issued_backfill(database, storage, confirmed=True)
        assert done["linked"] == 1 and done["uploaded"] == 1 and done["verified"] == 1
        assert done["skipped"] == plan["skipped"]
        with database.session() as session:
            row = session.get(TradeArtifact, "legacyfile")
            assert row.object_key == issued_object_key(1, proposal["id"], "pdf", digest)
            assert row.size_bytes == len(legacy)
            assert row.content == legacy  # 바이너리 열은 22절까지 보존한다
            assert session.get(TradeArtifact, "brokenfile").object_key is None
        assert storage.objects[row.object_key] == legacy
        assert sha256(legacy_repository.file("legacyfile")["content"]).hexdigest() == digest  # Storage 읽기

        again = issued_backfill(database, storage, confirmed=True)  # 반복 실행은 검증만 한다
        assert again["linked"] == 0 and again["uploaded"] == 0 and again["verified"] == 1
        assert again["skipped"] == plan["skipped"]


def test_cleanup_waits_for_reused_issued_object_to_be_committed(database_url, monkeypatch):
    """오래된 orphan을 재승인이 재사용하는 동안 정리가 승인 파일을 지우면 안 된다."""
    with configured_client(database_url) as client:
        database, storage = client.app.state.database, client.app.state.storage
        created = create_pi(client)
        proposal = propose(client, created)
        upload = storage.upload
        def partial(key, data, media_type):
            if "/xlsx/" in key:
                raise storage_error()
            upload(key, data, media_type)
        storage.upload = partial
        assert decide(client, proposal, "approve").status_code == 503
        storage.upload = upload
        [key] = issued_uploads(storage)
        storage.age_object(key, 48)
        reading, release, listed = Event(), Event(), Event()
        download = storage.download
        def paused_download(object_key):
            if object_key == key:
                reading.set()
                assert release.wait(10)
            return download(object_key)
        storage.download = paused_download
        unreferenced = cleanup.unreferenced_objects
        def list_then_signal(*args):
            result = unreferenced(*args)
            listed.set()
            return result
        monkeypatch.setattr(cleanup, "unreferenced_objects", list_then_signal)
        with ThreadPoolExecutor(max_workers=2) as pool:
            approving = pool.submit(decide, client, proposal, "approve")
            try:
                assert reading.wait(10)
                cleaning = pool.submit(cleanup.execute, database, storage, delete=True, confirmed=True)
                assert listed.wait(10)
            finally:
                release.set()
            assert approving.result(timeout=15).status_code == 200
            assert cleaning.result(timeout=15)[1] == []
        assert key in storage.objects
