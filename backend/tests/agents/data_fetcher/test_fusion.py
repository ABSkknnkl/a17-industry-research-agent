from datetime import date

from app.agents.data_fetcher.fusion import build_chart_datasets, fuse_evidence
from app.schemas.evidence import (
    AuditStatus,
    CorporateActionAdjustment,
    EvidenceGrade,
    EvidenceItem,
    RestatementStatus,
)


def _evidence(evidence_id: str, scope: str, value: float, source: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        metric_name="营业收入",
        value=value,
        unit="亿元",
        period_end=date(2025, 12, 31),
        available_at=date(2026, 3, 31),
        audit_status=AuditStatus.AUDITED,
        restatement_status=RestatementStatus.NOT_RESTATED,
        scope=scope,
        market="中国内地",
        exchange="不适用",
        security_type="普通股",
        currency="CNY",
        accounting_standard="中国企业会计准则",
        corporate_action_adjustment=CorporateActionAdjustment.NOT_APPLICABLE,
        source_name=source,
        source_locator=f"https://example.com/{evidence_id}",
        grade=EvidenceGrade.A,
    )


def test_fusion_deduplicates_exact_values_and_preserves_conflicts() -> None:
    items = [
        _evidence("E-001", "公司A", 100, "来源A"),
        _evidence("E-002", "公司A", 100, "来源B"),
        _evidence("E-003", "公司A", 110, "来源C"),
        _evidence("E-004", "公司B", 80, "来源D"),
    ]

    fused, conflicts, duplicate_groups, uniqueness = fuse_evidence([], items)

    assert len(fused) == 3
    assert len(conflicts) == 1
    assert set(conflicts[0].evidence_ids) == {"E-001", "E-003"}
    assert duplicate_groups[0].merged_evidence_ids == ["E-001", "E-002"]
    assert len(duplicate_groups[0].source_locators) == 2
    assert uniqueness == 0.75


def test_fusion_merges_numeric_noise_instead_of_creating_false_conflict() -> None:
    items = [
        _evidence("E-001", "公司A", 18.2, "来源A"),
        _evidence("E-002", " 公司 A ", 18.199999, "来源B"),
    ]

    fused, conflicts, duplicate_groups, uniqueness = fuse_evidence([], items)

    assert len(fused) == 1
    assert conflicts == []
    assert len(duplicate_groups) == 1
    assert uniqueness == 0.5


def test_fusion_preserves_large_real_world_conflict_group() -> None:
    """A high-volume provider response must not crash conflict auditing."""

    items = [
        _evidence(f"E-{index:03d}", "公司A", float(index), f"来源{index}") for index in range(1, 24)
    ]

    fused, conflicts, duplicate_groups, uniqueness = fuse_evidence([], items)

    assert len(fused) == 23
    assert len(conflicts) == 1
    assert conflicts[0].evidence_ids == [f"E-{index:03d}" for index in range(1, 24)]
    assert duplicate_groups == []
    assert uniqueness == 1.0


def _text_evidence(evidence_id: str, metric_name: str, value: str, source: str) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=evidence_id,
        metric_name=metric_name,
        value=value,
        unit=None,
        period_end=None,
        available_at=date(2026, 3, 31),
        audit_status=AuditStatus.UNAUDITED,
        restatement_status=RestatementStatus.NOT_RESTATED,
        scope="新闻资讯",
        market="中国内地",
        exchange="不适用",
        security_type="普通股",
        currency="CNY",
        accounting_standard="中国企业会计准则",
        corporate_action_adjustment=CorporateActionAdjustment.NOT_APPLICABLE,
        source_name=source,
        source_locator=f"https://example.com/{evidence_id}",
        grade=EvidenceGrade.C,
    )


def test_fusion_does_not_flag_text_title_or_summary_as_conflict() -> None:
    """BUG-4: distinct news titles/summaries sharing a comparison key must not
    surface as data conflicts. Only numeric metrics participate."""

    items = [
        _text_evidence("E-101", "标题", "宁德时代发布新一代电池产品", "来源A"),
        _text_evidence("E-102", "标题", "行业出货量创历史新高", "来源B"),
        _text_evidence("E-103", "summary", "动力电池需求持续增长", "来源A"),
        _text_evidence("E-104", "summary", "上游碳酸锂价格出现波动", "来源C"),
    ]

    fused, conflicts, duplicate_groups, uniqueness = fuse_evidence([], items)

    assert len(fused) == 4
    assert conflicts == []
    assert duplicate_groups == []
    assert uniqueness == 1.0


def test_fusion_text_noise_does_not_mask_a_real_numeric_conflict() -> None:
    """A genuine numeric conflict must still be reported even when text rows
    share the surrounding pipeline."""

    items = [
        _evidence("E-001", "公司A", 100, "来源A"),
        _evidence("E-002", "公司A", 120, "来源B"),
        _text_evidence("E-101", "标题", "宁德时代发布新一代电池产品", "来源A"),
        _text_evidence("E-102", "标题", "行业出货量创历史新高", "来源B"),
    ]

    fused, conflicts, duplicate_groups, uniqueness = fuse_evidence([], items)

    assert len(conflicts) == 1
    assert set(conflicts[0].evidence_ids) == {"E-001", "E-002"}
    assert conflicts[0].metric_name == "营业收入"


def test_chart_dataset_groups_comparable_entities_in_one_dataset() -> None:
    evidence = [
        _evidence("E-001", "公司A", 100, "来源A"),
        _evidence("E-002", "公司B", 80, "来源B"),
    ]

    datasets = build_chart_datasets(evidence, [])

    assert len(datasets) == 1
    assert datasets[0].kind == "categorical"
    assert len(datasets[0].points) == 2
    assert datasets[0].evidence_ids == ["E-001", "E-002"]


def test_chart_dataset_separates_generic_provider_values_by_metric_scope() -> None:
    output = _evidence("E-OUT", "全国:集成电路生产量", 4842.8, "来源A")
    output.metric_name = "宏观@值"
    output.unit = "亿块"
    imports = _evidence("E-IMPORT", "集成电路:进口金额:当月值", 638.3, "来源B")
    imports.metric_name = "宏观@值"
    imports.unit = "亿美元"

    datasets = build_chart_datasets([output, imports], [])

    assert len(datasets) == 2
    assert {item.metric_name for item in datasets} == {
        "全国:集成电路生产量",
        "集成电路:进口金额:当月值",
    }
