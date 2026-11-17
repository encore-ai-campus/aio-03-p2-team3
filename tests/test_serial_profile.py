"""Recorder preserves failing outcomes and emits metadata without exception payloads."""
import json
from pathlib import Path

import pytest


def test_profile_preserves_outcomes_and_omits_payloads(pytester, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    pytester.makepyfile("""
        import pytest
        from tests.serial_profile import span
        def test_success():
            with span('synthetic.work', 'fake'):
                pass
        def test_failure():
            with span('synthetic.work', 'fake'):
                raise ValueError('private-payload-never-record')
        @pytest.mark.skip(reason='synthetic skip')
        def test_skip(): pass
    """)
    common = ("-p", "tests.serial_profile", "-n", "0", "-q")
    plain = pytester.runpytest_subprocess(*common)
    measured = pytester.runpytest_subprocess(*common, "--serial-profile=cost.json")
    for result in (plain, measured):
        result.assert_outcomes(passed=1, failed=1, skipped=1)
    raw = (pytester.path / "cost.json").read_text(encoding="utf-8")
    assert "private-payload-never-record" not in raw
    report = json.loads(raw)
    assert report["exitstatus"] == pytest.ExitCode.TESTS_FAILED
    assert len(report["cases"]) == 3
    work = [event for event in report["events"] if event["phase"] == "synthetic.work"]
    assert len(work) == 2 and all(event["count"] == 1 and event["seconds"] >= 0 for event in work)
    assert all(case["old_nodeid"] == case["new_nodeid"] for case in report["cases"])
