'''Unit tests for shared content dedup (功能1: 指纹去重与冲突组择优).'''

from __future__ import annotations

from datetime import date

from app.agents.common.content_dedup import (
    ConflictGroup,
    canonicalize,
    content_fingerprint,
    evidence_point_key,
    group_conflicting_evidence,
    pick_richest,
    rank_by_richness,
)
from app.schemas.evidence import AuditStatus, EvidenceGrade, EvidenceItem


def _evidence(
    evidence_id: str,
    *,
    value: object = 100.0,
    locator: str | None = None,
    available: date | None = date(2026, 3, 1),
    notes: str | None = None,
    grade: str = "B",
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        metric_name="营业收入",
        value=value,
        unit="亿元",
        period_end=date(2025, 12, 31),
        fiscal_period="FY",
        available_at=available,
        audit_status=AuditStatus.AUDITED,
        scope="宁德时代",
        market="中国内地",
        exchange="SZSE",
        security_type="普通股",
        currency="CNY",
        accounting_standard="CAS",
        source_name="测试来源",
        source_locator=locator,
        grade=EvidenceGrade(grade),
        notes=notes,
    )


def test_same_content_same_fingerprint() -> None:
    payload = {"metric": "营业收入", "evidence_ids": ["E-01", "E-02"], "value": 100}
    assert content_fingerprint(payload, kind="point") == content_fingerprint(
        {**payload}, kind="point"
    )


def test_dict_key_order_irrelevant() -> None:
    a = {"x": 1, "y": 2}
    b = {"y": 2, "x": 1}
    assert canonicalize(a) == canonicalize(b)


def test_drop_fields_excluded_from_fingerprint() -> None:
    a = {"dataset_id": "D-1", "rows": [1, 2]}
    b = {"dataset_id": "D-2", "rows": [1, 2]}
    assert (
        content_fingerprint(a, kind="chart", drop_fields=("dataset_id",))
        == content_fingerprint(b, kind="chart", drop_fields=("dataset_id",))
    )
    assert content_fingerprint(a, kind="chart") != content_fingerprint(b, kind="chart")


def test_content_change_changes_fingerprint() -> None:
    a = {"metric": "营业收入", "value": 100}
    b = {"metric": "营业收入", "value": 101}
    assert content_fingerprint(a, kind="point") != content_fingerprint(b, kind="point")


def test_tracking_params_stripped_from_urls() -> None:
    a = {"url": "https://example.com/filing?id=1&utm_source=x"}
    b = {"url": "https://example.com/filing?id=1"}
    assert canonicalize(a) == canonicalize(b)


def test_kind_separates_fingerprints() -> None:
    payload = {"value": 1}
    assert content_fingerprint(payload, kind="chart") != content_fingerprint(
        payload, kind="point"
    )


def test_point_key_identity() -> None:
    assert evidence_point_key(_evidence("E-01")) == evidence_point_key(_evidence("E-02"))


def test_richest_wins_on_source_locator() -> None:
    poor = _evidence("E-01")
    rich = _evidence("E-02", locator="https://example.com/filing")
    assert pick_richest([poor, rich]).evidence_id == "E-02"


def test_richest_wins_on_populated_fields() -> None:
    poor = _evidence("E-01", notes=None)
    rich = _evidence("E-02", notes="年报附注第12页")
    assert pick_richest([poor, rich]).evidence_id == "E-02"


def test_duplicate_points_form_conflict_group() -> None:
    items = [
        _evidence("E-01"),
        _evidence("E-02", locator="https://example.com/filing"),
        _evidence("E-03"),
    ]
    kept, groups = group_conflicting_evidence(items)

    assert len(kept) == 1
    assert len(groups) == 1
    group = groups[0]
    assert group.recommended_id == "E-02"
    assert set(group.evidence_ids) == {"E-01", "E-02", "E-03"}
    assert set(group.dropped_ids) == {"E-01", "E-03"}
    assert kept[0].evidence_id == "E-02"


def test_unique_points_pass_through() -> None:
    a = _evidence("E-01")
    b = EvidenceItem(
        **{**a.model_dump(), "evidence_id": "E-02", "metric_name": "毛利率"}
    )
    kept, groups = group_conflicting_evidence([a, b])
    assert len(kept) == 2
    assert groups == []


def test_different_periods_do_not_group() -> None:
    a = _evidence("E-01")
    b = EvidenceItem(
        **{
            **a.model_dump(),
            "evidence_id": "E-02",
            "period_end": date(2024, 12, 31),
        }
    )
    kept, groups = group_conflicting_evidence([a, b])
    assert len(kept) == 2
    assert groups == []


def test_group_record_is_immutable() -> None:
    group = ConflictGroup(
        metric_name="营业收入",
        period_end="2025-12-31",
        scope="宁德时代",
        evidence_ids=("E-01", "E-02"),
        recommended_id="E-02",
        dropped_ids=("E-01",),
    )
    assert group.evidence_ids == ("E-01", "E-02")


def test_rank_by_richness_orders_richest_first() -> None:
    poor = _evidence("E-poor", locator=None, available=None, notes=None, grade="E")
    rich = _evidence("E-rich", locator="doc://1", notes="附注", grade="A")
    middle = _evidence("E-mid", locator="doc://2")

    ranked = rank_by_richness([poor, rich, middle])

    assert [item.evidence_id for item in ranked] == ["E-rich", "E-mid", "E-poor"]


def test_rank_by_richness_matches_pick_richest_winner() -> None:
    items = [
        _evidence("E-01", locator=None, available=None, grade="D"),
        _evidence("E-02", locator="doc://1", grade="A"),
        _evidence("E-03", locator="doc://2", grade="B"),
    ]
    assert rank_by_richness(items)[0] == pick_richest(items)
