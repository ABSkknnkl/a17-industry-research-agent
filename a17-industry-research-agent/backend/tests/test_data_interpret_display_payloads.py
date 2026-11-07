from datetime import date
from types import SimpleNamespace

from backend.app.agents import adapters


def test_evidence_digest_only_contains_referenced_readable_records():
    report = SimpleNamespace(
        insights=[SimpleNamespace(evidence_record_ids=["R-1"])],
        evidence_index={
            "R-1": SimpleNamespace(
                entity="宁德时代",
                metric="营业收入",
                value=2769.17,
                unit="亿元",
                period=date(2024, 12, 31),
                domain="financials",
                skill_id="hithink-finance-query",
            ),
            "R-unused": SimpleNamespace(
                entity="未引用公司",
                metric="未引用指标",
                value=1,
                unit=None,
                period=None,
                domain="companies",
                skill_id="hithink-basicinfo-query",
            ),
        },
    )

    assert adapters._build_evidence_digest(report) == {
        "R-1": {
            "label": "宁德时代 · 营业收入 2769.17亿元",
            "entity": "宁德时代",
            "metric": "营业收入",
            "value": 2769.17,
            "unit": "亿元",
            "period": "2024-12-31",
            "domain": "financials",
            "skill_id": "hithink-finance-query",
        }
    }


def test_anomaly_risk_keeps_fields_needed_for_distinct_user_messages():
    anomaly = SimpleNamespace(
        anomaly_id="ANO-1",
        kind="cross_sectional_outlier",
        severity="high",
        entity="宁德时代",
        metric="营业收入",
        period=date(2024, 12, 31),
        observed_value=92.12,
        expected_range="40–60",
        score=4.2,
        explanation="该值的稳健 Z 分数超过阈值。",
    )

    assert adapters._serialize_anomaly_risk(anomaly) == {
        "risk_code": "ANO-1",
        "title": "离群异常: 营业收入",
        "level": "warning",
        "kind": "cross_sectional_outlier",
        "severity": "high",
        "entity": "宁德时代",
        "metric": "营业收入",
        "period": "2024-12-31",
        "observed_value": 92.12,
        "expected_range": "40–60",
        "score": 4.2,
        "description": "该值的稳健 Z 分数超过阈值。",
    }
