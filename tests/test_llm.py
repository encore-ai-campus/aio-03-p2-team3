from google.api_core import exceptions as google_errors
from google.genai.errors import ClientError, ServerError
import httpx
from langchain_google_genai.chat_models import GoogleRateLimitError
from pydantic import BaseModel
import pytest

from app.config import Settings
from app.llm import client
from app.prompts import Prompt
from tests.fakes.llm import FakeLLM


class Answer(BaseModel):
    answer: str


PROMPT = Prompt("test", "v1", "{input}")


@pytest.fixture(autouse=True)
def no_network_or_wait(monkeypatch):
    monkeypatch.setattr(client, "get_backend", lambda: pytest.fail("실제 LLM은 호출하면 안 됩니다"))
    waits = []
    monkeypatch.setattr(client, "sleep", waits.append)
    return waits


def invoke(responses):
    fake = FakeLLM(responses)
    with client.use_backend(fake):
        result = client.call_structured(PROMPT, Answer, {"input": "가상 입력"})
    return result, fake


def test_structured_success():
    result, fake = invoke([{"answer": "가상 답변"}])
    assert result.ok and result.value == Answer(answer="가상 답변")
    assert result.attempts == 1 and result.prompt_version == "test.v1"
    assert result.duration_ms >= 0 and fake.schemas == [Answer]


@pytest.mark.parametrize("error", [
    ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}}),
    google_errors.ResourceExhausted("가상 한도 오류"),
    httpx.HTTPStatusError("가상 한도 오류", request=httpx.Request("GET", "https://example.invalid"), response=httpx.Response(429)),
])
def test_rate_limit_never_retries(error, no_network_or_wait):
    result, fake = invoke([error, {"answer": "사용하면 안 되는 응답"}])
    assert not result.ok and result.error_kind == "rate_limit"
    assert result.attempts == len(fake.calls) == 1
    assert no_network_or_wait == []


def test_langchain_wrapped_rate_limit():
    error = GoogleRateLimitError("가상 래퍼")
    error.__cause__ = ClientError(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})
    result, _ = invoke([error])
    assert result.error_kind == "rate_limit" and result.attempts == 1


@pytest.mark.parametrize("error", [
    TimeoutError("가상 시간 초과"), ConnectionError("가상 연결 실패"),
    httpx.ConnectError("가상 연결 실패"), httpx.ReadTimeout("가상 시간 초과"),
    ServerError(500, {"error": {"status": "INTERNAL"}}),
    ServerError(503, {"error": {"status": "UNAVAILABLE"}}),
    google_errors.ServiceUnavailable("가상 통신 실패"),
])
def test_network_failure_exhausts_three_attempts(error, no_network_or_wait):
    result, fake = invoke([error] * 3)
    assert not result.ok and result.error_kind == "network"
    assert result.attempts == len(fake.calls) == 3
    assert no_network_or_wait == [1, 2]


def test_network_retry_can_recover(no_network_or_wait):
    result, _ = invoke([TimeoutError(), {"answer": "복구"}])
    assert result.ok and result.attempts == 2 and no_network_or_wait == [1]


def test_invalid_output_has_separate_budget(no_network_or_wait):
    result, fake = invoke([{"wrong_key": "값"}] * 2)
    assert result.error_kind == "invalid_output" and result.attempts == len(fake.calls) == 2
    assert no_network_or_wait == []


def test_invalid_output_can_recover():
    result, _ = invoke([{}, {"answer": "수정"}])
    assert result.ok and result.attempts == 2


@pytest.mark.parametrize("error, kind", [
    (ClientError(400, {"error": {"status": "INVALID_ARGUMENT"}}), "invalid_input"),
    (RuntimeError("가상 내부 오류"), "internal"),
])
def test_nonretryable_errors(error, kind, no_network_or_wait):
    result, _ = invoke([error])
    assert result.error_kind == kind and result.attempts == 1 and no_network_or_wait == []


def test_missing_prompt_variable_does_not_call_backend():
    fake = FakeLLM([])
    with client.use_backend(fake):
        result = client.call_structured(PROMPT, Answer, {})
    assert result.error_kind == "invalid_input" and result.attempts == 0
    assert fake.calls == []


def test_backend_override_is_scoped():
    outer = FakeLLM([{"answer": "바깥"}])
    inner = FakeLLM([{"answer": "안쪽"}])
    with client.use_backend(outer):
        with client.use_backend(inner):
            assert client.call_structured(PROMPT, Answer, {"input": "입력"}).value.answer == "안쪽"
        assert client.call_structured(PROMPT, Answer, {"input": "입력"}).value.answer == "바깥"


def test_model_name_default_and_override():
    # 기본은 gemini-3.6-flash(#62), GEMINI_MODEL 값이 있으면 앞뒤 공백을 빼고 그 모델을 쓴다.
    assert client.DEFAULT_MODEL == "gemini-3.6-flash"
    assert client.model_name(Settings()) == "gemini-3.6-flash"
    assert client.model_name(Settings(gemini_model=" gemini-3.5-flash-lite ")) == "gemini-3.5-flash-lite"


@pytest.mark.parametrize("error, code, kind, attempts", [
    (ServerError(503, {"error": {"message": "private-body fake-api-key", "status": "UNAVAILABLE"}}),
     "HTTP 503", "network", 3),
    (ClientError(429, {"error": {"message": "private-body fake-api-key", "status": "RESOURCE_EXHAUSTED"}}),
     "HTTP 429", "rate_limit", 1),
    (httpx.ReadTimeout("private-body fake-api-key"), "ReadTimeout", "network", 3),
    (google_errors.ServiceUnavailable("private-body fake-api-key"), "HTTP 503", "network", 3),
    (httpx.HTTPStatusError("private-body fake-api-key",
                           request=httpx.Request("GET", "https://example.invalid?key=fake-api-key"),
                           response=httpx.Response(503)), "HTTP 503", "network", 3),
])
def test_failure_and_retries_record_only_short_codes(monkeypatch, error, code, kind, attempts):
    logged = []
    monkeypatch.setattr(client, "current_event", lambda event, **data: logged.append((event, data)))
    result, _ = invoke([error] * attempts)

    assert result.error_kind == kind and result.attempts == attempts
    assert [event for event, _ in logged] == ["retry"] * (attempts - 1) + ["llm_call"]
    assert all(data["detail"]["error_code"] == code for _, data in logged)
    assert [data["detail"]["attempt"] for event, data in logged if event == "retry"] == list(range(2, attempts + 1))
    assert "private-body" not in repr(logged) and "fake-api-key" not in repr(logged)


def test_wrapped_sdk_code_and_recovery_are_recorded(monkeypatch):
    logged = []
    monkeypatch.setattr(client, "current_event", lambda event, **data: logged.append((event, data)))
    error = RuntimeError("private-wrapper-message")
    error.__cause__ = ServerError(503, {"error": {"message": "private-sdk-message"}})
    result, _ = invoke([error, {"answer": "복구"}])

    assert result.ok and result.attempts == 2
    assert logged[0][1]["detail"]["error_code"] == "HTTP 503"
    assert logged[-1][1]["detail"]["error_code"] is None
    assert "private-" not in repr(logged)


def test_error_label_stops_at_cause_cycle():
    error = RuntimeError("private-cycle-message")
    error.__cause__ = error
    assert client._error_label(error) == "RuntimeError"


def test_backend_setup_failure_records_only_exception_type(monkeypatch):
    logged = []
    monkeypatch.setattr(client, "current_event", lambda event, **data: logged.append((event, data)))

    def fail():
        raise ValueError("private-setup-message fake-api-key")

    monkeypatch.setattr(client, "get_backend", fail)
    result = client.call_structured(PROMPT, Answer, {"input": "가상 입력"})
    assert result.error_kind == "internal" and result.attempts == 0
    assert logged[-1][1]["detail"]["error_code"] == "ValueError"
    assert "private-" not in repr(logged) and "fake-api-key" not in repr(logged)
