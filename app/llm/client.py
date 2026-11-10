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

from google.api_core import exceptions as google_errors
from google.genai.errors import APIError
import httpx
from langchain_core.exceptions import OutputParserException
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, ValidationError

from app.config import LIMITS, Settings, get_settings
from app.prompts import Prompt
from app.runlog.logger import current_event

_override = ContextVar("llm_backend", default=None)
# 2026-11-10(#62): 무료 등급 gemini-3.8-flash가 503을 반복해 3.6으로 바꿨다. GEMINI_MODEL로 덮어쓴다.
DEFAULT_MODEL = "gemini-3.6-flash"


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


@contextmanager
def use_backend(fake):
    token = _override.set(fake)
    try:
        yield fake
    finally:
        _override.reset(token)


def classify_error(error: Exception) -> str:
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        code = None
        if isinstance(current, APIError):
            code = current.code
        elif isinstance(current, httpx.HTTPStatusError):
            code = current.response.status_code
        elif isinstance(current, google_errors.GoogleAPICallError):
            code = current.code
        if code == 429 or isinstance(current, (google_errors.ResourceExhausted, google_errors.TooManyRequests)):
            return "rate_limit"
        if code == 400 or isinstance(current, google_errors.InvalidArgument):
            return "invalid_input"
        if (isinstance(code, int) and 500 <= code <= 599) or isinstance(current, (
            TimeoutError, ConnectionError, httpx.TimeoutException, httpx.NetworkError,
            google_errors.DeadlineExceeded, google_errors.ServiceUnavailable,
        )):
            return "network"
        if isinstance(current, (ValidationError, OutputParserException)):
            return "invalid_output"
        current = current.__cause__
    return "internal"


def call_structured(prompt: Prompt, schema: type[BaseModel], variables: dict) -> LLMResult:
    started = perf_counter()
    attempts = 0
    counts = {"network": 0, "invalid_output": 0}

    def finish(ok, value=None, error_kind=None):
        result = LLMResult(
            ok=ok, value=value, error_kind=error_kind, attempts=attempts,
            prompt_version=prompt.version, duration_ms=int((perf_counter() - started) * 1000),
        )
        current_event("llm_call", duration_ms=result.duration_ms, detail={
            "prompt_version": result.prompt_version, "ok": ok,
            "error_kind": error_kind, "attempts": attempts,
        })
        return result

    try:
        rendered = prompt.TEMPLATE.format_map(variables)
    except (KeyError, ValueError, TypeError):
        return finish(False, error_kind="invalid_input")
    try:
        backend = _override.get()
        if backend is None:
            backend = get_backend()
        structured = backend.with_structured_output(schema)
    except Exception:
        return finish(False, error_kind="internal")
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
                return finish(False, error_kind=kind)
            counts[kind] += 1
            current_event("retry", detail={"error_kind": kind, "attempt": attempts + 1})
            if kind == "network":
                sleep(2 ** (counts[kind] - 1))
