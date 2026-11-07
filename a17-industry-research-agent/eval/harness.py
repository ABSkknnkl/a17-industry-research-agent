"""Fail-closed terminal and gate evaluation shared by all runners."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _status(value: Any) -> str:
    text = str(getattr(value, "value", value) or "").upper()
    return text.rsplit(".", 1)[-1]


STAGE_ORDER = (
    "data_fetch",
    "data_interpret",
    "chart_generate",
    "chapter_write",
    "report_fusion",
)

_SUBGOAL_STAGE = {
    "a1_plan": "data_fetch",
    "a1_fetch": "data_fetch",
    "a2_calc": "data_interpret",
    "a3_chart": "chart_generate",
    "a4_chapter": "chapter_write",
    "a5_export": "report_fusion",
}

_PARTIAL_OUTCOMES = frozenset({"intent_plan", "tool_plan", "specialized"})

# Stops that are legitimate human-in-the-loop outcomes, not defects.  A
# partial-chain case (intent plan / retrieval plan / specialized check) that
# produces its plan and stops here has done its job honestly.
LEGITIMATE_STOP_ERRORS = frozenset(
    {"intent_clarification_required", "required_data_unavailable"}
)


def _plan_produced(stage: dict[str, Any]) -> bool:
    """Whether the stage emitted a usable intent/retrieval plan before stopping.

    A legitimate stop only counts if the artifact the case evaluates actually
    exists.  We accept a non-empty intent_routing plan map/list or a
    retrieval_plan with tasks, which is what the I/T/S checks consume.
    """
    data = stage.get("data", {}) or {}
    intent = data.get("intent_routing", {}) or {}
    plans = intent.get("plans") or intent.get("intent_plans")
    if isinstance(plans, dict) and plans:
        return True
    if isinstance(plans, list) and plans:
        return True
    retrieval = data.get("retrieval_plan", {}) or {}
    if retrieval.get("tasks"):
        return True
    return False


def target_stage_for(case: dict[str, Any]) -> str | None:
    """Deepest pipeline stage a partial-chain case needs; None = full chain.

    Full-chain (``completed``) and ``intercept`` cases return None so the
    runner drives them through the normal terminal logic.  Intent / tool-plan /
    specialized cases stop after their deepest referenced stage to conserve
    paid LLM and SkillHub calls.
    """
    if case.get("expected_outcome") not in _PARTIAL_OUTCOMES:
        return None
    stages = {
        _SUBGOAL_STAGE[goal]
        for goal in case.get("subgoals", []) or []
        if goal in _SUBGOAL_STAGE
    }
    if not stages:
        return None
    return max(stages, key=STAGE_ORDER.index)


@dataclass(frozen=True)
class TerminalGrade:
    passed: bool
    verdict: str
    reason: str


def evaluate_terminal_state(case: dict[str, Any], final: dict[str, Any]) -> TerminalGrade:
    """Evaluate terminal semantics before any quality score is allowed."""
    expected = case.get("expected_outcome", "completed")
    stage_results = final.get("stage_results", {}) or {}

    stage_errors = [
        f"{name}:{item.get('error')}"
        for name, item in stage_results.items()
        if isinstance(item, dict) and item.get("error")
    ]
    if _status(final.get("status")) == "COMPLETED" and stage_errors:
        return TerminalGrade(False, "fail", f"completed contains stage error: {stage_errors}")

    if expected == "intercept":
        wanted_stage = case.get("expected_stop_stage")
        actual_stage = str(final.get("current_stage") or "")
        if wanted_stage != actual_stage:
            return TerminalGrade(
                False,
                "fail",
                f"intercept stage mismatch: expected={wanted_stage} actual={actual_stage}",
            )
        stage = stage_results.get(actual_stage, {}) or {}
        actual_code = stage.get("error")
        allowed_codes = set(case.get("expected_error_codes", []))
        if actual_code and (not allowed_codes or actual_code in allowed_codes):
            return TerminalGrade(True, "intercept", "intercept stage and error code matched")
        # Soft intercept: a blocking collaboration request is the system's
        # designed human-in-the-loop stop (clarify caliber / scope instead of
        # fabricating data).  It is a legitimate interception even though no
        # hard error code is set, matching the V7 "或 WAITING_REVIEW 不造数"
        # branch for negative cases.
        stage_data = stage.get("data", {}) or {}
        collabs = stage_data.get("collaboration_requests", []) or []
        has_blocking_collab = any(
            (item.get("blocking") or item.get("severity") == "blocking")
            for item in collabs
            if isinstance(item, dict)
        )
        if has_blocking_collab:
            return TerminalGrade(
                True,
                "intercept",
                "intercept stage matched via blocking collaboration request (legitimate stop)",
            )
        return TerminalGrade(
            False,
            "fail",
            f"intercept error mismatch: expected={sorted(allowed_codes)} actual={actual_code}",
        )

    if expected in _PARTIAL_OUTCOMES:
        # Intent / tool-plan / specialized cases only need their target stage
        # to finish cleanly; downstream stages are not required and are not
        # driven, conserving paid provider calls.
        target = target_stage_for(case) or "data_fetch"
        stage = stage_results.get(target, {}) or {}
        if not stage:
            return TerminalGrade(
                False, "fail", f"partial-chain case never reached stage {target}"
            )
        error = stage.get("error")
        if error:
            # A legitimate human-in-the-loop stop (clarify / data-unavailable)
            # is not a defect for a partial-chain case as long as the plan it
            # is meant to produce was actually emitted.  The I/T/S checks then
            # grade the plan quality; the stop itself is the designed outcome.
            if error in LEGITIMATE_STOP_ERRORS and _plan_produced(stage):
                return TerminalGrade(
                    True,
                    "partial",
                    f"partial-chain case stopped legitimately at {target}: {error}",
                )
            return TerminalGrade(
                False,
                "fail",
                f"partial-chain case stopped with error at {target}: {error}",
            )
        if _status(stage.get("status")) not in {"COMPLETED", "APPROVED", "WAITING_REVIEW"}:
            return TerminalGrade(
                False,
                "fail",
                f"partial-chain case target stage {target} ended as {_status(stage.get('status'))}",
            )
        return TerminalGrade(
            True, "partial", f"partial-chain case completed target stage {target}"
        )

    if _status(final.get("status")) != "COMPLETED":
        return TerminalGrade(False, "fail", f"positive case ended as {_status(final.get('status'))}")

    fusion = stage_results.get("report_fusion", {}) or {}
    artifacts = fusion.get("artifacts", []) or []
    if not artifacts:
        return TerminalGrade(False, "fail", "已完成的正向用例缺少报告产物")

    required = set(
        (case.get("expected_stages", {}).get("agent5", {}) or {}).get(
            "required_artifacts", []
        )
    )
    if required:
        actual = {str(item.get("kind", "")).lower() for item in artifacts if isinstance(item, dict)}
        aliases = {
            "md": "markdown",
            "pdf": "pdf",
            "html": "html",
            "manifest": "manifest",
            "report_markdown": "markdown",
            "report_html": "html",
            "report_pdf": "pdf",
            "artifact_manifest": "manifest",
        }
        actual |= {aliases.get(item, item) for item in actual}
        missing = required - actual
        if missing:
            return TerminalGrade(False, "fail", f"missing report artifacts: {sorted(missing)}")
    return TerminalGrade(True, "pass", "completed with report artifacts")


def build_gate_record(
    case: dict[str, Any],
    *,
    check_results: list[dict[str, Any]],
    reached_subgoals: list[str],
) -> dict[str, Any]:
    """Consume must_pass/veto/subgoals and materialise an auditable gate."""
    failed = {item["check_id"] for item in check_results if not item.get("passed", False)}
    veto_hit = sorted(failed & set(case.get("veto", [])))
    missing_subgoals = [
        item for item in case.get("subgoals", []) if item not in set(reached_subgoals)
    ]
    must_pass = bool(case.get("must_pass", False))
    blocked = bool(veto_hit or missing_subgoals or (must_pass and failed))
    return {
        "must_pass": must_pass,
        "veto_hit": veto_hit,
        "missing_subgoals": missing_subgoals,
        "failed_checks": sorted(failed),
        "gate": "BLOCK" if blocked else "PASS",
    }
