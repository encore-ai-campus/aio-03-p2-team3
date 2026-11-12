"""실제 HTTPS 서버·별도 PC 프로세스 두 개·모의 OpenAI HTTP로 종단 간 검증한다."""
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
from ipaddress import ip_address
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
from time import monotonic, sleep

from cryptography.fernet import Fernet
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import httpx
from itsdangerous import TimestampSigner
import pytest
from sqlalchemy import select

from app.config import Settings
from app.db.engine import Database
from app.db.models import ProcessedMessage, ReplyCandidate, RunEvent, ThreadMessage, TradeDocument, User, WorkerDevice, WorkerJob
from app.services.auth import GoogleAccess, TokenCipher
from app.services.openai_keys import save_key
from app.services.watch import register_watch
from app.worker.pc import LocalPolicy, save_credentials
from app.worker.protocol import manifest
from tests.fakes.gmail import FakeGmailGoogle
from tests.test_gmail_push import setup_user, push_payload
from tests.test_pi_domain import pi_input
from tests.test_trade_flow import seal_png


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def until(function, seconds=15):
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        try:
            value = function()
            if value:
                return value
        except (httpx.TransportError, OSError):
            pass
        sleep(0.05)
    raise AssertionError("프로세스 시험의 완료 조건을 기다리다 시간이 초과됐습니다")


@contextmanager
def process(command, env):
    proc = subprocess.Popen([sys.executable, "-m", "tests.fakes.worker_process", *command],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.terminate()
        try:
            output, _ = proc.communicate(timeout=35)
        except subprocess.TimeoutExpired:
            proc.kill()
            output, _ = proc.communicate(timeout=5)
        assert all(key not in output for key in ("fake-pc-one", "fake-pc-two", "fake-pc-rotated", "fake-sensitive-sdk-error"))


@pytest.fixture
def system(tmp_path):
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(private.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip_address("127.0.0.1")),
                                                  x509.DNSName("localhost")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(private, hashes.SHA256()))
    key.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    ports = free_port(), free_port()
    service, mock = (f"https://127.0.0.1:{port}" for port in ports)
    config = Settings(database_url=f"sqlite:///{tmp_path / 'server.sqlite3'}", session_secret="fake-session",
                      token_encryption_key=Fernet.generate_key().decode(), app_base_url=service,
                      gmail_pubsub_topic="projects/fake/topics/fake", pubsub_push_token="fake-push-token")
    envfile = tmp_path / "server.env"
    envfile.write_text("\n".join(f"{name.upper()}={getattr(config, name)}" for name in (
        "database_url", "session_secret", "token_encryption_key", "app_base_url", "gmail_pubsub_topic", "pubsub_push_token")))
    database = Database(config.database_url)
    database.create_tables()
    cipher = TokenCipher(config.token_encryption_key)
    access = GoogleAccess(database, FakeGmailGoogle(), cipher, config.gmail_pubsub_topic)
    setup_user(access)
    setup_user(access, sub="fake-sub-2", address="other@example.invalid")
    for user_id in (1, 2):
        save_key(database, user_id, f"fake-server-stored-{user_id}", cipher, settings=config)
    with database.session() as session:
        session.get(User, 1).reflection_enabled = True
        for index in range(9):
            session.add(ThreadMessage(user_id=1, thread_id="fake-thread", gmail_message_id=f"old-{index}",
                direction="in", from_addr="sender@example.invalid", to_addrs=["demo@example.invalid"],
                subject="가상 과거 문의", body_text="가상 과거 내용", sent_at=datetime(2026, 11, 9, index, tzinfo=UTC)))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "LOCAL_OWNER_", "AI_RUNTIME"))}
    env["SSL_CERT_FILE"] = str(cert)
    with process(["server", "--env", str(envfile), "--port", str(ports[0]), "--cert", str(cert), "--key", str(key)], env), \
         process(["openai", "--port", str(ports[1]), "--cert", str(cert), "--key", str(key)], env), \
         httpx.Client(base_url=service, verify=ssl.create_default_context(cafile=str(cert)), timeout=15) as http, \
         httpx.Client(base_url=mock, verify=ssl.create_default_context(cafile=str(cert)), timeout=5) as openai:
        until(lambda: http.get("/healthz").status_code == 200)
        until(lambda: openai.get("/test/state").status_code == 200)
        yield dict(http=http, openai=openai, database=database, config=config, env=env,
                   service=service, mock=mock, tmp=tmp_path, cert=cert)
    database.close()


def login(system, user_id):
    http = system["http"]
    data = b64encode(json.dumps({"user_id": user_id}).encode())
    http.cookies.clear()
    http.cookies.set("gq_session", TimestampSigner(system["config"].session_secret).sign(data).decode())
    page = http.get("/settings")
    assert page.status_code == 200
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    http.headers["X-CSRF-Token"] = csrf
    return csrf


def connect(system, user_id):
    login(system, user_id)
    http = system["http"]
    assert http.post("/api/ai-execution/mode", json={"ai_execution_mode": "local_worker"}).status_code == 200
    name = f"가상 PC {user_id}"
    pair = http.post("/api/worker/pairings", json={"device_name": name, "capabilities": manifest("gpt-6-luna")}).json()
    assert http.post("/api/ai-execution/pairings/approve", json={"pairing_code": pair["pairing_code"], "device_name": name}).status_code == 200
    device = http.post(f"/api/worker/pairings/{pair['pairing_id']}/poll", json={"device_secret": pair["device_secret"]}).json()
    policy = LocalPolicy(system["service"], f"fake-sub-{user_id}", f"fake-pc-{'one' if user_id == 1 else 'two'}")
    credentials = system["tmp"] / f"device-{user_id}.json"
    save_credentials(credentials, policy, device)
    envfile = system["tmp"] / f"pc-{user_id}.env"
    envfile.write_text(f"LOCAL_OWNER_GOOGLE_SUB={policy.owner}\nOPENAI_API_KEY={policy.key}\n")
    return device, envfile, credentials


def command(system, envfile, credentials):
    return ["pc", "--mock-url", system["mock"] + "/v1", "run", "--service", system["service"],
            "--env", str(envfile), "--credentials", str(credentials), "--max-output-tokens", "313", "--requests-per-minute", "60"]


def test_two_real_pc_processes_gmail_without_session_documents_and_manual_flow(system):
    one, env_one, token_one = connect(system, 1)
    two, env_two, token_two = connect(system, 2)
    http, openai, database = (system[k] for k in ("http", "openai", "database"))
    with process(command(system, env_one, token_one), system["env"]), process(command(system, env_two, token_two), system["env"]):
        # 로그인 쿠키 없이 Gmail 푸시 → 서버 그래프 → 별도 PC → 후보, 승인 전 미발송.
        http.cookies.clear()
        response = http.post("/gmail/push?token=fake-push-token", json=push_payload())
        assert response.status_code == 204
        def pending():
            with database.session() as session:
                return session.scalar(select(ProcessedMessage).where(ProcessedMessage.status == "awaiting_approval"))
        until(pending, 20)
        assert http.get("/test/state").json()["sends"] == 0
        with database.session() as session:
            candidates = list(session.scalars(select(ReplyCandidate)))
        login(system, 1)
        assert http.post(f"/candidates/{candidates[0].id}/approve").status_code == 303
        assert http.get("/test/state").json()["sends"] == 1
        # 다른 사용자들의 추출은 서로 다른 PC의 .env 키를 사용한다.
        for user_id in (1, 2):
            login(system, user_id)
            for kind in ("pi", "po", "pl"):
                response = http.post(f"/api/trade/{kind}/extract", json={"text": "가상 문서"})
                assert response.status_code == 201, response.text
        with httpx.Client(base_url=system["service"], verify=ssl.create_default_context(cafile=str(system["cert"])), timeout=15) as second:
            login({**system, "http": second}, 2)
            login(system, 1)
            with ThreadPoolExecutor() as pool:
                concurrent = [pool.submit(http.post, "/api/trade/pi/extract", json={"text": "OWNER1 가상 문서"}),
                              pool.submit(second.post, "/api/trade/pi/extract", json={"text": "OWNER2 가상 문서"})]
                assert all(future.result().status_code == 201 for future in concurrent)
        # 웹 요청 세션 밖의 거래 도구도 사용자 범위의 같은 큐를 사용한다.
        from app.services.openai_keys import user_openai
        from app.tools.extract_deal_terms import extract_deal_terms
        with user_openai(database, 2, settings=system["config"], cipher=TokenCipher(system["config"].token_encryption_key)):
            deal = extract_deal_terms.invoke({"email": {
                "gmail_message_id": "deal-test", "thread_id": "deal-test", "rfc_message_id": None,
                "from_addr": "sender@example.invalid", "from_name": None, "to_addrs": ["other@example.invalid"],
                "subject": "가상 견적 문의", "body_text": "가상상사 견적 문의", "received_at": datetime.now(UTC).isoformat(), "direction": "in"}})
            assert deal.ok
        # CI의 원본 PI는 사용자가 직접 작성/검토/승인한 특정 버전으로 고정한다.
        login(system, 1)
        assert http.put("/api/trade/settings/company", json={"company_name": "Testworks", "legal_name_en": "Testworks", "address": "Test address"}).status_code == 200
        assert http.put("/api/trade/settings/banks/USD", json={"beneficiary": "Testworks", "bank_name": "Example", "branch": "Example", "swift": "EXAMPLE", "account_number": "000", "bank_address": "Test address"}).status_code == 200
        assert http.put("/api/trade/settings/prices", json={"item_name": "Virtual Serum", "capacity": "50ml", "role": "sale", "currency": "USD", "unit_price": "8", "price_basis": "PCS"}).status_code == 200
        assert http.post("/api/trade/settings/branding/seal", files={"image": ("seal.png", seal_png(), "image/png")}).status_code == 200
        source = http.post("/api/trade/pi", json=pi_input().model_dump(mode="json")).json()
        proposal = http.post(f"/api/trade/pi/{source['document_id']}/reviews", json={"revision": 1}).json()
        approved = http.post(f"/api/trade/pi/{source['document_id']}/reviews/{proposal['id']}/decisions", json={"action": "approve", "revision": 1, "content_hash": proposal["content_hash"]})
        assert approved.status_code == 200, approved.text
        assert http.get(approved.json()["files"][0]["download_url"]).status_code == 200
        response = http.post("/api/trade/ci/extract", json={"text": "가상 송장", "source_pi_id": source["document_id"], "source_revision": 1})
        assert response.status_code == 201, response.text
        calls = openai.get("/test/state").json()
        assert {c["key_tag"] for c in calls} == {"one", "two"}
        assert all(c["key_tag"] == c["owner_marker"] for c in calls if c["owner_marker"])
        assert all(c["tokens"] == 313 and c["model"] == "gpt-6-luna" for c in calls)
        assert {c["schema"] for c in calls} >= {"EmailAnalysis", "DraftOutput", "ThreadSummary", "ReflectAnalysis", "ExtractedDealTerms", "PIExtractionWire", "POExtractionWire", "CIExtractionWire", "PLExtractionWire"}
        with database.session() as session:
            jobs = list(session.scalars(select(WorkerJob)))
            events = list(session.scalars(select(RunEvent)))
            assert all(j.payload is None and j.result_enc is None for j in jobs)
            assert all(secret not in json.dumps([e.detail for e in events]) for secret in ("fake-pc-one", "fake-pc-two"))
        for url in ("/settings", "/api/ai-execution", "/inbox", "/threads/fake-thread"):
            body = http.get(url).text
            assert all(secret not in body for secret in ("fake-pc-one", "fake-pc-two", one["device_token"], two["device_token"]))


@pytest.mark.parametrize("code,expected,attempts", [(401, "WORKER_KEY_REQUIRED", 1), (429, "WORKER_RATE_LIMIT", 1), (503, "WORKER_NETWORK", 3)])
def test_real_pc_http_errors_do_not_create_documents(system, code, expected, attempts):
    device, envfile, credentials = connect(system, 1)
    with process(command(system, envfile, credentials), system["env"]):
        response = system["http"].post("/api/trade/pi/extract", json={"text": f"API{code}"})
        assert response.json()["error"]["code"] == expected, response.text
        assert len(system["openai"].get("/test/state").json()) == attempts
        with system["database"].session() as session:
            assert not list(session.scalars(select(TradeDocument)))


def test_pc_restart_reads_rotated_or_deleted_env_key_and_disconnect_blocks_results(system):
    device, envfile, credentials = connect(system, 1)
    http = system["http"]
    for value, tag in (("fake-pc-one", "one"), ("fake-pc-rotated", "rotated"), ("", None)):
        envfile.write_text(f"LOCAL_OWNER_GOOGLE_SUB=fake-sub-1\nOPENAI_API_KEY={value}\n")
        with process(command(system, envfile, credentials), system["env"]) as runner:
            try:
                response = http.post("/api/trade/pi/extract", json={"text": "가상 문서"})
            except httpx.TimeoutException:
                with system["database"].session() as session:
                    states = [(job.status, job.error_kind) for job in session.scalars(select(WorkerJob))]
                pytest.fail(f"PC restart {tag or 'deleted'}: exit={runner.poll()}, job states={states}")
            if tag:
                assert response.status_code == 201, response.text
                assert system["openai"].get("/test/state").json()[-1]["key_tag"] == tag
            else:
                assert response.json()["error"]["code"] == "WORKER_KEY_REQUIRED"
    assert http.post(f"/api/ai-execution/devices/{device['device_id']}/disconnect", json={}).status_code == 200
    response = http.post("/api/trade/pi/extract", json={"text": "가상 문서"})
    assert response.json()["error"]["code"] == "WORKER_UNAVAILABLE"
