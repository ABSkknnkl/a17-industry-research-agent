import asyncio
from datetime import date

import pytest

from chart_generator import ChartGenerationRequest, ChartGeneratorAgent
from chart_generator.models import ChartPreferences, InterpretationReport
from chart_generator.render import render_svg


def report_payload():
    evidence={}
    for index,(entity,value) in enumerate((("甲",10),("乙",-3),("丙",8)),1):
        evidence[f"R{index}"]={"record_id":f"R{index}","domain":"financials","entity":entity,"metric":"利润增长率","value":value,"unit":"%","period":"2026-06-30"}
    for index,value in enumerate((10,13,16),4):
        evidence[f"R{index}"]={"record_id":f"R{index}","domain":"industry","entity":"行业","metric":"市场规模","value":value,"unit":"亿元","period":f"202{index-3}-12-31"}
    return InterpretationReport.model_validate({"report_id":"A1","subject":"测试行业","as_of":"2026-09-01","status":"completed","evidence_index":evidence})


def test_selects_signed_bar_and_time_series(tmp_path):
    agent=ChartGeneratorAgent()
    agent.settings=type(agent.settings)(output_dir=tmp_path)
    result=asyncio.run(agent.run(ChartGenerationRequest(report=report_payload())))
    types={item.chart_type for item in result.charts}
    assert "comparison_bar" in types
    assert "line" in types
    assert (tmp_path/"runs"/result.run_id/"preview.html").is_file()
    assert all(item.evidence_ids for item in result.charts)
    assert {item.name for item in result.applied_skills} >= {"chart-selection","chart-readability","financial-charting"}


def test_empty_evidence_does_not_fabricate_chart():
    report=InterpretationReport(report_id="A2",subject="空行业",as_of=date.today(),status="partial")
    result=asyncio.run(ChartGeneratorAgent().run(ChartGenerationRequest(report=report),save_artifacts=False))
    assert result.status == "partial"
    assert result.charts == []
    assert result.suppressed_charts[0].reason_code == "no_numeric_evidence"


def test_supports_composition_radar_chain_and_advanced_families():
    evidence={}
    counter=1
    for entity,share in (("甲",40),("乙",25),("丙",15),("丁",12),("戊",8)):
        for metric,value in (("市场份额占比",share),("营业收入",share*10),("净利润",share*2),("现金流",share*3),("估值",share/2)):
            rid=f"R{counter}";counter+=1
            evidence[rid]={"record_id":rid,"domain":"financials","entity":entity,"metric":metric,"value":value,"unit":"%" if "占比" in metric else "亿元","period":"2026-06-30"}
        for year,value in ((2023,share*6),(2024,share*7),(2025,share*8),(2026,share*10)):
            rid=f"R{counter}";counter+=1
            evidence[rid]={"record_id":rid,"domain":"financials","entity":entity,"metric":"历史收入","value":value,"unit":"亿元","period":f"{year}-06-30"}
            rid=f"R{counter}";counter+=1
            evidence[rid]={"record_id":rid,"domain":"financials","entity":entity,"metric":"历史利润","value":value/5,"unit":"亿元","period":f"{year}-06-30"}
    for label,value in (("上游材料","锂矿"),("中游制造","电池"),("下游应用","整车")):
        rid=f"R{counter}";counter+=1
        evidence[rid]={"record_id":rid,"domain":"industry_chain","entity":label,"metric":label,"value":value}
    report=InterpretationReport.model_validate({"report_id":"ADV","subject":"先进制造","as_of":"2026-09-01","status":"completed","evidence_index":evidence})
    requested=["pie","radar","industry_chain","area","combo","bubble","heatmap","boxplot","treemap"]
    result=asyncio.run(ChartGeneratorAgent().run(ChartGenerationRequest(report=report,preferences={"max_charts":30,"requested_types":requested}),save_artifacts=False))
    types={chart.chart_type for chart in result.charts}
    assert {"pie","radar","industry_chain","area","combo","bubble","heatmap","boxplot","treemap"} <= types
    assert "industry-chain-visualization" in {item.name for item in result.applied_skills}


class MockLLM:
    @property
    def is_available(self) -> bool:
        return True

    async def run_skill_and_chart_loop(self, system_prompt, user_prompt, tools, skill_resolver):
        # Simulate autonomous tool calling: LLM chooses to invoke financial-charting and chart-selection
        called_skills = [
            {"skill_name": "financial-charting", "reason": "需要对财务利润指标进行同口径比较与正负值零轴对齐"},
            {"skill_name": "chart-selection", "reason": "依据数据特征选择对比柱状图"},
        ]
        # Resolve skills
        for item in called_skills:
            skill_resolver(item["skill_name"])

        # Simulate generated JSON
        chart_json = {
            "charts": [
                {
                    "title": "测试行业企业利润增长率对比",
                    "chart_type": "comparison_bar",
                    "insight_goal": "比较甲乙丙三家企业的利润增长率差异",
                    "recommended_chapter_id": "CH-05",
                    "evidence_ids": ["R1", "R2", "R3"],
                    "footnotes": ["包含负利润增长率，显式保留零轴"],
                    "option": {
                        "tooltip": {"trigger": "axis"},
                        "xAxis": {"type": "category", "data": ["甲", "乙", "丙"]},
                        "yAxis": {"type": "value", "name": "%"},
                        "series": [{"name": "利润增长率", "type": "bar", "data": [10, -3, 8]}],
                    },
                }
            ],
            "suppressed_charts": [
                {
                    "title": "未充分支持的饼图",
                    "requested_type": "pie",
                    "reason_code": "not_compositional",
                    "reason": "利润增长率非互斥构成数据，不适用饼图",
                    "evidence_ids": ["R1", "R2", "R3"],
                }
            ],
        }
        return called_skills, chart_json


def test_llm_driven_chart_generation_with_tool_calling(tmp_path):
    mock_llm = MockLLM()
    agent = ChartGeneratorAgent(llm=mock_llm)
    agent.settings = type(agent.settings)(output_dir=tmp_path)
    result = asyncio.run(agent.run(ChartGenerationRequest(report=report_payload())))

    assert len(result.charts) == 1
    chart = result.charts[0]
    assert chart.title == "测试行业企业利润增长率对比"
    assert chart.chart_type == "comparison_bar"
    assert chart.recommended_chapter_id == "CH-05"
    assert set(chart.evidence_ids) == {"R1", "R2", "R3"}
    assert (tmp_path / "runs" / result.run_id / "charts" / f"{chart.chart_id}.svg").is_file()

    applied_names = {s.name for s in result.applied_skills}
    assert "financial-charting" in applied_names
    assert "chart-selection" in applied_names
    assert len(result.suppressed_charts) >= 1
    assert result.suppressed_charts[0].reason_code == "not_compositional"


def test_render_svg_publication_grade():
    from chart_generator.render import render_svg

    # 1. Horizontal bar test with long labels
    opt_hbar = {
        "subtitle": "样本龙头估值对比",
        "xAxis": {"name": "倍"},
        "series": [{"data": [112.5, 359.6, -10.2]}],
        "xAxis": {"data": ["中航成飞主机制造", "航发动力发动机", "亏损标的"]}
    }
    svg_hbar = render_svg("重点企业市盈率横向对比", "horizontal_bar", opt_hbar, ["测试附注"])
    assert "中航成飞主机制造" in svg_hbar
    assert "航发动力发动机" in svg_hbar
    assert "359.6" in svg_hbar
    assert "数据来源：" in svg_hbar

    # 2. Industry chain 3-column layout test
    opt_chain = {
        "series": [{
            "data": [
                {"name": "万泽股份", "category": "上游", "margin": "35%"},
                {"name": "中航成飞", "category": "中游", "margin": "18%"},
                {"name": "中信海直", "category": "下游", "margin": "22%"},
            ]
        }]
    }
    svg_chain = render_svg("产业链三段式架构", "industry_chain", opt_chain, [])
    assert "上游：基础支撑与核心供给" in svg_chain
    assert "中游：核心产品与系统集成" in svg_chain
    assert "下游：场景应用与商业化生态" in svg_chain
    assert "万泽股份" in svg_chain
    assert "中航成飞" in svg_chain
    assert "中信海直" in svg_chain

    # 3. Scatter quadrant test with 2D list and entity labels
    opt_scatter = {
        "title": "研发费用率与净利率分布（单位：百分比）",
        "xAxis": {"data": ["公司A", "公司B"]},
        "series": [{"data": [[5.2, 12.8], [8.4, 21.0]]}],
    }
    svg_scatter = render_svg("研发与盈利定位", "scatter", opt_scatter, [])
    assert "标的1" not in svg_scatter
    assert "公司A" in svg_scatter
    assert "公司B" in svg_scatter
    assert "单位：百分比" in svg_scatter

    # 4. Empty scatter test ensures no fake '标的1-5'
    opt_empty_scatter = {"series": [{"data": []}]}
    svg_empty = render_svg("空散点图", "scatter", opt_empty_scatter, [])
    assert "标的1" not in svg_empty
    assert "暂无有效散点坐标数据" in svg_empty


def test_chart_skill_linter_diversity_and_zero_axis():
    from chart_generator.linter import ChartSkillLinter

    class DummyCand:
        def __init__(self, title, chart_type, option, evidence_ids):
            self.title = title
            self.chart_type = chart_type
            self.option = option
            self.evidence_ids = evidence_ids

    linter = ChartSkillLinter(min_diversity_threshold=4, min_unique_types=3, max_bar_ratio=0.40)
    evidence_index = {"R1": {}, "R2": {}, "R3": {}}

    # 1. Diversity violation: 4 charts, all bars
    cands_all_bars = [
        DummyCand("图1", "bar", {"series": [{"data": [10, 20]}]}, ["R1"]),
        DummyCand("图2", "bar", {"series": [{"data": [15, 25]}]}, ["R2"]),
        DummyCand("图3", "horizontal_bar", {"series": [{"data": [30, 40]}]}, ["R1"]),
        DummyCand("图4", "comparison_bar", {"series": [{"data": [50, 60]}]}, ["R3"]),
    ]
    violations = linter.lint(cands_all_bars, evidence_index)
    v_codes = {v.code for v in violations}
    assert "bar_chart_ratio_exceeded" in v_codes

    # 2. Zero-axis violation: negative data with yAxis min > 0
    cands_clipped = [
        DummyCand("利润图", "bar", {
            "yAxis": {"min": 5},
            "series": [{"data": [-10, 20]}],
        }, ["R1"]),
    ]
    violations_clipped = linter.lint(cands_clipped, evidence_index)
    assert any(v.code == "zero_axis_clipped" for v in violations_clipped)

    # 3. Grounding violation: hallucinated evidence ID
    cands_fake_eid = [
        DummyCand("虚假图", "donut", {"series": [{"data": [10, 20]}]}, ["R999_FAKE"]),
    ]
    violations_fake = linter.lint(cands_fake_eid, evidence_index)
    assert any(v.code == "hallucinated_evidence" for v in violations_fake)


def test_chart_skill_linter_data_fitness():
    from chart_generator.linter import ChartSkillLinter

    class DummyCand:
        def __init__(self, title, chart_type, option, evidence_ids):
            self.title = title
            self.chart_type = chart_type
            self.option = option
            self.evidence_ids = evidence_ids

    linter = ChartSkillLinter()
    evidence_index = {f"R{i}": {} for i in range(1, 20)}

    # 1. Boxplot with < 15 points
    cand_box = [DummyCand("小样本箱线图", "boxplot", {"series": [{"data": [1, 2, 3]}]}, ["R1", "R2", "R3"])]
    v_box = linter.lint(cand_box, evidence_index)
    assert any(v.code == "boxplot_insufficient_sample" for v in v_box)

    # 2. Treemap with < 8 items
    cand_tree = [DummyCand("小样本树图", "treemap", {"series": [{"data": [{"name": "A", "value": 1}, {"name": "B", "value": 2}]}]}, ["R1", "R2"])]
    v_tree = linter.lint(cand_tree, evidence_index)
    assert any(v.code == "treemap_insufficient_items" for v in v_tree)

    # 3. Redundant line and area
    cand_redundant = [
        DummyCand("营收趋势", "line", {"series": [{"data": [10, 20]}]}, ["R1", "R2"]),
        DummyCand("营收面积", "area", {"series": [{"data": [10, 20]}]}, ["R1", "R2"]),
    ]
    v_red = linter.lint(cand_redundant, evidence_index)
    assert any(v.code == "redundant_line_and_area" for v in v_red)



def test_self_healing_reflection_loop_on_linter_violation(tmp_path):
    """Verifies that if the initial LLM response violates diversity, Linter triggers reflection loop and self-heals."""
    class ReflectiveMockLLM:
        def __init__(self):
            self.call_count = 0

        @property
        def is_available(self) -> bool:
            return True

        async def run_skill_and_chart_loop(self, system_prompt, user_prompt, tools, skill_resolver):
            self.call_count += 1
            if self.call_count == 1:
                # 1st call: returns 4 charts, all bars (violates diversity)
                return [{"skill_name": "chart-selection", "reason": "初步柱图"}], {
                    "charts": [
                        {"title": "图1", "chart_type": "bar", "evidence_ids": ["R1"], "option": {"series": [{"data": [10]}]}},
                        {"title": "图2", "chart_type": "bar", "evidence_ids": ["R2"], "option": {"series": [{"data": [20]}]}},
                        {"title": "图3", "chart_type": "bar", "evidence_ids": ["R3"], "option": {"series": [{"data": [30]}]}},
                        {"title": "图4", "chart_type": "bar", "evidence_ids": ["R1"], "option": {"series": [{"data": [40]}]}},
                    ],
                    "suppressed_charts": [],
                }
            else:
                # 2nd call (Reflection): repairs diversity by introducing combo, donut, radar
                assert "Hard Linter Violations" in user_prompt
                return [{"skill_name": "chart-selection", "reason": "自愈丰富图表类型"}], {
                    "charts": [
                        {"title": "营收与增速", "chart_type": "combo", "evidence_ids": ["R1"], "option": {"series": [{"type": "bar", "data": [10]}, {"type": "line", "data": [15]}]}},
                        {"title": "业务构成", "chart_type": "donut", "evidence_ids": ["R2"], "option": {"series": [{"type": "pie", "data": [{"name": "A", "value": 40}]}]}},
                        {"title": "竞争画像", "chart_type": "radar", "evidence_ids": ["R3"], "option": {"radar": {"indicator": []}, "series": [{"type": "radar", "data": []}]}},
                        {"title": "企业排名", "chart_type": "horizontal_bar", "evidence_ids": ["R1"], "option": {"series": [{"type": "bar", "data": [50]}]}},
                    ],
                    "suppressed_charts": [],
                }

    events = []
    async def record_event(e):
        events.append(e)

    mock_llm = ReflectiveMockLLM()
    agent = ChartGeneratorAgent(llm=mock_llm)
    agent.settings = type(agent.settings)(output_dir=tmp_path)
    result = asyncio.run(agent.run(ChartGenerationRequest(report=report_payload()), emit=record_event))

    assert mock_llm.call_count == 2  # Proves reflection loop was triggered!
    event_names = [e["event"] for e in events]
    assert "skill_linter_checked" in event_names
    assert "skill_correction_triggered" in event_names
    assert "skill_correction_resolved" in event_names

    types = {c.chart_type for c in result.charts}
    assert len(types) >= 3
    assert "combo" in types
    assert "donut" in types
    assert "radar" in types


def test_deterministic_records_policy_routing_and_linter_audit(tmp_path):
    events = []
    async def record_event(e):
        events.append(e)

    agent = ChartGeneratorAgent()
    agent.settings = type(agent.settings)(output_dir=tmp_path)
    result = asyncio.run(agent.run(ChartGenerationRequest(report=report_payload()), emit=record_event))

    event_names = [e["event"] for e in events]
    # Verify honest auditing: deterministic uses skill_routed_by_policy, NOT skill_invoked_by_llm
    assert "skill_routed_by_policy" in event_names
    assert "skill_invoked_by_llm" not in event_names
    assert "skill_linter_checked" in event_names
    assert len(result.charts) >= 1


def test_render_svg_long_timeseries_downsampling():
    from chart_generator.render import render_svg
    import re

    dates = [f"202{i//12}-{i%12+1:02d}-28" for i in range(120)]
    vals = [float(i * 1.5 + (i % 5)) for i in range(120)]
    opt = {
        "xAxis": {"data": dates},
        "yAxis": {"name": "点"},
        "series": [{"data": vals, "type": "line"}],
    }
    svg = render_svg("长期历史走势", "line", opt, ["时序数据校验"])
    assert "<svg" in svg
    assert "</svg>" in svg
    # Count the date labels rendered on the X-axis
    date_texts = re.findall(r'<text x="([\d.]+)" y="458"[^>]*>(\d{4}-\d{2}-\d{2})</text>', svg)
    # Must be downsampled to between 6 and 8 labels, not squeezed 12 or all 120
    assert 6 <= len(date_texts) <= 8
    # The first date text should be near the left, and the last date text near the right
    x_coords = [float(x[0]) for x in date_texts]
    assert x_coords[0] < 200
    assert x_coords[-1] > 800


def test_render_svg_line_with_none_values():
    from chart_generator.render import render_svg

    opt = {
        "xAxis": {"data": ["2023", "2024", "2025", "2026"]},
        "series": [{"data": [None, 15.2, None, 38.5], "type": "line", "name": "指标A"}],
    }
    svg = render_svg("含空值折线走势", "line", opt, [])
    assert "<svg" in svg
    assert "15.2" in svg
    assert "38.5" in svg


def test_calc_ticks_coverage():
    from chart_generator.render import _calc_ticks
    # Test case where high is not an exact multiple: 0 to 3.8
    ticks = _calc_ticks(0.0, 3.8, 5)
    assert ticks[0] <= 0.0
    assert ticks[-1] >= 3.8
    # Test negative and positive range
    ticks_neg = _calc_ticks(-48.08, 33.57, 5)
    assert ticks_neg[0] <= -48.08
    assert ticks_neg[-1] >= 33.57


def test_render_svg_heatmap_and_treemap():
    from chart_generator.render import render_svg

    # 1. Heatmap
    hm_opt = {
        "xAxis": {"data": ["企业A", "企业B", "企业C"]},
        "yAxis": {"data": ["ROE", "净现比", "毛利率"]},
        "visualMap": {"min": 0, "max": 100},
        "series": [{"type": "heatmap", "data": [[0, 0, 80], [1, 1, 45], [2, 2, 95]]}],
    }
    svg_hm = render_svg("多指标横向热力图", "heatmap", hm_opt, ["注释说明"])
    assert "<svg" in svg_hm
    assert "企业A" in svg_hm
    assert "ROE" in svg_hm
    assert "80" in svg_hm
    assert "hm_grad" in svg_hm

    # 2. Treemap
    tm_opt = {
        "series": [{
            "type": "treemap",
            "data": [
                {"name": "小米", "value": 6800.5},
                {"name": "工业富联", "value": 5200.0},
                {"name": "立讯精密", "value": 3500.0},
                {"name": "歌尔股份", "value": 800.0},
            ]
        }]
    }
    svg_tm = render_svg("市值规模矩形树", "treemap", tm_opt, ["市值对标"])
    assert "<svg" in svg_tm
    assert "小米" in svg_tm
    assert "工业富联" in svg_tm
    assert "6800.5" in svg_tm or "6801" in svg_tm or "68.0亿" in svg_tm or "6800" in svg_tm

    # 3. Boxplot
    box_opt = {
        "xAxis": {"type": "category", "data": ["材料", "电池", "整车"]},
        "yAxis": {"type": "value"},
        "series": [{
            "type": "boxplot",
            "data": [
                [10.0, 15.0, 22.0, 30.0, 42.0],
                [12.0, 18.0, 25.0, 35.0, 48.0],
                [8.0, 14.0, 20.0, 28.0, 38.0],
            ]
        }]
    }
    svg_box = render_svg("细分赛道估值分布", "boxplot", box_opt, ["分位数样本统计"])
    assert "<svg" in svg_box
    assert "细分赛道估值分布" in svg_box
    assert "材料" in svg_box
    assert "电池" in svg_box
    assert "整车" in svg_box
    assert "22" in svg_box


def test_render_all_twelve_benchmark_chart_types():
    """Verify that all 12 institutional chart types render publication-grade SVGs without error."""
    from chart_generator.render import render_svg

    benchmark_cases = [
        ("line", "营业收入趋势", {"xAxis": {"data": ["2021", "2022", "2023"]}, "series": [{"type": "line", "data": [100, 150, 220]}]}),
        ("horizontal_bar", "全球动力电池装机份额", {"xAxis": {"type": "value"}, "yAxis": {"data": ["企业A", "企业B"]}, "series": [{"type": "bar", "data": [35.5, 18.2]}]}),
        ("combo", "市场规模与同比增速", {"xAxis": {"data": ["2021", "2022", "2023"]}, "series": [{"name": "规模", "type": "bar", "data": [1000, 1500, 2100]}, {"name": "增速", "type": "line", "data": [25.0, 50.0, 40.0]}]}),
        ("area", "营业收入历史与预测", {"xAxis": {"data": ["2021", "2022", "2023"]}, "series": [{"type": "line", "areaStyle": {}, "data": [120, 180, 260]}]}),
        ("donut", "全球动力电池市场构成", {"series": [{"type": "pie", "radius": ["40%", "70%"], "data": [{"name": "宁德时代", "value": 37.0}, {"name": "比亚迪", "value": 16.0}]}]}),
        ("radar", "龙头企业综合能力", {"radar": {"indicator": [{"name": "盈利能力", "max": 100}, {"name": "成长性", "max": 100}]}, "series": [{"type": "radar", "data": [{"value": [85, 90], "name": "龙头A"}]}]}),
        ("scatter", "企业估值定位", {"xAxis": {"type": "value"}, "yAxis": {"type": "value"}, "series": [{"type": "scatter", "data": [[15.2, 28.5], [22.0, 15.0]]}]}),
        ("bubble", "份额、增速与收入规模", {"xAxis": {"type": "value"}, "yAxis": {"type": "value"}, "series": [{"type": "scatter", "data": [["企业A", 15.2, 28.5, 30.0], ["企业B", 22.0, 15.0, 15.0]]}]}),
        ("heatmap", "企业能力矩阵", {"xAxis": {"data": ["A", "B"]}, "yAxis": {"data": ["ROE", "毛利"]}, "series": [{"type": "heatmap", "data": [[0, 0, 85], [1, 1, 92]]}]}),
        ("boxplot", "细分赛道估值分布", {"xAxis": {"data": ["赛道1", "赛道2"]}, "series": [{"type": "boxplot", "data": [[10, 15, 20, 25, 30], [12, 16, 22, 28, 35]]}]}),
        ("treemap", "产业链收入构成", {"series": [{"type": "treemap", "data": [{"name": "环节A", "value": 500}, {"name": "环节B", "value": 300}]}]}),
        ("industry_chain", "动力电池产业链", {"series": [{"type": "graph", "data": [{"name": "锂矿", "category": 0}, {"name": "电芯", "category": 1}, {"name": "新能源车", "category": 2}], "links": [{"source": "锂矿", "target": "电芯"}]}]}),
    ]

    for ctype, title, opt in benchmark_cases:
        svg = render_svg(title, ctype, opt, ["来源：测试"])
        assert "<svg" in svg, f"Failed for {ctype}"
        assert title in svg, f"Title missing for {ctype}"


def test_llm_chart_spec_with_empty_option_synthesizes_automatically(tmp_path):
    class LightweightMockLLM:
        @property
        def is_available(self) -> bool:
            return True

        async def run_skill_and_chart_loop(self, system_prompt, user_prompt, tools, skill_resolver):
            called_skills = [{"skill_name": "financial-charting", "reason": "测试轻量级规范"}]
            chart_json = {
                "charts": [
                    {
                        "title": "企业利润增长率对比",
                        "chart_type": "bar",
                        "insight_goal": "快速比对",
                        "recommended_chapter_id": "CH-04",
                        "evidence_ids": ["R1", "R2", "R3"],
                        "footnotes": ["单位：%"],
                        "option": {},
                    },
                    {
                        "title": "市场规模趋势",
                        "chart_type": "line",
                        "insight_goal": "时序分析",
                        "recommended_chapter_id": "CH-02",
                        "evidence_ids": ["R4", "R5", "R6"],
                        "footnotes": ["单位：亿元"],
                        "option": None,
                    }
                ],
                "suppressed_charts": [],
            }
            return called_skills, chart_json

    agent = ChartGeneratorAgent(llm=LightweightMockLLM())
    agent.settings = type(agent.settings)(output_dir=tmp_path)
    result = asyncio.run(agent.run(ChartGenerationRequest(report=report_payload())))

    assert len(result.charts) == 2
    for chart in result.charts:
        assert chart.option
        assert "series" in chart.option
        assert (tmp_path / "runs" / result.run_id / "charts" / f"{chart.chart_id}.svg").is_file()


def test_scatter_radar_combo_donut_compiler_diversity():
    from chart_generator.compiler import EChartsCompiler
    from chart_generator.data_formulation import DataFormulator

    evidence = {
        "E1": {"record_id": "E1", "domain": "financials", "entity": "阳光电源", "metric": "市盈率", "value": 33.27, "unit": "倍"},
        "E2": {"record_id": "E2", "domain": "financials", "entity": "德业股份", "metric": "市盈率", "value": 82.20, "unit": "倍"},
        "E3": {"record_id": "E3", "domain": "financials", "entity": "特变电工", "metric": "市盈率", "value": -48.70, "unit": "倍"},
        "E4": {"record_id": "E4", "domain": "financials", "entity": "阳光电源", "metric": "市净率", "value": 9.09, "unit": "倍"},
        "E5": {"record_id": "E5", "domain": "financials", "entity": "德业股份", "metric": "市净率", "value": 39.37, "unit": "倍"},
        "E6": {"record_id": "E6", "domain": "financials", "entity": "特变电工", "metric": "市净率", "value": 4.82, "unit": "倍"},
        "E7": {"record_id": "E7", "domain": "financials", "entity": "阳光电源", "metric": "总市值", "value": 1834.17, "unit": "亿元"},
        "E8": {"record_id": "E8", "domain": "financials", "entity": "德业股份", "metric": "总市值", "value": 1043.71, "unit": "亿元"},
        "E9": {"record_id": "E9", "domain": "financials", "entity": "阳光电源", "metric": "a股流通市值", "value": 1404.97, "unit": "亿元"},
        "E10": {"record_id": "E10", "domain": "financials", "entity": "德业股份", "metric": "a股流通市值", "value": 1041.62, "unit": "亿元"},
        "E11": {"record_id": "E11", "domain": "financials", "entity": "阳光电源", "metric": "营业收入", "value": 722.5, "unit": "亿元"},
        "E12": {"record_id": "E12", "domain": "financials", "entity": "阳光电源", "metric": "净利润", "value": 94.4, "unit": "亿元"},
        "E13": {"record_id": "E13", "domain": "financials", "entity": "阳光电源", "metric": "资产负债率", "value": 66.3, "unit": "%"},
    }
    report = InterpretationReport.model_validate({"report_id": "DIV", "subject": "多样性测试", "as_of": "2026-09-01", "status": "completed", "evidence_index": evidence})

    # 1. Test Scatter formulation and compilation
    scatter_table = DataFormulator.formulate(["E1", "E2", "E3", "E4", "E5", "E6"], report, target_chart_type="scatter")
    assert scatter_table is not None
    assert len(scatter_table.categories) == 3
    scatter_opt = EChartsCompiler.compile(scatter_table, "scatter", "PE-PB四象限散点定位")
    assert scatter_opt["series"][0]["type"] == "scatter"
    assert scatter_opt["xAxis"]["type"] == "value"
    assert scatter_opt["yAxis"]["type"] == "value"
    assert len(scatter_opt["series"][0]["data"]) == 3
    assert "markLine" in scatter_opt["series"][0]

    # 2. Test Combo formulation (market cap + float ratio) and compilation
    combo_table = DataFormulator.formulate(["E7", "E8", "E9", "E10"], report, target_chart_type="combo")
    assert combo_table is not None
    assert combo_table.secondary_series_name == "流通市值占比"
    combo_opt = EChartsCompiler.compile(combo_table, "combo", "总市值与流通占比双轴组合")
    assert combo_opt["series"][0]["type"] == "bar"
    assert combo_opt["series"][1]["type"] == "line"
    assert combo_opt["series"][0]["data"] != combo_opt["series"][1]["data"]

    # 3. Test Radar formulation and compilation
    radar_table = DataFormulator.formulate(["E11", "E12", "E13"], report, target_chart_type="radar")
    assert radar_table is not None
    radar_opt = EChartsCompiler.compile(radar_table, "radar", "阳光电源财务画像")
    assert radar_opt["series"][0]["type"] == "radar"
    assert len(radar_opt["radar"]["indicator"]) == 3

    # 4. Test Donut formulation and compilation
    donut_table = DataFormulator.formulate(["E7", "E8"], report, target_chart_type="donut")
    assert donut_table is not None
    donut_opt = EChartsCompiler.compile(donut_table, "donut", "龙头市值构成")
    assert donut_opt["series"][0]["type"] == "pie"
    assert donut_opt["series"][0]["radius"] == ["36%", "68%"]


def test_chart_data_demands_generation():
    evidence = {
        "E1": {"record_id": "E1", "domain": "companies", "entity": "隆基绿能", "metric": "revenue", "value": 100.0, "unit": "亿元", "period": "2024-09-30"},
        "E2": {"record_id": "E2", "domain": "companies", "entity": "通威股份", "metric": "revenue", "value": 80.0, "unit": "亿元", "period": "2024-09-30"},
    }
    report = InterpretationReport.model_validate({
        "report_id": "DMD-REP",
        "subject": "光伏设备",
        "as_of": "2026-09-01",
        "status": "completed",
        "evidence_index": evidence,
        "comps_matrix": [{"entity_name": "隆基绿能"}, {"entity_name": "通威股份"}],
    })
    req = ChartGenerationRequest(
        report=report,
        preferences=ChartPreferences(requested_types=["combo", "industry_chain", "donut"])
    )
    agent = ChartGeneratorAgent()
    res = asyncio.run(agent.run(req, save_artifacts=False))
    assert res.data_demands
    demand_domains = {d.domain for d in res.data_demands}
    assert "financials" in demand_domains
    time_demand = next((d for d in res.data_demands if "TIME" in d.demand_id), None)
    assert time_demand is not None
    assert "隆基绿能" in time_demand.query_hint or "通威股份" in time_demand.query_hint


def test_metric_level_deduplication_prevents_redundant_charts():
    evidence = {
        "R1": {"record_id": "R1", "domain": "financials", "entity": "企业A", "metric": "经营活动现金流增长率", "value": -15.0, "unit": "%", "period": "2026-06-30"},
        "R2": {"record_id": "R2", "domain": "financials", "entity": "企业B", "metric": "经营活动现金流增长率", "value": 30.0, "unit": "%", "period": "2026-06-30"},
        "R3": {"record_id": "R3", "domain": "financials", "entity": "企业C", "metric": "经营活动现金流增长率", "value": 45.0, "unit": "%", "period": "2026-06-30"},
        "R4": {"record_id": "R4", "domain": "financials", "entity": "企业A", "metric": "营业收入", "value": 100.0, "unit": "亿元", "period": "2026-06-30"},
        "R5": {"record_id": "R5", "domain": "financials", "entity": "企业B", "metric": "营业收入", "value": 150.0, "unit": "亿元", "period": "2026-06-30"},
    }
    report = InterpretationReport.model_validate({
        "report_id": "DEDUP-REP",
        "subject": "测试行业",
        "as_of": "2026-09-01",
        "status": "completed",
        "evidence_index": evidence,
    })
    req = ChartGenerationRequest(report=report)
    agent = ChartGeneratorAgent()
    res = asyncio.run(agent.run(req, save_artifacts=False))
    bar_charts = [c for c in res.charts if c.chart_type in ("bar", "horizontal_bar", "comparison_bar", "diverging_bar")]
    metrics_in_bars = []
    for c in bar_charts:
        m = report.evidence_index[c.evidence_ids[0]].metric
        metrics_in_bars.append(m)
    assert len(metrics_in_bars) == len(set(metrics_in_bars)), f"Duplicate metric detected in bars: {metrics_in_bars}"


def test_render_type_safety_against_raw_floats_and_nested_lists():
    """Verify render_svg handles raw numbers, lists of floats, nested lists, and non-dicts defensively."""
    # 1. Industry chain with raw floats
    svg_chain_floats = render_svg("产业链浮点测试", "industry_chain", {"series": [{"data": [12.5, 34.2, 50.1]}]}, [])
    assert "<svg" in svg_chain_floats

    # 2. Industry chain with mixed raw strings and objects
    svg_chain_mixed = render_svg("产业链混合测试", "industry_chain", {"series": [{"data": [{"name": "上游矿产", "category": 0}, 42.0, "下游整车"]}]}, [])
    assert "<svg" in svg_chain_mixed

    # 3. Pie / donut with raw float data
    svg_pie = render_svg("饼图浮点测试", "pie", {"series": [{"data": [10.5, 20.3, 40.2]}]}, [])
    assert "<svg" in svg_pie
    svg_donut = render_svg("环形图浮点测试", "donut", {"series": [{"data": [10.5, 20.3, 40.2]}]}, [])
    assert "<svg" in svg_donut

    # 4. Radar with nested list [[80, 70]]
    svg_radar_nested = render_svg("雷达嵌套测试", "radar", {"series": [{"data": [[80, 70, 90]]}]}, [])
    assert "<svg" in svg_radar_nested

    # 5. Radar with float list [80, 70]
    svg_radar_floats = render_svg("雷达浮点测试", "radar", {"series": [{"data": [80, 70, 90]}]}, [])
    assert "<svg" in svg_radar_floats






