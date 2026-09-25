from __future__ import annotations

from eval.case_schema import (
    apply_synthetic_override,
    inject_trajectory,
    load_case_suite,
    validate_case_suite,
)
from eval.harness import build_gate_record
from eval.scorers.rules import registered_check_ids


def test_f0_07_all_101_cases_and_declarations_are_registered() -> None:
    cases = load_case_suite()
    errors = validate_case_suite(cases, registered_checks=registered_check_ids())
    assert len(cases) == 101
    assert errors == []


def test_f0_08_gate_fields_are_consumed_by_runner_record() -> None:
    case = {
        "id": "E-X",
        "must_pass": True,
        "veto": ["P2"],
        "subgoals": ["a1_fetch", "a2_calc"],
    }
    record = build_gate_record(
        case,
        check_results=[{"check_id": "P2", "passed": False, "reason": "broken"}],
        reached_subgoals=["a1_fetch"],
    )
    assert record["must_pass"] is True
    assert record["veto_hit"] == ["P2"]
    assert record["missing_subgoals"] == ["a2_calc"]
    assert record["gate"] == "BLOCK"


def test_f0_09_synthetic_overrides_for_t05_and_t06_are_effective() -> None:
    plan = {"tasks": [{"skill_name": "hithink_finance_query", "query": "宁德时代营收"}]}
    duplicated = apply_synthetic_override("duplicate_query", plan)
    expanded = apply_synthetic_override("over_30_tasks", plan)
    assert len(duplicated["tasks"]) == 2
    assert len(expanded["tasks"]) > 30
    assert plan["tasks"] != duplicated["tasks"]


def test_f0_10_t12_trajectory_injector_creates_wrong_then_correct_route() -> None:
    events = inject_trajectory(
        "wrong_then_correct_skill",
        required_skill="hithink_stock_selector",
        wrong_skill="hithink_finance_query",
    )
    assert [event["skill"] for event in events] == [
        "hithink_finance_query",
        "hithink_stock_selector",
    ]
    assert events[0]["sequence"] < events[1]["sequence"]
