"""검토한 독립 테스트만 분산하고 무거운/미분류 테스트는 직렬 단계로 둔다."""
from pathlib import Path

import pytest


# DB는 테스트별 UUID, 파일은 tmp_path/메모리, 외부 공급자는 가짜인 모듈.
# 새 모듈은 검토 후 여기에 추가한다. 미분류는 자동 병렬화하지 않는다.
PARALLEL_MODULES = frozenset("""
test_approval test_auth test_calendar_connect test_ci_scope test_ci_source_pis
test_db test_db_copy test_deal test_domain_graph test_domain_graph_adapters
test_env test_evaluation test_files_storage test_frontend_serving test_gmail_connect
test_gmail_push test_graph test_llm test_local_openai test_mail_analysis test_memory
test_openai_keys test_pages test_pi_api test_pi_domain test_postgres_only
test_product_search test_quote test_react_pi test_reflect test_runs test_supabase_auth
test_tools test_trade_branding test_trade_branding_storage test_trade_ci_import
test_trade_ci_pl_parity test_trade_counterparties test_trade_documents
test_trade_domain_api test_trade_domain_operations test_trade_extract test_trade_flow
test_trade_packing test_trade_packing_approval test_trade_parity test_trade_pdf_pagination
test_trade_pdf_parity test_trade_postgres test_trade_pricing test_trade_product_matching
test_trade_promotions test_trade_renderers test_trade_samples test_trade_store
test_trade_upgrade test_trade_wire_schema test_web
test_worker_execution test_worker_queue
""".split())


def pytest_configure(config):
    config.addinivalue_line("markers", "parallel: 검토한 테스트별 독립 자원 사용")
    config.addinivalue_line("markers", "serial: 무거운 자원 또는 미분류, 별도 직렬 단계에서 실행")
    workers = config.getoption("numprocesses", default=0)
    args = config.invocation_params.args
    automatic = any(
        arg in ("-nauto", "-nlogical", "-n=auto", "-n=logical", "--numprocesses=auto", "--numprocesses=logical")
        or (arg in ("-n", "--numprocesses") and i + 1 < len(args) and args[i + 1] in ("auto", "logical"))
        for i, arg in enumerate(args)
    )
    if automatic or workers not in (None, 0, 1, 2, 3, 4, 5, 6, 7, 8):
        raise pytest.UsageError("workers는 0~8의 고정 정수만 허용합니다 (-n auto 사용 금지).")
    if workers and config.getoption("markexpr") != "parallel":
        raise pytest.UsageError("병렬 검사는 -m parallel로 실행해야 합니다. serial 검사는 -n 0으로 분리하세요.")


def pytest_itemcollected(item):
    if Path(item.path).stem in PARALLEL_MODULES:
        item.add_marker(pytest.mark.parallel)
    else:
        item.add_marker(pytest.mark.serial)


def require_test_database(connection):
    """외부 URL은 주소가 아니라 DB 자체의 명시적 테스트 표식으로 확인한다."""
    marker = connection.execute(
        "SELECT shobj_description(oid, 'pg_database') FROM pg_database "
        "WHERE datname = current_database()"
    ).fetchone()
    if not marker or marker[0] != "aio pytest disposable":
        raise pytest.UsageError(
            "TEST_DATABASE_URL에 테스트 전용 DB 표식이 없습니다. "
            "공유/운영 DB에 표식을 추가하지 말고 README의 일회용 DB를 준비하세요."
        )
