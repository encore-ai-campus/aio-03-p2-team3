"""Run prepared Linux serial tests once on an internal Docker network.

Invoke repeatedly with different output directories; installs are outside this timer.
Network checks apply to all child processes, including Chromium, Node and libpq.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from threading import Event, Thread
from time import perf_counter
from xml.etree import ElementTree


def live_processes():
    result = set()
    for path in Path("/proc").glob("[0-9]*/stat"):
        try:
            # Exclude already terminated zombies waiting for the container init.
            if path.read_text().rsplit(")", 1)[1].split()[0] != "Z":
                result.add(int(path.parent.name))
        except (FileNotFoundError, ProcessLookupError):
            pass
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("Use a disposable Linux container on an internal-only Docker network")
    routes = Path("/proc/net/route").read_text().splitlines()[1:]
    if any(line.split()[1] == "00000000" for line in routes):
        parser.error("External default route exists; disconnect the non-internal Docker network")
    # Also test a literal external address, avoiding a DNS-only false assurance.
    with socket.socket() as probe:
        probe.settimeout(.3)
        if probe.connect_ex(("1.1.1.1", 443)) == 0:
            parser.error("External TCP is reachable")
    import psycopg
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tests.parallel import require_test_database
    # Check the same dedicated DB marker as the fixture, before running any test.
    with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as connection:
        require_test_database(connection)
        def databases_left():
            return connection.execute(
                "SELECT count(*) FROM pg_database WHERE datname ~ '^test_[0-9a-f]{32}$'"
            ).fetchone()[0]
        if databases_left():
            parser.error("Disposable database server already contains leftover test databases")
    args.output.mkdir(parents=True, exist_ok=False)
    before = live_processes()
    group = Path("/sys/fs/cgroup")
    def memory_events():
        return dict(line.split() for line in (group / "memory.events").read_text().splitlines())
    initial = memory_events()
    samples = []
    stop = Event()
    def sample():
        while not stop.is_set():
            samples.append(int((group / "memory.current").read_text()))
            stop.wait(.1)
    thread = Thread(target=sample)
    thread.start()
    command = ["uv", "run", "pytest", "-n", "0", "-m", "serial",
               "--ignore=tests/test_parallel.py", "--ignore=tests/test_serial_profile.py",
               "--junitxml=" + str(args.output / "results.xml"), "-q"]
    if args.profile:
        command.append("--serial-profile=" + str(args.output / "cost.json"))
    started = perf_counter()
    try:
        result = subprocess.run(command)
    finally:
        elapsed = perf_counter() - started
        stop.set()
        thread.join()
    after = memory_events()
    cases = []
    for case in ElementTree.parse(args.output / "results.xml").iter("testcase"):
        outcome = "failed" if case.find("failure") is not None or case.find("error") is not None else (
            "skipped" if case.find("skipped") is not None else "passed")
        cases.append(dict(nodeid=case.attrib["classname"].replace(".", "/") + ".py::" + case.attrib["name"],
                          outcome=outcome))
    manifest = json.loads((Path(__file__).resolve().parents[1] /
                           "docs/test-records/20261117_serial_cases.json").read_text(encoding="utf-8"))
    expected = [case["new_nodeid"] for case in manifest["cases"]]
    actual = [case["nodeid"] for case in cases]
    manifest_match = len(actual) == len(set(actual)) == len(expected) and set(actual) == set(expected)
    with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as connection:
        residual_databases = databases_left()
    report = dict(profile=args.profile, seconds=round(elapsed, 6), returncode=result.returncode,
                  memory_sampled_peak_bytes=max(samples, default=0),
                  memory_limit_bytes=int((group / "memory.max").read_text()),
                  oom_events=int(after["oom"]) - int(initial["oom"]),
                  oom_kill_events=int(after["oom_kill"]) - int(initial["oom_kill"]),
                  residual_live_processes=len(live_processes() - before), external_tcp_blocked=True)
    report.update(residual_databases=residual_databases, manifest_match=manifest_match, cases=cases)
    (args.output / "run.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}))
    return result.returncode or int(bool(report["oom_events"] or report["residual_live_processes"]
                                        or residual_databases or not manifest_match))


if __name__ == "__main__":
    raise SystemExit(main())
