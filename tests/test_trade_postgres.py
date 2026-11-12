"""실제 PostgreSQL 검사. pgserver가 개발 의존성이라 `uv run pytest`에 항상 포함된다(3절)."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import func, inspect, select

from app.db.engine import Database
from app.db.migrations import upgrade_database
from app.db.models import CompanyProfile, PriceListItem, ReplyCandidate, TradeArtifact, User


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
            with database.session() as session:
                assert session.scalar(select(func.count()).select_from(TradeArtifact)) == 4  # 두 문서 × 두 형식
        finally:
            second_database.close()


def test_postgres_po_ci_pl_full_http_flows(database_url):
    from app.web.deps import current_user_id
    from tests.test_pi_api import configured_client
    from tests.test_trade_domain_api import test_each_domain_cancel_modify_approve_download_and_version_history

    with configured_client(database_url) as client:
        for kind in ("po", "ci", "pl"):
            client.app.dependency_overrides[current_user_id] = lambda: 1
            test_each_domain_cancel_modify_approve_download_and_version_history(client, kind)
