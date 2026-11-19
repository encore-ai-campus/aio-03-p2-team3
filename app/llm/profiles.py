"""기능별 LLM 프로필 해석기(llm-model-profiles 계획 2절, 결정 1a·2a).

원본은 `docs/plans/llm-model-profiles.contract.json`이다. 이 모듈은 계약을 읽기만 한다.
- 기본값은 모든 기능이 `<기능>.baseline`이고, baseline 요청은 기존 코드와 같다(모델은 기존
  `OPENAI_MODEL`/`KNOWLEDGE_VISION_MODEL` 덮어쓰기를 따른다).
- 기능별 서버 설정(`LLM_PROFILE_<기능>`)에 프로필 이름을 명시했을 때만 다른 프로필을 쓴다.
- 잘못된 이름·운영 선택 불가 상태는 시작 시 오류다. 조용히 baseline으로 대체하지 않는다.
- 상향 프로필은 서버 저장 키(stored_key) 경로에만 적용한다. 개인 PC 경로는 baseline이다.
- 비밀값은 다루지 않는다(키는 계속 사용자별 저장 키/PC .env).
"""
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "docs/plans/llm-model-profiles.contract.json"
# Settings 필드 이름(소문자) = 계약 selection.config_names 값의 소문자.
SELECTABLE_FEATURES = ("default_structured", "trade_extraction", "vision_transcription")
BASELINE = "baseline"


@dataclass(frozen=True)
class ResolvedProfile:
    feature: str
    name: str
    status: str
    model: str | None  # None이면 baseline: 기존 모델 결정(legacy env)을 그대로 쓴다.
    reasoning_effort: str | None  # None이면 요청에 노력치를 보내지 않는다.
    timeout_seconds: int
    max_output_tokens: int | None
    sdk_max_retries: int | None
    network_retries: int
    invalid_output_retries: int
    logical_deadline_seconds: int | None

    @property
    def profile_id(self) -> str:
        return f"{self.feature}.{self.name}"

    @property
    def is_baseline(self) -> bool:
        return self.name == BASELINE


@lru_cache(maxsize=1)
def load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def config_name(feature: str) -> str:
    return load_contract()["selection"]["config_names"][feature]


def _field(feature: str) -> str:
    return config_name(feature).lower()


@lru_cache(maxsize=1)
def _prompt_features() -> dict[str, str]:
    features = load_contract()["features"]
    return {prompt_id: feature for feature in ("default_structured", "trade_extraction")
            for prompt_id in features[feature]["prompt_ids"]}


def feature_for_prompt(prompt_name: str) -> str | None:
    """계약에 매핑된 프롬프트의 기능 키. 매핑 밖 프롬프트는 None(항상 baseline)."""
    return _prompt_features().get(prompt_name)


def _normalize(feature: str, raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return BASELINE
    prefix = f"{feature}."
    return value[len(prefix):] if value.startswith(prefix) else value


def validate_name(feature: str, raw: str) -> str:
    """설정값을 프로필 이름으로 바꾸고 운영 선택 가능 여부를 확인한다. 잘못되면 ValueError."""
    contract = load_contract()
    name = _normalize(feature, raw)
    profiles = contract["features"][feature]["profiles"]
    env = config_name(feature)
    if name not in profiles:
        raise ValueError(f"{env}={raw!r}: 계약에 없는 프로필입니다. 허용: {', '.join(sorted(profiles))}")
    profile = profiles[name]
    if profile["status"] not in contract["selection"]["production_selectable_statuses"]:
        raise ValueError(f"{env}={raw!r}: 운영에서 고를 수 없는 상태({profile['status']})입니다")
    if "stored_key" not in profile["modes"]:
        raise ValueError(f"{env}={raw!r}: 서버 저장 키 경로 값이 없는 프로필입니다")
    if profile["reasoning_effort"] in contract["forbidden"]["efforts"]:
        raise ValueError(f"{env}={raw!r}: 금지된 노력치입니다")
    return name


def validate_settings(settings) -> None:
    """서버 시작(Settings 생성) 때 세 기능의 선택값을 모두 확인한다."""
    for feature in SELECTABLE_FEATURES:
        validate_name(feature, getattr(settings, _field(feature), ""))


def selected_name(feature: str, settings) -> str:
    return validate_name(feature, getattr(settings, _field(feature), "") if settings is not None else "")


def resolve(feature: str, name: str) -> ResolvedProfile:
    """프로필 이름을 stored_key 실행 값으로 푼다. baseline의 모델은 None(기존 결정 유지)."""
    profile = load_contract()["features"][feature]["profiles"][name]
    values = profile["modes"]["stored_key"]
    baseline = name == BASELINE
    effort = profile["reasoning_effort"]
    return ResolvedProfile(
        feature=feature, name=name, status=profile["status"],
        model=None if baseline else profile["model"],
        reasoning_effort=None if effort == "default" else effort,
        timeout_seconds=values["timeout_seconds"],
        max_output_tokens=values["max_output_tokens"],
        sdk_max_retries=values.get("sdk_max_retries"),
        network_retries=values.get("network_retries", 0),
        invalid_output_retries=values.get("invalid_output_retries", 0),
        logical_deadline_seconds=values.get("logical_deadline_seconds"),
    )


def resolve_for_prompt(prompt_name: str, settings) -> ResolvedProfile:
    """구조화 호출의 프로필. 매핑 밖 프롬프트는 default_structured.baseline(상향 안 함)."""
    feature = feature_for_prompt(prompt_name)
    if feature is None:
        return resolve("default_structured", BASELINE)
    return resolve(feature, selected_name(feature, settings))


def resolve_selected(feature: str, settings) -> ResolvedProfile:
    return resolve(feature, selected_name(feature, settings))
