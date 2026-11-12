"""기존 구조화 호출을 사용자별 큐로 연결한다. 재시도 책임은 이 서버 어댑터에만 둔다."""
from time import monotonic, sleep
from uuid import uuid4

from app.config import LIMITS
from app.llm.client import LLMResult, OpenAIKeyError, model_name
from app.runlog.logger import current_event, current_run_id
from app.worker import service
from app.worker.protocol import WorkerError, find_definition

ERRORS = {
    "worker_unavailable": ("WORKER_UNAVAILABLE", "개인 PC가 오프라인이거나 연결이 해제됐습니다. 실행 프로그램과 연결 상태를 확인하세요.", 409),
    "expired": ("WORKER_TIMEOUT", "개인 PC 작업 시간이 초과됐습니다. 프로그램을 확인하고 새 요청을 시작하세요.", 504),
    "unsupported_version": ("WORKER_VERSION_MISMATCH", "서버와 개인 실행 프로그램의 버전·모델을 맞추고 다시 연결하세요.", 409),
    "key_required": ("WORKER_KEY_REQUIRED", "개인 PC의 .env 키가 없거나 거부됐습니다. 키를 지정하고 실행 프로그램을 다시 시작하세요.", 409),
    "owner_mismatch": ("WORKER_OWNER_MISMATCH", "개인 PC에 지정한 본인 Google 계정과 연결 계정이 다릅니다.", 403),
    "rate_limit": ("WORKER_RATE_LIMIT", "OpenAI 또는 개인 PC의 요청 한도에 도달했습니다. 잠시 뒤 새 요청을 시작하세요.", 429),
    "network": ("WORKER_NETWORK", "개인 PC의 OpenAI 연결에 실패했습니다. 네트워크를 확인하세요.", 503),
    "invalid_output": ("WORKER_INVALID_OUTPUT", "개인 PC의 AI 결과 형식을 확인하지 못했습니다. 새 요청을 시작하거나 직접 입력하세요.", 503),
    "invalid_input": ("WORKER_INVALID_INPUT", "개인 PC에서 요청 모델·입력을 거부했습니다. 로컬 설정을 확인하세요.", 409),
    "internal": ("WORKER_FAILED", "개인 PC 작업을 완료하지 못했습니다. 프로그램을 확인하거나 직접 입력하세요.", 503),
}


class QueueCall:
    def __init__(self, access):
        self.access = access
        self.run_id = str(uuid4())

    def guard(self):
        if self.access.issue is not None:
            raise self.access.issue

    def __call__(self, prompt, schema, variables):
        access = self.access
        started, attempts, payload = monotonic(), 0, None
        counts = {"network": 0, "invalid_output": 0}
        model = model_name(access.settings)
        error_kind = "internal"
        value = None
        try:
            self.guard()
            if access.cipher is None:
                raise WorkerError("worker_unavailable", 409)
            definition = find_definition(prompt.NAME, prompt.VERSION, schema.__name__, "v1")
            if definition.prompt != prompt or definition.schema.model_json_schema() != schema.model_json_schema():
                raise WorkerError("unsupported_version", 409)
            payload = service.enqueue(access.database, access.user_id, prompt_id=prompt.NAME,
                prompt_version=prompt.VERSION, schema_id=schema.__name__, schema_version="v1",
                variables=variables, requested_model=model, run_id=current_run_id() or self.run_id, model=model)
            deadline = started + 120
            while True:
                attempts += 1
                while True:
                    outcome = service.outcome(access.database, access.user_id, payload["job_id"],
                                              payload["attempt_id"], access.cipher)
                    if outcome is not None:
                        break
                    if monotonic() >= deadline:
                        service.cancel(access.database, access.user_id, payload["job_id"])
                        raise WorkerError("expired", 410)
                    sleep(min(0.1, max(0, deadline - monotonic())))
                if outcome["ok"]:
                    value = schema.model_validate(outcome["value"])
                    error_kind = None
                    break
                error_kind = outcome["error_kind"]
                # 임대가 끊긴 시도는 재실행하지 않는다. 완료된 network/형식 오류만 예산 내 재시도한다.
                budget = {"network": LIMITS["LLM_MAX_RETRIES"],
                          "invalid_output": LIMITS["LLM_INVALID_OUTPUT_RETRIES"]}.get(error_kind, 0)
                delay = 2 ** counts["network"] if error_kind == "network" else 0
                if error_kind not in counts or counts[error_kind] >= budget or monotonic() + delay + 20 >= deadline:
                    break
                counts[error_kind] += 1
                current_event("retry", detail={"error_kind": error_kind, "error_code": "worker_" + error_kind,
                                               "attempt": attempts + 1})
                if delay:
                    sleep(delay)
                payload = service.retry(access.database, access.user_id, payload, model)
        except WorkerError as error:
            error_kind = error.code if error.code in ERRORS else "invalid_input"
        except OpenAIKeyError as error:
            error_kind = next((kind for kind, (code, _, _) in ERRORS.items() if code == error.code), "worker_unavailable")
        except Exception:
            error_kind = "internal"
        if error_kind is not None:
            if payload is not None:
                try:
                    service.cancel(access.database, access.user_id, payload["job_id"])
                except WorkerError:
                    pass  # 이미 확정/만료/취소된 시도는 상태를 되돌리지 않는다.
            access.issue = OpenAIKeyError(*ERRORS[error_kind])
        result = LLMResult(ok=error_kind is None, value=value, error_kind=(
            error_kind if error_kind in {"rate_limit", "network", "invalid_output", "invalid_input", "internal"}
            else "network" if error_kind in {"worker_unavailable", "expired"} else "invalid_input"),
            attempts=attempts, prompt_version=prompt.version, duration_ms=int((monotonic() - started) * 1000))
        if result.ok:
            result.error_kind = None
        current_event("llm_call", duration_ms=result.duration_ms, detail={
            "prompt_version": prompt.version, "ok": result.ok, "error_kind": result.error_kind,
            "error_code": "worker_" + error_kind if error_kind else None, "attempts": attempts,
            "job_id": payload["job_id"] if payload else None})
        return result
