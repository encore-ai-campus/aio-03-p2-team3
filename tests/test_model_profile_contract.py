"""기능별 LLM 프로필 계약의 무료 검사. 네트워크·키·DB를 쓰지 않는다.

운영 코드는 아직 이 계약을 읽지 않는다. 이 검사는 계약 파일이 금지 조건을 지키는지,
현재 소스의 baseline과 어긋나지 않는지, 기한 산식이 막히는 조합을 알려 주는지만 확인한다.
"""
import copy
import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_model_profile_contract", ROOT / "scripts/check_model_profile_contract.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@pytest.fixture()
def contract():
    return copy.deepcopy(checker.load_contract())


def test_committed_contract_is_valid_and_matches_current_baseline_code(contract):
    assert checker.validate_contract(contract) == []
    assert checker.check_code_facts(contract) == []
    assert checker.blocked_selectable(checker.deadline_report(contract)) == []


@pytest.mark.parametrize("effort", ["high", "xhigh", "max", "none"])
def test_forbidden_efforts_are_rejected(contract, effort):
    contract["features"]["trade_extraction"]["profiles"]["sol-medium"]["reasoning_effort"] = effort
    assert any("노력치" in e for e in checker.validate_contract(contract))


def test_model_effort_pairs_are_limited_to_the_allowed_combinations(contract):
    # Terra는 low만, Sol은 medium만, 일반 구조화에는 Luna만 허용한다.
    contract["features"]["vision_transcription"]["profiles"]["terra-low"]["reasoning_effort"] = "medium"
    assert any("terra" in e.lower() or "노력치" in e for e in checker.validate_contract(contract))
    contract = checker.load_contract()
    contract["features"]["default_structured"]["profiles"]["luna-medium"]["model"] = "gpt-6.1-sol"
    assert any("허용되지 않은" in e for e in checker.validate_contract(contract))


def test_secret_like_fields_and_values_are_rejected(contract):
    contract["features"]["trade_extraction"]["profiles"]["sol-medium"]["api_key"] = "x"
    contract["features"]["trade_extraction"]["profiles"]["sol-medium"]["values_origin"] = "sk-abcdefgh12345678"
    errors = checker.validate_contract(contract)
    assert any("비밀 이름" in e for e in errors) and any("비밀 값" in e for e in errors)


def test_candidates_cannot_be_production_selectable_or_have_unresolved_baseline(contract):
    contract["selection"]["production_selectable_statuses"].append("candidate")
    assert any("후보 상태" in e for e in checker.validate_contract(contract))
    contract = checker.load_contract()
    contract["features"]["vision_transcription"]["profiles"]["baseline"]["unresolved"] = ["timeout_seconds"]
    assert any("미정 필드" in e for e in checker.validate_contract(contract))


def test_explicit_luna_medium_return_target_is_required_and_fixed(contract):
    contract["features"]["trade_extraction"]["profiles"]["luna-medium"]["model_source"] = "legacy_env:OPENAI_MODEL"
    errors = checker.validate_contract(contract)
    assert any("명시 복귀" in e for e in errors)


def test_drift_between_contract_and_source_is_detected(tmp_path, contract):
    for fact in contract["baseline_code_facts"].values():
        target = tmp_path / fact["file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy(ROOT / fact["file"], target)
    shutil.copytree(ROOT / "app/prompts", tmp_path / "app/prompts", dirs_exist_ok=True)
    for agent in (ROOT / "app/trade").glob("*/agent.py"):
        destination = tmp_path / agent.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(agent, destination)
    assert checker.check_code_facts(contract, tmp_path) == []
    pc = tmp_path / "app/worker/pc.py"
    pc.write_text(pc.read_text(encoding="utf-8").replace("max_output_tokens: int = 2048", "max_output_tokens: int = 4096"), encoding="utf-8")
    assert any("pc_default_max_output_tokens" in e for e in checker.check_code_facts(contract, tmp_path))


def test_new_prompt_without_profile_mapping_is_detected(tmp_path, contract):
    for fact in contract["baseline_code_facts"].values():
        target = tmp_path / fact["file"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy(ROOT / fact["file"], target)
    shutil.copytree(ROOT / "app/prompts", tmp_path / "app/prompts", dirs_exist_ok=True)
    for agent in (ROOT / "app/trade").glob("*/agent.py"):
        destination = tmp_path / agent.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(agent, destination)
    (tmp_path / "app/prompts/new_feature.py").write_text('NAME = "new_feature"\n', encoding="utf-8")
    assert any("new_feature" in e for e in checker.check_code_facts(contract, tmp_path))


def test_deadline_arithmetic_marks_candidate_pc_profile_and_keeps_baseline_ok(contract):
    rows = {(r["profile"], r["mode"]): r for r in checker.deadline_report(contract)}
    assert rows[("trade_extraction.baseline", "local_worker")]["verdict"] == "ok"
    sol = rows[("trade_extraction.sol-medium", "local_worker")]
    assert sol["verdict"] == "feasible_zero_slack_no_retry"
    assert sol["required_min_queue_s"] == 120 == sol["protocol_cap_s"]
    assert any("30000" in n for n in sol["notes"])
    contract["features"]["trade_extraction"]["profiles"]["sol-medium"]["modes"]["local_worker"]["queue_deadline_seconds"] = 150
    rows = {(r["profile"], r["mode"]): r for r in checker.deadline_report(contract)}
    assert rows[("trade_extraction.sol-medium", "local_worker")]["verdict"] == "blocked_by_protocol_cap"


def test_baseline_server_path_has_no_logical_deadline_and_vision_lease_is_bounded(contract):
    rows = {(r["profile"], r["mode"]): r for r in checker.deadline_report(contract)}
    server = rows[("trade_extraction.baseline", "stored_key")]
    assert server["worst_case_provider_s"] == 4 * 20 + 1 + 2  # 시도 4회 + 백오프 1·2초
    assert server["deadline_s"] is None
    vision = rows[("vision_transcription.baseline", "stored_key")]
    assert vision["worst_case_provider_s"] == 4 * 180
    assert vision["pages_within_lease_worst_case"] == 5


def test_timeout_never_calls_another_model_automatically(contract):
    for feature, profile, mode in (("trade_extraction", "sol-medium", "local_worker"),
                                   ("vision_transcription", "terra-low", "stored_key"),
                                   ("catalog_candidates", "sol-medium", "stored_key")):
        action = checker.route_failure(contract, feature=feature, profile_id=profile, mode=mode, error_kind="timeout")
        assert action["action"] == "preserve_input_and_stop"
        assert action["new_attempt"] is False and action["other_model_called"] is False
        assert action["replay_side_effects"] is False


def test_other_profile_requires_explicit_choice_and_counts_previous_cost(contract):
    action = checker.route_failure(contract, feature="trade_extraction", profile_id="sol-medium", mode="local_worker",
                                   error_kind="invalid_output", explicit_profile_choice="luna-medium")
    assert action["action"] == "new_attempt_new_revision" and action["profile"] == "luna-medium"
    assert action["sum_costs_of_previous_attempts"] is True and action["replay_side_effects"] is False
    missing = checker.route_failure(contract, feature="vision_transcription", profile_id="baseline", mode="stored_key",
                                    error_kind="timeout", explicit_profile_choice="no-such-profile")
    assert missing["action"] == "reject_choice"


def test_baseline_keeps_legacy_same_model_retry_but_candidate_does_not(contract):
    legacy = checker.route_failure(contract, feature="trade_extraction", profile_id="baseline", mode="stored_key", error_kind="timeout")
    assert legacy["action"] == "retry_same_profile_new_attempt" and legacy["new_attempt"] is True
    exhausted = checker.route_failure(contract, feature="trade_extraction", profile_id="baseline", mode="stored_key",
                                      error_kind="network", retries_used={"network": 2})
    assert exhausted["action"] == "preserve_input_and_stop"


def test_late_or_superseded_results_are_not_applied():
    current = {"work_unit_id": "w1", "attempt_id": "a2", "revision": 3, "profile_id": "trade_extraction.sol-medium"}
    assert checker.accept_result(current, dict(current))
    for key, value in (("attempt_id", "a1"), ("revision", 2), ("profile_id", "trade_extraction.luna-medium"), ("work_unit_id", "w2")):
        assert not checker.accept_result(current, {**current, key: value})
    assert not checker.accept_result({**current, "cancelled": True}, dict(current))
    assert not checker.accept_result({**current, "expired": True}, dict(current))
