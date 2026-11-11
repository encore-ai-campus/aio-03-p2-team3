"""구조화 호출 한 곳에서 SDK 재시도를 끄고 계약의 재시도만 수행한다.

예외 기준: google-genai errors.APIError(code), google-api-core exceptions,
httpx TimeoutException/NetworkError, Pydantic ValidationError,
LangChain OutputParserException. 설치된 SDK의 docstring·원본과 대조했다.
https://googleapis.github.io/python-genai/#error-handling
https://reference.langchain.com/python/integrations/langchain_google_genai/ChatGoogleGenerativeAI/
LangChain이 감싼 SDK 오류는 __cause__에서 원래 HTTP 코드를 읽는다.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from time import perf_counter, sleep
from typing import Literal

import openai
from google.api_core import exceptions as google_errors
from google.genai.errors import APIError
import httpx
from langchain_core.exceptions import OutputParserException
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from app.config import LIMITS, Settings, get_settings
from app.prompts import Prompt
from app.runlog.logger import current_event

_override = ContextVar("llm_backend", default=None)
# 2026-11-10(#62): 무료 등급 gemini-3.8-flash가 503을 반복해 3.6으로 바꿨다. GEMINI_MODEL로 덮어쓴다.
DEFAULT_MODEL = "gemini-3.6-flash"
# 무역 문서 추출용 OpenAI Responses 기본 모델. 원본: reference/kekorea/Quotation_KEKOREA/agent/extractor.py
RESPONSES_DEFAULT_MODEL = "gpt-6-luna"


class LLMResult(BaseModel):
    ok: bool
    value: BaseModel | None = None
    error_kind: Literal["rate_limit", "network", "invalid_output", "invalid_input", "internal"] | None = None
    attempts: int
    prompt_version: str
    duration_ms: int


def model_name(settings: Settings | None = None) -> str:
    """쓸 Gemini 모델. 환경변수 `GEMINI_MODEL`이 있으면 그것, 없으면 `DEFAULT_MODEL`."""
    return (settings or get_settings()).gemini_model.strip() or DEFAULT_MODEL


def model_source() -> str:
    """ToolResult.source 값(`gemini:<모델>`)."""
    return f"gemini:{model_name()}"


def responses_model_name(settings: Settings | None = None) -> str:
    """무역 추출에 쓸 OpenAI 모델. 환경변수 `OPENAI_MODEL`이 있으면 그것, 없으면 원본 기본값."""
    return (settings or get_settings()).openai_model.strip() or RESPONSES_DEFAULT_MODEL


def get_backend(settings: Settings | None = None):
    return _backend_for_settings(settings or get_settings())


@lru_cache(maxsize=1)
def _backend_for_settings(settings: Settings):
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY 설정이 필요합니다")
    return ChatGoogleGenerativeAI(
        model=model_name(settings), google_api_key=settings.gemini_api_key,
        max_retries=0, timeout=LIMITS["LLM_TIMEOUT_SECONDS"],
    )


def get_responses_backend(settings: Settings | None = None):
    """무역 문서 추출용 OpenAI Responses 백엔드(계약 재시도만 쓰게 SDK 재시도는 끈다)."""
    return _responses_backend_for_settings(settings or get_settings())


@lru_cache(maxsize=1)
def _responses_backend_for_settings(settings: Settings):
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY 설정이 필요합니다")
    return ChatOpenAI(
        model=responses_model_name(settings), api_key=settings.openai_api_key,
        use_responses_api=True,
        max_retries=0, timeout=LIMITS["LLM_TIMEOUT_SECONDS"],
    )


@contextmanager
def use_backend(fake):
    token = _override.set(fake)
    try:
        yield fake
    finally:
        _override.reset(token)


def _http_code(error: Exception):
    if isinstance(error, APIError):
        return error.code
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code
    if isinstance(error, google_errors.GoogleAPICallError):
        return error.code
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
        if code == 429 or isinstance(current, (google_errors.ResourceExhausted, google_errors.TooManyRequests)):
            return "rate_limit"
        if code == 400 or isinstance(current, (google_errors.InvalidArgument, openai.BadRequestError)):
            return "invalid_input"
        if (isinstance(code, int) and 500 <= code <= 599) or isinstance(current, (
            TimeoutError, ConnectionError, httpx.TimeoutException, httpx.NetworkError,
            google_errors.DeadlineExceeded, google_errors.ServiceUnavailable,
            openai.APIConnectionError,  # APITimeoutError도 이 클래스를 상속한다
        )):
            return "network"
        if isinstance(current, (ValidationError, OutputParserException)):
            return "invalid_output"
        current = current.__cause__
    return "internal"


def call_structured(prompt: Prompt, schema: type[BaseModel], variables: dict,
                    backend=None, backend_factory=None) -> LLMResult:
    """구조화 호출. 백엔드 우선순위: use_backend 오버라이드 > 명시 backend > backend_factory() > 기본 Gemini.

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
        structured = chosen.with_structured_output(schema)
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
