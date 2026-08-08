"""Tests for chart global planner."""

from app.agents.chart_generator.planner import (
    detect_conflict_groups,
    plan_chart_selection,
)
from app.schemas.decision import (
    ChartCandidateResult,
    ChartCandidateStatus,
)


def _make_candidate(
    candidate_id: str,
    title: str,
    chart_type: str,
    priority: int = 50,
    chapter_id: str = "CH-04",
    evidence_ids: list[str] | None = None,
) -> ChartCandidateResult:
    return ChartCandidateResult(
        candidate_id=candidate_id,
        title=title,
        chart_type=chart_type,
        status=ChartCandidateStatus.VALID,
        recommended_chapter_id=chapter_id,
        priority=priority,
        evidence_ids=evidence_ids or ["E-001"],
    )


def test_planner_recommends_top_8() -> None:
    """13 candidates → planner recommends top 8."""
    candidates = [
        _make_candidate(f"C-{i:02d}", f"Chart {i}", "bar", priority=80 - i * 3) for i in range(13)
    ]
    result = plan_chart_selection(candidates)
    recommended = [c for c in result if c.status == ChartCandidateStatus.RECOMMENDED]
    assert len(recommended) <= 8


def test_planner_respects_chapter_budget() -> None:
    """5 candidates in same chapter → at most 2 recommended."""
    candidates = [
        _make_candidate(f"C-{i:02d}", f"Chart {i}", "bar", priority=80 - i * 5, chapter_id="CH-04")
        for i in range(5)
    ]
    result = plan_chart_selection(candidates)
    chapter_recommended = [
        c
        for c in result
        if c.status == ChartCandidateStatus.RECOMMENDED and c.recommended_chapter_id == "CH-04"
    ]
    assert len(chapter_recommended) <= 2


def test_planner_all_candidates_remain_valid() -> None:
    """All 5 candidates remain valid (not deleted), some are NOT_RECOMMENDED."""
    candidates = [
        _make_candidate(f"C-{i:02d}", f"Chart {i}", "bar", priority=80 - i * 5, chapter_id="CH-04")
        for i in range(5)
    ]
    result = plan_chart_selection(candidates)
    valid_count = len([c for c in result if c.status != ChartCandidateStatus.HARD_BLOCKED])
    assert valid_count == 5


def test_detect_line_area_combo_conflict() -> None:
    """Line, area, combo sharing same data → one conflict group."""
    candidates = [
        _make_candidate("C-LINE", "Trend Line", "line", evidence_ids=["E-001", "E-002"]),
        _make_candidate("C-AREA", "Trend Area", "area", evidence_ids=["E-001", "E-002"]),
        _make_candidate("C-COMBO", "Trend Combo", "combo", evidence_ids=["E-001", "E-002"]),
    ]
    groups = detect_conflict_groups(candidates, [])
    assert len(groups) == 1
    assert groups[0].recommended_candidate_id == "C-COMBO"


def test_different_evidence_no_conflict() -> None:
    """Different evidence → no conflict group."""
    candidates = [
        _make_candidate("C-1", "A", "line", evidence_ids=["E-001"]),
        _make_candidate("C-2", "B", "line", evidence_ids=["E-002"]),
    ]
    groups = detect_conflict_groups(candidates, [])
    assert len(groups) == 0


def test_same_evidence_different_chart_families_are_not_forced_into_conflict() -> None:
    candidates = [
        _make_candidate("C-LINE", "趋势", "line", evidence_ids=["E-001"]),
        _make_candidate("C-RADAR", "综合评分", "radar", evidence_ids=["E-001"]),
    ]

    assert detect_conflict_groups(candidates, []) == []


def test_planner_handles_empty_list() -> None:
    result = plan_chart_selection([])
    assert result == []


def test_planner_skips_hard_blocked() -> None:
    """Hard blocked candidates are not scored or recommended."""
    candidates = [
        _make_candidate("C-01", "A", "bar", priority=90),
        _make_candidate("C-02", "B", "bar", priority=90),
    ]
    candidates[1].status = ChartCandidateStatus.HARD_BLOCKED
    result = plan_chart_selection(candidates)
    hard_blocked = [c for c in result if c.status == ChartCandidateStatus.HARD_BLOCKED]
    assert len(hard_blocked) == 1


def test_planner_adds_budget_risk_notices() -> None:
    """More than 8 valid candidates → risk notice added."""
    candidates = [
        _make_candidate(f"C-{i:02d}", f"Chart {i}", "bar", priority=80 - i * 3) for i in range(13)
    ]
    result = plan_chart_selection(candidates)
    valid_candidates = [c for c in result if c.status != ChartCandidateStatus.HARD_BLOCKED]
    # At least one candidate should have a CHART-COUNT-OVER-RECOMMENDED notice
    budget_notices = []
    for c in valid_candidates:
        for n in c.risk_notices:
            if n.risk_code == "CHART-COUNT-OVER-RECOMMENDED":
                budget_notices.append(n)
    assert len(budget_notices) > 0
