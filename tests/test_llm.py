import json

import httpx
import openai
from pydantic import BaseModel
import pytest

from app.config import Settings
from app.llm import client
from app.prompts import Prompt
from tests.fakes.llm import FakeLLM, openai_error


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
    openai_error(429),
    httpx.HTTPStatusError("가상 한도 오류", request=httpx.Request("GET", "https://example.invalid"), response=httpx.Response(429)),
])
def test_rate_limit_never_retries(error, no_network_or_wait):
    result, fake = invoke([error, {"answer": "사용하면 안 되는 응답"}])
    assert not result.ok and result.error_kind == "rate_limit"
    assert result.attempts == len(fake.calls) == 1
    assert no_network_or_wait == []


def test_langchain_wrapped_rate_limit():
    error = RuntimeError("가상 래퍼")
    error.__cause__ = openai_error(429)
    result, _ = invoke([error])
    assert result.error_kind == "rate_limit" and result.attempts == 1


@pytest.mark.parametrize("error", [
    TimeoutError("가상 시간 초과"), ConnectionError("가상 연결 실패"),
    httpx.ConnectError("가상 연결 실패"), httpx.ReadTimeout("가상 시간 초과"),
    openai_error(500),
    openai_error(503),
    openai_error(502),
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
    (openai_error(400), "invalid_input"),
    (openai_error(401), "invalid_input"),
    (openai_error(403), "invalid_input"),
    (openai_error(404), "invalid_input"),
    (openai_error(422), "invalid_input"),
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
    # 기존 무역 추출 모델을 전체 호출에 적용하고 OPENAI_MODEL로 덮어쓴다.
    assert client.DEFAULT_MODEL == "gpt-6-luna"
    assert client.model_name(Settings()) == "gpt-6-luna"
    assert client.model_name(Settings(openai_model=" gpt-fake ")) == "gpt-fake"
    assert client.model_name(Settings(openai_model="  ")) == "gpt-6-luna"


@pytest.mark.parametrize("error, code, kind, attempts", [
    (openai_error(503, message="private-body fake-api-key"),
     "HTTP 503", "network", 3),
    (openai_error(429, message="private-body fake-api-key"),
     "HTTP 429", "rate_limit", 1),
    (httpx.ReadTimeout("private-body fake-api-key"), "ReadTimeout", "network", 3),
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
    error.__cause__ = openai_error(503, message="private-sdk-message")
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


def _openai_status_error(cls, status):
    request = httpx.Request("POST", "https://api.openai.invalid/v1/responses")
    return cls("가상 오류", response=httpx.Response(status, request=request), body=None)


def test_openai_rate_limit_and_bad_request_do_not_retry(no_network_or_wait):
    for error, kind in [
        (_openai_status_error(openai.RateLimitError, 429), "rate_limit"),
        (_openai_status_error(openai.BadRequestError, 400), "invalid_input"),
    ]:
        result, fake = invoke([error, {"answer": "사용하면 안 되는 응답"}])
        assert not result.ok and result.error_kind == kind
        assert result.attempts == len(fake.calls) == 1 and no_network_or_wait == []


def test_openai_connection_errors_retry_like_network(no_network_or_wait):
    # APITimeoutError는 APIConnectionError를 상속한다(client 분류 주석 참고).
    request = httpx.Request("POST", "https://api.openai.invalid")
    timeout = openai.APITimeoutError(request=request)
    for error in [openai.APIConnectionError(message="가상 연결 실패", request=request), timeout]:
        no_network_or_wait.clear()
        result, fake = invoke([error] * 3)
        assert not result.ok and result.error_kind == "network"
        assert result.attempts == len(fake.calls) == 3 and no_network_or_wait == [1, 2]


def test_responses_model_default_and_override():
    # 기존 Responses 진입점도 동일한 공통 모델 설정을 쓴다.
    assert client.RESPONSES_DEFAULT_MODEL == "gpt-6-luna"
    assert client.responses_model_name(Settings()) == "gpt-6-luna"
    assert client.responses_model_name(Settings(openai_model=" gpt-fake ")) == "gpt-fake"


def test_responses_backend_requires_openai_key(monkeypatch):
    monkeypatch.setattr(client, "get_backend", client._backend_for_settings)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        client.get_responses_backend(Settings())


def test_backend_factory_supplies_the_backend():
    fake = FakeLLM([{"answer": "팩토리 백엔드"}])
    result = client.call_structured(PROMPT, Answer, {"input": "입력"}, backend_factory=lambda: fake)
    assert result.ok and result.value.answer == "팩토리 백엔드" and fake.schemas == [Answer]


def test_override_and_explicit_backend_beat_factory(no_network_or_wait):
    def forbidden():
        raise AssertionError("팩토리가 불리면 안 됩니다")

    override = FakeLLM([{"answer": "오버라이드"}])
    with client.use_backend(override):
        result = client.call_structured(PROMPT, Answer, {"input": "입력"}, backend_factory=forbidden)
    assert result.value.answer == "오버라이드"

    explicit = FakeLLM([{"answer": "명시 백엔드"}])
    unused = FakeLLM([])
    result = client.call_structured(PROMPT, Answer, {"input": "입력"},
                                    backend=explicit, backend_factory=lambda: unused)
    assert result.value.answer == "명시 백엔드" and unused.calls == []


def test_backend_factory_failure_records_only_exception_type(monkeypatch):
    logged = []
    monkeypatch.setattr(client, "current_event", lambda event, **data: logged.append((event, data)))

    def fail():
        raise ValueError("private-factory-message fake-api-key")

    result = client.call_structured(PROMPT, Answer, {"input": "가상 입력"}, backend_factory=fail)
    assert result.error_kind == "internal" and result.attempts == 0
    assert logged[-1][1]["detail"]["error_code"] == "ValueError"
    assert "private-" not in repr(logged) and "fake-api-key" not in repr(logged)


def test_openai_backend_configuration_without_global_key_cache():
    settings = Settings(openai_api_key="fake-openai-key", openai_model=" gpt-fake ")
    backend = client._backend_for_settings(settings)
    assert backend.model_name == "gpt-fake" and backend.use_responses_api is True
    assert backend.max_retries == 0 and backend.request_timeout == 20
    assert backend.openai_api_key.get_secret_value() == "fake-openai-key"
    assert client._backend_for_settings(Settings(**vars(settings))) is not backend
    changed = client._backend_for_settings(Settings(openai_api_key="fake-other-key", openai_model="gpt-other"))
    assert changed is not backend and changed.model_name == "gpt-other"


@pytest.mark.parametrize("key", ["", "   "])
def test_openai_backend_requires_key_without_contacting_sdk(monkeypatch, key):
    def forbidden(**kwargs):
        pytest.fail("키가 없으면 SDK를 구성하면 안 됩니다")

    monkeypatch.setattr(client, "ChatOpenAI", forbidden)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        client._backend_for_settings(Settings(openai_api_key=key))


@pytest.mark.parametrize("runtime", ["server", "local"])
def test_openai_settings_load_env_and_ignore_previous_provider(monkeypatch, runtime):
    from app import config
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")
    monkeypatch.setenv("AI_RUNTIME", runtime)
    monkeypatch.setenv("OPENAI_MODEL", "gpt-fake")
    monkeypatch.setenv("GEMINI_API_KEY", "unused-fake-key")
    monkeypatch.setenv("GEMINI_MODEL", "unused-fake-model")
    monkeypatch.setenv("TRADE_EXTRACT_BACKEND", "gemini")
    config.get_settings.cache_clear()
    try:
        settings = config.get_settings()
        assert settings.openai_api_key == ("fake-openai-key" if runtime == "local" else "")
        assert settings.openai_model == "gpt-fake"
        assert not hasattr(settings, "gemini_api_key") and not hasattr(settings, "trade_extract_backend")
        assert "fake-openai-key" not in repr(settings)
    finally:
        config.get_settings.cache_clear()


def test_model_source_uses_openai_model_settings(monkeypatch):
    monkeypatch.setattr(client, "get_settings", lambda: Settings(openai_model=" gpt-fake "))
    assert client.model_source() == "openai:gpt-fake"


@pytest.fixture
def mock_openai():
    """실제 LangChain·OpenAI SDK를 통과하되 HTTP는 프로세스 안에서만 처리한다."""
    from langchain_openai import ChatOpenAI

    clients = []

    def make(outputs):
        outputs = iter(outputs)
        requests = []

        def respond(request):
            payload = json.loads(request.content)
            requests.append((request.url.path, payload))
            value = next(outputs)
            if isinstance(value, int):
                return httpx.Response(value, json={"error": {"message": "private-body fake-api-key"}})
            return httpx.Response(200, json={
                "id": "resp_fake", "object": "response", "created_at": 1,
                "model": "gpt-6-luna", "status": "completed", "error": None,
                "incomplete_details": None,
                "output": [{
                    "type": "function_call", "id": "fc_fake", "call_id": "call_fake",
                    "name": payload["tools"][0]["name"],
                    "arguments": value if isinstance(value, str) else json.dumps(value),
                }],
                "parallel_tool_calls": False, "tool_choice": payload["tool_choice"],
                "tools": payload["tools"],
                "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10},
            })

        http = httpx.Client(transport=httpx.MockTransport(respond))
        clients.append(http)
        backend = ChatOpenAI(model="gpt-6-luna", api_key="fake-key", use_responses_api=True,
                             http_client=http, http_socket_options=(), max_retries=0, timeout=20)
        return backend, requests

    yield make
    for http in clients:
        http.close()


def _production_schemas():
    from app.graph.nodes.analyze_email import EmailAnalysis
    from app.graph.nodes.reflect import ReflectAnalysis
    from app.services.memory import ThreadSummary
    from app.tools.draft_replies import DraftOutput
    from app.tools.draft_followup_replies import FollowupDraft
    from app.tools.extract_deal_terms import ExtractedDealTerms, ExtractedTradeDoc, ExtractedTradeCIDoc
    from app.trade.common.extraction import wire_schema
    from app.trade.pi.models import PIExtraction
    from app.trade.po.models import POExtraction
    from app.trade.ci.models import CIExtraction
    from app.trade.pl.models import PLExtraction

    candidates = [{"label": "간단 안내", "body": "가상 답장"}, {"label": "상세 안내", "body": "가상 안내"}]
    return [
        (EmailAnalysis, {"intent": "general", "reason": "가상 문의"}),
        (ReflectAnalysis, {"cause": "가상 원인", "feedback": "가상 수정"}),
        (ThreadSummary, {"deal_conditions": [], "confirmed_fields": [], "unanswered_questions": []}),
        (DraftOutput, {"candidates": candidates}),
        (FollowupDraft, {"candidates": candidates}),
        (ExtractedDealTerms, {"customer_name": "가상상사"}),
        (ExtractedTradeDoc, {"currency": "USD"}),
        (ExtractedTradeCIDoc, {"source_document_type": "PI"}),
        *[(wire_schema(schema), {}) for schema in (PIExtraction, POExtraction, CIExtraction, PLExtraction)],
    ]


@pytest.mark.parametrize("schema,value", _production_schemas(), ids=lambda value: getattr(value, "__name__", None))
def test_production_schemas_through_openai_responses_sdk(mock_openai, schema, value):
    backend, requests = mock_openai([value])
    result = client.call_structured(PROMPT, schema, {"input": "가상 입력"}, backend=backend)

    assert result.ok and result.value == schema.model_validate(value)
    [(path, payload)] = requests
    assert path == "/v1/responses" and payload["model"] == "gpt-6-luna"
    assert payload["tools"][0]["strict"] is False
    assert payload["tool_choice"] == {"type": "function", "name": schema.__name__}


@pytest.mark.parametrize("outputs,kind,attempts,waits", [
    ([429], "rate_limit", 1, []),
    ([401], "invalid_input", 1, []),
    ([503, 503, 503], "network", 3, [1, 2]),
])
def test_http_errors_do_not_add_sdk_retries(mock_openai, no_network_or_wait, outputs, kind, attempts, waits):
    backend, requests = mock_openai(outputs)
    result = client.call_structured(PROMPT, Answer, {"input": "가상 입력"}, backend=backend)
    assert not result.ok and result.error_kind == kind
    assert result.attempts == len(requests) == attempts
    assert no_network_or_wait == waits


@pytest.mark.parametrize("invalid", [{"wrong_key": "가상 값"}, "{invalid-json"])
def test_sdk_output_validation_retries_and_recovers(mock_openai, no_network_or_wait, invalid):
    backend, requests = mock_openai([invalid, {"answer": "가상 복구"}])
    result = client.call_structured(PROMPT, Answer, {"input": "가상 입력"}, backend=backend)
    assert result.ok and result.value.answer == "가상 복구"
    assert result.attempts == len(requests) == 2 and no_network_or_wait == []


def test_real_evaluation_backend_uses_same_output_adapter(mock_openai):
    from app.evaluation.injection import ScenarioBackend

    backend, requests = mock_openai([{"answer": "가상 실제경로"}])
    scenario = ScenarioBackend(real=lambda: backend)
    with client.use_backend(scenario):
        result = client.call_structured(PROMPT, Answer, {"input": "가상 입력"})
    assert result.ok and result.value.answer == "가상 실제경로"
    assert scenario.calls == [("Answer", None)] and len(requests) == 1
