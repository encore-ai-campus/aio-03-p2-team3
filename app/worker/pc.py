"""개인 PC 전용 실행기. 서버에서 실행 코드·프롬프트·스키마·OpenAI URL을 받지 않는다."""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import signal
from threading import Event
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from dotenv import dotenv_values
from langchain_openai import ChatOpenAI

from app.config import LIMITS
from app.llm.client import DEFAULT_MODEL, _http_code, classify_error, structured_output
from app.worker.protocol import MAX_JSON_BYTES, WorkerError, find_definition, json_bytes, manifest, validate_request, validate_result
from app.worker.credentials import read_private, write_private


def service_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise WorkerError("https_required")
    return value.rstrip("/")


@dataclass(frozen=True)
class LocalPolicy:
    service: str
    owner: str = field(repr=False)
    key: str = field(repr=False)
    model: str = DEFAULT_MODEL
    max_output_tokens: int = 2048
    requests_per_minute: int = 10
    max_concurrency: int = 1

    def __post_init__(self):
        service_url(self.service)
        if not self.owner.strip():
            raise WorkerError("owner_mismatch")
        if not 1 <= self.max_output_tokens <= 32768 or not 1 <= self.requests_per_minute <= 60 or self.max_concurrency != 1:
            raise WorkerError("invalid_input")
        if not self.model.strip():
            raise WorkerError("invalid_input")


def load_policy(args):
    # 지정한 개인 파일만 읽는다. 서버/프로세스의 OPENAI_* 값으로 대체하지 않는다.
    env = dotenv_values(args.env)
    return LocalPolicy(service_url(args.service), env.get("LOCAL_OWNER_GOOGLE_SUB") or "",
                       env.get("OPENAI_API_KEY") or "", env.get("OPENAI_MODEL") or DEFAULT_MODEL,
                       args.max_output_tokens, args.requests_per_minute, args.max_concurrency)


def _backend(policy):
    # SDK 환경변수의 BASE_URL/HEADERS/조직 설정도 목적지를 바꾸지 못한다.
    return ChatOpenAI(model=policy.model, api_key=policy.key.strip(),
                      base_url="https://api.openai.com/v1", organization="", project="",
                      default_headers={}, use_responses_api=True, http_socket_options=(),
                      max_retries=0, timeout=LIMITS["LLM_TIMEOUT_SECONDS"],
                      max_tokens=policy.max_output_tokens)


def save_credentials(path, policy, value):
    """토큰을 출력하지 않고 사용자 전용 파일에 저장한다. 기존 파일/심볼릭 링크를 덮지 않는다."""
    if value.get("google_sub") != policy.owner:
        raise WorkerError("owner_mismatch")
    UUID(value["device_id"])
    data = {k: value[k] for k in ("device_id", "device_token", "google_sub", "expires_at")}
    data["service"] = policy.service
    write_private(path, json_bytes(data))


def read_credentials(path, policy):
    value = json.loads(read_private(path, MAX_JSON_BYTES))
    if value["service"] != policy.service or value["google_sub"] != policy.owner:
        raise WorkerError("owner_mismatch")
    if datetime.fromisoformat(value["expires_at"]) <= datetime.now(UTC):
        raise WorkerError("expired")
    UUID(value["device_id"])
    if not isinstance(value["device_token"], str) or not 40 <= len(value["device_token"]) <= 100:
        raise WorkerError("unauthorized")
    return value


class PCWorker:
    def __init__(self, policy, credentials=None, *, http=None, stop=None):
        self.policy, self.credentials = policy, credentials
        self.stop = stop or Event()
        self.http = http or httpx.Client(timeout=httpx.Timeout(30, connect=10), follow_redirects=False)
        self.calls = deque()

    def request(self, method, path, value=None, *, authenticated=False):
        headers = {}
        if authenticated:
            headers["Authorization"] = "Bearer " + self.credentials["device_token"]
        # 경로는 설치 코드가 구성한다. 리다이렉트·서버가 준 URL을 따르지 않는다.
        with self.http.stream(method, self.policy.service + path, json=value, headers=headers,
                              follow_redirects=False) as response:
            if response.status_code != 200:
                code = {401: "unauthorized", 403: "owner_mismatch", 410: "expired", 429: "rate_limit",
                        409: "unsupported_version"}.get(response.status_code, "worker_unavailable")
                raise WorkerError(code, response.status_code)
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > MAX_JSON_BYTES:
                    raise WorkerError("payload_too_large")
            return json.loads(data)

    def check_protocol(self):
        if self.request("GET", "/api/worker/protocol") != manifest(self.policy.model):
            raise WorkerError("unsupported_version")

    def pair(self, path, name):
        self.check_protocol()
        created = self.request("POST", "/api/worker/pairings", {
            "device_name": name, "capabilities": manifest(self.policy.model)})
        pairing_id = str(UUID(created["pairing_id"]))
        # 유일하게 표시하는 일회용 연결 코드. secret/token/키는 출력하지 않는다.
        print(f"서비스: {self.policy.service}\n장치 이름: {name}\n연결 코드: {created['pairing_code']}", flush=True)
        print("본인 Google 계정의 /settings에서 이름·코드를 대조하고 승인하세요. 10분 뒤 만료됩니다.", flush=True)
        deadline = monotonic() + 600
        while monotonic() < deadline and not self.stop.is_set():
            result = self.request("POST", f"/api/worker/pairings/{pairing_id}/poll",
                                  {"device_secret": created["device_secret"]})
            if result["status"] == "connected":
                save_credentials(path, self.policy, result)
                print("본인 계정 확인·장치 연결 완료. run 명령으로 시작하세요.", flush=True)
                return
            self.stop.wait(5)
        raise WorkerError("expired")

    def execute(self, raw):
        """시도마다 SDK 1회. 모든 예외는 안전한 오류 종류로만 변환한다."""
        keys = ("protocol_version", "job_id", "attempt_id", "device_id", "schema_id", "schema_version")
        envelope = {key: raw[key] for key in keys}
        started = monotonic()
        try:
            job = validate_request(raw, manifest(self.policy.model), self.policy.model)
            if job.device_id != self.credentials["device_id"] or self.credentials["google_sub"] != self.policy.owner:
                raise WorkerError("owner_mismatch")
            remaining = (datetime.fromisoformat(job.expires_at) - datetime.now(UTC)).total_seconds()
            if remaining <= LIMITS["LLM_TIMEOUT_SECONDS"]:
                raise WorkerError("expired")
            if not self.policy.key.strip():
                raise WorkerError("key_required")
            now = monotonic()
            while self.calls and self.calls[0] <= now - 60:
                self.calls.popleft()
            if len(self.calls) >= self.policy.requests_per_minute:
                raise WorkerError("rate_limit")
            self.calls.append(now)
            definition = find_definition(job.prompt_id, job.prompt_version, job.schema_id, job.schema_version)
            backend = _backend(self.policy)
            value = structured_output(backend, definition.schema).invoke(definition.prompt.TEMPLATE.format_map(job.variables))
            value = definition.schema.model_validate(value).model_dump(mode="json")
            encoded = json_bytes(value).decode()
            # 키·장치 인증값이 모델 출력에 들어 있어도 서버/문서로 전달하지 않는다.
            if any(secret and secret in encoded for secret in (self.policy.key.strip(), self.credentials["device_token"])):
                raise WorkerError("invalid_output")
            if datetime.fromisoformat(job.expires_at) <= datetime.now(UTC):
                raise WorkerError("expired")
            result = {**envelope, "ok": True, "value": value, "duration_ms": min(30000, int((monotonic() - started) * 1000))}
            validate_result(result, job.schema_id, job.schema_version)
            return result
        except WorkerError as error:
            kind = error.code if error.code in {"owner_mismatch", "key_required", "expired", "rate_limit", "unsupported_version", "invalid_output"} else "invalid_input"
        except Exception as error:
            # API 401/403은 로컬 키 거부로 구분한다. SDK 메시지/원문은 보관·출력하지 않는다.
            kind = "key_required" if _http_code(error) in {401, 403} else classify_error(error)
        return {**envelope, "ok": False, "error_kind": kind}

    def run(self):
        self.check_protocol()
        device_id = str(UUID(self.credentials["device_id"]))
        prefix = f"/api/worker/devices/{device_id}"
        print(f"개인 AI 실행 시작: {self.policy.service} · 모델 {self.policy.model} · 출력 {self.policy.max_output_tokens} 토큰 · 분당 {self.policy.requests_per_minute}회 · 동시 1개. 중지: Ctrl+C", flush=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            while not self.stop.is_set():
                raw = self.request("POST", prefix + "/claim", {"wait_seconds": 5}, authenticated=True)["job"]
                if raw is None or self.stop.is_set():
                    continue
                # HTTP 경로에 쓰기 전에 식별자의 형식과 본인 장치를 검사한다.
                UUID(raw["job_id"])
                UUID(raw["attempt_id"])
                if raw["device_id"] != device_id:
                    raise WorkerError("owner_mismatch")
                future = pool.submit(self.execute, raw)
                while not self.stop.is_set():
                    try:
                        result = future.result(timeout=10)
                        self.request("POST", prefix + f"/jobs/{raw['job_id']}/complete", result, authenticated=True)
                        break
                    except FutureTimeout:
                        self.request("POST", prefix + f"/jobs/{raw['job_id']}/heartbeat",
                                     {"attempt_id": raw["attempt_id"]}, authenticated=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Windows/macOS/Linux에서 개인 .env의 본인 키만 사용하는 AI 실행기. Windows PowerShell에서 WSL 없이 실행할 수 있습니다. 서버 URL과 Google 식별자를 직접 지정하세요.",
        epilog="설치: uv sync. pair 후 서버 /settings에서 승인하고 run. PC를 켜 두어야 AI가 동작합니다. 중지: Ctrl+C. 해제: 서버 설정. 키 교체/삭제: .env 수정 후 재시작. HTTPS 인증서 검증을 유지하며 서버는 여전히 메일·프롬프트 변수·AI 결과를 봅니다. 전체 로컬 앱: uv run python -m app.local. 문제 해결은 README 개인 PC AI 실행 절을 확인하세요.")
    parser.add_argument("command", choices=["pair", "run"])
    parser.add_argument("--service", required=True, help="본인이 허용하는 HTTPS 서비스 원점")
    parser.add_argument("--env", default=".env", help="개인 PC .env 파일 (업로드하지 않음)")
    parser.add_argument("--credentials", default=".worker-device.json", help="본인 전용 장치 토큰 파일")
    parser.add_argument("--name", default="개인 PC", help="pair 때 서버 화면과 대조할 이름")
    parser.add_argument("--max-output-tokens", type=int, default=2048, help="PC에서 강제할 출력 토큰 상한")
    parser.add_argument("--requests-per-minute", type=int, default=10, help="PC에서 강제할 분당 호출 상한 (1~60)")
    parser.add_argument("--max-concurrency", type=int, choices=[1], default=1, help="PC와 서버의 동시 작업 상한")
    args = parser.parse_args(argv)
    stop = Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    # HTTP 라이브러리 로그가 Bearer 헤더/요청 내용을 출력하지 않게 기본 수준을 유지한다.
    import logging
    for name in ("httpx", "httpcore", "openai", "langchain"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    try:
        policy = load_policy(args)
        credentials = read_credentials(args.credentials, policy) if args.command == "run" else None
        with httpx.Client(timeout=30, follow_redirects=False) as http:
            worker = PCWorker(policy, credentials, http=http, stop=stop)
            worker.pair(args.credentials, args.name) if args.command == "pair" else worker.run()
        return 0
    except Exception as error:
        code = error.code if isinstance(error, WorkerError) else "worker_unavailable"
        print(f"실행 중단: {code}. README의 문제 해결을 확인하세요. 서버 저장 키로 전환하지 않습니다.", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
