"""기능별 모델 프로필 선택(llm-model-profiles 2·5절, 결정 1a·2a). 실제 API·키를 쓰지 않는다.

모의 HTTPS 전송(httpx.MockTransport)으로 실제 SDK가 만드는 요청 본문만 확인한다.
"""
import json

import httpx
import pytest
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.config import Settings
from app.knowledge import router as knowledge_router
from app.knowledge.extract import OpenAIDocumentExtractor
from app.knowledge.schemas import KnowledgeError, PageImage
from app.llm import client as llm
from app.llm import profiles
from app.prompts import Prompt

MAPPED_STRUCTURED = Prompt("analyze_email", "vtest", "가상 메일: {text}")
MAPPED_TRADE = Prompt("pi_extract", "vtest", "Synthetic text: {text}")
UNMAPPED = Prompt("workflow_plan", "vtest", "가상 요청: {text}")


class Out(BaseModel):
    label: str


def _ok(payload):
    return httpx.Response(200, json={
        "id": "resp_fake", "object": "response", "created_at": 1, "model": payload["model"],
        "status": "completed", "error": None, "incomplete_details": None,
        "output": [{"type": "function_call", "id": "fc_fake", "call_id": "call_fake",
                    "name": "Out", "arguments": json.dumps({"label": "가상"})}],
        "parallel_tool_calls": False, "tool_choice": payload["tool_choice"], "tools": payload["tools"],
        "usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10,
                  "input_tokens_details": {"cached_tokens": 2}, "output_tokens_details": {"reasoning_tokens": 1}},
    })


@pytest.fixture
def sdk(monkeypatch):
    """실제 ChatOpenAI에 모의 HTTP 전송만 끼운다. 요청 본문·timeout을 기록한다."""
    state = {"bodies": [], "timeouts": [], "respond": _ok, "events": []}

    def transport(request):
        body = json.loads(request.content)
        state["bodies"].append(body)
        state["timeouts"].append(request.extensions.get("timeout", {}).get("read"))
        return state["respond"](body)

    http = httpx.Client(transport=httpx.MockTransport(transport))

    class Mocked(ChatOpenAI):
        def __init__(self, **kwargs):
            super().__init__(http_client=http, **kwargs)

    monkeypatch.setattr(llm, "ChatOpenAI", Mocked)
    monkeypatch.setattr(llm, "sleep", lambda _: None)
    monkeypatch.setattr(llm, "current_event", lambda kind, **kw: state["events"].append((kind, kw.get("detail"))))
    yield state
    http.close()


def call(prompt, settings, **kwargs):
    with llm.use_user_key(lambda: "fake-user-key", settings):
        return llm.call_structured(prompt, Out, {"text": "가상"}, **kwargs)


def test_default_is_baseline_and_request_matches_legacy_backend(sdk):
    settings = Settings()
    result = call(MAPPED_TRADE, settings)
    assert result.ok and result.profile_id == "trade_extraction.baseline"
    legacy = llm.ChatOpenAI(model="gpt-6-luna", api_key="fake-user-key", use_responses_api=True,
                            http_socket_options=(), max_retries=0, timeout=20)
    # 기존 방식(설정 없이 만든 같은 백엔드)의 요청과 바이트 단위로 같아야 한다.
    llm.call_structured(MAPPED_TRADE, Out, {"text": "가상"}, backend=legacy)
    assert json.dumps(sdk["bodies"][0], sort_keys=True) == json.dumps(sdk["bodies"][1], sort_keys=True)
    assert "reasoning" not in sdk["bodies"][0] and "max_output_tokens" not in sdk["bodies"][0]
    assert sdk["timeouts"][0] == 20


def test_trade_upgrade_applies_fixed_model_effort_cap_timeout_only_to_its_feature(sdk):
    settings = Settings(openai_model="gpt-6-luna-legacy-override", llm_profile_trade_extraction="sol-medium")
    trade = call(MAPPED_TRADE, settings)
    mail = call(MAPPED_STRUCTURED, settings)
    assert trade.ok and trade.profile_id == "trade_extraction.sol-medium"
    assert sdk["bodies"][0]["model"] == "gpt-6.1-sol"  # 계약 고정 모델: OPENAI_MODEL로 바뀌지 않는다
    assert sdk["bodies"][0]["reasoning"] == {"effort": "medium"}
    assert sdk["bodies"][0]["max_output_tokens"] == 8192 and sdk["timeouts"][0] == 90
    # 다른 기능은 baseline 그대로(기존 OPENAI_MODEL 덮어쓰기 유지).
    assert mail.profile_id == "default_structured.baseline"
    assert sdk["bodies"][1]["model"] == "gpt-6-luna-legacy-override" and "reasoning" not in sdk["bodies"][1]


def test_trade_sol_low_sends_low_effort_with_upgrade_limits_and_covers_mail_trade_extraction(sdk):
    # 2026-11-19 요청자 결정: 무역 추출만 Sol low로 상향(25·49품목 baseline 20초 시간 초과 대응).
    settings = Settings(llm_profile_trade_extraction="sol-low")
    mail_trade = Prompt("extract_trade_terms", "vtest", "Synthetic mail: {text}")
    for prompt in (MAPPED_TRADE, mail_trade):  # PI 화면 추출과 메일의 무역 조건 추출이 같은 기능 키다
        result = call(prompt, settings)
        assert result.ok and result.profile_id == "trade_extraction.sol-low"
    for body, timeout in zip(sdk["bodies"], sdk["timeouts"]):
        assert body["model"] == "gpt-6.1-sol" and body["reasoning"] == {"effort": "low"}
        assert body["max_output_tokens"] == 8192 and timeout == 90
    # 메일 분석 등 다른 기능은 baseline 그대로다.
    assert call(MAPPED_STRUCTURED, settings).profile_id == "default_structured.baseline"
    assert sdk["bodies"][2]["model"] == "gpt-6-luna" and "reasoning" not in sdk["bodies"][2]


def test_sol_low_is_only_selectable_for_trade_extraction():
    assert profiles.validate_name("trade_extraction", "trade_extraction.sol-low") == "sol-low"
    with pytest.raises(ValueError, match="LLM_PROFILE_DEFAULT_STRUCTURED"):
        Settings(llm_profile_default_structured="sol-low")


def test_default_structured_upgrade_covers_mail_prompts_but_not_unmapped_calls(sdk):
    # 결정 1a: 메일→견적 단계(default_structured)도 Sol medium으로 상향할 수 있다.
    settings = Settings(llm_profile_default_structured="default_structured.sol-medium")
    assert call(MAPPED_STRUCTURED, settings).profile_id == "default_structured.sol-medium"
    assert sdk["bodies"][0]["model"] == "gpt-6.1-sol"
    # 계약에 매핑되지 않은 구조화 호출은 상향하지 않는다.
    unmapped = call(UNMAPPED, settings)
    assert unmapped.profile_id == "default_structured.baseline" and sdk["bodies"][1]["model"] == "gpt-6-luna"


def test_explicit_return_profile_sends_luna_medium(sdk):
    assert call(MAPPED_TRADE, Settings(llm_profile_trade_extraction="luna-medium")).ok
    assert sdk["bodies"][0]["model"] == "gpt-6-luna" and sdk["bodies"][0]["reasoning"] == {"effort": "medium"}
    assert "max_output_tokens" not in sdk["bodies"][0] and sdk["timeouts"][0] == 20


def test_upgrade_timeout_is_not_retried_and_never_calls_another_model(sdk):
    def timeout(_body):
        raise httpx.ReadTimeout("fake timeout")
    sdk["respond"] = timeout
    upgraded = call(MAPPED_TRADE, Settings(llm_profile_trade_extraction="sol-medium"))
    assert not upgraded.ok and upgraded.error_kind == "network" and upgraded.error_detail == "timeout"
    assert upgraded.attempts == 1 and [b["model"] for b in sdk["bodies"]] == ["gpt-6.1-sol"]
    # baseline은 기존 동작(시간 초과도 network 재시도 2회)을 유지한다.
    sdk["bodies"].clear()
    legacy = call(MAPPED_TRADE, Settings())
    assert legacy.attempts == 3 and legacy.error_detail == "timeout"
    assert {b["model"] for b in sdk["bodies"]} == {"gpt-6-luna"}


def test_access_denied_and_usage_are_recorded_without_key(sdk):
    sdk["respond"] = lambda _body: httpx.Response(401, json={"error": {"message": "fake-private"}})
    denied = call(MAPPED_TRADE, Settings(llm_profile_trade_extraction="sol-medium"))
    assert denied.error_kind == "invalid_input" and denied.error_detail == "access_denied"
    sdk["respond"] = _ok
    assert call(MAPPED_TRADE, Settings(llm_profile_trade_extraction="sol-medium")).ok
    calls = [detail for kind, detail in sdk["events"] if kind == "llm_call"]
    assert calls[0]["usage_unknown_attempts"] == 1  # 실패한 시도는 0이 아니라 미상
    assert calls[1]["profile_id"] == "trade_extraction.sol-medium" and calls[1]["usage_unknown_attempts"] == 0
    assert calls[1]["usage"] == {"input_tokens": 7, "output_tokens": 3, "cached_input_tokens": 2, "reasoning_tokens": 1}
    assert calls[1]["model"] == "gpt-6.1-sol" and calls[1]["reasoning_effort"] == "medium"
    assert "fake-user-key" not in repr(sdk["events"]) and "fake-private" not in repr(sdk["events"])


def test_incomplete_output_is_distinguished(sdk):
    def incomplete(payload):
        response = _ok(payload).json()
        response.update(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
        response["output"][0]["arguments"] = '{"label": "가'
        return httpx.Response(200, json=response)
    sdk["respond"] = incomplete
    result = call(MAPPED_TRADE, Settings(llm_profile_trade_extraction="sol-medium"))
    assert not result.ok and result.error_kind == "invalid_output" and result.error_detail == "incomplete_output"
    assert result.attempts == 1  # 상향 프로필은 invalid_output 재시도 0


def test_local_worker_stays_baseline_and_records_requested_profile(sdk):
    seen = []

    def worker(prompt, schema, variables):
        seen.append(prompt.NAME)
        return llm.LLMResult(ok=True, value=Out(label="pc"), attempts=1, prompt_version=prompt.version, duration_ms=1)

    worker.guard = lambda: None
    with llm.use_worker_call(worker):
        result = call(MAPPED_TRADE, Settings(llm_profile_trade_extraction="sol-medium"))
    assert result.ok and seen == ["pi_extract"] and sdk["bodies"] == []
    assert ("llm_profile", {"prompt_version": "pi_extract.vtest", "requested_profile": "trade_extraction.sol-medium",
                            "applied_profile": "trade_extraction.baseline",
                            "reason": "local_worker_baseline_only"}) in sdk["events"]


@pytest.mark.parametrize("field,value", [
    ("llm_profile_trade_extraction", "luna-high"),
    ("llm_profile_default_structured", "terra-low"),
    ("llm_profile_vision_transcription", "sol-medium"),
])
def test_invalid_profile_names_fail_at_startup(field, value):
    with pytest.raises(ValueError, match=field.upper()):
        Settings(**{field: value})


def test_non_selectable_status_fails_at_startup(monkeypatch):
    profile = profiles.load_contract()["features"]["trade_extraction"]["profiles"]["sol-medium"]
    monkeypatch.setitem(profile, "status", "candidate")
    with pytest.raises(ValueError, match="운영에서 고를 수 없는"):
        Settings(llm_profile_trade_extraction="sol-medium")


def test_every_selectable_feature_has_a_settings_field_matching_the_contract():
    names = profiles.load_contract()["selection"]["config_names"]
    for feature in profiles.SELECTABLE_FEATURES:
        assert names[feature].lower() in Settings.__dataclass_fields__


@pytest.fixture
def adapters(monkeypatch):
    class Access:
        def __init__(self, *args):
            pass

        def read(self):
            return "fake-user-key"

    monkeypatch.setattr(knowledge_router, "UserKeyAccess", Access)
    monkeypatch.setattr(knowledge_router, "make_cipher", lambda settings: None)
    return lambda settings, snapshot: knowledge_router.make_adapters(None, settings, 1, snapshot)[1]


def test_vision_profile_applies_only_to_new_processing(adapters):
    settings = Settings(llm_profile_vision_transcription="terra-low", knowledge_vision_model="gpt-6-luna-legacy")
    new = adapters(settings, {})
    assert (new.profile.model, new.reasoning_effort, new.timeout, new.max_retries, new.max_output_tokens) == (
        "gpt-6.1-terra", "low", 180, 3, 10000)
    assert new.profile_id == "vision_transcription.terra-low"
    # 이미 baseline으로 시작한 처리(키 없는 스냅샷)는 선택이 바뀌어도 baseline·저장 모델을 유지한다.
    started = adapters(settings, {"extraction": {"provider": "openai", "model": "gpt-6-luna"},
                                  "embedding": {"provider": "openai", "model": "text-embedding-3-small", "dimensions": 1536}})
    assert started.profile.model == "gpt-6-luna" and started.reasoning_effort is None
    assert started.profile_id == "vision_transcription.baseline"
    # 상향으로 시작한 처리는 선택을 지워도 고정된 프로필로 이어 간다.
    pinned = adapters(Settings(), {"extraction": {"provider": "openai", "model": "gpt-6.1-terra"},
                                   "embedding": {"provider": "openai", "model": "text-embedding-3-small", "dimensions": 1536},
                                   "vision_profile": "vision_transcription.terra-low"})
    assert pinned.profile.model == "gpt-6.1-terra" and pinned.reasoning_effort == "low"
    with pytest.raises(KnowledgeError):
        adapters(Settings(), {"extraction": {"provider": "openai", "model": "x"},
                              "embedding": {"provider": "openai", "model": "y", "dimensions": 1},
                              "vision_profile": "vision_transcription.no-such"})


def test_vision_baseline_request_has_no_reasoning_and_upgrade_sends_it():
    sent = []

    class Response:
        status, output_parsed = "completed", None

    class Client:
        def __init__(self, **options):
            sent.append(("client", options))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        @property
        def responses(self):
            return self

        def parse(self, **request):
            sent.append(("parse", {k: v for k, v in request.items() if k not in {"input", "instructions"}}))
            return Response()

    page = [PageImage(number=1, source="가상.png", png=b"x")]
    OpenAIDocumentExtractor(lambda: "fake-user-key", "gpt-6-luna", client_factory=Client).extract(page)
    OpenAIDocumentExtractor(lambda: "fake-user-key", "gpt-6.1-terra", client_factory=Client,
                            reasoning_effort="low", profile_id="vision_transcription.terra-low").extract(page)
    assert sent[0] == ("client", {"api_key": "fake-user-key", "timeout": 180, "max_retries": 3})
    assert "reasoning" not in sent[1][1] and sent[1][1]["max_output_tokens"] == 10000
    assert sent[3][1]["reasoning"] == {"effort": "low"} and sent[3][1]["model"] == "gpt-6.1-terra"
