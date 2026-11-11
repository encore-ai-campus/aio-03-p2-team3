"""무역 문서 AI 추출의 wire 스키마·백엔드 선택 단위 테스트(외부 모델을 호출하지 않는다)."""
from decimal import Decimal
from types import UnionType
from typing import Union, get_args, get_origin

import pytest
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import Settings
from app.llm.client import use_backend
from app.prompts import Prompt
from app.trade.ci.models import CIExtraction
from app.trade.common import extraction
from app.trade.common.extraction import extract_facts, trade_backend, wire_schema
from app.trade.common.models import Number, Text
from app.trade.pi.models import PIExtraction
from app.trade.pl.models import PLExtraction
from app.trade.po.models import POExtraction
from tests.fakes.llm import FakeLLM

DOMAIN_SCHEMAS = [PIExtraction, POExtraction, CIExtraction, PLExtraction]


def _nested_models(annotation):
    """어노테이션 얕은 한 겹에서 중첩 pydantic 모델을 건진다(Annotated·Optional·list를 풀고)."""
    core = get_args(annotation)[0] if hasattr(annotation, "__metadata__") else annotation
    origin = get_origin(core)
    if origin is list:
        core = get_args(core)[0]
    if origin in (Union, UnionType):
        return [arg for arg in get_args(core) if isinstance(arg, type) and issubclass(arg, BaseModel)]
    if isinstance(core, type) and issubclass(core, BaseModel):
        return [core]
    return []


@pytest.mark.parametrize("schema", DOMAIN_SCHEMAS)
def test_wire_schema_keeps_every_field(schema):
    """reflection이 필드를 놓치면 검증 단계에서 그 필드가 통째로 사라진다 — 원본·wire가 재귀적으로 같은지 본다."""
    def walk(model):
        wire = wire_schema(model)
        assert list(wire.model_fields) == list(model.model_fields), model.__name__
        for name, info in model.model_fields.items():
            children = _nested_models(info.annotation)
            wire_children = _nested_models(wire.model_fields[name].annotation)
            assert len(children) == len(wire_children), f"{model.__name__}.{name}"
            for child, child_wire in zip(children, wire_children):
                walk(child)
    walk(schema)


_BANNED_KEYS = ("pattern", "maxLength", "maxItems", "minimum", "maximum")


def _schema_violations(node):
    found = set()
    if isinstance(node, dict):
        if node.get("type") == "number":
            found.add("type: number")
        found |= {key for key in _BANNED_KEYS if key in node}
        for value in node.values():
            found |= _schema_violations(value)
    elif isinstance(node, list):
        for value in node:
            found |= _schema_violations(value)
    return found


@pytest.mark.parametrize("schema", DOMAIN_SCHEMAS)
def test_wire_json_schema_has_no_numbers_or_http_constraints(schema):
    """숫자는 문자열로 받고(JSON number 정밀도 보존·HTTP 제약 분리) HTTP 입력 제약은 떼어냈다."""
    assert _schema_violations(wire_schema(schema).model_json_schema()) == set()


class _Line(BaseModel):
    quantity: Number = None
    unit_price: Number = None


class _QuoteExtraction(BaseModel):
    document_number: Text = None
    lines: list[_Line] = Field(default_factory=list)


PROMPT = Prompt("quote", "v1", "{text}")


def test_extract_facts_turns_wire_strings_into_validated_decimals():
    fake = FakeLLM([{"document_number": " Q-1 ", "lines": [
        {"quantity": "10", "unit_price": "8.10"}]}])
    with use_backend(fake):
        draft = extract_facts(PROMPT, _QuoteExtraction, "Q-1 10 PCS USD 8.10")
    assert fake.schemas[0] is wire_schema(_QuoteExtraction)  # 캐시된 같은 wire 스키마가 갔다
    assert draft["document_number"] == "Q-1"  # wire 모델이 앞뒤 공백을 지운다
    assert draft["lines"] == [{"quantity": "10", "unit_price": "8.10"}]  # 십진수 정밀도 유지
    assert _QuoteExtraction.model_validate(draft).lines[0].unit_price == Decimal("8.10")


def test_trade_backend_defaults_to_openai_responses():
    backend = trade_backend(Settings(openai_api_key="가짜 키"))
    assert isinstance(backend, ChatOpenAI)
    assert backend.model_name == "gpt-6-luna"
    assert backend.use_responses_api


def test_trade_backend_model_follows_settings():
    backend = trade_backend(Settings(openai_api_key="가짜 키", openai_model=" gpt-fake "))
    assert backend.model_name == "gpt-fake"


def test_trade_backend_uses_the_shared_openai_backend(monkeypatch):
    settings = Settings(openai_api_key="가짜 키", openai_model="gpt-fake")
    received = []
    sentinel = object()

    def shared(config=None):
        received.append(config)
        return sentinel

    monkeypatch.setattr(extraction, "get_backend", shared)
    assert trade_backend(settings) is sentinel and received == [settings]


def test_old_gemini_env_does_not_enable_trade_fallback(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "unused-fake-key")
    monkeypatch.setenv("GEMINI_MODEL", "unused-fake-model")
    monkeypatch.setenv("TRADE_EXTRACT_BACKEND", "gemini")
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        trade_backend(Settings())


def test_trade_backend_needs_openai_key_by_default():
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        trade_backend(Settings())
