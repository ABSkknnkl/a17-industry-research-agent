import asyncio
from datetime import date
import pytest

from chart_generator.data_formulation import DataFormulator
from chart_generator.linter import ChartSkillLinter
from chart_generator.models import (
    ChartGenerationRequest,
    ChartSpec,
    EvidenceRef,
    InterpretationReport,
)
from chart_generator.agent import ChartGeneratorAgent


def create_sample_report():
    evidence = {
        "R1": {"record_id": "R1", "domain": "financials", "entity": "宁德时代", "metric": "营业收入", "value": 3000.0, "unit": "亿元", "period": "2025-12-31"},
        "R2": {"record_id": "R2", "domain": "financials", "entity": "比亚迪", "metric": "营业收入", "value": 4500.0, "unit": "亿元", "period": "2025-12-31"},
        "R3": {"record_id": "R3", "domain": "financials", "entity": "国轩高科", "metric": "营业收入", "value": 350.0, "unit": "亿元", "period": "2025-12-31"},
        "R4": {"record_id": "R4", "domain": "financials", "entity": "亿纬锂能", "metric": "营业收入", "value": 400.0, "unit": "亿元", "period": "2024-12-31"},  # 历史期
        "R10": {"record_id": "R10", "domain": "financials", "entity": "行业", "metric": "行业营收", "value": 1000.0, "unit": "亿元", "period": "2023-12-31"},
        "R11": {"record_id": "R11", "domain": "financials", "entity": "行业", "metric": "行业营收", "value": 1500.0, "unit": "亿元", "period": "2024-12-31"},
        "R12": {"record_id": "R12", "domain": "financials", "entity": "行业", "metric": "行业营收", "value": 2200.0, "unit": "亿元", "period": "2025-12-31"},
    }
    return InterpretationReport.model_validate({
        "report_id": "REP-PT-01",
        "subject": "动力电池",
        "as_of": "2026-01-01",
        "status": "completed",
        "evidence_index": evidence,
    })


def test_data_formulator_time_series_point_evidence():
    report = create_sample_report()
    dated_records = [
        EvidenceRef.model_validate(report.evidence_index["R10"]),
        EvidenceRef.model_validate(report.evidence_index["R11"]),
        EvidenceRef.model_validate(report.evidence_index["R12"]),
    ]
    unique_periods = [date(2023, 12, 31), date(2024, 12, 31), date(2025, 12, 31)]
    table = DataFormulator._formulate_time_series(dated_records, unique_periods)

    assert table is not None
    assert "行业" in table.point_evidence_ids
    assert table.point_evidence_ids["行业"] == ["R10", "R11", "R12"]
    assert table.point_periods["行业"] == ["2023-12-31", "2024-12-31", "2025-12-31"]


def test_data_formulator_cohort_alignment_and_point_evidence():
    report = create_sample_report()
    records = [
        EvidenceRef.model_validate(report.evidence_index["R1"]),
        EvidenceRef.model_validate(report.evidence_index["R2"]),
        EvidenceRef.model_validate(report.evidence_index["R3"]),
        EvidenceRef.model_validate(report.evidence_index["R4"]),
    ]
    unique_entities = ["宁德时代", "比亚迪", "国轩高科", "亿纬锂能"]
    table = DataFormulator._formulate_entity_cross_section(records, unique_entities)

    assert table is not None
    # 共同报告期 2025-12-31 包含 3 家，优先选中该期，亿纬锂能（2024年报）被排除在严格同期对比之外
    assert table.categories == ["宁德时代", "比亚迪", "国轩高科"]
    assert "营业收入" in table.point_evidence_ids
    assert table.point_evidence_ids["营业收入"] == ["R1", "R2", "R3"]
    assert table.point_periods["营业收入"] == ["2025-12-31", "2025-12-31", "2025-12-31"]


def test_linter_point_grounding_verification():
    report = create_sample_report()
    linter = ChartSkillLinter()

    # 1. 合法图表：点级证据均在 evidence_index 中
    valid_spec = ChartSpec(
        chart_id="C1",
        title="行业营收趋势",
        chart_type="line",
        option={"series": [{"data": [1000, 1500, 2200]}]},
        evidence_ids=["R10", "R11", "R12"],
        point_evidence_ids=["R10", "R11", "R12"],
        insight_goal="观察时序趋势",
        data_fingerprint="fp1",
    )
    violations = linter.lint([valid_spec], report.evidence_index)
    point_violations = [v for v in violations if v.code == "hallucinated_point_evidence"]
    assert len(point_violations) == 0

    # 2. 伪溯源图表：图级 evidence_ids 合法，但点级含有伪造证据 R999
    invalid_spec = ChartSpec(
        chart_id="C2",
        title="营收横向对比",
        chart_type="bar",
        option={"series": [{"data": [3000, 4500, 9999]}]},
        evidence_ids=["R1", "R2"],
        point_evidence_ids=["R1", "R2", "R999"],  # R999 不存在
        insight_goal="横向对比",
        data_fingerprint="fp2",
    )
    violations = linter.lint([invalid_spec], report.evidence_index)
    point_violations = [v for v in violations if v.code == "hallucinated_point_evidence"]
    assert len(point_violations) == 1
    assert "R999" in point_violations[0].message


def test_agent_end_to_end_point_evidence():
    report = create_sample_report()
    agent = ChartGeneratorAgent()
    req = ChartGenerationRequest(report=report)
    result = asyncio.run(agent.run(req, save_artifacts=False))

    assert len(result.charts) > 0
    for chart in result.charts:
        # 验证点级证据存在
        assert hasattr(chart, "point_evidence_ids")
        assert len(chart.point_evidence_ids) > 0
        # 验证所有点级证据均真实存在于证据库中，杜绝幻觉
        for eid in chart.point_evidence_ids:
            assert eid in report.evidence_index
