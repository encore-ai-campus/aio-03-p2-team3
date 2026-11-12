"""실제 ASGI/파일 DB에서 장치와 작업의 소유권·경합·재시작을 검증한다. 외부 API 없음."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
import json
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import inspect, select
from starlette.requests import Request

from app.config import Settings
from app.db.engine import Database
from app.db.migrations import upgrade_database
from app.db.models import User, WorkerDevice, WorkerJob, WorkerPairing
from app.llm import client as llm
from app.main import create_app
from app.services.openai_keys import UserKeyAccess, save_key
from app.worker import service
from app.worker.protocol import (
    WorkerError, definitions, manifest, validate_result,
)
from tests.fakes.gmail import FakeGmailGoogle
from tests.test_openai_keys import login

MODEL = "gpt-6-luna"


@pytest.fixture
def web(tmp_path, monkeypatch):
    clock = [datetime(2026, 11, 12, 4, 0, tzinfo=UTC)]
    monkeypatch.setattr(service, "utcnow", lambda: clock[0])
    def forbidden(*args, **kwargs):
        pytest.fail("장치 연결/큐는 OpenAI를 호출하면 안 됩니다")
    monkeypatch.setattr(llm, "_backend_for_settings", forbidden)
    config = Settings(database_url=f"sqlite:///{tmp_path / 'worker.sqlite3'}", session_secret="fake-session",
                      token_encryption_key=Fernet.generate_key().decode(), app_base_url="https://testserver",
                      openai_api_key="fake-unused-server-key")
    with TestClient(create_app(config, google=FakeGmailGoogle()), base_url="https://testserver") as client:
        with client.app.state.database.session() as session:
            session.add_all([User(id=n, google_sub=f"fake-sub-{n}", email=f"user{n}@example.invalid",
                                 last_login_at=clock[0]) for n in (1, 2)])
        yield client, config, clock


def pair(web, user_id=1, *, name="가상 개인 PC", capabilities=None):
    client, config, clock = web
    csrf = login(client, config, user_id)
    changed = client.post("/api/ai-execution/mode", json={"ai_execution_mode": "local_worker"},
                          headers={"X-CSRF-Token": csrf})
    assert changed.status_code == 200, changed.text
    response = client.post("/api/worker/pairings", json={"device_name": name,
                           "capabilities": capabilities or manifest(MODEL)})
    assert response.status_code == 200, response.text
    pending = response.json()
    approved = client.post("/api/ai-execution/pairings/approve", headers={"X-CSRF-Token": csrf},
                           json={"pairing_code": pending["pairing_code"], "device_name": name})
    assert approved.status_code == 200, approved.text
    response = client.post(f"/api/worker/pairings/{pending['pairing_id']}/poll",
                           json={"device_secret": pending["device_secret"]})
    assert response.status_code == 200, response.text
    return response.json(), pending, csrf


def enqueue(web, user_id=1, **changes):
    client, config, clock = web
    kwargs = dict(prompt_id="analyze_email", prompt_version="v1", schema_id="EmailAnalysis", schema_version="v1",
                  variables={"thread_context": "가상 과거 내용", "email": "가상 메일 내용"},
                  requested_model=MODEL, run_id=str(uuid4()), model=MODEL)
    kwargs.update(changes)
    return service.enqueue(client.app.state.database, user_id, **kwargs)


def path(device, suffix):
    return f"/api/worker/devices/{device['device_id']}/{suffix}"


def auth(device):
    return {"Authorization": "Bearer " + device["device_token"]}


def test_disconnected_long_poll_does_not_lease_a_new_job(web):
    from app.worker.router import claim as claim_route
    device, _, _ = pair(web)
    job = enqueue(web)
    messages = iter([{"type": "http.request", "body": b'{"wait_seconds":0}', "more_body": False},
                     {"type": "http.disconnect"}])
    async def receive():
        return next(messages)
    request = Request({"type": "http", "method": "POST", "scheme": "https", "path": path(device, "claim"),
                       "query_string": b"", "headers": [(b"authorization", auth(device)["Authorization"].encode()),
                                                           (b"content-type", b"application/json")],
                       "client": ("127.0.0.1", 1234), "server": ("testserver", 443), "app": web[0].app}, receive)
    response = asyncio.run(claim_route(request, device["device_id"]))
    assert json.loads(response.body) == {"job": None}
    with web[0].app.state.database.session() as session:
        assert session.get(WorkerJob, job["job_id"]).status == "queued"
    assert claim(web, device).json()["job"] == job


def result(job, **changes):
    value = {k: job[k] for k in ("protocol_version", "job_id", "attempt_id", "device_id", "schema_id", "schema_version")}
    value.update(ok=True, value={"intent": "general", "reason": "가상 문의"}, duration_ms=20)
    value.update(changes)
    return value


def claim(web, device):
    return web[0].post(path(device, "claim"), headers=auth(device), json={})


def complete(web, device, job, value=None):
    return web[0].post(path(device, f"jobs/{job['job_id']}/complete"), headers=auth(device),
                       json=result(job) if value is None else value)


def test_two_users_pair_and_own_claim_complete_are_isolated(web):
    client, config, clock = web
    first, pending, csrf = pair(web)
    second, _, _ = pair(web, 2, name="다른 가상 PC")
    one, two = enqueue(web), enqueue(web, 2)
    assert claim(web, first).json()["job"] == one
    assert claim(web, second).json()["job"] == two
    # 다른 사용자 토큰을 탈취해도 다른 장치 ID/작업에 사용할 수 없다.
    assert client.post(path(first, "claim"), headers=auth(second), json={}).status_code == 401
    assert complete(web, second, one).status_code == 404
    assert complete(web, first, two).status_code == 404
    assert complete(web, first, one).json() == {"status": "succeeded", "duplicate": False}
    assert complete(web, second, two).status_code == 200
    overview = client.get("/api/ai-execution").json()
    assert [d["device_id"] for d in overview["devices"]] == [second["device_id"]]
    assert [j["job_id"] for j in overview["jobs"]] == [two["job_id"]]
    assert overview["ai_ready"] is True and overview["integration"] == "ready"
    assert client.post(f"/api/ai-execution/devices/{first['device_id']}/disconnect",
                       json={}, headers={"X-CSRF-Token": overview["csrf_token"]}).status_code == 404
    assert client.post(f"/api/ai-execution/jobs/{one['job_id']}/cancel",
                       json={}, headers={"X-CSRF-Token": overview["csrf_token"]}).status_code == 404


def test_pairing_login_csrf_name_confirmation_single_use_and_secret_hash_only(web, caplog):
    client, config, clock = web
    created = client.post("/api/worker/pairings", json={"device_name": "가상 PC", "capabilities": manifest(MODEL)}).json()
    request = dict(pairing_code=created["pairing_code"], device_name="가상 PC")
    assert client.post("/api/ai-execution/pairings/approve", json=request).status_code == 401
    csrf = login(client, config, 1)
    for token in (None, "wrong", {"fake": "token"}):
        payload = dict(request)
        if token is not None:
            payload["csrf_token"] = token
        assert client.post("/api/ai-execution/pairings/approve", json=payload).status_code == 403
    assert client.post("/api/ai-execution/mode", json={"ai_execution_mode": "local_worker"},
                       headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.post("/api/ai-execution/pairings/approve", json={**request, "device_name": "틀린 이름"},
                       headers={"X-CSRF-Token": csrf}).status_code == 404
    poll_path = f"/api/worker/pairings/{created['pairing_id']}/poll"
    poll_json = {"device_secret": created["device_secret"]}
    assert client.post(poll_path, json=poll_json).json() == {"status": "pending"}
    assert client.post("/api/ai-execution/pairings/approve", json=request,
                       headers={"X-CSRF-Token": csrf}).status_code == 200
    assert client.post("/api/ai-execution/pairings/approve", json=request,
                       headers={"X-CSRF-Token": csrf}).status_code == 409
    assert client.post(poll_path, json=poll_json).status_code == 429
    clock[0] += timedelta(seconds=5)
    connected = client.post(poll_path, json=poll_json)
    assert connected.headers["cache-control"] == "private, no-store"
    device = connected.json()
    assert device["google_sub"] == "fake-sub-1" and device["scopes"] == ["ai:claim", "ai:complete"]
    assert client.post(poll_path, json=poll_json).status_code == 410
    with client.app.state.database.session() as session:
        pairing = session.get(WorkerPairing, created["pairing_id"])
        row = session.get(WorkerDevice, device["device_id"])
        stored = repr(pairing.__dict__) + repr(row.__dict__)
        assert pairing.consumed_at is not None and len(row.token_hash) == 64
    page = client.get("/settings").text
    for secret in (created["device_secret"], created["pairing_code"], device["device_token"]):
        assert secret not in stored + page + caplog.text


def test_other_user_cannot_reapprove_a_used_code(web):
    client, config, clock = web
    first, pending, _ = pair(web)
    csrf = login(client, config, 2)
    client.post("/api/ai-execution/mode", json={"ai_execution_mode": "local_worker", "csrf_token": csrf})
    assert client.post("/api/ai-execution/pairings/approve", json={"csrf_token": csrf,
                       "pairing_code": pending["pairing_code"], "device_name": "가상 개인 PC"}).status_code == 409
    with client.app.state.database.session() as session:
        assert session.get(WorkerDevice, first["device_id"]).user_id == 1


def test_device_token_has_no_session_gmail_or_download_authority(web):
    client, config, clock = web
    device, _, _ = pair(web)
    job = enqueue(web)
    assert claim(web, device).status_code == 200
    client.cookies.clear()
    for url in ("/settings", "/candidates/1/approve", "/quotes/1/approve", "/runs"):
        method = client.post if "approve" in url else client.get
        assert method(url, headers=auth(device), follow_redirects=False).status_code in (303, 401)
    for url in ("/api/ai-execution", "/api/trade/pi", "/api/trade/pi/1/files/1"):
        assert client.get(url, headers=auth(device), follow_redirects=False).status_code in (401, 404)
    assert client.post("/api/ai-execution/mode", json={"ai_execution_mode": "stored_key"}, headers=auth(device)).status_code == 401
    assert complete(web, device, job).status_code == 200


def test_duplicate_completion_only_accepts_same_result_and_wipes_payload(web):
    device, _, _ = pair(web)
    job = enqueue(web)
    claim(web, device)
    assert complete(web, device, job).json()["duplicate"] is False
    assert complete(web, device, job).json()["duplicate"] is True
    assert complete(web, device, job, result(job, value={"intent": "ignore", "reason": "변조"})).status_code == 410
    with web[0].app.state.database.session() as session:
        row = session.get(WorkerJob, job["job_id"])
        assert row.status == "succeeded" and row.payload is None and row.result_hash
        assert "가상 메일 내용" not in repr(row.__dict__) and "가상 문의" not in repr(row.__dict__)


@pytest.mark.parametrize("error_kind", ["rate_limit", "network", "invalid_output", "invalid_input", "internal", "key_required",
                                        "owner_mismatch", "unsupported_version", "worker_unavailable", "expired"])
def test_safe_worker_failures_and_no_retry_distribution(web, error_kind):
    device, _, _ = pair(web)
    job = enqueue(web)
    claim(web, device)
    error = result(job)
    del error["value"], error["duration_ms"]
    error.update(ok=False, error_kind=error_kind)
    assert complete(web, device, job, error).json()["status"] == "failed"
    assert claim(web, device).json() == {"job": None}
    with web[0].app.state.database.session() as session:
        row = session.get(WorkerJob, job["job_id"])
        assert row.error_kind == error_kind and row.payload is None


@pytest.mark.parametrize("change", [
    {"attempt_id": str(uuid4())}, {"device_id": str(uuid4())}, {"job_id": str(uuid4())},
    {"protocol_version": 2}, {"protocol_version": True}, {"ok": 1},
    {"schema_version": "v2"}, {"schema_id": "DraftOutput"},
    {"value": {"intent": "impossible", "reason": "가상"}},
    {"value": {"intent": "general", "reason": "가상", "execute": "fake command"}},
    {"duration_ms": 30001}, {"duration_ms": -1}, {"error_kind": "network"},
    {"api_key": "fake-must-never-be-echoed"}, {"value": {"intent": "general", "reason": 3}},
])
def test_forged_schema_version_identity_and_extra_fields_do_not_apply(web, change):
    device, _, _ = pair(web)
    job = enqueue(web)
    assert complete(web, device, job).status_code == 410  # claim 전 결과 금지
    claim(web, device)
    value = result(job, **change)
    response = complete(web, device, job, value)
    assert response.status_code in (400, 404, 409, 422), response.text
    assert "fake-must-never-be-echoed" not in response.text
    with web[0].app.state.database.session() as session:
        assert session.get(WorkerJob, job["job_id"]).status == "leased"


def test_oversized_result_and_invalid_json_never_echo_input(web):
    device, _, _ = pair(web)
    job = enqueue(web)
    claim(web, device)
    response = complete(web, device, job, result(job, value={"reason": "가" * 100000, "intent": "general"}))
    assert response.status_code == 413
    url = path(device, f"jobs/{job['job_id']}/complete")
    for raw in ('{"ok":true,"ok":false}', '{"ok":NaN}', '{"api_key":"fake-secret"', '[]'):
        response = web[0].post(url, content=raw, headers={**auth(device), "content-type": "application/json"})
        assert response.status_code == 400 and "fake-secret" not in response.text


@pytest.mark.parametrize("action", ["disconnect", "mode", "cancel", "token_expiry", "lease_expiry", "job_expiry"])
def test_revoked_cancelled_and_expired_results_are_rejected(web, action):
    client, config, clock = web
    device, _, csrf = pair(web)
    job = enqueue(web)
    claim(web, device)
    headers = {"X-CSRF-Token": csrf}
    if action == "disconnect":
        assert client.post(f"/api/ai-execution/devices/{device['device_id']}/disconnect", json={}, headers=headers).status_code == 200
    elif action == "mode":
        assert client.post("/api/ai-execution/mode", json={"ai_execution_mode": "stored_key"}, headers=headers).status_code == 200
    elif action == "cancel":
        assert client.post(f"/api/ai-execution/jobs/{job['job_id']}/cancel", json={}, headers=headers).status_code == 200
    else:
        clock[0] += timedelta(seconds={"lease_expiry": 31, "job_expiry": 121, "token_expiry": 30 * 86400}[action])
    assert complete(web, device, job).status_code in (401, 410)
    service.cleanup(client.app.state.database)
    with client.app.state.database.session() as session:
        row = session.get(WorkerJob, job["job_id"])
        assert row.status in ("expired", "cancelled") and row.payload is None
    response = claim(web, device)
    assert response.status_code == 401 or response.json() == {"job": None}


def test_heartbeat_timing_lease_extension_and_hard_deadline(web):
    client, config, clock = web
    device, _, _ = pair(web)
    job = enqueue(web)
    claim(web, device)
    url = path(device, f"jobs/{job['job_id']}/heartbeat")
    assert client.post(url, headers=auth(device), json={"attempt_id": job["attempt_id"]}).status_code == 429
    for _ in range(11):
        clock[0] += timedelta(seconds=10)
        assert client.post(url, headers=auth(device), json={"attempt_id": job["attempt_id"]}).status_code == 200
    with client.app.state.database.session() as session:
        assert session.get(WorkerJob, job["job_id"]).lease_expires_at.isoformat() == job["expires_at"]
    clock[0] += timedelta(seconds=10)
    assert complete(web, device, job).status_code == 410


def test_offline_status_and_queue_expiration(web):
    client, config, clock = web
    device, _, _ = pair(web)
    job = enqueue(web)
    clock[0] += timedelta(seconds=45)
    assert client.get("/api/ai-execution").json()["devices"][0]["status"] == "offline"
    with pytest.raises(WorkerError, match="worker_unavailable"):
        enqueue(web)
    clock[0] += timedelta(seconds=75)
    service.cleanup(client.app.state.database)
    assert claim(web, device).json() == {"job": None}
    with client.app.state.database.session() as session:
        assert session.get(WorkerJob, job["job_id"]).payload is None


def test_rotation_requires_new_approval_revokes_old_credentials_and_jobs(web):
    client, config, clock = web
    old, _, _ = pair(web)
    job = enqueue(web)
    claim(web, old)
    new, _, _ = pair(web, name="교체 PC")
    assert old["device_id"] != new["device_id"]
    assert claim(web, old).status_code == 401
    assert complete(web, old, job).status_code == 401
    assert claim(web, new).json() == {"job": None}
    with client.app.state.database.session() as session:
        assert len(session.scalars(select(WorkerDevice).where(WorkerDevice.revoked_at.is_(None))).all()) == 1
        assert session.get(WorkerJob, job["job_id"]).status == "cancelled"


def test_concurrent_claim_and_complete_across_distinct_database_engines(web):
    client, config, clock = web
    device, _, _ = pair(web)
    job = enqueue(web)
    db2 = Database(config.database_url)
    db2.create_tables()
    dbs = [client.app.state.database, db2]
    barrier = Barrier(2)
    def simultaneous_claim(db):
        barrier.wait(timeout=5)
        return service.claim(db, device["device_id"], device["device_token"], MODEL)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(simultaneous_claim, dbs))
        assert sum(c["job"] is not None for c in claims) == 1
        def simultaneous_complete(db):
            barrier.wait(timeout=5)
            return service.complete(db, device["device_id"], device["device_token"], job["job_id"], result(job))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(simultaneous_complete, dbs))
        assert sorted(r["duplicate"] for r in results) == [False, True]
    finally:
        db2.close()


def test_concurrent_asgi_claim_is_single_and_long_poll_releases_database(web):
    client, config, clock = web
    device, _, _ = pair(web)
    job = enqueue(web)
    barrier = Barrier(2)
    def claim_together(_):
        barrier.wait(timeout=5)
        return claim(web, device).json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(claim_together, range(2)))
    assert sum(c["job"] is not None for c in claims) == 1
    complete(web, device, job)
    # 대기 중 다른 연결이 작업을 커밋할 수 있어야 한다.
    from threading import Event
    entered = Event()
    original_claim = service.claim
    def watched_claim(*args, **kwargs):
        out = original_claim(*args, **kwargs)
        if out["job"] is None:
            entered.set()
        return out
    from unittest.mock import patch
    with patch.object(service, "claim", watched_claim), ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, path(device, "claim"), headers=auth(device), json={"wait_seconds": 3})
        assert entered.wait(2)
        new_job = enqueue(web)
        assert future.result(timeout=5).json()["job"] == new_job


def test_restart_preserves_device_and_queued_jobs_and_expires_interrupted_lease(web):
    client, config, clock = web
    device, _, _ = pair(web)
    leased, queued = enqueue(web), enqueue(web)
    claimed = claim(web, device).json()["job"]
    other = queued if claimed["job_id"] == leased["job_id"] else leased
    clock[0] += timedelta(seconds=31)
    # 동일 설정의 새 앱 lifespan에서 정리한다. 첫 프로세스가 가진 메모리에 의존하지 않는다.
    with TestClient(create_app(config, google=FakeGmailGoogle()), base_url="https://testserver") as restarted:
        with restarted.app.state.database.session() as session:
            assert session.get(WorkerJob, claimed["job_id"]).status == "expired"
            assert session.get(WorkerJob, claimed["job_id"]).payload is None
            assert session.get(WorkerJob, other["job_id"]).status == "queued"
        assert restarted.post(path(device, "claim"), headers=auth(device), json={}).json()["job"] == other


def test_rate_limits_survive_database_reconnect_and_failed_approvals(web):
    client, config, clock = web
    for _ in range(6):
        assert client.post("/api/worker/pairings", json={"device_name": "가상 PC", "capabilities": manifest(MODEL)}).status_code == 200
    assert client.post("/api/worker/pairings", json={"device_name": "가상 PC", "capabilities": manifest(MODEL)}).status_code == 429
    db2 = Database(config.database_url)
    try:
        with pytest.raises(WorkerError, match="rate_limit"):
            service.rate_limit(db2, "ip:testclient", "pair", 6, 600)
    finally:
        db2.close()
    csrf = login(client, config, 1)
    client.post("/api/ai-execution/mode", json={"ai_execution_mode": "local_worker", "csrf_token": csrf})
    for _ in range(10):
        assert client.post("/api/ai-execution/pairings/approve", json={"pairing_code": "fake-nonexistent-code",
                           "device_name": "가상", "csrf_token": csrf}).status_code == 404
    assert client.post("/api/ai-execution/pairings/approve", json={"pairing_code": "fake-nonexistent-code",
                       "device_name": "가상", "csrf_token": csrf}).status_code == 429


def test_pairing_expiration_and_unverified_user_cannot_connect(web):
    client, config, clock = web
    pending = client.post("/api/worker/pairings", json={"device_name": "가상", "capabilities": manifest(MODEL)}).json()
    csrf = login(client, config, 1)
    with client.app.state.database.session() as session:
        session.get(User, 1).last_login_at = None
    assert client.post("/api/ai-execution/mode", json={"ai_execution_mode": "local_worker", "csrf_token": csrf}).status_code == 403
    clock[0] += timedelta(minutes=10)
    assert client.post(f"/api/worker/pairings/{pending['pairing_id']}/poll",
                       json={"device_secret": pending["device_secret"]}).status_code == 410


def test_https_required_even_with_spoofed_header_and_pairing_errors_hide_secrets(web):
    client, config, clock = web
    response = client.post("http://testserver/api/worker/pairings", headers={"X-Forwarded-Proto": "https"},
                           json={"device_name": "가상", "capabilities": manifest(MODEL)})
    assert response.status_code == 400 and response.json()["error"]["code"] == "https_required"
    response = client.post("/api/worker/pairings", json={"device_name": "가상", "capabilities": manifest(MODEL),
                           "openai_api_key": "fake-secret-never-echo"})
    assert response.status_code == 400 and "fake-secret-never-echo" not in response.text


def test_selected_worker_mode_cannot_fall_back_to_existing_user_or_server_key(web):
    client, config, clock = web
    database = client.app.state.database
    save_key(database, 1, "fake-user-key", client.app.state.google_access.cipher, settings=config)
    device, _, csrf = pair(web)
    with pytest.raises(llm.OpenAIKeyError, match="개인 PC 실행"):
        UserKeyAccess(database, 1, client.app.state.google_access.cipher, config).read()
    page = client.get("/settings")
    assert "PC가 켜져 있을 때 본인 .env 키로 AI를 실행합니다" in page.text
    assert "fake-user-key" not in page.text
    assert client.post("/api/ai-execution/mode", json={"ai_execution_mode": "stored_key", "csrf_token": csrf}).status_code == 200
    assert UserKeyAccess(database, 1, client.app.state.google_access.cipher, config).read() == "fake-user-key"


def test_legacy_user_migration_preserves_data_and_default_mode(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'legacy.sqlite3'}")
    try:
        with db.engine.begin() as connection:
            connection.exec_driver_sql("""CREATE TABLE users (id INTEGER PRIMARY KEY, google_sub VARCHAR NOT NULL UNIQUE,
                email VARCHAR NOT NULL, display_name VARCHAR, reflection_enabled BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL, last_login_at DATETIME)""")
            connection.exec_driver_sql("""INSERT INTO users VALUES
                (1,'fake-legacy-sub','legacy@example.invalid',NULL,0,'2026-11-12 00:00:00',NULL)""")
        db.create_tables()
        upgrade_database(db.engine)
        with db.session() as session:
            user = session.get(User, 1)
            assert user.google_sub == "fake-legacy-sub" and user.ai_execution_mode == "stored_key"
        assert {"worker_devices", "worker_jobs", "worker_pairings", "worker_rate_limits"} <= set(inspect(db.engine).get_table_names())
        for model in (WorkerDevice, WorkerPairing, WorkerJob):
            assert not any("openai" in c.name or c.name in {"device_secret", "pairing_code", "device_token"} for c in model.__table__.columns)
    finally:
        db.close()


@pytest.mark.parametrize("mutation", ["unknown_prompt", "old_prompt", "hash", "model", "protocol"])
def test_pairing_rejects_incompatible_installed_definitions(web, mutation):
    cap = manifest(MODEL)
    if mutation == "unknown_prompt":
        cap["definitions"][0]["prompt_id"] = "execute_shell"
    elif mutation == "old_prompt":
        cap["definitions"][1]["prompt_version"] = "v2"
    elif mutation == "hash":
        cap["definitions"][0]["schema_sha256"] = "0" * 64
    elif mutation == "model":
        cap["models"] = ["arbitrary-model"]
    else:
        cap["protocol_version"] = 2
    response = web[0].post("/api/worker/pairings", json={"device_name": "가상", "capabilities": cap})
    assert response.status_code in (400, 409)


@pytest.mark.parametrize("changes", [
    {"variables": {"email": {"command": "fake"}, "thread_context": ""}},
    {"variables": {"email": "가" * 44000, "thread_context": ""}},
    {"variables": {"email": "x", "thread_context": "", "url": "https://example.invalid"}},
    {"variables": {"email": "x"}}, {"prompt_version": "v0"}, {"requested_model": "arbitrary-model"},
    {"schema_id": "DraftOutput"}, {"run_id": "not-a-uuid"},
])
def test_internal_enqueue_validates_versions_variables_sizes_and_ids(web, changes):
    pair(web)
    with pytest.raises(WorkerError):
        enqueue(web, **changes)


def test_subset_capabilities_and_document_wire_schema_are_validated(web):
    cap = manifest(MODEL)
    cap["definitions"] = [d for d in cap["definitions"] if d["prompt_id"] == "pi_extract"]
    device, _, _ = pair(web, capabilities=cap)
    with pytest.raises(WorkerError, match="unsupported_version"):
        enqueue(web)
    job = enqueue(web, prompt_id="pi_extract", prompt_version="v1", schema_id="PIExtractionWire", variables={"text": "가상 PI"})
    claim(web, device)
    assert complete(web, device, job, result(job, value={"items": [{"quantity": 1.1}]})).status_code == 422
    assert complete(web, device, job, result(job, value={})).status_code == 200
    with pytest.raises(WorkerError):
        enqueue(web, prompt_id="pi_extract", schema_id="PIExtractionWire", variables={"text": "가" * 20001})


def test_terminal_job_cannot_be_reported_cancelled_and_modifications_require_csrf(web):
    client, config, clock = web
    device, _, csrf = pair(web)
    job = enqueue(web)
    claim(web, device)
    for url, value in (
        ("/api/ai-execution/mode", {"ai_execution_mode": "stored_key"}),
        (f"/api/ai-execution/devices/{device['device_id']}/disconnect", {}),
        (f"/api/ai-execution/jobs/{job['job_id']}/cancel", {}),
    ):
        assert client.post(url, json=value).status_code == 403
    assert complete(web, device, job).status_code == 200
    assert client.post(f"/api/ai-execution/jobs/{job['job_id']}/cancel", json={"csrf_token": csrf}).status_code == 409
    assert client.get("/api/ai-execution").json()["jobs"][0]["status"] == "succeeded"


def test_pairing_secret_is_required_and_credentials_are_delivered_once_under_race(web):
    client, config, clock = web
    device, pending, csrf = pair(web)
    url = f"/api/worker/pairings/{pending['pairing_id']}/poll"
    assert client.post(url, json={"device_secret": "wrong-secret" * 4}).status_code == 401
    created = client.post("/api/worker/pairings", json={"device_name": "가상 교체 PC", "capabilities": manifest(MODEL)}).json()
    assert client.post("/api/ai-execution/pairings/approve", json={"device_name": "가상 교체 PC",
                       "pairing_code": created["pairing_code"], "csrf_token": csrf}).status_code == 200
    barrier = Barrier(2)
    def poll_together(_):
        barrier.wait(timeout=5)
        return client.post(f"/api/worker/pairings/{created['pairing_id']}/poll",
                           json={"device_secret": created["device_secret"]})
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(poll_together, range(2)))
    assert sorted(r.status_code for r in replies) == [200, 410]
    assert sum("device_token" in r.json() for r in replies) == 1


@pytest.mark.parametrize("name", ["", "   ", " 가상 PC", "가상 PC ", "가상\nPC"])
def test_pairing_names_are_explicit_and_visible(web, name):
    response = web[0].post("/api/worker/pairings", json={"device_name": name, "capabilities": manifest(MODEL)})
    assert response.status_code == 400


def test_all_installed_protocol_schema_pairs_and_schema_hashes():
    from tests.test_llm import _production_schemas
    # 각 설치 스키마가 검증 가능한지 기존 실제 SDK 시험의 가상 응답을 재사용한다.
    values = {schema.__name__: value for schema, value in _production_schemas()}
    for d in definitions():
        cap = d.capability()
        assert len(cap["prompt_sha256"]) == len(cap["schema_sha256"]) == 64
        value = values[d.schema.__name__]
        envelope = dict(protocol_version=1, job_id=str(uuid4()), attempt_id=str(uuid4()), device_id=str(uuid4()),
                        schema_id=d.schema.__name__, schema_version="v1", ok=True, value=value, duration_ms=0)
        assert validate_result(envelope, d.schema.__name__, "v1").ok
