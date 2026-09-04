'''Deterministic value-anomaly pre-check for Agent 2 (功能2).

借鉴 business-ops-analysis 的 anomaly-identification.md：在证据进入
LLM 分析与确定性计算前，用 3σ / IQR / 突变检测做确定性异常质检，
产出 CRITICAL/WARN/INFO 分级。原则：只标记 + 给出基线依据，不替
业务做决策；样本不足时明确降级（不告警）。

分级映射（不改 DataQualityIssue 结构体）：
- CRITICAL -> impact_level=high
- WARN      -> impact_level=medium
- INFO      -> impact_level=medium，description 前缀 [INFO] 标记
'''

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from app.schemas.analysis import DataQualityIssue

_INFO_PREFIX = "[INFO] "


@dataclass(frozen=True, slots=True)
class AnomalyFinding:
    metric_name: str
    method: str
    severity: str
    description: str
    value: float | None = None
    baseline_low: float | None = None
    baseline_high: float | None = None
    period: str | None = None


_SEVERITY_ORDER = {"INFO": 0, "WARN": 1, "CRITICAL": 2}


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _std(values: Sequence[float], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return variance**0.5


def _quartiles(values: Sequence[float]) -> tuple[float, float, float]:
    ordered = sorted(values)
    n = len(ordered)

    def _at(position: float) -> float:
        lower = int(position)
        upper = min(lower + 1, n - 1)
        fraction = position - lower
        return ordered[lower] * (1 - fraction) + ordered[upper] * fraction

    return _at((n - 1) * 0.25), _at((n - 1) * 0.5), _at((n - 1) * 0.75)


def _zscore_findings(
    values: Sequence[float],
    periods: Sequence[str | None],
    metric_name: str,
) -> list[AnomalyFinding]:
    mean = _mean(values)
    std = _std(values, mean)
    if std == 0:
        return []
    findings: list[AnomalyFinding] = []
    for index, value in enumerate(values):
        z = (value - mean) / std
        if abs(z) <= 3.0:
            continue
        severity = "CRITICAL" if abs(z) > 4.0 else "WARN"
        findings.append(
            AnomalyFinding(
                metric_name=metric_name,
                method="zscore",
                severity=severity,
                description=(
                    f"偏离基线均值{mean:.4g}达{abs(z):.1f}个标准差"
                    f"（3σ判定阈值3.0）"
                ),
                value=value,
                baseline_low=mean - 3 * std,
                baseline_high=mean + 3 * std,
                period=periods[index] if index < len(periods) else None,
            )
        )
    return findings


def _iqr_findings(
    values: Sequence[float],
    periods: Sequence[str | None],
    metric_name: str,
) -> list[AnomalyFinding]:
    q1, _, q3 = _quartiles(values)
    iqr = q3 - q1
    if iqr == 0:
        return []
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    extreme_low = q1 - 3 * iqr
    extreme_high = q3 + 3 * iqr
    findings: list[AnomalyFinding] = []
    for index, value in enumerate(values):
        if low <= value <= high:
            continue
        severity = (
            "CRITICAL"
            if value < extreme_low or value > extreme_high
            else "WARN"
        )
        findings.append(
            AnomalyFinding(
                metric_name=metric_name,
                method="iqr",
                severity=severity,
                description=(
                    f"超出四分位区间[{low:.4g}, {high:.4g}]"
                    f"（Q1={q1:.4g}, Q3={q3:.4g}, IQR判定1.5倍）"
                ),
                value=value,
                baseline_low=low,
                baseline_high=high,
                period=periods[index] if index < len(periods) else None,
            )
        )
    return findings


def _shift_findings(
    values: Sequence[float],
    periods: Sequence[str | None],
    metric_name: str,
    *,
    shift_threshold: float,
) -> list[AnomalyFinding]:
    findings: list[AnomalyFinding] = []
    for index in range(1, len(values)):
        previous = values[index - 1]
        if previous == 0:
            continue
        change = (values[index] - previous) / abs(previous)
        magnitude = abs(change)
        if magnitude <= shift_threshold:
            continue
        if magnitude > 3 * shift_threshold:
            severity = "CRITICAL"
        elif magnitude > 1.5 * shift_threshold:
            severity = "WARN"
        else:
            severity = "INFO"
        findings.append(
            AnomalyFinding(
                metric_name=metric_name,
                method="shift",
                severity=severity,
                description=(
                    f"环比变化{change:+.1%}，超出突变阈值±{shift_threshold:.0%}"
                ),
                value=values[index],
                baseline_low=previous,
                baseline_high=previous,
                period=periods[index] if index < len(periods) else None,
            )
        )
    return findings


def detect_value_anomalies(
    values: Sequence[float],
    *,
    metric_name: str,
    periods: Sequence[str | None] | None = None,
    shift_threshold: float = 0.2,
) -> list[AnomalyFinding]:
    """Run 3σ / IQR / shift detection on one numeric series.

    少于 3 个样本时无法建立稳定基线，明确返回空（降级不告警）。
    同一数据点命中多种方法时保留最高严重度的一条。
    """

    clean = [float(v) for v in values if v is not None]
    if len(clean) < 3:
        return []
    period_list: list[str | None] = list(periods or [])
    if len(period_list) < len(clean):
        period_list.extend([None] * (len(clean) - len(period_list)))

    by_period: dict[str | None, AnomalyFinding] = {}
    for finding in (
        *_zscore_findings(clean, period_list, metric_name),
        *_iqr_findings(clean, period_list, metric_name),
        *_shift_findings(
            clean, period_list, metric_name, shift_threshold=shift_threshold
        ),
    ):
        key = finding.period
        current = by_period.get(key)
        if current is None or _SEVERITY_ORDER[finding.severity] > _SEVERITY_ORDER[
            current.severity
        ]:
            by_period[key] = finding
    return sorted(
        by_period.values(),
        key=lambda f: _SEVERITY_ORDER[f.severity],
        reverse=True,
    )


_SEVERITY_IMPACT = {"CRITICAL": "high", "WARN": "medium", "INFO": "medium"}


def to_quality_issue(
    finding: AnomalyFinding,
    *,
    issue_id: str,
    evidence_ids: Iterable[str] = (),
) -> DataQualityIssue:
    """Convert a finding into the existing DataQualityIssue contract.

    INFO 复用 medium（不改结构体），以 description 前缀 [INFO] 与
    issue_id 的 ANOM-INFO 段作为额外标记。
    """

    prefix = _INFO_PREFIX if finding.severity == "INFO" else ""
    return DataQualityIssue(
        issue_id=issue_id,
        issue_type="conflict",
        metric=finding.metric_name,
        description=(
            f"{prefix}{finding.method}异常检测（{finding.severity}）："
            f"{finding.description}。"
            f"基线区间[{finding.baseline_low}, {finding.baseline_high}]，"
            "仅标记偏离，不构成结论。"
        )[:2_000],
        impact_level=_SEVERITY_IMPACT[finding.severity],
        evidence_ids=list(evidence_ids),
        suggested_handling=(
            "核实该数据点口径与录入；若为真实业务变化，保留并在分析中"
            "单独归因，不与其他期间直接平均。"
        ),
    )
