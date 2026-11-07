"""Financial meaning and evidence identity regressions from the project audit."""

import asyncio
from datetime import date, datetime, timezone
from itertools import permutations

import pytest

from data_interpreter.agent import DataInterpreterAgent
from data_interpreter.config import Settings
from data_interpreter.engine import DeterministicAnalysisEngine
from data_interpreter.models import AnalysisRequest, Domain, ResearchRecord, SourceRef, StructuredResearchDataset


def record(record_id, metric, value, unit="亿元"):
    return ResearchRecord(
        record_id=record_id, domain=Domain.FINANCIALS, entity_name="公司甲",
        metric=metric, value=value, unit=unit, period_end=date(2025, 12, 31),
        source=SourceRef(task_id=record_id, skill_id="fixture", trace_id=record_id,
                         retrieved_at=datetime(2026, 10, 30, tzinfo=timezone.utc)),
    )


def test_peer_amounts_exclude_growth_rates_in_every_record_order():
    rows = [record("rev-yoy", "营业收入同比", 12, "%"),
            record("rev", "营业收入", 100),
            record("profit-yoy", "净利润同比", 8, "%"),
            record("profit", "净利润", 10)]
    for ordered in permutations(rows):
        entry = DeterministicAnalysisEngine().build_peer_comps_matrix(
            StructuredResearchDataset(financials=list(ordered))).entries[0]
        assert (entry.revenue, entry.net_profit, entry.net_margin) == (100, 10, 10)


def test_peer_amounts_prefer_exact_metric_over_segment_amount():
    rows = [record("segment", "主营业务营业收入", 40),
            record("rev", "营业收入", 100), record("profit", "净利润", 10)]
    for ordered in (rows, list(reversed(rows))):
        entry = DeterministicAnalysisEngine().build_peer_comps_matrix(
            StructuredResearchDataset(financials=ordered)).entries[0]
        assert entry.revenue == 100


@pytest.mark.parametrize("metric, unit", [("营业收入增长率", "亿元"), ("营业收入", "%")])
def test_rate_metrics_and_percent_units_cannot_supply_monetary_amount(metric, unit):
    entry = DeterministicAnalysisEngine().build_peer_comps_matrix(
        StructuredResearchDataset(financials=[record("bad-revenue", metric, 12, unit),
                                               record("profit", "净利润", 10)])).entries[0]
    assert entry.revenue is None
    assert entry.net_margin is None


@pytest.mark.parametrize("value, unit, expected, strength", [
    (1.5, "%", 0.015, "weak"), (-1.5, "%", -0.015, "weak"),
    (0, "%", 0, "weak"), (2, "%", 0.02, "weak"),
    (2.1, "%", 0.021, "weak"), (0.015, "ratio", 0.015, "weak"),
    (1.5, "ratio", 1.5, "strong"), (1.5, "百分比", 0.015, "weak"),
])
def test_explicit_growth_units_determine_fraction(value, unit, expected, strength):
    _, trends, *_ = DeterministicAnalysisEngine().analyze(
        StructuredResearchDataset(financials=[record("growth", "营业收入同比增长率", value, unit)]),
        AnalysisRequest(enable_semantic_analysis=False),
    )
    assert trends[0].total_change_pct == pytest.approx(expected)
    assert trends[0].strength == strength


def test_all_original_duplicate_and_conflicting_evidence_ids_remain_resolvable(tmp_path):
    rows = [record("e-low", "营业收入", 10.0),
            record("e-high", "营业收入", 10.123),
            record("e-same", "营业收入", 10.123)]
    report = asyncio.run(DataInterpreterAgent(settings=Settings(output_dir=tmp_path)).run(
        StructuredResearchDataset(financials=rows),
        AnalysisRequest(subject="测试行业", enable_semantic_analysis=False), save_artifacts=False,
    ))
    assert set(report.evidence_index) == {"e-low", "e-high", "e-same"}
    assert report.evidence_index["e-low"].value == 10.0
    assert report.evidence_index["e-high"].value == 10.123
    for group in (report.key_metrics, report.trends, report.anomalies, report.cross_validations,
                  report.insights, report.content_outline):
        for finding in group:
            assert set(finding.evidence_record_ids) <= set(report.evidence_index)


@pytest.mark.parametrize("value,unit,expected", [
    (0.5, "百分比", 0.5), (0.5, "％", 0.5), (0.5, "percent", 0.5),
    (1.5, "ratio", 150), (-0.015, "ratio", -1.5), (0, "%", 0),
])
def test_comps_growth_uses_explicit_units_for_percentage_points(value, unit, expected):
    entry = DeterministicAnalysisEngine().build_peer_comps_matrix(
        StructuredResearchDataset(financials=[record("revenue", "营业收入", 100),
                                               record("growth", "营业收入同比增长率", value, unit)]),
    ).entries[0]
    assert entry.revenue_yoy == pytest.approx(expected)
