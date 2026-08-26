'''Unit tests for measurement reconciliation (功能3: 口径统一).'''

from __future__ import annotations

from datetime import date

from app.agents.data_interpreter.reconciliation import reconcile_comparables
from app.schemas.evidence import AuditStatus, EvidenceGrade, EvidenceItem


def _evidence(
    evidence_id: str,
    *,
    value: object = 100.0,
    unit: str | None = "亿元",
    currency: str = "CNY",
    audit: AuditStatus = AuditStatus.AUDITED,
    locator: str | None = None,
    period_end: date = date(2025, 12, 31),
    metric: str = "营业收入",
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        metric_name=metric,
        value=value,
        unit=unit,
        period_end=period_end,
        fiscal_period="FY",
        available_at=date(2026, 3, 1),
        audit_status=audit,
        scope="宁德时代",
        market="中国内地",
        exchange="SZSE",
        security_type="普通股",
        currency=currency,
        accounting_standard="CAS",
        source_name="测试来源",
        source_locator=locator,
        grade=EvidenceGrade("B"),
    )


def test_unit_normalized_to_yuan() -> None:
    items = [_evidence("E-01", value=1.5, unit="亿元")]
    kept, issues = reconcile_comparables(items)
    assert not issues
    assert kept[0].normalized_value == 150_000_000.0
    assert kept[0].normalized_unit == "元"


def test_wan_unit_normalized() -> None:
    items = [_evidence("E-01", value=20_000.0, unit="万元")]
    kept, _ = reconcile_comparables(items)
    assert kept[0].normalized_value == 200_000_000.0


def test_different_units_same_point_converge_after_normalization() -> None:
    items = [
        _evidence("E-01", value=2.0, unit="亿元"),
        _evidence("E-02", value=20_000.0, unit="万元"),
    ]
    kept, issues = reconcile_comparables(items)
    assert not issues
    assert len(kept) == 2
    assert kept[0].normalized_value == kept[1].normalized_value == 200_000_000.0


def test_currency_mismatch_isolated() -> None:
    items = [_evidence("E-01", currency="USD")]
    kept, issues = reconcile_comparables(items)
    assert not kept
    assert len(issues) == 1
    assert issues[0].issue_type == "not_comparable"
    assert "USD" in issues[0].description


def test_non_monetary_unit_kept_as_is() -> None:
    """非货币单位无量纲换算需求，原样保留不隔离。"""
    items = [_evidence("E-01", value=35.0, unit="万辆")]
    kept, issues = reconcile_comparables(items)
    assert len(kept) == 1
    assert not issues
    assert kept[0].normalized_value == 35.0


def test_conflicting_values_pick_richest_and_record_conflict() -> None:
    items = [
        _evidence("E-01", value=100.0),
        _evidence("E-02", value=105.0, locator="https://example.com/filing"),
    ]
    kept, issues = reconcile_comparables(items)
    assert len(kept) == 1
    assert kept[0].evidence.evidence_id == "E-02"
    conflicts = [i for i in issues if i.issue_type == "conflict"]
    assert len(conflicts) == 1
    assert conflicts[0].evidence_ids == ["E-01", "E-02"]


def test_same_value_no_conflict_issue() -> None:
    items = [
        _evidence("E-01", value=100.0),
        _evidence("E-02", value=100.0, unit="亿元"),
    ]
    kept, issues = reconcile_comparables(items)
    assert len(kept) == 2
    assert not [i for i in issues if i.issue_type == "conflict"]


def test_audited_sorts_before_adjusted() -> None:
    items = [
        _evidence("E-02", audit=AuditStatus.UNAUDITED),
        _evidence("E-01", audit=AuditStatus.AUDITED),
    ]
    kept, _ = reconcile_comparables(items)
    assert kept[0].evidence.evidence_id == "E-01"


def test_different_periods_kept_separately() -> None:
    items = [
        _evidence("E-01", period_end=date(2025, 12, 31)),
        _evidence("E-02", period_end=date(2024, 12, 31), value=80.0),
    ]
    kept, issues = reconcile_comparables(items)
    assert len(kept) == 2
    assert not [i for i in issues if i.issue_type == "conflict"]


def test_text_value_preserved_without_normalization() -> None:
    items = [_evidence("E-01", value="预增50%以上", unit=None)]
    kept, issues = reconcile_comparables(items)
    assert kept[0].normalized_value is None
    assert not issues
