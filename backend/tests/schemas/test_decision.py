"""Contract tests for decision package and user decision schemas."""

from datetime import datetime, UTC

import pytest
from pydantic import ValidationError

from app.schemas.decision import (
    ChartCandidateResult,
    ChartCandidateStatus,
    ConflictGroup,
    DecisionPackage,
    DecisionStatus,
    ReleaseMode,
    RiskDisposition,
    RiskNotice,
    RiskSeverity,
    UserDecision,
    compute_risk_snapshot_sha256,
)


def test_risk_notice_factory() -> None:
    notice = RiskNotice(
        risk_code="CHART-COUNT-OVER-RECOMMENDED",
        stage="chart_generate",
        severity=RiskSeverity.WARNING,
        disposition=RiskDisposition.ADVISORY,
        title="图表数量超过推荐值",
        detail="当前13张候选图表超过推荐值5-8张",
        affected_ids=["CHART-001", "CHART-002"],
        recommendation="建议保留8张核心图表",
        consequence="报告信息密度下降，可能影响阅读体验",
        can_override=True,
    )
    assert notice.risk_code == "CHART-COUNT-OVER-RECOMMENDED"
    assert notice.can_override is True


def test_hard_block_risk_cannot_override() -> None:
    notice = RiskNotice(
        risk_code="UNKNOWN-EVIDENCE",
        stage="chart_generate",
        severity=RiskSeverity.CRITICAL,
        disposition=RiskDisposition.HARD_BLOCK,
        title="引用不存在的证据",
        detail="证据ID E-999 不存在",
        affected_ids=["E-999"],
        recommendation="修正证据引用后重新生成",
        consequence="无法生成有效图表",
        can_override=False,
    )
    assert notice.can_override is False


def test_decision_package_requires_acknowledgement() -> None:
    notices = [
        RiskNotice(
            risk_code="CHART-CHAPTER-DENSITY",
            stage="chart_generate",
            severity=RiskSeverity.HIGH,
            disposition=RiskDisposition.ACKNOWLEDGEMENT_REQUIRED,
            title="第4章图表密度过高",
            detail="第4章有5张图表，推荐上限2张",
            affected_ids=["CH-04"],
            recommendation="将部分图表分配到其他章节",
            consequence="PDF中可能连续出现多页图表",
            can_override=True,
        )
    ]
    snapshot = compute_risk_snapshot_sha256(
        risk_notices=notices,
        blocking_risk_codes=[],
        acknowledgement_required_codes=["CHART-CHAPTER-DENSITY"],
    )
    package = DecisionPackage(
        decision_id="DP-001",
        run_id="run-123",
        stage="chart_generate",
        revision=1,
        all_candidates=[],
        recommended_selection=[],
        conflict_groups=[],
        risk_notices=notices,
        blocking_risk_codes=[],
        acknowledgement_required_codes=["CHART-CHAPTER-DENSITY"],
        decision_status=DecisionStatus.AWAITING_USER,
        risk_snapshot_sha256=snapshot,
        generated_at=datetime.now(UTC),
    )
    assert package.decision_status == DecisionStatus.AWAITING_USER
    assert len(package.acknowledgement_required_codes) == 1


def test_decision_package_rejects_tampered_risk_snapshot() -> None:
    with pytest.raises(ValidationError, match="risk_snapshot_sha256"):
        DecisionPackage(
            decision_id="DP-001",
            run_id="run-123",
            stage="chart_generate",
            revision=1,
            risk_snapshot_sha256="a" * 64,
        )


def test_user_decision_accept_with_risks() -> None:
    decision = UserDecision(
        decision_id="DP-001",
        run_id="run-123",
        owner_id="test-user",
        stage="chart_generate",
        action="accept_with_risks",
        selected_chart_ids=["CHART-001", "CHART-002"],
        excluded_chart_ids=[],
        placement_overrides={},
        accepted_risk_codes=["CHART-CHAPTER-DENSITY"],
        release_mode=ReleaseMode.DRAFT_WITH_WARNINGS,
        comment="已知风险，接受继续",
        expected_revision=1,
        risk_snapshot_sha256="a" * 64,
        decided_at=datetime.now(UTC),
    )
    assert decision.action == "accept_with_risks"
    assert decision.release_mode == ReleaseMode.DRAFT_WITH_WARNINGS


def test_user_decision_must_have_owner_id() -> None:
    """owner_id is required and must be set by the server."""
    with pytest.raises(ValidationError):
        UserDecision(
            decision_id="DP-001",
            run_id="run-123",
            owner_id="",  # empty
            stage="chart_generate",
            action="accept_recommendation",
            accepted_risk_codes=[],
            expected_revision=1,
            risk_snapshot_sha256="a" * 64,
        )
