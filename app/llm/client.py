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
from app.prompts import Prompt
from app.runlog.logger import current_event

_override = ContextVar("llm_backend", default=None)
_user_key = ContextVar("llm_user_key", default=None)
# 무역 추출에서 사용하던 기본 모델을 모든 LLM 호출에 사용한다. OPENAI_MODEL로 덮어쓴다.
DEFAULT_MODEL = "gpt-6-luna"
RESPONSES_DEFAULT_MODEL = DEFAULT_MODEL


class LLMResult(BaseModel):
    ok: bool
    value: BaseModel | None = None
    error_kind: Literal["rate_limit", "network", "invalid_output", "invalid_input", "internal"] | None = None
    attempts: int
    prompt_version: str
    duration_ms: int


def model_name(settings: Settings | None = None) -> str:
    """모든 LLM 호출에 쓸 OpenAI 모델. `OPENAI_MODEL`이 비면 `DEFAULT_MODEL`."""
    return (settings or get_settings()).openai_model.strip() or DEFAULT_MODEL


def model_source() -> str:
    """ToolResult.source 값(`openai:<모델>`)."""
    return f"openai:{model_name()}"


def responses_model_name(settings: Settings | None = None) -> str:
    """기존 무역 추출 호출자도 공통 모델 이름을 사용한다."""
    return model_name(settings)


def get_backend(settings: Settings | None = None):
    binding = _user_key.get()
    if binding is None:
        raise OpenAIKeyError()
    provider, configured = binding
    # 사용자 범위의 소스를 확인한다(DB 개인 키 또는 검증된 로컬 소유자의 .env).
    key = provider()
    return _backend_for_settings(replace(settings or configured or get_settings(), openai_api_key=key))


def _backend_for_settings(settings: Settings):
    if not settings.openai_api_key.strip():
        raise ValueError("OPENAI_API_KEY 설정이 필요합니다")
    return ChatOpenAI(
        model=model_name(settings), api_key=settings.openai_api_key.strip(),
        use_responses_api=True,
        # LangChain의 자체 socket transport 대신 httpx의 환경 프록시/CA 설정을 따른다.
        http_socket_options=(),
        max_retries=0, timeout=LIMITS["LLM_TIMEOUT_SECONDS"],
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


def structured_output(backend, schema: type[BaseModel]):
    """기존 기본값·dict 필드를 허용하고 반환값은 Pydantic으로 검증한다.

    Responses의 strict JSON Schema는 자유 키 dict와 선택 기본값을 제한한다.
    OpenAI는 non-strict 함수 스키마로 출력만 받으며 업무 도구는 실행하지 않는다.
    대역은 기존 schema-only 인터페이스를 그대로 사용한다.
    """
    if isinstance(backend, ChatOpenAI):
        return backend.with_structured_output(schema, method="function_calling", strict=False)
    return backend.with_structured_output(schema)


@contextmanager
def use_backend(fake):
    token = _override.set(fake)
    try:
        yield fake
    finally:
        _override.reset(token)


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


def call_structured(prompt: Prompt, schema: type[BaseModel], variables: dict,
                    backend=None, backend_factory=None) -> LLMResult:
    """구조화 호출. 백엔드 우선순위: use_backend 오버라이드 > 명시 backend > backend_factory() > 기본 OpenAI.

    `backend`는 백엔드 인스턴스, `backend_factory`는 인자 없는 팩토리. 팩토리는 앞선
    둘이 없을 때만 부른다(가짜 주입 테스트에서 키 없는 팩토리가 먼저 실패하는 일이
    없게 한다)."""
    started = perf_counter()
    attempts = 0
    counts = {"network": 0, "invalid_output": 0}

    def finish(ok, value=None, error_kind=None, error=None):
        result = LLMResult(
            ok=ok, value=value, error_kind=error_kind, attempts=attempts,
            prompt_version=prompt.version, duration_ms=int((perf_counter() - started) * 1000),
        )
        current_event("llm_call", duration_ms=result.duration_ms, detail={
            "prompt_version": result.prompt_version, "ok": ok,
            "error_kind": error_kind, "attempts": attempts,
            "error_code": _error_label(error) if error is not None else None,
        })
        return result

    try:
        rendered = prompt.TEMPLATE.format_map(variables)
    except (KeyError, ValueError, TypeError) as error:
        return finish(False, error_kind="invalid_input", error=error)
    try:
        chosen = _override.get() or backend
        if chosen is None and backend_factory is not None:
            chosen = backend_factory()
        if chosen is None:
            chosen = get_backend()
        structured = structured_output(chosen, schema)
    except OpenAIKeyError as error:
        current_event("error", detail={"kind": error.code.lower(), "message": error.message})
        return finish(False, error_kind="invalid_input", error=error)
    except Exception as error:
        return finish(False, error_kind="internal", error=error)
    while True:
        attempts += 1
        try:
            value = structured.invoke(rendered)
            value = schema.model_validate(value)
            return finish(True, value=value)
        except Exception as error:
            kind = classify_error(error)
            budget = {
                "network": LIMITS["LLM_MAX_RETRIES"],
                "invalid_output": LIMITS["LLM_INVALID_OUTPUT_RETRIES"],
            }.get(kind, 0)
            if kind not in counts or counts[kind] >= budget:
                return finish(False, error_kind=kind, error=error)
            counts[kind] += 1
            current_event("retry", detail={
                "error_kind": kind, "error_code": _error_label(error), "attempt": attempts + 1,
            })
            if kind == "network":
                sleep(2 ** (counts[kind] - 1))
