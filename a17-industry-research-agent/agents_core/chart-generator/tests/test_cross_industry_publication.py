import asyncio

import pytest

from chart_generator.agent import ChartGeneratorAgent
from chart_generator.models import ChartGenerationRequest, InterpretationReport


def evidence(rid, entity, year, value, *, domain="financials"):
    return {
        "record_id": rid, "domain": domain, "entity": entity, "metric": "gross_margin",
        "value": value, "unit": "%", "period": f"{year}-12-31", "period_type": "annual",
    }


def report(subject, rows, **kwargs):
    return InterpretationReport.model_validate({
        "report_id": "A2", "subject": subject, "as_of": "2026-11-09", "status": "completed",
        "evidence_index": {row["record_id"]: row for row in rows}, **kwargs,
    })


def run(subject, rows, dataset=None, **kwargs):
    req = ChartGenerationRequest(report=report(subject, rows, **kwargs), input_dataset=dataset)
    return asyncio.run(ChartGeneratorAgent().run(req, save_artifacts=False))


@pytest.mark.parametrize("subject", ["白酒", "半导体设备", "光伏产业链", "低空经济", "未知行业"])
def test_generic_chart_keeps_safe_series_and_excludes_unapproved_evidence(subject):
    result = run(subject, [
        evidence("ok24", "甲", 2024, 22), evidence("ok25", "甲", 2025, 23),
        evidence("out24", "乙", 2024, 55), evidence("out25", "乙", 2025, 60),
        evidence("chain24", "甲", 2024, 77, domain="industry_chain"),
        evidence("chain25", "甲", 2025, 81, domain="industry_chain"),
    ], comps_matrix={"entries": [{"company_name": "甲"}]})
    assert result.charts
    assert {rid for chart in result.charts for rid in chart.evidence_ids} == {"ok24", "ok25"}
    assert all(chart.model_dump()["data_contract"]["selection_source"] == "deterministic"
               for chart in result.charts)


def test_a1_conflict_is_reported_and_never_drawn():
    rows = [evidence("ok24", "甲", 2024, 22), evidence("ok25", "甲", 2025, 23),
            evidence("wrong", "甲", 2023, 99)]
    dataset = {"subject": "白酒", "financials": [
        dict(row, entity_name=row["entity"], period_end=row["period"],
             value=33 if row["record_id"] == "wrong" else row["value"])
        for row in rows
    ]}
    result = run("白酒", rows, dataset=dataset)
    assert result.charts
    assert all("wrong" not in chart.evidence_ids for chart in result.charts)
    assert any(item.reason_code == "source_conflict" and item.evidence_ids == ["wrong"]
               for item in result.suppressed_charts)


def test_option_drift_blocks_only_the_affected_chart(monkeypatch):
    from chart_generator.compiler import EChartsCompiler

    compile_chart = EChartsCompiler.compile

    def corrupt(table, kind, title):
        option = compile_chart(table, kind, title)
        if kind == "line":
            option["series"][0]["data"] = [999] * len(table.categories)
        return option

    monkeypatch.setattr(EChartsCompiler, "compile", corrupt)
    result = run("白酒", [evidence("a", "甲", 2024, 22), evidence("b", "甲", 2025, 23)])
    assert all(chart.chart_type != "line" for chart in result.charts)
    assert any(item.reason_code == "output_contract" for item in result.suppressed_charts)


def test_rejected_chart_type_does_not_create_a_supplement_without_a2_requirement():
    from chart_generator.models import SuppressedChart

    req = ChartGenerationRequest(report=report("白酒", []))
    rows = [SuppressedChart(title="环形图", requested_type="donut", reason_code="measurement_contract",
                            reason="当前指标不支持")]
    assert ChartGeneratorAgent()._extract_data_demands(req, rows) == []


def test_out_of_range_numeric_record_cannot_crash_the_fallback():
    result = run("白酒", [
        evidence("a", "甲", 2024, 22), evidence("b", "甲", 2025, 23),
        evidence("overflow", "甲", 2023, 10 ** 400),
    ])
    assert result.charts
    assert all("overflow" not in chart.evidence_ids for chart in result.charts)


def test_compact_annual_volume_uses_one_combo_and_leaves_the_first_yoy_empty():
    from chart_generator.models import ChartPreferences

    rows = [
        {**evidence(str(year), "中国", year, value, domain="industry"),
         "metric": "新能源汽车:销量:累计值", "unit": "辆", "period_start": f"{year}-01-01"}
        for year, value in ((2023, 100000), (2024, 120000), (2025, 108000))
    ]
    a2 = report("新能源汽车", rows, trends=[{
        "trend_id": "T", "metric": rows[0]["metric"], "entity": "中国",
        "direction": "up", "strength": "strong", "observations": 3,
        "evidence_record_ids": [row["record_id"] for row in rows],
    }])
    req = ChartGenerationRequest(report=a2, preferences=ChartPreferences(max_charts=6, prefer_combined=True))
    result = asyncio.run(ChartGeneratorAgent().run(req, save_artifacts=False))
    assert [chart.chart_type for chart in result.charts] == ["combo"]
    chart = result.charts[0]
    bar, line = chart.option["series"]
    assert (bar["type"], bar["data"], bar["yAxisIndex"]) == ("bar", [10, 12, 10.8], 0)
    assert (line["type"], line["data"], line["yAxisIndex"]) == ("line", [None, 20, -10], 1)
    assert [axis["name"] for axis in chart.option["yAxis"]] == ["万辆", "%"]
    growth = [point for point in chart.data_contract["points"] if point.get("calculation") == "yoy_percent"]
    assert [point["source_record_ids"] for point in growth] == [["2024", "2023"], ["2025", "2024"]]


def test_question_plan_binds_indicator_entity_and_full_window():
    from chart_generator.models import ChartPreferences

    rows = [
        {**evidence(f"{entity}-{year}", entity, year, 20 + year % 3), "period_start": f"{year}-01-01"}
        for entity in ("比亚迪", "长安汽车", "赛力斯", "宁德时代")
        for year in (2023, 2024, 2025)
    ]
    a2 = report("新能源汽车", rows, chain_analysis={
        "method": "reviewed_chain_facts_group_comparison",
        "groups": {"整车组": {"members": ["比亚迪", "长安汽车", "赛力斯"]},
                   "电池组": {"members": ["宁德时代"]}},
    })
    result = asyncio.run(ChartGeneratorAgent().run(ChartGenerationRequest(
        report=a2, question_ids=["q2"],
        preferences=ChartPreferences(max_charts=6, prefer_combined=True, requested_types=["bar"]),
    ), save_artifacts=False))
    assert len(result.charts) == 1
    chart = result.charts[0]
    assert chart.chart_type == "line"
    assert {p["entity"] for p in chart.data_contract["points"]} == {"比亚迪", "长安汽车", "赛力斯"}
    assert chart.data_contract["question_ids"] == ["q2"]
    assert any(row["status"] == "evidence_gap" and row["intent_id"] == "nev.q2.revenue"
               for row in result.question_coverage)


def test_question_ignores_chain_type_preference_without_chain_intent():
    from chart_generator.selection import question_chain_request

    assert question_chain_request("新能源汽车", ["q1"], None) is False
    assert question_chain_request("新能源汽车", ["q3"], None) is True
    assert question_chain_request("新能源汽车", ["q3"], False) is False


def test_equipment_ratio_needs_matched_denominator_even_if_axis_is_valid():
    from chart_generator.selection import question_intents

    rows = [{**evidence("rev", "设备甲", 2025, 100), "metric": "revenue",
             "unit": "亿元", "period_start": "2025-01-01"}]
    a2 = report("半导体设备", rows)
    rule = next(rule for rule in question_intents(a2.subject, ["q2"]) if rule.ratio_denominator)
    metadata = {
        "entity": "设备甲", "period": "2025-12-31", "period_start": "2025-01-01",
        "period_type": "annual", "scope": "consolidated", "currency": "CNY",
    }
    points = [
        {**metadata, "record_id": "cost", "series": "金额", "metric": "rd_expense", "unit": "亿元", "value": 10},
        {**metadata, "record_id": "ratio", "series": "费用率", "metric": "rd_ratio", "unit": "%", "value": 10},
    ]
    assert rule.ratio_support(a2, points, ["金额", "费用率"]) == {"ratio": ["cost", "rev"]}
    points[1]["value"] = 12
    assert rule.ratio_support(a2, points, ["金额", "费用率"]) == {}


@pytest.mark.parametrize(("subject", "question_id", "metric", "domain", "unit"), [
    ("白酒", "q2", "revenue_yoy", "financials", "%"),
    ("半导体设备", "q2", "revenue_yoy", "financials", "%"),
    ("光伏产业链", "q1", "pv_new_installations", "industry", "GW"),
    ("低空经济", "q3", "uav_registration", "industry", "架"),
])
def test_other_industries_keep_only_the_requested_metrics(subject, question_id, metric, domain, unit):
    rows = [
        {**evidence(f"ok-{year}", "甲", year, value, domain=domain), "metric": metric,
         "unit": unit, "period_start": f"{year}-01-01"}
        for year, value in ((2024, 22), (2025, 23))
    ]
    rows.extend(evidence(f"other-{year}", "甲", year, 40) for year in (2024, 2025))
    req = ChartGenerationRequest(
        report=report(subject, rows), question_ids=[question_id], want_industry_chain=False,
    )
    result = asyncio.run(ChartGeneratorAgent().run(req, save_artifacts=False))
    assert result.charts
    assert all(point["metric"] == metric for chart in result.charts for point in chart.data_contract["points"])
    assert all(chart.data_contract["question_ids"] == [question_id] for chart in result.charts)
