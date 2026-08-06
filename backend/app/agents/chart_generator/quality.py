"""BettaFish-inspired deterministic quality report for chart artifacts."""

import json
from typing import Any

from app.schemas.chart import ChartQualityReport, ChartSpec, SuppressedChart


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
) -> ChartQualityReport:
    issues = [issue for spec in specs for issue in validate_option(spec.option)]
    critical_suppressions = {
        item.reason_code
        for item in suppressed
        if item.reason_code not in {"duplicate_chart", "chart_budget_exceeded"}
    }
    if critical_suppressions:
        issues.extend(sorted(critical_suppressions))
    passed = not issues and (candidate_count == 0 or bool(specs))
    if candidate_count > 0 and not specs and "no_ready_charts" not in issues:
        issues.append("no_ready_charts")
    return ChartQualityReport(
        passed=passed,
        ready_count=len(specs),
        suppressed_count=len(suppressed),
        issues=issues,
    )
