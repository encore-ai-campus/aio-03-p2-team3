"""공통 구조화 호출·원문 확인. 프롬프트와 입력 형식은 문서별 agent가 소유한다.

백엔드 선택(2026-11-11): 무역 문서 추출은 OpenAI Responses API를 기본으로 쓰고
`TRADE_EXTRACT_BACKEND=gemini`로 Gemini를 고를 수 있다. 그래프(LangGraph)는 기존
Gemini 백엔드를 그대로 쓴다. 원본 사본의 추출기도 OpenAI Responses API를 썼다
(reference/kekorea/Quotation_KEKOREA/agent/extractor.py).

LLM에는 wire 스키마를 준다: 입력 검증 모델에서 Gemini 구조화 출력이 거부하는 제약
(`pattern`·문자열/리스트 `max_length`)을 떼고, 숫자는 원본 사본처럼 전부 문자열로
받는다(모델이 JSON 숫자를 내놓으면 십진수 정밀도가 깨진다). 돌려받은 값은 이 module이
원래 스키마로 다시 검증해 Decimal로 바꾼다. HTTP 입력 검증은 그대로 입력 모델이 맡는다.
"""
from decimal import Decimal
from functools import lru_cache
from types import UnionType
from typing import Union, get_args, get_origin

from pydantic import ConfigDict, Field, ValidationError, create_model
from pydantic import BaseModel as PydanticBaseModel

from app.config import Settings, get_settings
from app.llm.client import call_structured, get_backend, get_responses_backend
from app.trade.common.models import DocumentError
from app.trade.common.verify_quotes import verify_item_quotes


def trade_backend(settings: Settings | None = None):
    """무역 문서 추출 백엔드. `TRADE_EXTRACT_BACKEND`(기본 `openai_responses`)."""
    choice = ((settings or get_settings()).trade_extract_backend.strip() or "openai_responses").lower()
    if choice == "gemini":
        return get_backend(settings)
    if choice == "openai_responses":
        return get_responses_backend(settings)
    raise ValueError(f"TRADE_EXTRACT_BACKEND은 openai_responses 또는 gemini여야 합니다(입력: {choice})")


def _core_type(annotation):
    """`Annotated[X, ...]`에서 X를 꺼낸다."""
    if hasattr(annotation, "__metadata__"):
        return get_args(annotation)[0]
    return annotation


def _wire_annotation(annotation):
    """숫자는 문자열로, 문자열 제약(Annotated Field)은 벗기고, 중첩 모델은 wire 모델로 바꾼다."""
    core = _core_type(annotation)
    if core is Decimal:
        return str
    if get_origin(core) in (Union, UnionType):  # X | None (PEP 604)과 typing.Union 모두
        args = get_args(core)
        if any(arg is Decimal for arg in args):
            return Union[tuple(str if arg is Decimal else arg for arg in args)]
        if any(hasattr(arg, "__metadata__") for arg in args):
            return Union[tuple(get_args(arg)[0] if hasattr(arg, "__metadata__") else arg for arg in args)]
        return annotation
    if hasattr(core, "__metadata__"):  # Annotated[str, Field(max_length=...)] → str
        return get_args(core)[0]
    if get_origin(core) is list:  # list[모델] → list[wire 모델]
        item = get_args(core)[0]
        if isinstance(item, type) and issubclass(item, PydanticBaseModel):
            return list[wire_schema(item)]
        return core
    if isinstance(core, type) and issubclass(core, PydanticBaseModel):
        return wire_schema(core)
    return annotation


@lru_cache(maxsize=None)
def wire_schema(model: type[PydanticBaseModel]) -> type[PydanticBaseModel]:
    """LLM에 보낼 스키마. 숫자는 문자열, 문자열/리스트 제약(pattern·max_length)은 없앤다."""
    fields = {}
    for name, info in model.model_fields.items():
        annotation = _wire_annotation(info.annotation)
        default = str(info.default) if isinstance(info.default, Decimal) else info.default
        if info.default_factory is not None:
            factory = annotation if isinstance(annotation, type) and issubclass(annotation, PydanticBaseModel) \
                else info.default_factory
            fields[name] = (annotation, Field(default_factory=factory))
        elif info.is_required():
            fields[name] = (annotation, ...)
        else:
            fields[name] = (annotation, default)
    return create_model(f"{model.__name__}Wire", __config__=ConfigDict(str_strip_whitespace=True), **fields)


def extract_facts(prompt, schema: type[PydanticBaseModel], text: str, backend=None) -> dict:
    """문장을 wire 스키마로 추출해 원래 스키마로 검증한 dict를 돌려준다.

    백엔드를 명시하지 않으면 `trade_backend` 팩토리가 고른다(오버라이드·명시 백엔드가
    있으면 팩토리는 부르지도 않는다)."""
    result = call_structured(prompt, wire_schema(schema), {"text": text},
                             backend=backend, backend_factory=trade_backend)
    if not result.ok:
        raise DocumentError("AI_" + (result.error_kind or "internal").upper(),
                            "문서 내용을 추출하지 못했습니다. 다시 시도하거나 직접 입력하세요", 503)
    try:
        validated = schema.model_validate(result.value.model_dump(mode="json"))
    except ValidationError:
        raise DocumentError("AI_INVALID_OUTPUT",
                            "추출 결과를 문서 형식으로 바꾸지 못했습니다. 다시 시도하거나 직접 입력하세요", 503) from None
    draft = validated.model_dump(mode="json")
    draft["source_notes"] = []
    for item in draft.get("items", []):
        if "confirm_price_override" in item:
            item["confirm_price_override"] = False
        if item.get("product_code") and item["product_code"].casefold() not in str(item.get("source") or "").casefold():
            draft.setdefault("conflicts", []).append("Confirm product code against its exact source quote")
    verify_item_quotes(draft, text)
    return draft
