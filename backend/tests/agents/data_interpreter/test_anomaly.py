'''Unit tests for deterministic anomaly detection (功能2).'''

from __future__ import annotations

from app.agents.data_interpreter.anomaly import (
    AnomalyFinding,
    detect_value_anomalies,
    to_quality_issue,
)


def _periods(n: int) -> list[str]:
    return [f"2024-Q{index}" for index in range(1, n + 1)]


def test_stable_series_no_findings() -> None:
    values = [100.0, 101.0, 99.5, 100.5, 100.0]
    assert detect_value_anomalies(values, metric_name="营业收入") == []


def test_insufficient_samples_degrade_silently() -> None:
    assert detect_value_anomalies([100.0, 500.0], metric_name="营业收入") == []


def test_extreme_outlier_flagged_critical_by_zscore() -> None:
    values = [100.0, 101.0, 99.0, 100.5, 100.0, 400.0]
    findings = detect_value_anomalies(values, metric_name="营业收入", periods=_periods(6))
    assert any(f.severity == "CRITICAL" and f.period == "2024-Q6" for f in findings)


def test_moderate_outlier_flagged_by_iqr() -> None:
    values = [10.0, 11.0, 10.5, 10.8, 10.2, 30.0]
    findings = detect_value_anomalies(values, metric_name="毛利率", periods=_periods(6))
    assert any(f.period == "2024-Q6" and f.severity in {"WARN", "CRITICAL"} for f in findings)


def test_shift_over_threshold_flagged() -> None:
    values = [100.0, 105.0, 103.0, 102.0, 130.0]
    findings = detect_value_anomalies(values, metric_name="净利润", periods=_periods(5))
    period5 = [f for f in findings if f.period == "2024-Q5"]
    assert period5 and period5[0].severity in {"WARN", "CRITICAL"}


def test_shift_mild_change_is_info() -> None:
    values = [100.0, 130.0, 100.0, 130.0, 100.0, 121.0]
    findings = detect_value_anomalies(values, metric_name="营收", periods=_periods(6))
    info = [f for f in findings if f.severity == "INFO"]
    assert info, findings


def test_zero_previous_skips_shift() -> None:
    values = [0.0, 50.0, 51.0, 50.5]
    findings = detect_value_anomalies(values, metric_name="新开工面积", periods=_periods(4))
    assert not any(f.method == "shift" and f.period == "2024-Q2" for f in findings)


def test_same_period_keeps_highest_severity() -> None:
    values = [100.0, 101.0, 99.0, 100.5, 500.0]
    findings = detect_value_anomalies(values, metric_name="营业收入", periods=_periods(5))
    period5 = [f for f in findings if f.period == "2024-Q5"]
    assert len(period5) == 1
    assert period5[0].severity == "CRITICAL"


def test_sorted_by_severity_desc() -> None:
    values = [100.0, 121.0, 100.0, 300.0, 121.0]
    findings = detect_value_anomalies(values, metric_name="营收", periods=_periods(5))
    order = {"CRITICAL": 2, "WARN": 1, "INFO": 0}
    severities = [order[f.severity] for f in findings]
    assert severities == sorted(severities, reverse=True)


def test_to_quality_issue_critical_maps_high() -> None:
    finding = AnomalyFinding(
        metric_name="营业收入",
        method="zscore",
        severity="CRITICAL",
        description="偏离基线均值100达4.5个标准差",
        value=400.0,
        baseline_low=70.0,
        baseline_high=130.0,
        period="2024-Q6",
    )
    issue = to_quality_issue(finding, issue_id="DQ-ANOM-01", evidence_ids=["E-01"])
    assert issue.impact_level == "high"
    assert issue.issue_type == "conflict"
    assert issue.evidence_ids == ["E-01"]
    assert "zscore" in issue.description


def test_to_quality_issue_info_reuses_medium_with_marker() -> None:
    finding = AnomalyFinding(
        metric_name="营收",
        method="shift",
        severity="INFO",
        description="环比变化+21.0%，超出突变阈值±20%",
        value=121.0,
        baseline_low=100.0,
        baseline_high=100.0,
        period="2024-Q4",
    )
    issue = to_quality_issue(finding, issue_id="DQ-ANOM-INFO-01")
    assert issue.impact_level == "medium"
    assert issue.description.startswith("[INFO] ")
    assert "INFO" in issue.description


def test_to_quality_issue_warn_maps_medium() -> None:
    finding = AnomalyFinding(
        metric_name="毛利率",
        method="iqr",
        severity="WARN",
        description="超出四分位区间",
        value=30.0,
        baseline_low=5.0,
        baseline_high=20.0,
        period="2024-Q3",
    )
    issue = to_quality_issue(finding, issue_id="DQ-ANOM-02")
    assert issue.impact_level == "medium"
    assert not issue.description.startswith("[INFO] ")


def test_periodic_series_baseline() -> None:
    """10组基准之一：规律季节性序列不应误报。"""
    values = [100.0, 120.0, 100.0, 120.0, 100.0, 120.0, 100.0, 120.0]
    findings = detect_value_anomalies(values, metric_name="季节性营收", periods=_periods(8))
    critical = [f for f in findings if f.severity == "CRITICAL"]
    assert not critical
