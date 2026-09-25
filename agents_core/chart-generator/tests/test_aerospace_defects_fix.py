import asyncio
import json
from pathlib import Path
import pytest

from chart_generator import ChartGenerationRequest, ChartGeneratorAgent
from chart_generator.models import ChartPreferences, InterpretationReport, EvidenceRef
from chart_generator.linter import ChartSkillLinter


class DummyCand:
    def __init__(self, title: str, chart_type: str, option: dict, evidence_ids: list[str]):
        self.title = title
        self.chart_type = chart_type
        self.option = option
        self.evidence_ids = evidence_ids
        self.point_evidence_ids = evidence_ids


def test_treemap_rejects_non_additive_metric():
    """Verify that Treemap rejects non-additive metrics like stock prices, P/E, and margins."""
    linter = ChartSkillLinter()
    evidence_index = {
        f"R{i}": {"metric": "最新股价", "value": 10.0 + i, "entity": f"公司{i}"}
        for i in range(1, 10)
    }

    # 1. Non-additive: stock price
    cand_price = [
        DummyCand(
            "最新股价规模矩形树",
            "treemap",
            {"series": [{"type": "treemap", "data": [{"name": f"公司{i}", "value": 10.0 + i} for i in range(1, 10)]}]},
            list(evidence_index.keys()),
        )
    ]
    v_price = linter.lint(cand_price, evidence_index)
    assert any(v.code == "treemap_non_additive_metric" for v in v_price), "Price treemap must trigger treemap_non_additive_metric"

    # 2. Additive: market cap (should NOT trigger non-additive error)
    ev_mc = {
        f"R{i}": {"metric": "总市值", "value": 100.0 * i, "entity": f"公司{i}"}
        for i in range(1, 10)
    }
    cand_mc = [
        DummyCand(
            "总市值规模矩形树",
            "treemap",
            {"series": [{"type": "treemap", "data": [{"name": f"公司{i}", "value": 100.0 * i} for i in range(1, 10)]}]},
            list(ev_mc.keys()),
        )
    ]
    v_mc = linter.lint(cand_mc, ev_mc)
    assert not any(v.code == "treemap_non_additive_metric" for v in v_mc), "Market cap treemap must be valid"


def test_radar_rejects_insufficient_dimensions():
    """Verify that radar charts with only 1 or 2 indicators are flagged as degenerate."""
    linter = ChartSkillLinter()
    evidence_index = {
        "R1": {"metric": "社融同比", "value": 8.5},
        "R2": {"metric": "工业增加值", "value": 6.2},
    }

    cand_radar_2 = [
        DummyCand(
            "宏观双维度雷达",
            "radar",
            {
                "radar": {"indicator": [{"name": "社融同比", "max": 100}, {"name": "工业增加值", "max": 100}]},
                "series": [{"type": "radar", "data": [{"value": [80, 60]}]}],
            },
            ["R1", "R2"],
        )
    ]
    v_radar = linter.lint(cand_radar_2, evidence_index)
    assert any(v.code == "radar_insufficient_dimensions" for v in v_radar), "2-dimensional radar must be flagged"


def test_macro_quota_and_deduplication_in_industry_report():
    """Verify that in an industry report, macro charts are capped and duplicate standalone lines are suppressed."""
    evidence = {
        # Macro indicators (both in combo and individual series)
        "M1_1": {"record_id": "M1_1", "domain": "macro", "entity": "宏观", "metric": "社会融资规模存量:期末同比", "value": 8.9, "period": "2024-01-31"},
        "M1_2": {"record_id": "M1_2", "domain": "macro", "entity": "宏观", "metric": "社会融资规模存量:期末同比", "value": 9.2, "period": "2024-02-29"},
        "M2_1": {"record_id": "M2_1", "domain": "macro", "entity": "宏观", "metric": "规模以上工业增加值:累计同比", "value": 5.5, "period": "2024-01-31"},
        "M2_2": {"record_id": "M2_2", "domain": "macro", "entity": "宏观", "metric": "规模以上工业增加值:累计同比", "value": 5.8, "period": "2024-02-29"},
        # Corporate comparison bars
        "C1": {"record_id": "C1", "domain": "financials", "entity": "企业A", "metric": "营业收入增长率", "value": 25.0, "unit": "%", "period": "2024-12-31"},
        "C2": {"record_id": "C2", "domain": "financials", "entity": "企业B", "metric": "营业收入增长率", "value": 15.0, "unit": "%", "period": "2024-12-31"},
        "C3": {"record_id": "C3", "domain": "financials", "entity": "企业C", "metric": "营业收入增长率", "value": -5.0, "unit": "%", "period": "2024-12-31"},
    }
    report = InterpretationReport.model_validate({
        "report_id": "AERO-01",
        "subject": "商业航天",
        "as_of": "2026-09-23",
        "status": "completed",
        "evidence_index": evidence,
    })

    agent = ChartGeneratorAgent()
    req = ChartGenerationRequest(report=report, preferences={"max_charts": 5})
    result = asyncio.run(agent.run(req, save_artifacts=False))

    # Assert macro charts count <= 1 in an industry report
    macro_charts = [c for c in result.charts if agent._is_macro_candidate(c, report.evidence_index)]
    assert len(macro_charts) <= 1, f"Expected at most 1 macro chart in industry report, got {len(macro_charts)}"

    # Assert corporate comparison bar is preserved!
    bar_charts = [c for c in result.charts if c.chart_type in ("comparison_bar", "diverging_bar", "bar", "horizontal_bar")]
    assert len(bar_charts) >= 1, "Corporate comparison bar must be generated and preserved"


def test_core_bar_reservation_eliminates_reverse_elimination():
    """Verify that core financial comparison bars are prioritized and not squeezed out by variety of non-bars."""
    evidence = {}
    # 5 entities with revenue and profit
    for i, name in enumerate(["航天电子", "中国卫星", "中兴通讯", "中国卫通", "铖昌科技"], 1):
        evidence[f"REV_{i}"] = {"record_id": f"REV_{i}", "domain": "financials", "entity": name, "metric": "营业收入同比增长率", "value": 10.0 + i * 5, "unit": "%", "period": "2024-12-31"}
        evidence[f"PRF_{i}"] = {"record_id": f"PRF_{i}", "domain": "financials", "entity": name, "metric": "归母净利润同比增长率", "value": -5.0 + i * 8, "unit": "%", "period": "2024-12-31"}
        evidence[f"MC_{i}"] = {"record_id": f"MC_{i}", "domain": "financials", "entity": name, "metric": "总市值", "value": 100.0 * i, "unit": "亿元", "period": "2024-12-31"}

    # Industry chain
    evidence["CH1"] = {"record_id": "CH1", "domain": "industry_chain", "entity": "上游", "metric": "上游环节", "value": "航天电子"}
    evidence["CH2"] = {"record_id": "CH2", "domain": "industry_chain", "entity": "中游", "metric": "中游环节", "value": "中国卫星"}

    report = InterpretationReport.model_validate({
        "report_id": "AERO-02",
        "subject": "商业航天",
        "as_of": "2026-09-23",
        "status": "completed",
        "evidence_index": evidence,
    })

    agent = ChartGeneratorAgent()
    # Limit to 5 charts
    req = ChartGenerationRequest(report=report, preferences={"max_charts": 5})
    result = asyncio.run(agent.run(req, save_artifacts=False))

    titles = [c.title for c in result.charts]
    chart_types = [c.chart_type for c in result.charts]

    # Revenue comparison bar must be present in top charts
    has_rev_bar = any("营业收入" in t for t in titles)
    assert has_rev_bar, f"营业收入横向比较必须在前列保留，实际标题: {titles}"

    # Net profit comparison bar must be present in top charts
    has_prf_bar = any("归母净利润" in t for t in titles)
    assert has_prf_bar, f"归母净利润横向比较必须在前列保留，实际标题: {titles}"


def test_real_aerospace_dataset_offline_run():
    """Verify end-to-end against the real commercial aerospace run dataset."""
    repo_root = Path(__file__).resolve().parents[3]
    aerospace_path = repo_root / "data/runs/run-20260923181514-452/artifacts/interpretation_report.json"
    if not aerospace_path.exists():
        aerospace_path = Path("data/runs/run-20260923181514-452/artifacts/interpretation_report.json")
    if not aerospace_path.exists():
        pytest.skip("Historical aerospace interpretation report not found on disk")

    data = json.loads(aerospace_path.read_text("utf-8"))
    report = InterpretationReport.model_validate(data)

    agent = ChartGeneratorAgent()
    req = ChartGenerationRequest(report=report, preferences={"max_charts": 8})
    result = asyncio.run(agent.run(req, save_artifacts=False))

    assert len(result.charts) == 8, f"Expected 8 charts, got {len(result.charts)}"

    # 1. No stock price Treemap!
    for c in result.charts:
        if c.chart_type == "treemap":
            assert "股价" not in c.title, f"Treemap must not be used for stock prices: {c.title}"

    # 2. Macro charts <= 1
    macro_charts = [c for c in result.charts if agent._is_macro_candidate(c, report.evidence_index)]
    assert len(macro_charts) <= 1, f"Expected at most 1 macro chart, got {len(macro_charts)}"

    # 3. Revenue comparison bar is present
    has_rev_bar = any("营业收入" in c.title and c.chart_type in ("comparison_bar", "bar", "horizontal_bar", "diverging_bar") for c in result.charts)
    assert has_rev_bar, "Expected 营业收入横向比较 in charts"

    # 4. Point-level evidence IDs are valid and non-empty for every chart
    for c in result.charts:
        assert c.point_evidence_ids, f"Chart {c.chart_id} ({c.title}) missing point_evidence_ids"
        assert all(eid in report.evidence_index for eid in c.point_evidence_ids), f"Chart {c.chart_id} has invalid point evidence ID"

    # 5. Verify chart timeliness: macro chart does NOT contain ancient 2005 data and has accurate as_of
    for c in macro_charts:
        x_data = c.option.get("xAxis", {}).get("data", [])
        if x_data:
            first_year = int(str(x_data[0])[:4])
            assert first_year >= 2018, f"Macro chart should not start in {first_year} (ancient records should be pruned to recent 3-5 years)"
        assert c.option.get("as_of") != "2026-09-23", f"Macro chart as_of should reflect real data period (2023-08-31), not false report as_of: {c.option.get('as_of')}"


def test_timeseries_ancient_records_pruned_to_recent_window():
    """Verify that an 18-year sequence (2005-2023) is automatically trimmed to recent 5 years."""
    from chart_generator.data_formulation import _filter_recent_periods
    from datetime import date

    # 216 monthly periods from 2005-01 to 2022-12
    periods = [
        date(2005 + i // 12, (i % 12) + 1, 28)
        for i in range(216)
    ]
    assert len(periods) == 216
    assert periods[0].year == 2005
    assert periods[-1].year == 2022

    pruned = _filter_recent_periods(periods)
    assert len(pruned) < len(periods)
    assert pruned[0].year >= 2018, f"Pruned time series should start >= 2018, but got {pruned[0]}"
    assert pruned[-1].year == 2022


def test_dynamic_chart_as_of_resolution():
    """Verify that chart generator resolves true data period instead of blindly stamping report as_of."""
    from datetime import date
    from chart_generator.agent import ChartGeneratorAgent, _Candidate

    evidence = {
        "M1": {"record_id": "M1", "domain": "macro", "metric": "社融同比", "value": 9.5, "period": "2023-08-31"},
        "M2": {"record_id": "M2", "domain": "macro", "metric": "工业增加值", "value": 5.4, "period": "2023-08-31"},
        "F1": {"record_id": "F1", "domain": "financials", "metric": "营业收入", "value": 100.0, "period": "2025-12-31"},
        "S1": {"record_id": "S1", "domain": "companies", "metric": "最新价", "value": 32.5, "period": "2026-09-23"},
    }
    report = InterpretationReport.model_validate({
        "report_id": "REP-TIME-01",
        "subject": "商业航天",
        "as_of": "2026-09-23",
        "status": "completed",
        "evidence_index": evidence,
    })

    cand_macro = _Candidate(
        title="宏观社融趋势",
        chart_type="line",
        option={"xAxis": {"data": ["2023-07-31", "2023-08-31"]}},
        evidence_ids=["M1", "M2"],
        point_evidence_ids=["M1", "M2"],
        goal="宏观走势",
        chapter="CH-02",
        footnotes=[],
    )
    as_of_macro = ChartGeneratorAgent._resolve_chart_as_of(cand_macro, report)
    assert as_of_macro == "2023-08-31", f"Expected 2023-08-31 for macro chart, got {as_of_macro}"

    cand_fin = _Candidate(
        title="企业营收对比",
        chart_type="bar",
        option={},
        evidence_ids=["F1"],
        point_evidence_ids=["F1"],
        goal="财务对比",
        chapter="CH-04",
        footnotes=[],
    )
    as_of_fin = ChartGeneratorAgent._resolve_chart_as_of(cand_fin, report)
    assert as_of_fin == "2025-12-31", f"Expected 2025-12-31 for financial chart, got {as_of_fin}"

    cand_snap = _Candidate(
        title="最新股价对比",
        chart_type="bar",
        option={},
        evidence_ids=["S1"],
        point_evidence_ids=["S1"],
        goal="行情快照",
        chapter="CH-04",
        footnotes=[],
    )
    as_of_snap = ChartGeneratorAgent._resolve_chart_as_of(cand_snap, report)
    assert as_of_snap == "2026-09-23", f"Expected 2026-09-23 for market snapshot, got {as_of_snap}"

