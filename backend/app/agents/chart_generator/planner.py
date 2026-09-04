"""Chart global planner: recommend selections, detect conflicts, suggest placements."""

import hashlib
from collections import defaultdict
from typing import cast

from app.agents.chart_generator.router import CHART_FAMILY
from app.schemas.chart import ChartDataset, ChartType
from app.schemas.decision import (
    ChartCandidateResult,
    ChartCandidateStatus,
    ConflictGroup,
    RiskDisposition,
    RiskNotice,
    RiskSeverity,
)

RECOMMENDED_CHARTS = (5, 8)
RECOMMENDED_PER_CHAPTER = 2
RECOMMENDED_PER_FAMILY = 2
RECOMMENDED_P1 = 3
RECOMMENDED_CHAIN = 1

P1_CHART_TYPES = {"combo", "area", "scatter", "bubble", "heatmap", "boxplot", "treemap"}


def plan_chart_selection(
    candidates: list[ChartCandidateResult],
    chapter_assignments: dict[str, str] | None = None,
    *,
    target_count: int | None = None,
    user_priority: bool = False,
) -> list[ChartCandidateResult]:
    """Score and classify all technically valid candidates.

    Returns candidates with status updated to:
    - RECOMMENDED: system recommends inclusion
    - NOT_RECOMMENDED: valid but lower priority
    - NEEDS_REASSIGNMENT: valid but suggested chapter change
    """
    if not candidates:
        return []

    valid = [c for c in candidates if c.status == ChartCandidateStatus.VALID]
    if not valid:
        return candidates

    # Score each candidate
    scored = [(c, _score_candidate(c)) for c in valid]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Select top N by score within budget
    selections: list[str] = []
    chapter_counts: dict[str, int] = defaultdict(int)
    family_counts: dict[str, int] = defaultdict(int)
    p1_count = 0
    chain_count = 0

    for candidate, score in scored:
        chart_type = _to_chart_type(candidate.chart_type)
        if chart_type is None:
            continue

        family = CHART_FAMILY.get(chart_type, "other")
        assign = chapter_assignments or {}
        chapter = assign.get(candidate.candidate_id, candidate.recommended_chapter_id or "CH-00")

        # Check recommended budgets
        selection_limit = target_count or RECOMMENDED_CHARTS[1]
        if len(selections) >= selection_limit:
            break
        if not user_priority and chapter_counts[chapter] >= RECOMMENDED_PER_CHAPTER:
            continue
        if not user_priority and family_counts[family] >= RECOMMENDED_PER_FAMILY:
            continue
        is_p1 = chart_type in P1_CHART_TYPES
        if not user_priority and is_p1 and p1_count >= RECOMMENDED_P1:
            continue
        if (
            not user_priority
            and chart_type == "industry_chain"
            and chain_count >= RECOMMENDED_CHAIN
        ):
            continue

        selections.append(candidate.candidate_id)
        chapter_counts[chapter] += 1
        family_counts[family] += 1
        if is_p1:
            p1_count += 1
        if chart_type == "industry_chain":
            chain_count += 1

    # Update statuses
    for candidate in candidates:
        if candidate.status == ChartCandidateStatus.VALID:
            if candidate.candidate_id in selections:
                candidate.status = ChartCandidateStatus.RECOMMENDED
            else:
                candidate.status = ChartCandidateStatus.NOT_RECOMMENDED

    # Add risk notices for over-budget situations
    _add_budget_risk_notices(candidates, chapter_counts)

    return candidates


def detect_conflict_groups(
    candidates: list[ChartCandidateResult],
    datasets: list[ChartDataset],
) -> list[ConflictGroup]:
    """Group candidates that share the same data fingerprint into conflict groups."""
    del datasets  # Candidate evidence IDs are the stable normalized-data identity in P0/P1.
    groups: dict[str, list[ChartCandidateResult]] = defaultdict(list)

    for candidate in candidates:
        if candidate.status == ChartCandidateStatus.HARD_BLOCKED:
            continue
        # Build fingerprint from candidate info
        fingerprint = _candidate_fingerprint(candidate)
        groups[fingerprint].append(candidate)

    conflict_groups: list[ConflictGroup] = []
    for fingerprint, group in groups.items():
        if len(group) < 2:
            continue
        # Pick recommended: prefer combo > line > area, user_requested, higher priority
        recommended = _pick_recommended(group)
        group_id = f"CONFLICT-{hashlib.sha256(fingerprint.encode()).hexdigest()[:12].upper()}"

        conflict_groups.append(
            ConflictGroup(
                conflict_group_id=group_id,
                candidate_ids=[c.candidate_id for c in group],
                recommended_candidate_id=recommended.candidate_id,
                reason=f"推荐 {recommended.title}（{recommended.chart_type}），信息表达更完整",
                risk_if_keep_all="重复表达同一数据趋势，降低报告信息密度",
            )
        )

        # Tag candidates with conflict group
        for c in group:
            c.conflict_group_id = group_id

    return conflict_groups


def _score_candidate(candidate: ChartCandidateResult) -> float:
    """Score a candidate for recommendation priority."""
    score = float(candidate.priority) / 100.0  # 0-1 base

    # User-requested bonus
    if candidate.priority >= 90:  # proxy for user_requested
        score += 0.3

    # Chart type diversity bonus (lower for common types)
    chart_type = _to_chart_type(candidate.chart_type)
    if chart_type in {"industry_chain", "radar", "heatmap"}:
        score += 0.1

    return min(score, 1.5)


_VALID_CHART_TYPES = frozenset(
    {
        "line",
        "bar",
        "pie",
        "radar",
        "industry_chain",
        "combo",
        "area",
        "scatter",
        "bubble",
        "heatmap",
        "boxplot",
        "treemap",
    }
)


def _to_chart_type(raw: str) -> ChartType | None:
    """Validate raw chart type string against known types."""
    return cast(ChartType, raw) if raw in _VALID_CHART_TYPES else None


def _candidate_fingerprint(candidate: ChartCandidateResult) -> str:
    chart_type = _to_chart_type(candidate.chart_type)
    family = CHART_FAMILY.get(chart_type, "other") if chart_type else "other"
    return hashlib.sha256(f"{family}:{sorted(candidate.evidence_ids)}".encode()).hexdigest()


def _pick_recommended(group: list[ChartCandidateResult]) -> ChartCandidateResult:
    """Pick the best candidate from a conflict group."""
    # Sort by: combo > line > area, then priority
    type_order = {"combo": 0, "line": 1, "area": 2, "scatter": 1, "bubble": 0}
    group.sort(
        key=lambda c: (
            type_order.get(c.chart_type, 3),
            -c.priority,
        )
    )
    return group[0]


def _add_budget_risk_notices(
    candidates: list[ChartCandidateResult],
    chapter_counts: dict[str, int],
) -> None:
    """Add advisory risk notices for budget overruns."""
    total = len(
        [
            c
            for c in candidates
            if c.status
            in {
                ChartCandidateStatus.VALID,
                ChartCandidateStatus.RECOMMENDED,
                ChartCandidateStatus.NOT_RECOMMENDED,
            }
        ]
    )

    if total > RECOMMENDED_CHARTS[1]:
        for c in candidates:
            if c.status != ChartCandidateStatus.HARD_BLOCKED:
                c.risk_notices.append(
                    RiskNotice(
                        risk_code="CHART-COUNT-OVER-RECOMMENDED",
                        stage="chart_generate",
                        severity=RiskSeverity.WARNING,
                        disposition=RiskDisposition.ADVISORY,
                        title=f"候选图表数量 ({total}) 超过推荐上限 ({RECOMMENDED_CHARTS[1]})",
                        detail=(
                            f"当前共 {total} 张候选图表，推荐 "
                            f"{RECOMMENDED_CHARTS[0]}-{RECOMMENDED_CHARTS[1]} 张"
                        ),
                        recommendation=f"建议保留 {RECOMMENDED_CHARTS[1]} 张核心图表",
                        consequence="图表过多会降低报告信息密度",
                        can_override=True,
                    )
                )

    for chapter_id, count in chapter_counts.items():
        if count > RECOMMENDED_PER_CHAPTER:
            for c in candidates:
                if (
                    c.recommended_chapter_id == chapter_id
                    and c.status != ChartCandidateStatus.HARD_BLOCKED
                ):
                    c.risk_notices.append(
                        RiskNotice(
                            risk_code="CHART-CHAPTER-DENSITY",
                            stage="chart_generate",
                            severity=RiskSeverity.HIGH,
                            disposition=RiskDisposition.ACKNOWLEDGEMENT_REQUIRED,
                            title=f"{chapter_id} 图表密度过高 ({count}张，推荐{RECOMMENDED_PER_CHAPTER}张)",
                            detail=f"该章节有 {count} 张图表，推荐上限 {RECOMMENDED_PER_CHAPTER} 张",
                            recommendation="建议将部分图表分配到其他章节",
                            consequence="PDF中可能连续出现多页图表，部分图表分析目的相近",
                            can_override=True,
                        )
                    )
