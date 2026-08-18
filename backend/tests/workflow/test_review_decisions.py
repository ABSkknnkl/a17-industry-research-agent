"""Regression tests for server-bound human review decisions."""

from typing import Any

import pytest

import app.workflow.graph as graph_module
from app.schemas.decision import (
    DecisionPackage,
    DecisionStatus,
    RiskDisposition,
    RiskNotice,
    RiskSeverity,
    compute_risk_snapshot_sha256,
)
from app.schemas.workflow import StageName, StageResult, StageStatus
from app.workflow.state import PipelineGraphState, create_pipeline_state


def _package(
    *,
    run_id: str,
    stage: StageName,
    recommended: list[str] | None = None,
    acknowledgement_required: bool = False,
) -> dict[str, Any]:
    notices: list[RiskNotice] = []
    required_codes: list[str] = []
    if acknowledgement_required:
        required_codes = ["REPORT-QUALITY-ADVISORY"]
        notices = [
            RiskNotice(
                risk_code=required_codes[0],
                stage=stage.value,
                severity=RiskSeverity.HIGH,
                disposition=RiskDisposition.ACKNOWLEDGEMENT_REQUIRED,
                title="需要人工确认",
                detail="存在可接受的专业风险",
                recommendation="仅导出带警示的内部草稿",
                consequence="未确认时不得导出",
                can_override=True,
            )
        ]
    snapshot = compute_risk_snapshot_sha256(
        risk_notices=notices,
        blocking_risk_codes=[],
        acknowledgement_required_codes=required_codes,
    )
    return DecisionPackage(
        decision_id=f"DEC-{run_id}",
        run_id=run_id,
        stage=stage.value,
        revision=1,
        recommended_selection=recommended or [],
        risk_notices=notices,
        blocking_risk_codes=[],
        acknowledgement_required_codes=required_codes,
        decision_status=(
            DecisionStatus.AWAITING_USER if required_codes else DecisionStatus.NOT_REQUIRED
        ),
        risk_snapshot_sha256=snapshot,
    ).model_dump(mode="json")


def _state(stage: StageName, data: dict[str, Any], *, run_id: str) -> PipelineGraphState:
    state = create_pipeline_state(project_id="project", run_id=run_id, input_data={})
    state["current_stage"] = stage
    state["status"] = StageStatus.WAITING_REVIEW
    state["stage_results"] = {
        stage.value: StageResult(
            stage=stage,
            status=StageStatus.WAITING_REVIEW,
            revision=1,
            data=data,
        ).model_dump(mode="json")
    }
    return state


def test_decision_package_requires_server_decision_id_and_snapshot(monkeypatch) -> None:
    run_id = "run-secure-decision"
    package = _package(
        run_id=run_id,
        stage=StageName.CHART_GENERATE,
        recommended=["CHART-001"],
    )
    state = _state(
        StageName.CHART_GENERATE,
        {
            "charts": [{"chart_id": "CHART-001"}],
            "decision_package": package,
        },
        run_id=run_id,
    )
    monkeypatch.setattr(
        graph_module,
        "interrupt",
        lambda _: {"action": "accept_recommendation", "expected_revision": 1},
    )

    with pytest.raises(ValueError, match="decision_id is required"):
        graph_module._review_gate(state)


def test_accept_recommendation_propagates_recommended_chart_ids(monkeypatch) -> None:
    run_id = "run-recommended"
    package = _package(
        run_id=run_id,
        stage=StageName.CHART_GENERATE,
        recommended=["CHART-001"],
    )
    state = _state(
        StageName.CHART_GENERATE,
        {
            "charts": [{"chart_id": "CHART-001"}, {"chart_id": "CHART-002"}],
            "decision_package": package,
        },
        run_id=run_id,
    )
    monkeypatch.setattr(
        graph_module,
        "interrupt",
        lambda _: {
            "action": "accept_recommendation",
            "expected_revision": 1,
            "decision_id": package["decision_id"],
            "risk_snapshot_sha256": package["risk_snapshot_sha256"],
        },
    )

    result = graph_module._review_gate(state)

    assert result["input_data"]["selected_chart_ids"] == ["CHART-001"]


def test_missing_required_data_cannot_be_approved_without_reinput(monkeypatch) -> None:
    run_id = "run-missing-data"
    state = _state(
        StageName.DATA_FETCH,
        {"blocking_issues": ["required_data_unavailable"]},
        run_id=run_id,
    )
    state["stage_results"][StageName.DATA_FETCH.value]["error"] = "required_data_unavailable"
    monkeypatch.setattr(
        graph_module,
        "interrupt",
        lambda _: {"action": "approve", "expected_revision": 1},
    )

    with pytest.raises(ValueError, match="不能直接放行"):
        graph_module._review_gate(state)


def test_partial_requested_data_can_continue_after_explicit_acknowledgement(monkeypatch) -> None:
    run_id = "run-partial-requested-data"
    package = _package(
        run_id=run_id,
        stage=StageName.DATA_FETCH,
        acknowledgement_required=True,
    )
    # Use the Agent 1 risk code instead of the generic test fixture code.
    package["risk_notices"][0]["risk_code"] = "REQUESTED-DATA-PARTIAL"
    package["acknowledgement_required_codes"] = ["REQUESTED-DATA-PARTIAL"]
    package["risk_snapshot_sha256"] = compute_risk_snapshot_sha256(
        risk_notices=package["risk_notices"],
        blocking_risk_codes=[],
        acknowledgement_required_codes=["REQUESTED-DATA-PARTIAL"],
    )
    state = _state(
        StageName.DATA_FETCH,
        {
            "blocking_issues": [],
            "advisory_issues": ["requested_data_partial"],
            "missing_requirements": [{"requirement_id": "REQ-02"}],
            "decision_package": package,
        },
        run_id=run_id,
    )
    state["stage_results"][StageName.DATA_FETCH.value]["error"] = "requested_data_partial"
    monkeypatch.setattr(
        graph_module,
        "interrupt",
        lambda _: {
            "action": "accept_with_risks",
            "expected_revision": 1,
            "decision_id": package["decision_id"],
            "risk_snapshot_sha256": package["risk_snapshot_sha256"],
            "accepted_risk_codes": ["REQUESTED-DATA-PARTIAL"],
            "release_mode": "draft_with_warnings",
        },
    )

    result = graph_module._review_gate(state)

    assert result["status"] == StageStatus.APPROVED
    assert result["input_data"]["accepted_risk_codes"] == ["REQUESTED-DATA-PARTIAL"]
    assert result["input_data"]["accepted_missing_requirement_ids"] == ["REQ-02"]


def test_tampered_review_snapshot_is_rejected(monkeypatch) -> None:
    run_id = "run-tampered-snapshot"
    package = _package(
        run_id=run_id,
        stage=StageName.CHART_GENERATE,
        recommended=["CHART-001"],
    )
    state = _state(
        StageName.CHART_GENERATE,
        {
            "charts": [{"chart_id": "CHART-001"}],
            "decision_package": package,
        },
        run_id=run_id,
    )
    monkeypatch.setattr(
        graph_module,
        "interrupt",
        lambda _: {
            "action": "accept_recommendation",
            "expected_revision": 1,
            "decision_id": package["decision_id"],
            "risk_snapshot_sha256": "0" * 64,
        },
    )

    with pytest.raises(ValueError, match="Risk snapshot hash mismatch"):
        graph_module._review_gate(state)


def test_report_risk_acknowledgement_accepts_only_snapshot_codes(monkeypatch) -> None:
    run_id = "run-report-risk"
    package = _package(
        run_id=run_id,
        stage=StageName.REPORT_FUSION,
        acknowledgement_required=True,
    )
    state = _state(
        StageName.REPORT_FUSION,
        {
            "acknowledgement_required_codes": ["REPORT-QUALITY-ADVISORY"],
            "decision_package": package,
        },
        run_id=run_id,
    )
    monkeypatch.setattr(
        graph_module,
        "interrupt",
        lambda _: {
            "action": "accept_with_risks",
            "expected_revision": 1,
            "decision_id": package["decision_id"],
            "risk_snapshot_sha256": package["risk_snapshot_sha256"],
            "accepted_risk_codes": ["REPORT-QUALITY-ADVISORY"],
            "release_mode": "draft_with_warnings",
        },
    )

    result = graph_module._review_gate(state)

    assert result["input_data"]["accepted_risk_codes"] == ["REPORT-QUALITY-ADVISORY"]
    assert result["input_data"]["risk_acknowledged_by"] == "internal-test"


def test_chapter_level_placement_override_is_rejected(monkeypatch) -> None:
    run_id = "run-placement"
    package = _package(
        run_id=run_id,
        stage=StageName.CHART_GENERATE,
        recommended=["CHART-001"],
    )
    state = _state(
        StageName.CHART_GENERATE,
        {
            "charts": [{"chart_id": "CHART-001"}],
            "decision_package": package,
        },
        run_id=run_id,
    )
    monkeypatch.setattr(
        graph_module,
        "interrupt",
        lambda _: {
            "action": "customize",
            "expected_revision": 1,
            "decision_id": package["decision_id"],
            "risk_snapshot_sha256": package["risk_snapshot_sha256"],
            "selected_chart_ids": ["CHART-001"],
            "placement_overrides": {"CHART-001": "CH-04"},
        },
    )

    with pytest.raises(ValueError, match="must match SEC-NN-NN"):
        graph_module._review_gate(state)
