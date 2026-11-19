#!/usr/bin/env python3
"""기능별 LLM 프로필 계약의 무료·오프라인 검사기.

`docs/plans/llm-model-profiles.contract.json`을 읽어 다음만 확인한다. 네트워크·API 키·DB·LLM 호출은 없다.
1. 계약 자체: 허용 모델/노력치 조합, 금지 노력치(high/xhigh/max 등), 비밀 필드 없음, 필수 baseline·명시 복귀 프로필.
2. 현재 코드와 baseline 대조: 계약에 적은 기준값이 실제 소스에 그대로 있는지(어긋나면 오류).
3. 기한 계층 산식: 프로필별 최악 소요·큐 기한·프로토콜 상한·임대 대비 여유(측정값이 아니라 산술이다).
4. 실패 처리 기준 구현(reference): 시간 초과 뒤 다른 모델 자동 호출 금지, 지연 결과 차단.

운영 코드(`app/llm/profiles.py`)는 계약 JSON을 직접 읽고, 이 검사기는 그 계약이 규칙을 지키는지만 본다.
manual_upgrade(결정 2a)는 환경변수로 명시했을 때만 쓰는 수동 상향이며 품질 승인이 아니다.
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO / "docs/plans/llm-model-profiles.contract.json"
STATUSES = {"baseline", "explicit_return", "candidate", "measurement_prep", "approved", "manual_upgrade"}
SELECTABLE = {"baseline", "explicit_return", "approved", "manual_upgrade"}
# 서버 설정 필드가 있는(운영에서 고를 수 있는) 기능. catalog_candidates는 기능 미구현, mail_gate는 고정.
RUNTIME_SELECTABLE_FEATURES = ("default_structured", "trade_extraction", "vision_transcription")
REQUIRED_FEATURES = {"default_structured", "trade_extraction", "catalog_candidates", "vision_transcription", "mail_gate"}
SECRET_WORDS = {"key", "token", "secret", "password", "credential", "authorization", "apikey"}
EXECUTION_MODE_NAMES = {"stored_key", "local_worker"}  # 기존 ai_execution_mode 열거값(비밀 필드가 아님)
SECRET_VALUE = re.compile(r"sk-[A-Za-z0-9_-]{8,}")
ERROR_KINDS = {"timeout", "network", "rate_limit", "invalid_output", "incomplete_output",
               "grounding_failed", "access_denied", "invalid_input", "internal"}


def load_contract(path: Path = CONTRACT_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _walk(value, path=""):
    if isinstance(value, dict):
        for key, child in value.items():
            yield f"{path}/{key}", key, child
            yield from _walk(child, f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def validate_contract(contract: dict) -> list[str]:
    errors: list[str] = []
    forbidden = contract["forbidden"]
    models, allowed = contract["models"], contract["allowed_models_by_feature"]
    limits = contract["limits"]
    features = contract["features"]
    if set(features) != REQUIRED_FEATURES:
        errors.append(f"기능 키가 다릅니다: {sorted(set(features) ^ REQUIRED_FEATURES)}")

    # 비밀 필드·값 금지. forbidden.secret_field_name_patterns 자체(목록 설명)는 제외한다.
    for path, key, child in _walk(contract):
        if path.startswith("/forbidden/") or path == "/forbidden":
            continue
        words = set(re.split(r"[_\-\s]+", str(key).lower()))
        if key not in EXECUTION_MODE_NAMES and words & SECRET_WORDS:
            errors.append(f"비밀 이름으로 보이는 필드: {path}")
        if isinstance(child, str) and SECRET_VALUE.search(child):
            errors.append(f"비밀 값으로 보이는 문자열: {path}")

    seen_prompts: dict[str, str] = {}
    for feature, spec in features.items():
        for prompt_id in spec.get("prompt_ids", []):
            if prompt_id in seen_prompts:
                errors.append(f"프롬프트 {prompt_id}가 {seen_prompts[prompt_id]}와 {feature}에 모두 있습니다")
            seen_prompts[prompt_id] = feature
        modes_allowed = set(spec["execution_modes"])
        if "local_worker" in modes_allowed and not spec.get("prompt_ids"):
            errors.append(f"{feature}: 설치 프롬프트 없이 local_worker를 허용할 수 없습니다")
        profiles = spec["profiles"]
        if feature != "mail_gate" and not any(
                p["model"] == "gpt-6-luna" and p["reasoning_effort"] == "medium" and p["model_source"] == "fixed"
                for p in profiles.values()):
            errors.append(f"{feature}: 명시 복귀용 gpt-6-luna medium(고정 모델) 프로필이 없습니다")
        if feature not in {"catalog_candidates"} and "baseline" not in profiles:
            errors.append(f"{feature}: baseline 프로필이 없습니다")
        for name, profile in profiles.items():
            where = f"{feature}.{name}"
            status, model, effort = profile["status"], profile["model"], profile["reasoning_effort"]
            if status not in STATUSES:
                errors.append(f"{where}: 알 수 없는 status {status}")
            if model not in models or model not in allowed.get(feature, []):
                errors.append(f"{where}: 허용되지 않은 모델 {model}")
            elif effort not in models[model]["efforts"]:
                errors.append(f"{where}: {model}에 허용되지 않은 노력치 {effort}")
            if effort in forbidden["efforts"]:
                errors.append(f"{where}: 금지 노력치 {effort}")
            if status == "baseline" and (model != "gpt-6-luna" or effort != "default"):
                errors.append(f"{where}: baseline은 gpt-6-luna/default여야 합니다")
            if status == "explicit_return" and (model != "gpt-6-luna" or effort != "medium" or profile["model_source"] != "fixed"):
                errors.append(f"{where}: 명시 복귀는 고정 gpt-6-luna medium이어야 합니다")
            if status == "manual_upgrade":
                if feature not in RUNTIME_SELECTABLE_FEATURES:
                    errors.append(f"{where}: manual_upgrade는 {RUNTIME_SELECTABLE_FEATURES}에만 둘 수 있습니다")
                if set(profile["modes"]) != {"stored_key"}:
                    errors.append(f"{where}: manual_upgrade는 stored_key 경로만 가집니다(PC는 baseline 유지)")
                for mode_values in profile["modes"].values():
                    if mode_values.get("network_retries", 0) or mode_values.get("invalid_output_retries", 0):
                        errors.append(f"{where}: manual_upgrade는 자동 재시도 0이어야 합니다")
            if status in {"candidate", "measurement_prep", "manual_upgrade"} and not profile.get("values_origin"):
                errors.append(f"{where}: 후보 값의 출처·미검증 표시(values_origin)가 없습니다")
            if status in {"candidate", "measurement_prep"} and status in SELECTABLE:
                errors.append(f"{where}: 후보가 운영 선택 가능 상태입니다")
            unresolved = set(profile.get("unresolved", []))
            known = set()
            for mode, values in profile["modes"].items():
                if mode not in modes_allowed:
                    errors.append(f"{where}: {mode}는 {feature}가 지원하지 않는 실행 방식입니다")
                known |= set(values)
                timeout, cap = values["timeout_seconds"], values["max_output_tokens"]
                if not isinstance(timeout, int) or not 1 <= timeout <= limits["timeout_seconds_max"]:
                    errors.append(f"{where}.{mode}: timeout_seconds 범위 오류")
                if cap is not None and (not isinstance(cap, int) or not 1 <= cap <= limits["max_output_tokens_max"]):
                    errors.append(f"{where}.{mode}: max_output_tokens 범위 오류")
                sdk = values.get("sdk_max_retries")
                if sdk is not None and (not isinstance(sdk, int) or sdk < 0):
                    errors.append(f"{where}.{mode}: sdk_max_retries 오류")
                if mode == "local_worker" and not isinstance(values.get("queue_deadline_seconds"), int):
                    errors.append(f"{where}.{mode}: queue_deadline_seconds가 필요합니다")
            if unresolved - known:
                errors.append(f"{where}: unresolved에 없는 필드 {sorted(unresolved - known)}")
            if status in SELECTABLE and unresolved:
                errors.append(f"{where}: 운영 선택 가능 프로필에 미정 필드가 있습니다")

    selection = contract["selection"]
    if set(selection["config_names"]) != REQUIRED_FEATURES - {"mail_gate"}:
        errors.append("selection.config_names가 네 기능 키와 다릅니다")
    if set(selection["production_selectable_statuses"]) & {"candidate", "measurement_prep"}:
        errors.append("selection.production_selectable_statuses에 후보 상태가 있습니다")
    if not selection.get("never_auto_promote"):
        errors.append("후보 자동 승격 금지(never_auto_promote)가 꺼져 있습니다")
    if not forbidden.get("automatic_cross_model_fallback_after_timeout"):
        errors.append("시간 초과 뒤 다른 모델 자동 호출 금지가 꺼져 있습니다")
    return errors


def _read(repo: Path, relative: str) -> str:
    return (repo / relative).read_text(encoding="utf-8")


def check_code_facts(contract: dict, repo: Path = REPO) -> list[str]:
    """계약의 baseline 근거 문자열이 실제 소스에 있는지, 그리고 baseline 프로필 값과 같은지 본다."""
    errors: list[str] = []
    facts = contract["baseline_code_facts"]
    for name, fact in facts.items():
        try:
            text = _read(repo, fact["file"])
        except OSError:
            errors.append(f"{name}: {fact['file']}을 읽지 못했습니다")
            continue
        if fact["pattern"] not in text:
            errors.append(f"{name}: {fact['file']}에서 `{fact['pattern']}`를 찾지 못했습니다(코드가 바뀌었거나 계약이 낡음)")

    def value(name):
        return facts[name]["value"]

    features = contract["features"]
    for feature in ("default_structured", "trade_extraction"):
        base = features[feature]["profiles"]["baseline"]["modes"]
        server, pc = base["stored_key"], base["local_worker"]
        expected = {
            "server timeout": (server["timeout_seconds"], value("llm_timeout_seconds")),
            "server network retries": (server["network_retries"], value("llm_max_retries")),
            "server invalid_output retries": (server["invalid_output_retries"], value("llm_invalid_output_retries")),
            "pc timeout": (pc["timeout_seconds"], value("llm_timeout_seconds")),
            "pc max_output_tokens": (pc["max_output_tokens"], value("pc_default_max_output_tokens")),
            "pc queue deadline": (pc["queue_deadline_seconds"], value("queue_deadline_seconds_adapter")),
        }
        for label, (got, want) in expected.items():
            if got != want:
                errors.append(f"{feature}.baseline {label}: 계약 {got} ≠ 코드 {want}")
    if len({value("queue_deadline_seconds_adapter"), value("queue_deadline_seconds_service"),
            value("queue_deadline_seconds_protocol_cap")}) != 1:
        errors.append("큐 기한 상수(adapter/service/protocol)가 서로 다릅니다")
    vision = features["vision_transcription"]["profiles"]["baseline"]["modes"]["stored_key"]
    for label, got, want in (("timeout", vision["timeout_seconds"], value("vision_timeout_seconds")),
                             ("sdk retries", vision["sdk_max_retries"], value("vision_sdk_max_retries")),
                             ("max_output_tokens", vision["max_output_tokens"], value("vision_max_output_tokens"))):
        if got != want:
            errors.append(f"vision_transcription.baseline {label}: 계약 {got} ≠ 코드 {want}")
    gate = features["mail_gate"]["profiles"]["baseline"]
    if gate["model"] != value("mail_gate_model") or gate["modes"]["stored_key"]["timeout_seconds"] != value("mail_gate_timeout_seconds"):
        errors.append("mail_gate baseline이 코드와 다릅니다")

    # 설치된 프롬프트 이름과 계약 매핑이 같은지: 새 프롬프트가 생기면 프로필 기능을 정해야 한다.
    names = set()
    for path in (repo / "app/prompts").glob("*.py"):
        names |= set(re.findall(r'^NAME\s*=\s*"([^"]+)"', path.read_text(encoding="utf-8"), re.M))
    for path in (repo / "app/trade").glob("*/agent.py"):
        names |= set(re.findall(r'Prompt\("([^"]+)"', path.read_text(encoding="utf-8")))
    mapped = {p for f in ("default_structured", "trade_extraction") for p in features[f]["prompt_ids"]}
    if names != mapped:
        errors.append(f"프롬프트 이름 불일치. 코드에만: {sorted(names - mapped)}, 계약에만: {sorted(mapped - names)}")

    # 서버 설정 필드(get_settings가 대문자 환경변수로 읽는다)가 계약의 설정 이름과 같은지.
    config_source = _read(repo, "app/config.py")
    for feature in RUNTIME_SELECTABLE_FEATURES:
        field = contract["selection"]["config_names"][feature].lower()
        if not re.search(rf"^\s+{field}: str = \"\"", config_source, re.M):
            errors.append(f"app/config.py Settings에 {field} 필드가 없습니다")
    return errors


def _backoff(retries: int) -> int:
    """기존 network 재시도 대기(1, 2초 …)의 합."""
    return 2 ** retries - 1 if retries else 0


def deadline_report(contract: dict) -> list[dict]:
    facts = contract["baseline_code_facts"]
    cap = facts["queue_deadline_seconds_protocol_cap"]["value"]
    margin = contract["deadline_layers"]["claim_margin_seconds"]
    lease = facts["knowledge_lease_seconds"]["value"]
    duration_cap = facts["result_duration_ms_cap"]["value"] / 1000
    rows = []
    for feature, spec in contract["features"].items():
        for name, profile in spec["profiles"].items():
            for mode, v in profile["modes"].items():
                timeout = v["timeout_seconds"]
                sdk = v.get("sdk_max_retries")
                sdk_assumed = sdk is None
                calls = 1 + (3 if sdk_assumed else sdk)
                retries = v.get("network_retries", 0) + v.get("invalid_output_retries", 0)
                attempts = 1 + retries
                worst = attempts * calls * timeout + _backoff(v.get("network_retries", 0))
                row = {"profile": f"{feature}.{name}", "status": profile["status"], "mode": mode,
                       "timeout_s": timeout, "max_output_tokens": v["max_output_tokens"],
                       "worst_case_provider_s": worst, "notes": [],
                       "sdk_retries_assumed_3": sdk_assumed}
                if sdk_assumed:
                    row["notes"].append("sdk_max_retries 미정: 보수적으로 3회로 계산")
                if mode == "stored_key":
                    deadline = v.get("logical_deadline_seconds")
                    row["deadline_s"] = deadline
                    if deadline is None and feature != "vision_transcription":
                        row["notes"].append(f"논리 기한 없음: HTTP 요청이 최대 {worst}초까지 길어질 수 있음")
                    elif deadline is not None and timeout > deadline:
                        row["notes"].append("시도 1회 timeout이 논리 기한보다 큼")
                    elif deadline is not None and worst > deadline:
                        row["notes"].append("논리 기한 안에서 재시도 예산을 모두 쓸 수 없음(재시도 축소)")
                    if feature == "vision_transcription":
                        row["pages_within_lease_worst_case"] = lease // worst if worst else None
                        row["notes"].append(f"페이지당 최악 {worst}초(SDK 백오프 제외) → 1시간 임대 안 최악 {lease // worst}페이지")
                else:
                    deadline = v["queue_deadline_seconds"]
                    row["deadline_s"] = deadline
                    need_one = timeout + margin
                    need_full = worst + margin
                    row["required_min_queue_s"], row["required_full_queue_s"] = need_one, need_full
                    row["protocol_cap_s"] = cap
                    if need_one > cap:
                        row["verdict"] = "blocked_by_protocol_cap"
                    elif deadline < need_one:
                        row["verdict"] = "deadline_below_single_attempt"
                    elif deadline == need_one and retries == 0 and need_one == cap:
                        row["verdict"] = "feasible_zero_slack_no_retry"
                    elif deadline < need_full:
                        row["verdict"] = "retry_budget_not_fully_usable"
                    else:
                        row["verdict"] = "ok"
                    if deadline > cap:
                        row["verdict"] = "blocked_by_protocol_cap"
                    if timeout != facts["llm_timeout_seconds"]["value"]:
                        row["notes"].append("PC 실행기의 최소 잔여 기한(현재 상수 20초)과 시도 timeout을 프로필 값으로 연동해야 함")
                    if timeout > duration_cap:
                        row["notes"].append("성공 응답 duration_ms 상한 30000ms에서 실제 시간이 잘림(진단 정보 손실)")
                rows.append(row)
    return rows


def blocked_selectable(rows: list[dict]) -> list[str]:
    """운영에서 선택 가능한 상태(baseline/명시 복귀)인데 막히는 조합."""
    return [f"{r['profile']}/{r['mode']}: {r['verdict']}" for r in rows
            if r["status"] in SELECTABLE and r.get("verdict") not in (None, "ok")]


# ---- 실패 처리 기준 구현(reference). 운영 코드가 아니라 계약의 실행 가능한 명세다. ----

def route_failure(contract: dict, *, feature: str, profile_id: str, mode: str, error_kind: str,
                  retries_used: dict | None = None, explicit_profile_choice: str | None = None) -> dict:
    """실패 뒤 다음 동작. 다른 모델/프로필은 사용자의 명시적 선택으로만 새 시도(새 revision)가 된다."""
    if error_kind not in ERROR_KINDS:
        raise ValueError(error_kind)
    profiles = contract["features"][feature]["profiles"]
    if explicit_profile_choice is not None:
        target = profiles.get(explicit_profile_choice)
        if target is None or mode not in target["modes"]:
            return {"action": "reject_choice", "new_attempt": False, "replay_side_effects": False}
        if target["status"] not in SELECTABLE and target["status"] not in {"candidate", "measurement_prep"}:
            return {"action": "reject_choice", "new_attempt": False, "replay_side_effects": False}
        return {"action": "new_attempt_new_revision", "profile": explicit_profile_choice,
                "sum_costs_of_previous_attempts": True, "new_attempt": True, "replay_side_effects": False}
    profile = profiles[profile_id]
    values = profile["modes"][mode]
    used = retries_used or {}
    retriable = {"network": values.get("network_retries", 0), "invalid_output": values.get("invalid_output_retries", 0)}
    # baseline은 기존 동작을 보존한다: 시간 초과가 network로 분류되어 같은 모델 재시도 예산을 쓴다.
    if error_kind == "timeout" and profile["status"] == "baseline":
        error_kind = "network"
    if error_kind in retriable and used.get(error_kind, 0) < retriable[error_kind]:
        return {"action": "retry_same_profile_new_attempt", "profile": profile_id, "new_attempt": True,
                "replay_side_effects": False}
    return {"action": "preserve_input_and_stop", "profile": profile_id, "new_attempt": False,
            "other_model_called": False, "replay_side_effects": False}


def accept_result(current: dict, incoming: dict) -> bool:
    """지연 결과 차단: 현재 attempt·input revision·profile이 모두 같고 취소/만료가 아닐 때만 적용한다."""
    if current.get("cancelled") or current.get("expired"):
        return False
    return all(incoming.get(k) == current.get(k) for k in ("work_unit_id", "attempt_id", "revision", "profile_id"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=str(REPO), help="코드를 읽을 저장소 경로(읽기 전용)")
    parser.add_argument("--contract", default=str(CONTRACT_PATH))
    parser.add_argument("--json", action="store_true", help="기한 산식 표를 JSON으로 출력")
    args = parser.parse_args(argv)
    contract = load_contract(Path(args.contract))
    repo = Path(args.repo)
    errors = validate_contract(contract) + check_code_facts(contract, repo)
    rows = deadline_report(contract)
    blocked = blocked_selectable(rows)
    errors += [f"운영 선택 가능 프로필이 막힘: {b}" for b in blocked]
    if args.json:
        print(json.dumps({"errors": errors, "deadline": rows}, ensure_ascii=False, indent=2))
    else:
        print(f"계약 v{contract['contract_version']} ({contract['status']}) · 코드 기준 {repo}")
        for row in rows:
            extra = row.get("verdict") or ""
            print(f"- {row['profile']:<42} {row['mode']:<12} T={row['timeout_s']:>3}s cap={row['max_output_tokens']} "
                  f"최악={row['worst_case_provider_s']}s {extra}")
            for note in row["notes"]:
                print(f"    · {note}")
        print("오류 없음" if not errors else "오류:\n" + "\n".join(f"  ✗ {e}" for e in errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
