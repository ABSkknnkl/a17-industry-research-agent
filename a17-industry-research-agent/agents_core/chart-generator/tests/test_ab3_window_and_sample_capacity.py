"""AB-3 红测：图表窗口与样本规模服从研究需求（方案 §6.3 C01–C04）。

C01 显式研究窗口不被最近期裁剪静默截断，默认政策仍能限制非请求噪声；
C02 指定主体超过单图容量时按确定顺序拆图、同单位交付，不静默丢主体；
C03 两期同口径可出图且注明仅两期观察；缺年 None、真零 0、季度不补年、
     同期冲突隔离不因字典覆盖成为单一值；
C04 横截面对齐共同可比期，不把不同披露期拼进同一张对比图。

全部离线：DataFormulator 直调 + 不可用 LLM 的确定性兜底路径。
"""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

from chart_generator.agent import ChartGeneratorAgent
from chart_generator.data_formulation import DataFormulator
from chart_generator.models import (
    ChartGenerationRequest,
    EvidenceRef,
    InterpretationReport,
)


def _ref(rid, entity, metric, value, unit, period, domain="macro", issues=None):
    return EvidenceRef(
        record_id=rid, domain=domain, entity=entity, metric=metric,
        value=value, unit=unit, period=period, issues=issues or [],
    )


def _report(rows, matrix=None):
    index = {row.record_id: row for row in rows}
    appendix = {"requirement_evidence_matrix": matrix} if matrix is not None else {}
    return InterpretationReport(
        report_id="R-AB3", subject="测试行业", as_of="2026-11-06",
        status="completed", evidence_index=index, data_quality_appendix=appendix,
    )


def _month_ends(start_year, end_year):
    out = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            if month == 12:
                out.append(date(year, 12, 31))
            elif month in (1, 3, 5, 7, 8, 10):
                out.append(date(year, month, 31))
            elif month in (4, 6, 9, 11):
                out.append(date(year, month, 30))
            else:
                out.append(date(year, 2, 28))
    return sorted(out)


def _run_agent(report):
    agent = ChartGeneratorAgent(llm=SimpleNamespace(is_available=False))
    return asyncio.run(agent.run(
        ChartGenerationRequest(report=report, want_industry_chain=False),
        save_artifacts=False,
    ))


# ── C01：显式窗口 ────────────────────────────────────────────────────────────

def _monthly_rows(periods):
    return [
        _ref(f"M{i:03}", "全国", "新能源汽车销量", float(i + 1), "万辆", p)
        for i, p in enumerate(periods)
    ]


def test_c01_explicit_window_survives_recency_trim():
    """显式要求 2015-2025 月度窗口：132 期必须全部交付，不得静默裁成最近 5 年。"""
    periods = _month_ends(2015, 2025)
    rows = _monthly_rows(periods)
    matrix = [{
        "requirement": {
            "requirement_id": "annual_industry_nev_sales", "hard": True,
            "period_ends": [f"{y}-12-31" for y in range(2015, 2026)],
            "metric_families": ["nev_sales"],
        },
        "coverage": {"passed": True, "evidence_record_ids": []},
    }]
    report = _report(rows, matrix=matrix)
    table = DataFormulator.formulate([r.record_id for r in rows], report, "line")
    assert table is not None, "132 期月度序列无法成表"
    assert len(table.categories) == len(periods), (
        f"显式窗口期被静默裁剪: {len(table.categories)} / {len(periods)}"
    )
    assert table.categories[0].startswith("2015"), "窗口起点被裁掉"


def test_c01_default_policy_still_limits_unrequested_noise():
    """无显式窗口对照：默认最近期政策仍能限制非请求历史噪声。"""
    periods = _month_ends(2015, 2025)
    rows = _monthly_rows(periods)
    report = _report(rows)
    table = DataFormulator.formulate([r.record_id for r in rows], report, "line")
    assert table is not None
    assert len(table.categories) == 60, f"默认裁剪失效: {len(table.categories)}"
    assert table.categories[0].startswith("2021")


def test_c01_required_years_extracted_from_requirement_matrix():
    from chart_generator.data_formulation import _required_years_from_report

    matrix = [{
        "requirement": {
            "requirement_id": "annual_x", "hard": True,
            "period_ends": ["2015-12-31", "2020-12-31", "2025-12-31"],
        },
        "coverage": {"passed": True, "evidence_record_ids": []},
    }, {
        "requirement": {"requirement_id": "soft", "hard": False, "period_ends": ["1999-12-31"]},
        "coverage": {"passed": False, "evidence_record_ids": []},
    }]
    years = _required_years_from_report(_report([], matrix=matrix))
    assert years == {2015, 2020, 2025}, f"窗口年份提取错误: {years}"


# ── C02：拆图交付全部指定主体 ────────────────────────────────────────────────

def test_c02_twelve_companies_split_across_charts_all_delivered():
    """12 家指定公司：超过单图容量按确定顺序拆图，全部主体可核对、同轴单位一致。"""
    rows = []
    rid = 0
    for i in range(1, 13):
        for year in range(2021, 2026):
            rid += 1
            rows.append(_ref(
                f"C{rid:03}", f"公司{i:02d}", "营业收入", 100.0 + i, "亿元",
                date(year, 12, 31), domain="financials",
            ))
    result = _run_agent(_report(rows))

    line_charts = [c for c in result.charts if c.chart_type == "line"]
    assert line_charts, "无线图交付"
    covered: set[str] = set()
    units: set[str] = set()
    for chart in line_charts:
        series_names = {p["series"] for p in chart.data_contract["points"]}
        assert len(series_names) <= 10, f"单图系列超容量: {len(series_names)}"
        covered |= series_names
        units |= set(chart.data_contract["series_units"].values())
    expected = {f"公司{i:02d}" for i in range(1, 13)}
    assert covered == expected, f"未交付主体: {sorted(expected - covered)}"
    assert units == {"亿元"}, f"拆图轴单位不一致: {units}"


# ── C03：两期图与期间语义 ────────────────────────────────────────────────────

def test_c03_two_period_series_produces_chart_with_two_observation_note():
    """两期同口径数据允许出变化图，并写明只有两期观察、不构成长期趋势。"""
    rows = [
        _ref("R1", "公司甲", "营业收入", 100.0, "亿元", date(2024, 12, 31), domain="financials"),
        _ref("R2", "公司甲", "营业收入", 120.0, "亿元", date(2025, 12, 31), domain="financials"),
    ]
    result = _run_agent(_report(rows))
    assert result.charts, "两期同口径数据无图可出"
    line = next((c for c in result.charts if c.chart_type == "line"), None)
    if line is None:
        pytest_fail_with_charts(result)
    points = line.data_contract["points"]
    assert len(points) == 2, f"两期图点数错误: {len(points)}"
    assert any("两个观测期" in note for note in line.footnotes), (
        f"缺'仅两期观察'提示: {line.footnotes}"
    )
    assert not any("长期趋势" in (line.title or "") for _ in [0]), "标题不得宣称长期趋势"


def pytest_fail_with_charts(result):
    raise AssertionError(
        f"无线图: charts={[c.chart_type for c in result.charts]}, "
        f"suppressed=[{[(s.title, s.reason_code) for s in result.suppressed]}]"
    )


def test_c03_missing_year_stays_none_true_zero_stays_zero():
    """缺年保持 None（connectNulls 关闭语义），真零值保持 0.0，不互相冒充。

    2024 为要求但缺失的年份（需求矩阵 2023-2025）→ 补入空类别。
    """
    rows = [
        _ref("R1", "公司甲", "营业收入", 100.0, "亿元", date(2023, 12, 31), domain="financials"),
        # 2024 无记录（要求但缺失）
        _ref("R2", "公司甲", "营业收入", 0.0, "亿元", date(2025, 12, 31), domain="financials"),
    ]
    matrix = [{
        "requirement": {
            "requirement_id": "annual_x", "hard": True,
            "period_ends": ["2023-12-31", "2024-12-31", "2025-12-31"],
            "metric_families": ["revenue"],
        },
        "coverage": {"passed": True, "evidence_record_ids": ["R1", "R2"]},
    }]
    report = _report(rows, matrix=matrix)
    table = DataFormulator.formulate([r.record_id for r in rows], report, "line")
    assert table is not None
    assert table.categories == ["2023-12-31", "2024-12-31", "2025-12-31"], (
        f"要求但缺失的年份未补类别: {table.categories}"
    )
    series = next(iter(table.series_data.values()))
    assert series == [100.0, None, 0.0], f"缺年/真零被篡改: {series}"
    eids = next(iter(table.point_evidence_ids.values()))
    assert eids == ["R1", "", "R2"], f"点级证据错位: {eids}"


def test_c03_quarterly_not_backfilled_into_annual():
    """较新季度观测不得被混入年度序列补成年值。"""
    rows = [
        _ref("A1", "公司甲", "营业收入", 100.0, "亿元", date(2023, 12, 31), domain="financials"),
        _ref("A2", "公司甲", "营业收入", 110.0, "亿元", date(2024, 12, 31), domain="financials"),
        _ref("A3", "公司甲", "营业收入", 120.0, "亿元", date(2025, 12, 31), domain="financials"),
        _ref("Q1", "公司甲", "营业收入", 90.0, "亿元", date(2025, 9, 30), domain="financials"),
    ]
    report = _report(rows)
    table = DataFormulator.formulate([r.record_id for r in rows], report, "line")
    assert table is not None
    assert "Q1" not in table.raw_evidence_ids, "季度记录被并入年度序列"
    assert len(table.categories) == 3, f"季度冒充年度: {table.categories}"


def test_c03_conflicting_same_period_isolated_not_overwritten():
    """同主体同指标同期冲突值先隔离（period_conflict 议题），不得字典覆盖成单一值。"""
    rows = [
        _ref("X1", "公司甲", "营业收入", 100.0, "亿元", date(2024, 12, 31),
             domain="financials", issues=["period_conflict"]),
        _ref("X2", "公司甲", "营业收入", 999.0, "亿元", date(2024, 12, 31),
             domain="financials", issues=["period_conflict"]),
        _ref("A2", "公司甲", "营业收入", 110.0, "亿元", date(2025, 12, 31), domain="financials"),
    ]
    report = _report(rows)
    table = DataFormulator.formulate([r.record_id for r in rows], report, "line")
    assert table is not None
    assert "X1" not in table.raw_evidence_ids and "X2" not in table.raw_evidence_ids, (
        "冲突值未隔离，字典覆盖决定了赢家"
    )


# ── C04：横截面共同可比期 ────────────────────────────────────────────────────

def test_c04_cross_section_aligns_to_common_comparable_period():
    """三家最新披露期不同：横截面使用共同可比期，不跨期拼接。"""
    rows = [
        # 甲：最新 2025 年报
        _ref("A1", "公司甲", "营业收入", 100.0, "亿元", date(2023, 12, 31), domain="financials"),
        _ref("A2", "公司甲", "营业收入", 110.0, "亿元", date(2024, 12, 31), domain="financials"),
        _ref("A3", "公司甲", "营业收入", 120.0, "亿元", date(2025, 12, 31), domain="financials"),
        # 乙：最新 2025 三季报
        _ref("B1", "公司乙", "营业收入", 200.0, "亿元", date(2023, 12, 31), domain="financials"),
        _ref("B2", "公司乙", "营业收入", 210.0, "亿元", date(2024, 12, 31), domain="financials"),
        _ref("B3", "公司乙", "营业收入", 150.0, "亿元", date(2025, 9, 30), domain="financials"),
        # 丙：最新 2024 年报（无 2025）
        _ref("C1", "公司丙", "营业收入", 300.0, "亿元", date(2023, 12, 31), domain="financials"),
        _ref("C2", "公司丙", "营业收入", 310.0, "亿元", date(2024, 12, 31), domain="financials"),
    ]
    result = _run_agent(_report(rows))
    bars = [c for c in result.charts if c.chart_type in ("bar", "horizontal_bar", "comparison_bar", "diverging_bar")]
    assert bars, "无横截面图交付"
    cross = bars[0]
    points = cross.data_contract["points"]
    entities = {p["entity"] for p in points}
    assert entities == {"公司甲", "公司乙", "公司丙"}, f"横截面主体缺失: {entities}"
    assert all(p["period"] == "2024-12-31" for p in points), (
        f"横截面跨期拼接: {[(p['entity'], p['period']) for p in points]}"
    )
