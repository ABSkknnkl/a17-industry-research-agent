"""BettaFish-inspired deterministic quality report for chart artifacts."""

import json
import re
from typing import Any

from app.schemas.chart import ChartDataset, ChartQualityReport, ChartSpec, SuppressedChart
from app.schemas.decision import RiskNotice

_CONCLUSIVE_PATTERNS = re.compile(
    r"\d|同比|环比|增|降|涨|跌|领先|承压|攀升|回落|下滑|高增|收窄|扩大|转正|转负"
)


def check_title_conclusive(spec: ChartSpec) -> bool:
    """Whether a chart title contains a direction, comparison, or quantified finding."""
    return bool(_CONCLUSIVE_PATTERNS.search(spec.title))


def data_health_check(dataset: ChartDataset) -> list[str]:
    """Return deterministic completeness issues for one chart dataset."""
    if dataset.kind == "industry_chain":
        return []
    specialized = {
        "xy": dataset.xy_points,
        "matrix": dataset.matrix_cells,
        "distribution": dataset.distribution_samples,
        "hierarchy": dataset.hierarchy_nodes,
    }
    if dataset.kind in specialized:
        return [] if specialized[dataset.kind] else ["data_health_min_fields"]

    points = list(dataset.points)
    issues: list[str] = []
    if len(points) < 5:
        issues.append("data_health_min_rows")
    values = [point.value for point in points]
    numeric = [
        value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    forecast_nulls = sum(
        point.value is None
        and (point.value_kind == "forecast" or point.label.upper().endswith("E"))
        for point in points
    )
    if points and (len(points) - len(numeric) - forecast_nulls) / len(points) > 0.2:
        issues.append("data_health_missing_ratio")
    if not points or not any(point.label for point in points):
        issues.append("data_health_min_fields")
    if len({type(value) for value in numeric}) > 1:
        issues.append("data_health_type_consistency")
    return issues


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
    if any(not check_title_conclusive(spec) for spec in specs):
        issues.append("title_not_conclusive")

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

    # A failed individual candidate is advisory once at least one audited chart
    # is renderable. The fact gate lives in Agents 1/2; Agent 3 reports gaps but
    # does not suppress the whole report for a partial visualisation mismatch.
    passed = bool(specs) or candidate_count == 0
    if candidate_count > 0 and not specs and "no_ready_charts" not in issues:
        issues.append("no_ready_charts")
    return ChartQualityReport(
        passed=passed,
        ready_count=len(specs),
        suppressed_count=len(suppressed),
        issues=issues,
    )
