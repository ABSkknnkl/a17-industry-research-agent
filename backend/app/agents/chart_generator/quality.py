"""BettaFish-inspired deterministic quality report for chart artifacts."""

import json
from typing import Any

from app.schemas.chart import ChartQualityReport, ChartSpec, SuppressedChart
from app.schemas.decision import RiskDisposition, RiskNotice


def validate_option(option: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    try:
        serialized = json.dumps(option, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        return [f"echarts_option_not_json_serializable:{type(exc).__name__}"]
    if "function(" in serialized or "=>" in serialized:
        issues.append("echarts_option_contains_executable_code")
    if not option.get("series"):
        issues.append("echarts_option_has_no_series")
    return issues


def build_quality_report(
    *,
    candidate_count: int,
    specs: list[ChartSpec],
    suppressed: list[SuppressedChart],
    risk_notices: list[RiskNotice] | None = None,
) -> ChartQualityReport:
    """Build quality report with risk-aware classification.

    - hard_blocked issues → quality.passed = False
    - advisory/acknowledgement issues → quality.passed = True but with notices
    """
    issues = [issue for spec in specs for issue in validate_option(spec.option)]

    # 只有硬阻断才标记为 failed
    # 软规则（预算/重复/章节密度）不再标记为失败
    hard_blocked = {
        item.reason_code
        for item in (suppressed or [])
        if item.reason_code
        not in {
            "duplicate_chart",
            "duplicate_chart_family",
            "chart_budget_exceeded",
            "p1_chart_budget_exceeded",
            "chapter_chart_budget_exceeded",
            "chart_family_budget_exceeded",
            "chart_downgraded",
            "industry_chain_budget_exceeded",
            "chart_count_over_recommended",
            "chart_chapter_density",
            "chart_family_duplicate",
        }
    }
    if hard_blocked:
        issues.extend(sorted(hard_blocked))

    passed = not issues and (candidate_count == 0 or bool(specs))
    if candidate_count > 0 and not specs and "no_ready_charts" not in issues:
        issues.append("no_ready_charts")
    return ChartQualityReport(
        passed=passed,
        ready_count=len(specs),
        suppressed_count=len(suppressed),
        issues=issues,
    )
