from __future__ import annotations

from eval.harness import evaluate_terminal_state
from eval.provider_mode import ProviderModeError, validate_provider_identity
from eval.scorers.rules import run_l1_checks


def _positive_case(**overrides):
    case = {
        "id": "E-X",
        "expected_outcome": "completed",
        "checks": [],
        "veto": [],
        "must_pass": True,
        "subgoals": ["a1_fetch", "a2_calc", "a5_export"],
    }
    case.update(overrides)
    return case


def test_f0_01_unregistered_check_fails_closed() -> None:
    result = run_l1_checks({}, {}, checks=["NOT_IMPLEMENTED"])
    assert len(result) == 1
    assert result[0].passed is False
    assert "未注册" in result[0].reason or "未实现" in result[0].reason


def test_f0_02_completed_with_stage_error_fails() -> None:
    grade = evaluate_terminal_state(
        _positive_case(),
        {
            "status": "COMPLETED",
            "stage_results": {
                "data_fetch": {"status": "COMPLETED", "error": "provider_unavailable"},
                "report_fusion": {"status": "COMPLETED", "error": None, "artifacts": [{"kind": "markdown"}]},
            },
        },
    )
    assert grade.passed is False
    assert "error" in grade.reason


def test_f0_03_completed_without_report_artifacts_fails() -> None:
    grade = evaluate_terminal_state(
        _positive_case(),
        {
            "status": "COMPLETED",
            "stage_results": {
                "data_fetch": {"status": "COMPLETED", "error": None},
                "report_fusion": {"status": "COMPLETED", "error": None, "artifacts": []},
            },
        },
    )
    assert grade.passed is False
    assert "产物" in grade.reason


def test_f0_04_positive_case_intercept_is_not_success() -> None:
    grade = evaluate_terminal_state(
        _positive_case(),
        {
            "status": "WAITING_REVIEW",
            "current_stage": "data_fetch",
            "stage_results": {"data_fetch": {"status": "WAITING_REVIEW", "error": "no_data"}},
        },
    )
    assert grade.passed is False
    assert grade.verdict == "fail"


def test_f0_05_negative_case_requires_exact_stage_and_error_code() -> None:
    case = _positive_case(
        expected_outcome="intercept",
        expected_stop_stage="data_interpret",
        expected_error_codes=["requested_calculation_data_unavailable"],
    )
    wrong = evaluate_terminal_state(
        case,
        {
            "status": "WAITING_REVIEW",
            "current_stage": "data_fetch",
            "stage_results": {"data_fetch": {"status": "WAITING_REVIEW", "error": "no_data"}},
        },
    )
    right = evaluate_terminal_state(
        case,
        {
            "status": "WAITING_REVIEW",
            "current_stage": "data_interpret",
            "stage_results": {
                "data_fetch": {"status": "COMPLETED", "error": None},
                "data_interpret": {
                    "status": "WAITING_REVIEW",
                    "error": "requested_calculation_data_unavailable",
                },
            },
        },
    )
    assert wrong.passed is False
    assert right.passed is True
    assert right.verdict == "intercept"


def test_f0_06_provider_mode_cannot_hide_mock_implementation() -> None:
    try:
        validate_provider_identity(
            declared_mode="live",
            implementation_path="app.integrations.skillhub.mock.MockSkillHubClient",
        )
    except ProviderModeError as exc:
        assert "mock" in str(exc).lower()
    else:
        raise AssertionError("伪 live provider 未被 fail-closed 拒绝")
