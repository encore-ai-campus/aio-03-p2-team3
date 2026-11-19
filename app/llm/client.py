"""구조화 호출 한 곳에서 SDK 재시도를 끄고 계약의 재시도만 수행한다.

예외 기준: OpenAI APIStatusError/ APIConnectionError,
httpx TimeoutException/NetworkError, Pydantic ValidationError,
LangChain OutputParserException. 설치된 SDK의 docstring·원본과 대조했다.
https://github.com/openai/openai-python#handling-errors
LangChain이 감싼 SDK 오류는 __cause__에서 원래 HTTP 코드를 읽는다.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
from time import perf_counter, sleep
from typing import Literal

import openai
import httpx
from langchain_core.exceptions import OutputParserException
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from app.config import LIMITS, Settings, get_settings
from app.llm.profiles import ResolvedProfile, feature_for_prompt, resolve_for_prompt
from app.prompts import Prompt
from app.runlog.logger import current_event

_override = ContextVar("llm_backend", default=None)
_user_key = ContextVar("llm_user_key", default=None)
_worker_call = ContextVar("llm_worker_call", default=None)
# call_structured가 고른 프로필. 팩토리(get_backend)가 같은 프로필로 백엔드를 만들게 한다.
_active_profile = ContextVar("llm_active_profile", default=None)
# 무역 추출에서 사용하던 기본 모델을 모든 LLM 호출에 사용한다. OPENAI_MODEL로 덮어쓴다.
DEFAULT_MODEL = "gpt-6-luna"
RESPONSES_DEFAULT_MODEL = DEFAULT_MODEL


class LLMResult(BaseModel):
    ok: bool
    value: BaseModel | None = None
    error_kind: Literal["rate_limit", "network", "invalid_output", "invalid_input", "internal"] | None = None
    # 기존 5종을 유지한 채 더하는 세부 구분(계획 발견 9). 없으면 None.
    error_detail: Literal["timeout", "incomplete_output", "access_denied"] | None = None
    attempts: int
    prompt_version: str
    duration_ms: int
    profile_id: str | None = None


def model_name(settings: Settings | None = None) -> str:
    """모든 LLM 호출에 쓸 OpenAI 모델. `OPENAI_MODEL`이 비면 `DEFAULT_MODEL`."""
    return (settings or get_settings()).openai_model.strip() or DEFAULT_MODEL


def model_source() -> str:
    """ToolResult.source 값(`openai:<모델>`)."""
    return f"openai:{model_name()}"


def responses_model_name(settings: Settings | None = None) -> str:
    """기존 무역 추출 호출자도 공통 모델 이름을 사용한다."""
    return model_name(settings)


def get_backend(settings: Settings | None = None, profile: ResolvedProfile | None = None):
    binding = _user_key.get()
    if binding is None:
        raise OpenAIKeyError()
    provider, configured = binding
    # 사용자 범위의 소스를 확인한다(DB 개인 키 또는 검증된 로컬 소유자의 .env).
    key = provider()
    chosen = replace(settings or configured or get_settings(), openai_api_key=key)
    profile = profile or _active_profile.get()
    if profile is None or profile.is_baseline:
        return _backend_for_settings(chosen)  # baseline 호출 형태는 기존과 같다.
    return _backend_for_settings(chosen, profile)


def _backend_for_settings(settings: Settings, profile: ResolvedProfile | None = None):
    if not settings.openai_api_key.strip():
        raise ValueError("OPENAI_API_KEY 설정이 필요합니다")
    if profile is None or profile.is_baseline:
        # baseline: 기존과 같은 요청(노력치·출력 상한 미전송, OPENAI_MODEL 덮어쓰기 유지).
        return ChatOpenAI(
            model=model_name(settings), api_key=settings.openai_api_key.strip(),
            use_responses_api=True,
            # LangChain의 자체 socket transport 대신 httpx의 환경 프록시/CA 설정을 따른다.
            http_socket_options=(),
            max_retries=0, timeout=LIMITS["LLM_TIMEOUT_SECONDS"],
        )
    # 명시 프로필: 모델은 계약에 고정(환경변수로 바뀌지 않음). reasoning_effort는 Responses의
    # reasoning.effort로, max_tokens는 max_output_tokens로 전송된다(langchain-openai 1.7.4).
    options = {"reasoning_effort": profile.reasoning_effort} if profile.reasoning_effort else {}
    if profile.max_output_tokens is not None:
        options["max_tokens"] = profile.max_output_tokens
    return ChatOpenAI(
        model=profile.model, api_key=settings.openai_api_key.strip(),
        use_responses_api=True, http_socket_options=(),
        max_retries=0, timeout=profile.timeout_seconds, **options,
    )


class OpenAIKeyError(ValueError):
    """키 원문이나 SDK 오류를 담지 않는 사용자 키 오류."""

    def __init__(self, code="OPENAI_KEY_REQUIRED", message="설정에서 본인의 OpenAI API 키를 등록해 주세요.",
                 status_code=409):
        super().__init__(message)
        self.code, self.message, self.status_code = code, message, status_code


@contextmanager
def use_user_key(provider, settings: Settings | None = None):
    """HTTP 요청·백그라운드 실행별 키 조회 함수만 보관한다. 키는 상태·로그에 넣지 않는다."""
    token = _user_key.set((provider, settings))
    try:
        yield
    finally:
        _user_key.reset(token)


def get_responses_backend(settings: Settings | None = None):
    """기존 무역 추출 진입점. 메일과 같은 OpenAI Responses 백엔드를 공유한다."""
    return get_backend(settings)


def structured_output(backend, schema: type[BaseModel], include_raw: bool = False):
    """기존 기본값·dict 필드를 허용하고 반환값은 Pydantic으로 검증한다.

    Responses의 strict JSON Schema는 자유 키 dict와 선택 기본값을 제한한다.
    OpenAI는 non-strict 함수 스키마로 출력만 받으며 업무 도구는 실행하지 않는다.
    대역은 기존 schema-only 인터페이스를 그대로 사용한다.
    """
    if isinstance(backend, ChatOpenAI):
        return backend.with_structured_output(schema, method="function_calling", strict=False,
                                              include_raw=include_raw)
    return backend.with_structured_output(schema)


@contextmanager
def use_backend(fake):
    token = _override.set(fake)
    try:
        yield fake
    finally:
        _override.reset(token)


@contextmanager
def use_worker_call(callback):
    token = _worker_call.set(callback)
    try:
        yield
    finally:
        _worker_call.reset(token)


def delegated_to_worker() -> bool:
    return _worker_call.get() is not None and _override.get() is None


def require_completed_ai():
    """실패한 PC 호출이 성찰의 대체 경로를 통해 후보로 저장되지 않게 한다."""
    if delegated_to_worker():
        _worker_call.get().guard()


def _http_code(error: Exception):
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code
    if isinstance(error, openai.APIStatusError):
        return error.status_code
    return None


def _error_label(error: Exception) -> str:
    """감싼 SDK 오류의 HTTP 코드 또는 예외 종류만 남긴다. 메시지·응답은 기록하지 않는다."""
    seen = set()
    current = error
    label = type(error).__name__
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = _http_code(current)
        if isinstance(code, int) and 100 <= code <= 599:
            return f"HTTP {int(code)}"
        label = type(current).__name__
        current = current.__cause__
    return label


def classify_error(error: Exception) -> str:
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = _http_code(current)
        if code == 429:
            return "rate_limit"
        if isinstance(code, int) and 400 <= code <= 499:
            return "invalid_input"
        if (isinstance(code, int) and 500 <= code <= 599) or isinstance(current, (
            TimeoutError, ConnectionError, httpx.TimeoutException, httpx.NetworkError,
            openai.APIConnectionError,  # APITimeoutError도 이 클래스를 상속한다
        )):
            return "network"
        if isinstance(current, (ValidationError, OutputParserException)):
            return "invalid_output"
        current = current.__cause__
    return "internal"


def error_detail(error: Exception) -> str | None:
    """기존 error_kind 위에 시간 초과·권한/잔액 오류를 구분한다. 메시지·응답은 보지 않는다."""
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, httpx.TimeoutException, openai.APITimeoutError)):
            return "timeout"
        if _http_code(current) in {401, 402, 403}:
            return "access_denied"
        if isinstance(current, _IncompleteOutput):
            return "incomplete_output"
        current = current.__cause__
    return None


class _IncompleteOutput(ValueError):
    """Responses가 출력 상한 등으로 미완료(status=incomplete)를 알린 뒤의 파싱 실패."""


def _usage(raw) -> dict | None:
    """AIMessage.usage_metadata에서 토큰 수만 꺼낸다. 없으면 None(미상)."""
    meta = getattr(raw, "usage_metadata", None)
    if not meta:
        return None
    details_in = meta.get("input_token_details") or {}
    details_out = meta.get("output_token_details") or {}
    return {
        "input_tokens": meta.get("input_tokens"), "output_tokens": meta.get("output_tokens"),
        "cached_input_tokens": details_in.get("cache_read"), "reasoning_tokens": details_out.get("reasoning"),
    }


def _unwrap_raw(value):
    """include_raw=True 결과에서 파싱 값을 꺼낸다. 파싱 오류는 다시 올린다(기존 흐름과 같게)."""
    raw = value.get("raw")
    error, parsed = value.get("parsing_error"), value.get("parsed")
    if error is not None or parsed is None:
        # 미완료 응답의 잘린 인자는 파싱 오류 없이 parsed=None으로 올 수도 있다.
        metadata = getattr(raw, "response_metadata", None) or {}
        if metadata.get("status") == "incomplete" or metadata.get("incomplete_details"):
            raise _IncompleteOutput("incomplete") from error
    if error is not None:
        raise error
    return parsed


def call_structured(prompt: Prompt, schema: type[BaseModel], variables: dict,
                    backend=None, backend_factory=None) -> LLMResult:
    """구조화 호출. 백엔드 우선순위: use_backend 오버라이드 > 명시 backend > backend_factory() > 기본 OpenAI.

    `backend`는 백엔드 인스턴스, `backend_factory`는 인자 없는 팩토리. 팩토리는 앞선
    둘이 없을 때만 부른다(가짜 주입 테스트에서 키 없는 팩토리가 먼저 실패하는 일이
    없게 한다)."""
    binding = _user_key.get()
    try:
        profile = resolve_for_prompt(prompt.NAME, (binding[1] if binding else None) or get_settings())
    except ValueError:
        # 설정 검증은 시작 때 한다. 여기서 실패하면 조용히 대체하지 않고 내부 오류로 끝낸다.
        current_event("llm_call", duration_ms=0, detail={
            "prompt_version": prompt.version, "ok": False, "error_kind": "internal", "attempts": 0,
            "error_code": "profile_invalid",
        })
        return LLMResult(ok=False, error_kind="internal", attempts=0, prompt_version=prompt.version, duration_ms=0)
    if delegated_to_worker() and backend is None:
        if not profile.is_baseline:
            # 개인 PC는 PC가 모델·출력 상한을 강제한다(6.4절). 상향 요청과 실제 적용을 함께 남긴다.
            current_event("llm_profile", detail={
                "prompt_version": prompt.version, "requested_profile": profile.profile_id,
                "applied_profile": f"{profile.feature}.baseline", "reason": "local_worker_baseline_only",
            })
        return _worker_call.get()(prompt, schema, variables)
    started = perf_counter()
    attempts = 0
    counts = {"network": 0, "invalid_output": 0}
    usages: list[dict | None] = []
    real_backend = False

    def finish(ok, value=None, error_kind=None, error=None):
        detail_kind = error_detail(error) if error is not None else None
        result = LLMResult(
            ok=ok, value=value, error_kind=error_kind, error_detail=detail_kind, attempts=attempts,
            prompt_version=prompt.version, duration_ms=int((perf_counter() - started) * 1000),
            profile_id=profile.profile_id,
        )
        detail = {
            "prompt_version": result.prompt_version, "ok": ok,
            "error_kind": error_kind, "attempts": attempts,
            "error_code": _error_label(error) if error is not None else None,
            "error_detail": detail_kind,
            "profile_id": profile.profile_id, "prompt_feature": feature_for_prompt(prompt.NAME),
            "model": profile.model or model_name(binding[1] if binding else None), "reasoning_effort": profile.reasoning_effort or "default",
            "timeout_seconds": profile.timeout_seconds, "max_output_tokens": profile.max_output_tokens,
            "execution_mode": "stored_key",
        }
        if real_backend:
            # 시도별 사용량. 알 수 없는 시도(오류 등)는 0이 아니라 미상으로 센다(키·응답 원문 없음).
            known = [u for u in usages if u is not None]
            detail["usage"] = {
                name: sum(u.get(name) or 0 for u in known)
                for name in ("input_tokens", "output_tokens", "cached_input_tokens", "reasoning_tokens")
            }
            detail["usage_unknown_attempts"] = len(usages) - len(known)
        current_event("llm_call", duration_ms=result.duration_ms, detail=detail)
        return result

    try:
        rendered = prompt.TEMPLATE.format_map(variables)
    except (KeyError, ValueError, TypeError) as error:
        return finish(False, error_kind="invalid_input", error=error)
    token = _active_profile.set(profile)
    try:
        chosen = _override.get() or backend
        if chosen is None and backend_factory is not None:
            chosen = backend_factory()
        if chosen is None:
            chosen = get_backend()
        real_backend = isinstance(chosen, ChatOpenAI)
        structured = structured_output(chosen, schema, include_raw=real_backend)
    except OpenAIKeyError as error:
        current_event("error", detail={"kind": error.code.lower(), "message": error.message})
        return finish(False, error_kind="invalid_input", error=error)
    except Exception as error:
        return finish(False, error_kind="internal", error=error)
    finally:
        _active_profile.reset(token)
    budgets = ({"network": LIMITS["LLM_MAX_RETRIES"], "invalid_output": LIMITS["LLM_INVALID_OUTPUT_RETRIES"]}
               if profile.is_baseline else
               {"network": profile.network_retries, "invalid_output": profile.invalid_output_retries})
    deadline = profile.logical_deadline_seconds
    while True:
        attempts += 1
        try:
            value = structured.invoke(rendered)
            if real_backend:
                usages.append(_usage(value.get("raw")))
                value = _unwrap_raw(value)
            value = schema.model_validate(value)
            return finish(True, value=value)
        except Exception as error:
            if real_backend and len(usages) < attempts:
                usages.append(None)
            kind = classify_error(error)
            if isinstance(error, _IncompleteOutput):
                kind = "invalid_output"
            budget = budgets.get(kind, 0)
            # baseline은 기존 동작(시간 초과도 network 재시도). 명시 프로필은 시간 초과를 재요청하지 않는다.
            if not profile.is_baseline and error_detail(error) == "timeout":
                budget = 0
            # 논리 기한: 다음 시도를 끝까지 기다릴 시간이 없으면 재시도하지 않는다.
            if deadline is not None and (perf_counter() - started) + profile.timeout_seconds > deadline:
                budget = 0
            if kind not in counts or counts[kind] >= budget:
                return finish(False, error_kind=kind, error=error)
            counts[kind] += 1
            current_event("retry", detail={
                "error_kind": kind, "error_code": _error_label(error), "attempt": attempts + 1,
            })
            if kind == "network":
                sleep(2 ** (counts[kind] - 1))
