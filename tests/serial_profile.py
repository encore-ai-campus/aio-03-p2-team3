"""Opt-in serial cost records; never serialize arguments, responses or exceptions."""
from contextlib import contextmanager
from functools import wraps
import json
from pathlib import Path
from time import perf_counter

import pytest

_active = None


@contextmanager
def span(phase, role="pytest"):
    if _active is None:
        yield
        return
    started = perf_counter()
    try:
        yield
    finally:
        _active.record(phase, role, perf_counter() - started)


def enabled():
    return _active is not None


def identify(client, role):
    if _active is not None:
        client._serial_profile_role = role


def record(phase, role, seconds):
    if _active is not None:
        _active.record(phase, role, seconds)


def pytest_addoption(parser):
    parser.addoption("--serial-profile", metavar="PATH", help="Write opt-in serial cost JSON")


def pytest_configure(config):
    path = config.getoption("--serial-profile")
    if path:
        if config.getoption("numprocesses", default=0):
            raise pytest.UsageError("--serial-profile requires -n 0")
        config.pluginmanager.register(Profile(Path(path)), "serial-cost-recorder")


class Profile:
    def __init__(self, path):
        self.path = path
        self.nodeid = ""
        self.events = []
        self.cases = []
        self.patch = pytest.MonkeyPatch()

    def record(self, phase, role, seconds):
        self.events.append(dict(nodeid=self.nodeid, phase=phase, role=role,
                                seconds=round(seconds, 6), count=1))

    def wrap(self, owner, name, phase, role):
        original = getattr(owner, name)
        @wraps(original)
        def measured(*args, **kwargs):
            with span(phase, role):
                return original(*args, **kwargs)
        self.patch.setattr(owner, name, measured)

    def pytest_sessionstart(self, session):
        global _active
        _active = self
        import subprocess
        import pgserver
        import httpx
        import ssl
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography import x509
        from pgserver.postgres_server import PostgresServer
        from app.db.engine import Database
        from app.db import migrations
        self.wrap(pgserver, "get_server", "db.server_start", "postgres")
        self.wrap(PostgresServer, "_cleanup", "db.server_stop", "postgres")
        self.wrap(Database, "create_tables", "db.schema", "postgres")
        self.wrap(migrations, "upgrade_database", "db.migration", "postgres")
        self.wrap(rsa, "generate_private_key", "tls.key", "worker")
        self.wrap(x509.CertificateBuilder, "sign", "tls.certificate", "worker")
        self.wrap(ssl, "create_default_context", "tls.context", "client")
        original_send = httpx.Client.send
        @wraps(original_send)
        def send(client, *args, **kwargs):
            if self.nodeid.startswith(("tests/test_worker_process.py::", "tests/test_local_gmail.py::")):
                role = getattr(client, "_serial_profile_role", "local" if "test_local_gmail.py::" in self.nodeid else "server")
                with span("http.request", role):
                    return original_send(client, *args, **kwargs)
            return original_send(client, *args, **kwargs)
        self.patch.setattr(httpx.Client, "send", send)
        original = subprocess.run
        @wraps(original)
        def build(*args, **kwargs):
            command = args[0] if args else kwargs.get("args")
            if isinstance(command, (list, tuple)) and list(command[:3]) == ["npm", "run", "build"]:
                with span("frontend.build", "vite"):
                    return original(*args, **kwargs)
            return original(*args, **kwargs)
        self.patch.setattr(subprocess, "run", build)

    @pytest.hookimpl(wrapper=True)
    def pytest_collection(self, session):
        with span("collection"):
            return (yield)

    def pytest_collection_finish(self, session):
        self.cases = [dict(old_nodeid=item.nodeid, new_nodeid=item.nodeid,
                           purpose=item.name.removeprefix("test_").replace("_", " "))
                      for item in session.items]

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_protocol(self, item, nextitem):
        self.nodeid = item.nodeid
        try:
            return (yield)
        finally:
            self.nodeid = ""

    def pytest_runtest_logreport(self, report):
        self.events.append(dict(nodeid=report.nodeid, phase=report.when, role="pytest",
                                seconds=round(report.duration, 6), count=1, outcome=report.outcome))

    def pytest_sessionfinish(self, session, exitstatus):
        global _active
        self.patch.undo()
        _active = None
        self.path.write_text(json.dumps(dict(schema=1, exitstatus=int(exitstatus),
                                            cases=self.cases, events=self.events),
                                        ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

    def pytest_unconfigure(self, config):
        global _active
        self.patch.undo()
        if _active is self:
            _active = None
