"""본인 PC 정책·실제 SDK와 HTTP 대역·여러 DB 연결의 큐 결과 전달을 검증한다."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
import os
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import httpx
from langchain_openai import ChatOpenAI
import pytest
from sqlalchemy import select

from app.db.engine import Database
from app.db.models import ReplyCandidate, User, WorkerDevice, WorkerJob
from app.graph.run import start_run
from app.llm import client as llm
from app.prompts import analyze_email
from app.services.openai_keys import save_key, user_openai
from app.worker import pc, service
from app.worker.protocol import WorkerError, manifest
from tests.test_worker_queue import web, pair, enqueue, claim, complete, result, auth, path


@pytest.fixture
def http_sdk(monkeypatch):
    requests, replies, clients = [], [], []
    def respond(request):
        body = json.loads(request.content)
        requests.append((dict(request.headers), body))
        response = replies.pop(0) if replies else {"intent": "general", "reason": "가상 문의"}
        if isinstance(response, int):
            return httpx.Response(response, json={"error": {"message": "fake-secret-never-export", "type": "fake_error"}})
        name = body["tools"][0]["name"]
        return httpx.Response(200, json={
            "id": "resp_fake", "object": "response", "created_at": 1, "model": body["model"],
            "status": "completed", "error": None, "incomplete_details": None,
            "output": [{"type": "function_call", "id": "fc_fake", "call_id": "call_fake",
                        "name": name, "arguments": json.dumps(response)}],
            "parallel_tool_calls": False, "tool_choice": body["tool_choice"], "tools": body["tools"],
            "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10}})
    def backend(policy):
        http = httpx.Client(transport=httpx.MockTransport(respond))
        clients.append(http)
        return ChatOpenAI(model=policy.model, api_key=policy.key, base_url="https://api.openai.com/v1",
                          use_responses_api=True, max_retries=0, timeout=20, http_client=http,
                          http_socket_options=(), max_tokens=policy.max_output_tokens)
    monkeypatch.setattr(pc, "_backend", backend)
    yield requests, replies
    for http in clients:
        http.close()


def worker_for(web, device, **limits):
    return pc.PCWorker(pc.LocalPolicy("https://testserver", device["google_sub"], "fake-local-pc-key", **limits), device)


def fresh_job(web):
    device, _, _ = pair(web)
    job = enqueue(web)
    # 3절 테스트의 고정 DB 시계 대신 PC의 실제 시계를 기준으로 만든 프로토콜 입력.
    now = datetime.now(UTC)
    job.update(created_at=now.isoformat(), expires_at=(now + timedelta(seconds=120)).isoformat())
    return worker_for(web, device), job


def test_sdk_uses_only_local_key_model_token_cap_once(web, http_sdk):
    worker, job = fresh_job(web)
    worker.policy = replace(worker.policy, max_output_tokens=77)
    output = worker.execute(job)
    assert output["ok"] and output["value"]["intent"] == "general"
    requests, _ = http_sdk
    [(headers, body)] = requests
    assert headers["authorization"] == "Bearer fake-local-pc-key"
    assert body["model"] == worker.policy.model and body["max_output_tokens"] == 77
    assert "fake-local-pc-key" not in json.dumps(output)
    assert "fake-local-pc-key" not in repr(worker.policy)


@pytest.mark.parametrize("code,kind", [(401, "key_required"), (403, "key_required"), (429, "rate_limit"), (503, "network")])
def test_pc_sdk_never_retries_or_exports_raw_errors(web, http_sdk, code, kind):
    worker, job = fresh_job(web)
    http_sdk[1].append(code)
    output = worker.execute(job)
    assert output["ok"] is False and output["error_kind"] == kind
    assert len(http_sdk[0]) == 1
    assert "fake-secret-never-export" not in json.dumps(output)


@pytest.mark.parametrize("change,kind", [
    ({"requested_model": "server-chosen-unapproved"}, "unsupported_version"),
    ({"prompt_version": "v99"}, "unsupported_version"),
    ({"variables": {"code": "arbitrary executable content"}}, "invalid_input"),
    ({"url": "https://unapproved.invalid"}, "invalid_input"),
    ({"created_at": (datetime.now(UTC) - timedelta(seconds=100)).isoformat(),
      "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat()}, "expired"),
])
def test_pc_refuses_unapproved_input_before_sdk(web, http_sdk, change, kind):
    worker, job = fresh_job(web)
    output = worker.execute({**job, **change})
    assert output["ok"] is False and output["error_kind"] == kind
    assert not http_sdk[0]


def test_pc_local_rate_owner_key_and_output_secrets_cannot_be_overridden(web, http_sdk):
    worker, job = fresh_job(web)
    worker.policy = replace(worker.policy, requests_per_minute=1)
    assert worker.execute(job)["ok"]
    assert worker.execute({**job, "attempt_id": str(uuid4())})["error_kind"] == "rate_limit"
    worker.policy = replace(worker.policy, owner="different-sub")
    assert worker.execute(job)["error_kind"] == "owner_mismatch"
    worker.policy = replace(worker.policy, owner=worker.credentials["google_sub"], key="")
    assert worker.execute(job)["error_kind"] == "key_required"
    assert len(http_sdk[0]) == 1
    worker.policy = replace(worker.policy, key="fake-local-pc-key", requests_per_minute=10)
    http_sdk[1].append({"intent": "general", "reason": "fake-local-pc-key"})
    assert worker.execute(job)["error_kind"] == "invalid_output"
    http_sdk[1].append({"intent": "general", "reason": worker.credentials["device_token"]})
    assert worker.execute(job)["error_kind"] == "invalid_output"


@pytest.mark.parametrize("url", ["http://example.invalid", "https://user:pass@example.invalid", "https://example.invalid/path", "https://example.invalid?query=1"])
def test_service_is_explicit_https_origin(url):
    with pytest.raises(WorkerError):
        pc.service_url(url)


def test_credentials_private_owner_service_expiry_and_no_overwrite(tmp_path):
    policy = pc.LocalPolicy("https://testserver", "fake-sub", "fake-key")
    value = dict(device_id=str(uuid4()), device_token="x" * 43, google_sub="fake-sub",
                 expires_at=(datetime.now(UTC) + timedelta(days=1)).isoformat())
    path = tmp_path / "credentials"
    pc.save_credentials(path, policy, value)
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
    assert pc.read_credentials(path, policy)["device_token"] == "x" * 43
    with pytest.raises(FileExistsError):
        pc.save_credentials(path, policy, value)
    with pytest.raises(WorkerError):
        pc.read_credentials(path, replace(policy, owner="other"))
    with pytest.raises(WorkerError):
        pc.read_credentials(path, replace(policy, service="https://different.invalid"))
    if os.name == "posix":
        path.chmod(0o644)
        with pytest.raises(WorkerError):
            pc.read_credentials(path, policy)


def test_queue_result_is_encrypted_consumed_once_and_rechecked_after_disconnect(web):
    client, config, clock = web
    device, _, csrf = pair(web)
    job = enqueue(web)
    assert claim(web, device).json()["job"]
    assert complete(web, device, job).status_code == 200
    database = client.app.state.database
    with database.session() as session:
        row = session.get(WorkerJob, job["job_id"])
        assert row.payload is None and row.result_enc and "가상 문의" not in row.result_enc
    other_connection = Database(config.database_url)
    try:
        outcome = service.outcome(other_connection, 1, job["job_id"], job["attempt_id"], client.app.state.google_access.cipher)
        assert outcome["ok"] and outcome["value"]["intent"] == "general"
        assert service.outcome(database, 1, job["job_id"], job["attempt_id"], client.app.state.google_access.cipher)["ok"] is False
        second = enqueue(web)
        claim(web, device)
        complete(web, device, second)
        service.disconnect(database, 1, device["device_id"])
        assert service.outcome(database, 1, second["job_id"], second["attempt_id"], client.app.state.google_access.cipher)["ok"] is False
        with database.session() as session:
            assert session.get(WorkerJob, second["job_id"]).result_enc is None
    finally:
        other_connection.close()


def wait_job(web, device):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        response = claim(web, device)
        assert response.status_code == 200, response.text
        if response.json()["job"]:
            return response.json()["job"]
        sleep(0.05)
    pytest.fail("작업이 생성되지 않았습니다")


@pytest.mark.parametrize("errors,expected,attempts", [
    (["network", "network"], None, 3), (["invalid_output"], None, 2),
    (["rate_limit"], "WORKER_RATE_LIMIT", 1), (["key_required"], "WORKER_KEY_REQUIRED", 1),
    (["unsupported_version"], "WORKER_VERSION_MISMATCH", 1),
    (["owner_mismatch"], "WORKER_OWNER_MISMATCH", 1),
    (["network"] * 3, "WORKER_NETWORK", 3),
])
def test_server_owns_retry_budget_and_preserves_job_and_deadline(web, errors, expected, attempts):
    client, config, clock = web
    device, _, _ = pair(web)
    database = client.app.state.database
    save_key(database, 1, "fake-user-stored-key", client.app.state.google_access.cipher, settings=config)
    def run():
        with user_openai(database, 1, settings=config, cipher=client.app.state.google_access.cipher) as access:
            output = llm.call_structured(analyze_email.PROMPT,
                __import__("app.graph.nodes.analyze_email", fromlist=["EmailAnalysis"]).EmailAnalysis,
                {"thread_context": "", "email": "가상 문의"})
            return output, access.issue
    jobs = []
    with ThreadPoolExecutor() as pool:
        future = pool.submit(run)
        for index in range(attempts):
            job = wait_job(web, device)
            jobs.append(job)
            if index < len(errors):
                body = {k: job[k] for k in ("protocol_version", "job_id", "attempt_id", "device_id", "schema_id", "schema_version")}
                body.update(ok=False, error_kind=errors[index])
            else:
                body = result(job)
            assert complete(web, device, job, body).status_code == 200
        output, issue = future.result(timeout=10)
    assert output.attempts == attempts and (issue.code if issue else None) == expected
    assert output.ok is (expected is None)
    assert len({job["job_id"] for job in jobs}) == 1
    assert len({job["attempt_id"] for job in jobs}) == attempts
    assert len({job["expires_at"] for job in jobs}) == 1
    if attempts > 1:
        assert complete(web, device, jobs[0]).status_code == 404


def test_offline_worker_never_reads_stored_key_and_returns_specific_error(web):
    client, config, clock = web
    device, _, _ = pair(web)
    clock[0] += timedelta(seconds=46)
    database = client.app.state.database
    save_key(database, 1, "fake-user-stored-key", client.app.state.google_access.cipher, settings=config)
    with user_openai(database, 1, settings=config, cipher=client.app.state.google_access.cipher) as access:
        from app.graph.nodes.analyze_email import EmailAnalysis
        output = llm.call_structured(analyze_email.PROMPT, EmailAnalysis, {"thread_context": "", "email": "가상 문의"})
    assert output.ok is False and access.issue.code == "WORKER_UNAVAILABLE"
    assert output.attempts == 0


@pytest.mark.parametrize("stop_kind", ["lease_expired", "disconnected", "deadline"])
def test_interrupted_mail_run_saves_no_candidates_and_rejects_late_result(web, email, stop_kind):
    client, config, clock = web
    device, _, _ = pair(web)
    database = client.app.state.database
    with ThreadPoolExecutor() as pool:
        future = pool.submit(start_run, user_id=1, email=email, database=database,
                             key_cipher=client.app.state.google_access.cipher)
        job = wait_job(web, device)
        if stop_kind == "disconnected":
            service.disconnect(database, 1, device["device_id"])
        else:
            clock[0] += timedelta(seconds=31 if stop_kind == "lease_expired" else 121)
        state = future.result(timeout=10)
    assert state["end_reason"] == "failed" and not state["candidates"]
    assert state["notice"] == ("worker_unavailable" if stop_kind == "disconnected" else "worker_timeout")
    assert complete(web, device, job).status_code in (401, 410)
    with database.session() as session:
        assert not list(session.scalars(select(ReplyCandidate)))
        row = session.get(WorkerJob, job["job_id"])
        assert row.payload is None and row.result_enc is None


def test_expired_unconsumed_encrypted_result_is_purged_on_restart_cleanup(web):
    client, config, clock = web
    device, _, _ = pair(web)
    job = enqueue(web)
    claim(web, device)
    complete(web, device, job)
    clock[0] += timedelta(seconds=121)
    other = Database(config.database_url)
    try:
        service.cleanup(other)
        with other.session() as session:
            assert session.get(WorkerJob, job["job_id"]).result_enc is None
    finally:
        other.close()
