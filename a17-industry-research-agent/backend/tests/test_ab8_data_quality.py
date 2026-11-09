"""Regression tests for the 白酒/光伏 live-data quality fixes (2026-11-09)."""
from __future__ import annotations

from datetime import date, datetime, timezone

from data_fetcher.fusion import DataFusion
from data_fetcher.models import Domain, EventRecord, SkillResult, SourceRef


def _result(records, *, skill_id="hithink-finance-query", payload=None, domain=Domain.FINANCIALS, query="贵州茅台 2024年营业收入"):
    return SkillResult(
        task_id="t1", skill_name=skill_id, skill_id=skill_id, skill_version="1.0.0",
        domain=domain, query=query, trace_id="trace", success=True,
        records=records, raw_payload=payload,
    )


def test_provider_column_unit_is_used_for_amounts():
    records = [{
        "股票代码": "600519.SH", "股票简称": "贵州茅台",
        "营业收入[20241231]": 170899000000.0,
    }]
    payload = {"columns": [
        {"key": "股票代码", "unit": ""},
        {"key": "营业收入[20241231]", "unit": "元"},
    ]}
    dataset = DataFusion().fuse([_result(records, payload=payload)], date(2026, 11, 9))
    revenue = next(r for r in dataset.financials if r.metric == "revenue")
    assert revenue.unit == "元"
    assert revenue.unit_provenance == "source_schema"
    assert "unit_unknown" not in revenue.issues


def test_annual_report_toc_boilerplate_does_not_suspend_whole_year():
    records = [{
        "股票代码": "600809.SH", "股票简称": "山西汾酒",
        "营业收入[20241231]": 36010992321.46,
    }]
    payload = {"columns": [{"key": "营业收入[20241231]", "unit": "元"}]}
    dataset = DataFusion().fuse(
        [_result(records, payload=payload, query="山西汾酒 2024年营业收入")], date(2026, 11, 9))
    source = SourceRef(task_id="notice", skill_id="announcement-search", skill_version="1",
                       query="", trace_id="t", retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    dataset.events = [EventRecord(
        record_id="clue", entity_name="山西汾酒", entity_code="600809.SH",
        title="山西汾酒：2024年年度报告",
        body="十八、其他重要事项\n1、前期会计差错更正\n(1).追溯重述法\n(2).未来适用法",
        announce_date=date(2025, 4, 30), source=source,
        raw_fields={"url": "http://www.sse.com.cn/x.pdf"},
    )]
    DataFusion._mark_unverified_restatement_clues(dataset, date(2026, 11, 9), [])
    revenue = next(r for r in dataset.financials if r.metric == "revenue")
    assert "pending_restatement" not in revenue.issues


def test_verified_pv_capacity_series_is_injected_for_solar():
    dataset = DataFusion().fuse([], date(2026, 11, 9), industry="光伏")
    capacity = [r for r in dataset.industry if r.metric == "pv_new_capacity"]
    assert len(capacity) == 5
    assert {r.period_end.year for r in capacity} == {2021, 2022, 2023, 2024, 2025}
    assert all(r.unit == "万千瓦" and r.unit_provenance == "source_field" for r in capacity)
    assert all(r.source.skill_id == "official-statistics" for r in capacity)
    assert capacity[0].raw_fields.get("source_url")


def test_numeric_binding_accepts_unit_converted_amounts():
    from chapter_writer.agent import bind_numeric_evidence

    evidence = {
        "R1": {"value": "168838000000.0", "unit": "元", "entity": "贵州茅台", "metric": "revenue"},
        "R2": {"value": "40528509770.23", "unit": "元", "entity": "五粮液", "metric": "revenue"},
    }
    bound = bind_numeric_evidence(
        "2025年贵州茅台营业收入1,688.38亿元，五粮液营业收入405.29亿元。",
        evidence, {"R1", "R2"},
    )
    assert bound == ["R1", "R2"]
