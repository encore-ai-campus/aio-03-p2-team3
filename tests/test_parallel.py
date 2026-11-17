"""실제 8-worker 분배·직렬 단계와 DB 표식의 거부/허용 경계를 검증한다."""
from pathlib import Path

import psycopg
import pytest

from tests.parallel import require_test_database


def test_eight_workers_distribute_independent_tests_and_keep_unknown_serial(pytester, monkeypatch, request):
    if hasattr(request.config, "workerinput"):
        pytest.fail("worker 중첩 방지: 정책 검사는 -n 0으로 먼저 실행하고 병렬 본 실행에서 이 파일을 제외하세요.")
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    pytester.makepyfile(test_trade_pricing="""
        import os
        from pathlib import Path
        import time
        import pytest
        @pytest.mark.parametrize('case', range(32))
        def test_independent(case):
            Path('parallel-' + os.environ['PYTEST_XDIST_WORKER']).touch()
            time.sleep(.02)
    """, test_unknown="""
        import os
        from pathlib import Path
        import pytest
        @pytest.mark.parametrize('case', range(4))
        def test_serial(case, request):
            assert request.node.get_closest_marker('serial') is not None
            assert 'PYTEST_XDIST_WORKER' not in os.environ
            Path('serial-master').touch()
    """)
    result = pytester.runpytest_subprocess(
        "-p", "tests.parallel", "-n", "8", "-m", "parallel", "--max-worker-restart=0", "-q"
    )
    result.assert_outcomes(passed=32)
    assert len(list(pytester.path.glob("parallel-gw*"))) == 8
    assert not (pytester.path / "serial-master").exists()
    result = pytester.runpytest_subprocess("-p", "tests.parallel", "-n", "0", "-m", "serial", "-q")
    result.assert_outcomes(passed=4, deselected=32)
    assert (pytester.path / "serial-master").exists()


@pytest.mark.parametrize("options", [("-n", "auto"), ("-n", "9"), ("-n", "8", "-m", "serial")])
def test_unsafe_worker_options_fail_before_execution(pytester, monkeypatch, options):
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    pytester.makepyfile("def test_never_runs(): assert False")
    result = pytester.runpytest_subprocess("-p", "tests.parallel", *options)
    assert result.ret == pytest.ExitCode.USAGE_ERROR


def test_unmarked_database_is_rejected_before_test_database_creation(database_url):
    # database_url은 이번 테스트가 소유한 비어 있는 UUID DB다. 운영/공유 DB가 아니다.
    with psycopg.connect(database_url, autocommit=True) as connection:
        with pytest.raises(pytest.UsageError, match="테스트 전용 DB 표식"):
            require_test_database(connection)
        name = connection.execute("SELECT current_database()").fetchone()[0]
        from psycopg import sql
        connection.execute(sql.SQL("COMMENT ON DATABASE {} IS 'aio pytest disposable'").format(sql.Identifier(name)))
        require_test_database(connection)
