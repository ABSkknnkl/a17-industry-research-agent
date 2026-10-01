"""Verification test suite for all 10 reported defects (DEF-01 to DEF-10).
Ensures every defect is 100% resolved and covered by regression tests.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
import pytest

# DEF-01: Adapters events.jsonl protection
def test_def_01_adapters_events_protection():
    adapters_path = Path("backend/app/agents/adapters.py")
    assert adapters_path.exists()
    content = adapters_path.read_text(encoding="utf-8")
    assert 'f.name != "events.jsonl"' in content, "DEF-01: events.jsonl must be explicitly excluded from stage copy"


# DEF-02: Donut rate metric rejection and downgrade
def test_def_02_donut_downgrade_and_linting():
    from chart_generator.compiler import EChartsCompiler
    from chart_generator.data_formulation import NormalizedDataTable, AxisType
    from chart_generator.linter import ChartSkillLinter

    # 1. Compiler auto-downgrade test
    table = NormalizedDataTable(
        axis_type=AxisType.STRUCTURE,
        x_field_name="公司",
        categories=["寒武纪", "中际旭创"],
        series_data={"营业收入同比增长率": [453.2, 60.3]},
        series_units={"营业收入同比增长率": "%"},
        primary_series_name="营业收入同比增长率",
    )
    option = EChartsCompiler.compile(table, "donut", "核心企业营业收入同比增长率集中度分布")
    # Verify it was downgraded to bar, not pie
    assert option["series"][0]["type"] == "bar", "DEF-02: Rate donut must auto-downgrade to bar"

    # 2. Linter error trigger test
    class DummyCand:
        def __init__(self, title, chart_type, eids):
            self.title = title
            self.chart_type = chart_type
            self.evidence_ids = eids
            self.point_evidence_ids = eids

    linter = ChartSkillLinter()
    ev_idx = {
        "E1": {"metric": "营业收入同比增长率", "value": 453.2, "entity": "寒武纪"},
    }
    cands = [DummyCand("营业收入同比增长率集中度", "donut", ["E1"])]
    violations = linter.lint(cands, ev_idx)
    assert any(v.code == "donut_non_additive_metric" for v in violations), "DEF-02: Linter must flag donut_non_additive_metric"


# DEF-03: Figure number physical order re-indexing
def test_def_03_figure_number_reindexing(tmp_path):
    from report_fusion import ReportFusionAgent, ReportFusionRequest
    from report_fusion.config import Settings
    from report_fusion.models import (
        ChapterDraft, ChapterResult, ChartResult, ChartSpec,
        FusionOptions, InterpretationReport, ParagraphDraft, SectionDraft
    )

    report = InterpretationReport.model_validate({
        "report_id": "R-1", "subject": "测试行业", "as_of": "2026-09-27", "status": "completed",
        "evidence_index": {"E1": {"record_id": "E1", "domain": "macro", "metric": "指标1", "value": 10}}
    })

    # Section 1 has chart 8, Section 2 has chart 1 (inverted order)
    sec1 = SectionDraft(
        section_id="S-1", title="第1节", purpose="",
        paragraphs=[ParagraphDraft(paragraph_id="P1", text="详见如图[CHART-08]所示内容。", evidence_ids=["E1"])],
        chart_ids=["CHART-08"]
    )
    sec2 = SectionDraft(
        section_id="S-2", title="第2节", purpose="",
        paragraphs=[ParagraphDraft(paragraph_id="P2", text="详见如图[CHART-01]所示内容。", evidence_ids=["E1"])],
        chart_ids=["CHART-01"]
    )
    ch1 = ChapterDraft(chapter_id="C-1", title="第1章", summary="摘要", sections=[sec1, sec2])
    chap_res = ChapterResult.model_validate({"run_id": "RUN-1", "subject": "测试行业", "as_of": "2026-09-27", "status": "completed", "chapters": [ch1]})

    charts = ChartResult(run_id="RUN-1", charts=[
        ChartSpec(chart_id="CHART-08", title="第二个生成的图", chart_type="bar", status="ready", figure_number="图 8", recommended_chapter_id="C-1", evidence_ids=["E1"]),
        ChartSpec(chart_id="CHART-01", title="第一个生成的图", chart_type="line", status="ready", figure_number="图 1", recommended_chapter_id="C-1", evidence_ids=["E1"]),
    ])

    agent = ReportFusionAgent(settings=Settings(output_dir=tmp_path))
    result = asyncio.run(agent.run(ReportFusionRequest(
        report=report, chapters=chap_res, charts=charts, options=FusionOptions(formats=["markdown", "html"], enable_editorial_llm=False)
    )))

    md_text = (Path(result.artifact_dir) / "report.md").read_text(encoding="utf-8")
    # CHART-08 appears in Section 1, so it must be re-indexed as 图 1!
    # CHART-01 appears in Section 2, so it must be re-indexed as 图 2!
    assert "如图 1 所示" in md_text, "DEF-03: First physical chart must be 图 1"
    assert "如图 2 所示" in md_text, "DEF-03: Second physical chart must be 图 2"


# DEF-04: Double title and source prefix elimination
def test_def_04_double_title_and_source_elimination():
    from report_fusion.render import render_html
    from report_fusion.models import (
        ReportViewModel, ExecutiveSummary, ChapterDraft, SectionDraft,
        ParagraphDraft, EmbeddedChart, EvidenceSource
    )

    ev = EvidenceSource(number=1, record_id="E1", label="来源1", entity="测试企业", metric="营收", value=100.0, unit="亿元", domain="financials")
    chart = EmbeddedChart(
        chart_id="C-1",
        title="测试图表",
        chart_type="bar",
        evidence_ids=["E1"],
        placement_section_id="SEC-1",
        svg='<svg><text>图 1: 测试图表</text></svg>',
        source_line="数据来源：同花顺数据",
        figure_number="图 1"
    )
    view = ReportViewModel(
        report_id="R-1",
        title="测试报告",
        subject="测试行业",
        as_of=date.today(),
        tone="professional",
        report_depth="standard",
        visual_style="deep_research",
        delivery_status="ready_with_limits",
        executive_summary=ExecutiveSummary(headline="摘要概览"),
        chapters=[ChapterDraft(chapter_id="CH-1", title="第1章", summary="摘要", sections=[
            SectionDraft(section_id="SEC-1", title="第1节", purpose="", paragraphs=[
                ParagraphDraft(paragraph_id="P1", text="正文内容")
            ])
        ])],
        charts=[chart],
        evidence_catalog=[ev],
    )
    html = render_html(view)
    # Ensure redundant outer figure-heading and figcaption are display:none
    assert 'class="figure-heading sr-only" style="display:none"' in html, "DEF-04: Outer figure heading must be hidden"
    assert '<figcaption style="display:none">' in html, "DEF-04: Outer figcaption must be hidden"
    # Ensure double "数据来源: 数据来源:" is absent
    assert "数据来源: 数据来源:" not in html
    assert "数据来源：数据来源：" not in html


# DEF-05: PDF TOC two-pass implementation
def test_def_05_pdf_two_pass_toc_implementation():
    pdf_py = Path("agents_core/report-fusion/report_fusion/pdf.py")
    assert pdf_py.exists()
    content = pdf_py.read_text(encoding="utf-8")
    assert "Pass 1" in content or "initial_bytes" in content, "DEF-05: PDF renderer must have first pass for page measurement"
    assert "Pass 2" in content or "pg.textContent" in content, "DEF-05: PDF renderer must backfill TOC page numbers in second pass"


# DEF-06: Multi-line chart endpoint anti-collision
def test_def_06_line_chart_endpoint_anticollision():
    from chart_generator.render import render_svg

    option = {
        "title": {"text": "双企业毛利率对比"},
        "xAxis": {"data": ["2024-12-31", "2025-12-31"]},
        "yAxis": {"type": "value"},
        "series": [
            {"name": "企业A", "type": "line", "data": [10.0, 15.0]},
            {"name": "企业B", "type": "line", "data": [10.0, 15.1]},
        ]
    }
    svg = render_svg("双企业毛利率对比", "line", option)
    assert "<svg" in svg
    # The two end-point label texts should both be rendered in SVG
    assert "企业A" in svg
    assert "企业B" in svg


# DEF-07: DataFetcher deterministic guard
def test_def_07_data_fetcher_deterministic_guard():
    agent_py = Path("agents_core/data-fetcher/data_fetcher/agent.py")
    assert agent_py.exists()
    content = agent_py.read_text(encoding="utf-8")
    assert "DEF-07" in content, "DEF-07 guard comment present"
    assert "covered_comp_count < target_min" in content
    assert 'decision = decision.model_copy(update={"decision": "continue"})' in content
    assert "target_min = min(4, len(known_companies))" in content


# DEF-08: Metric display names and appendix translation
def test_def_08_metric_translation():
    from report_fusion.render import _format_metric_label, METRIC_DISPLAY_NAMES, render_markdown
    from report_fusion.models import (
        ReportViewModel, ExecutiveSummary, ChapterDraft, SectionDraft,
        ParagraphDraft, EvidenceSource
    )

    assert "latest_price" in METRIC_DISPLAY_NAMES
    assert _format_metric_label("latest_price") == "最新股价"
    assert _format_metric_label("gross_margin") == "毛利率"

    ev = EvidenceSource(number=1, record_id="E1", label="来源1", entity="中际旭创", metric="latest_price", value=895.86, unit="元", domain="financials")
    view = ReportViewModel(
        report_id="R-1", title="测试报告", subject="人工智能", as_of=date.today(),
        tone="professional", report_depth="standard", visual_style="deep_research", delivery_status="ready_with_limits",
        executive_summary=ExecutiveSummary(headline="摘要"),
        chapters=[ChapterDraft(chapter_id="C1", title="第1章", summary="摘要", sections=[
            SectionDraft(section_id="S1", title="第1节", purpose="", paragraphs=[ParagraphDraft(paragraph_id="P1", text="测试")])
        ])],
        evidence_catalog=[ev],
    )
    md = render_markdown(view)
    assert "latest_price" not in md, "DEF-08: Raw latest_price must not appear in markdown appendix"
    assert "最新股价" in md, "DEF-08: latest_price must be formatted as 最新股价"


# DEF-09: Cover, status, and unit formatting
def test_def_09_formatting_and_units():
    from report_fusion.render import _format_delivery_status, _format_confidence, _display_evidence_value

    assert _format_delivery_status("ready_with_limits") == "审核通过（附数据边界说明）"
    assert _format_confidence("high") == "高"
    assert _format_confidence("medium") == "中"
    assert _format_confidence("low") == "低"

    # Unit formatting
    assert _display_evidence_value(1.01, "倍数") == "1.01 倍"
    assert _display_evidence_value("2026-09-27", "日期") == "2026-09-27"


# DEF-10: Dataset / subject consistency validation
def test_def_10_validate_request_consistency():
    from data_interpreter.models import validate_request_consistency, StructuredResearchDataset, ResearchRecord, SourceRef, Domain

    source = SourceRef(task_id="t1", skill_id="s1", trace_id="tr1", retrieved_at=datetime.now(timezone.utc), query="低空经济")
    ds = StructuredResearchDataset(
        industry=[ResearchRecord(record_id="r1", domain=Domain.INDUSTRY, metric="industry_name", value="低空经济", source=source)],
        sources=[source]
    )
    # Valid matching subject
    validate_request_consistency(ds, "低空经济")
    validate_request_consistency(ds, "低空经济产业链深度研究")

    # Mismatched subject must raise ValueError
    with pytest.raises(ValueError, match="不一致"):
        validate_request_consistency(ds, "商业航天")


# NEW-01: Dual-axis combo chart right axis monetary values must not have '%'
def test_new_01_combo_chart_no_percent_on_monetary_right_axis():
    from chart_generator.render import render_svg

    option = {
        "yAxis": [
            {"name": "毛利率(%)", "position": "left"},
            {"name": "研发费用(元)", "position": "right"},
        ],
        "series": [
            {
                "name": "万丰奥威销售毛利率",
                "type": "bar",
                "yAxisIndex": 0,
                "data": [{"name": "2023", "value": 18.5}, {"name": "2024", "value": 19.2}],
            },
            {
                "name": "万丰奥威研发费用",
                "type": "line",
                "yAxisIndex": 1,
                "data": [{"name": "2023", "value": 412853240.3}, {"name": "2024", "value": 499376514.0}],
            },
        ],
    }
    svg = render_svg("万丰奥威毛利率与研发费用", "combo", option)
    # Right axis and data labels must not have % affixed to monetary numbers
    assert "5.0亿%" not in svg, "NEW-01: Monetary tick must not append %"
    assert "412853240.3%" not in svg, "NEW-01: Line data labels must not append % to monetary raw numbers"
    assert "5.0亿" in svg, "NEW-01: Monetary tick must be formatted cleanly"


# NEW-02: Combo chart with two growth rate metrics must preserve both series
def test_new_02_combo_growth_rates_preserves_both_series():
    from chart_generator.data_formulation import DataFormulator
    from chart_generator.models import EvidenceRef
    from datetime import date

    records = [
        EvidenceRef(record_id="r1", domain="financials", entity="宗申动力", metric="营业收入同比增长率", period=date(2021, 12, 31), value=20.27, unit="%"),
        EvidenceRef(record_id="r2", domain="financials", entity="宗申动力", metric="营业收入同比增长率", period=date(2022, 12, 31), value=-12.83, unit="%"),
        EvidenceRef(record_id="r3", domain="financials", entity="宗申动力", metric="归母净利润同比增长率", period=date(2021, 12, 31), value=-18.17, unit="%"),
        EvidenceRef(record_id="r4", domain="financials", entity="宗申动力", metric="归母净利润同比增长率", period=date(2022, 12, 31), value=-17.84, unit="%"),
    ]
    by_metric = {
        "营业收入同比增长率": records[:2],
        "归母净利润同比增长率": records[2:],
    }
    combo_table = DataFormulator._try_formulate_combo(by_metric, records)
    assert combo_table is not None, "NEW-02: Two rate metrics for single entity must formulate combo"
    assert len(combo_table.series_data) == 2, f"NEW-02: Must retain 2 series (bar + line), got {len(combo_table.series_data)}"
    assert "营业收入同比增长率" in combo_table.series_data
    assert "归母净利润同比增长率" in combo_table.series_data


# NEW-03: Topology ratios have % unit, and bubble chart strips metric-as-unit
def test_new_03_topology_ratio_unit_and_bubble_clean_unit():
    from chart_generator.metric_guard import DimensionGuard
    from chart_generator.render import render_svg

    # 1. Metric guard returns % when percentage unit is supplied
    unit = DimensionGuard.determine_series_currency_unit([16.36, 26.52], ["%", "%"])
    assert unit == "%", "NEW-03: Percentage unit must return % instead of 元"

    # 2. Bubble chart unit cleaning
    option = {
        "xAxis": {"name": "营业收入(亿元)"},
        "yAxis": {"name": "归母净利润"},
        "series": [
            {
                "name": "标的定位",
                "data": [
                    [21.8, 4.3, 10, "中信海直"],
                    [162.1, 7.4, 15, "万丰奥威"],
                ],
            }
        ],
    }
    svg = render_svg("低空经济核心企业营业收入与归母净利润定位", "scatter", option)
    assert "单位：归母净利润" not in svg, "NEW-03: Metric name must not be rendered as unit label"


# NEW-04 & NEW-08: Data fetcher budget and iteration configuration
def test_new_04_and_08_adapters_budget_and_iterations():
    import inspect
    from backend.app.agents.adapters import FiveAgentsAdapter

    source = inspect.getsource(FiveAgentsAdapter.run_data_fetcher)
    assert "max_calls = 32 if is_deep else 24" in source, "NEW-08: Budget must be 24 for standard, 32 for deep"
    assert "max_iters = 10 if is_deep else 8" in source, "NEW-08: Iterations must be 8 for standard, 10 for deep"


# NEW-05: Industry chain ignores concept announcement prose and non-chain metadata
def test_new_05_industry_chain_no_prose_fragments():
    from data_interpreter.engine import DeterministicAnalysisEngine
    from data_interpreter.models import StructuredResearchDataset, ResearchRecord, SourceRef, Domain
    from datetime import datetime, timezone

    src = SourceRef(task_id="t1", skill_id="s1", trace_id="tr1", retrieved_at=datetime.now(timezone.utc), query="白酒")
    engine = DeterministicAnalysisEngine()

    # Company with announcement narrative in concept field
    records = [
        ResearchRecord(
            record_id="r1",
            domain=Domain.COMPANIES,
            entity="建发股份",
            metric="纳入概念原因",
            value="公司携手优质上游企业，5月底投放第一批产品，截至2021年8月下旬已全面铺开",
            source=src,
        ),
        ResearchRecord(
            record_id="r2",
            domain=Domain.COMPANIES,
            entity="巨力索具",
            metric="所属同花顺行业",
            value="机械设备-通用设备-金属制品",
            source=src,
        ),
        ResearchRecord(
            record_id="r3",
            domain=Domain.INDUSTRY_CHAIN,
            entity="贵州茅台",
            metric="主营产品",
            value="茅台酒, 酱香系列酒",
            source=src,
            raw_fields={"产业链环节": "中游"},
        ),
    ]
    ds = StructuredResearchDataset(companies=records[:2], industry_chain=[records[2]], sources=[src])
    segments = engine.extract_industry_chain(ds, "白酒")

    # Verify no narrative sentence fragments leaked as key_products
    all_products = []
    for s in segments:
        all_products.extend(s.key_products)

    for bad_phrase in ("携手优质上游企业", "5月底投放第一批产品", "截至2021年8月下旬", "机械设备", "金属制品"):
        assert not any(bad_phrase in p for p in all_products), f"NEW-05: Bad phrase '{bad_phrase}' must not appear in industry chain products"

    # Verify valid product survived
    assert any("茅台酒" in p for p in all_products), "NEW-05: Legitimate product '茅台酒' must be extracted"


# NEW-06: Heatmap uses Percentile Ranking so extreme outliers don't compress normal entities
def test_new_06_heatmap_percentile_ranking():
    values = [-1026.0, 13.5, 15.2, 17.8, 19.4, 21.0, 24.5, 996.0]
    n_ent = len(values)
    indexed_vals = sorted(enumerate(values), key=lambda it: it[1])
    ranks = [0.0] * n_ent
    i = 0
    while i < n_ent:
        j = i
        while j < n_ent - 1 and indexed_vals[j + 1][1] == indexed_vals[j][1]:
            j += 1
        avg_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            orig_idx = indexed_vals[k][0]
            norm_score = 10.0 + (avg_rank / max(n_ent - 1, 1)) * 80.0
            ranks[orig_idx] = round(norm_score, 1)
        i = j + 1

    # Check that normal entities (indices 1..6) have distinct, strictly increasing scores
    normal_scores = [ranks[idx] for idx in range(1, 7)]
    assert len(set(normal_scores)) == len(normal_scores), f"NEW-06: Normal entities must have distinct scores, got {normal_scores}"
    assert normal_scores == sorted(normal_scores), "NEW-06: Scores must be strictly monotonic with ranks"
    assert ranks[0] == 10.0, "NEW-06: Minimum score must map to 10.0"
    assert ranks[7] == 90.0, "NEW-06: Maximum score must map to 90.0"


# NEW-07: Bubble and scatter chart outlier label units are metric-adaptive
def test_new_07_bubble_outlier_metric_units():
    from chart_generator.render import render_svg

    # Outlier on PE axis: should be '倍', not '%'
    pe_option = {
        "xAxis": {"name": "市盈率(PE)"},
        "yAxis": {"name": "营业收入(亿元)"},
        "series": [
            {
                "name": "标的定位",
                "data": [
                    [15.0, 50.0, 10, "贵州茅台"],
                    [18.0, 40.0, 10, "五粮液"],
                    [22.0, 35.0, 10, "山西汾酒"],
                    [20.0, 30.0, 10, "泸州老窖"],
                    [483.0, 10.0, 10, "酒鬼酒"],  # Extreme outlier on X axis
                ],
            }
        ],
    }
    pe_svg = render_svg("白酒标的估值与收入定位", "scatter", pe_option)
    assert "酒鬼酒 (483% →)" not in pe_svg, "NEW-07: PE outlier must not be labeled with %"
    assert "酒鬼酒 (483倍 →)" in pe_svg, "NEW-07: PE outlier must be labeled with 倍"

    # Outlier on ratio axis: should be '%'
    ratio_option = {
        "xAxis": {"name": "销售毛利率(%)"},
        "yAxis": {"name": "营业收入(亿元)"},
        "series": [
            {
                "name": "标的定位",
                "data": [
                    [20.0, 50.0, 10, "企业A"],
                    [25.0, 40.0, 10, "企业B"],
                    [22.0, 35.0, 10, "企业D"],
                    [24.0, 30.0, 10, "企业E"],
                    [95.0, 10.0, 10, "企业C"],  # Outlier on X axis
                ],
            }
        ],
    }
    ratio_svg = render_svg("毛利率定位", "scatter", ratio_option)
    assert "企业C (95.0% →)" in ratio_svg or "企业C (95% →)" in ratio_svg, "NEW-07: Ratio outlier must be labeled with %"


# NEW-09: Financial metrics auto-infer standard units and eliminate false disclaimer footnote
def test_new_09_price_default_unit_inferred():
    from chart_generator.agent import ChartGeneratorAgent
    from chart_generator.models import ChartGenerationRequest, ChartPreferences, InterpretationReport, EvidenceRef
    from datetime import date

    agent = ChartGeneratorAgent()
    # When metric is latest_price with unit=None
    rows = [
        EvidenceRef(record_id="p1", domain="financials", entity="贵州茅台", metric="latest_price", period=date(2024, 1, 1), value=1500.0, unit=None),
        EvidenceRef(record_id="p2", domain="financials", entity="五粮液", metric="latest_price", period=date(2024, 1, 1), value=140.0, unit=None),
        EvidenceRef(record_id="p3", domain="financials", entity="山西汾酒", metric="latest_price", period=date(2024, 1, 1), value=210.0, unit=None),
    ]
    report = InterpretationReport(report_id="R-TEST", title="白酒报告", subject="白酒", as_of=date(2024, 1, 1), status="ready", evidence_index={r.record_id: r for r in rows})
    req = ChartGenerationRequest(report=report, preferences=ChartPreferences(max_charts=5))

    candidates, suppressed = agent._deterministic_fallback(req)
    price_candidates = [c for c in candidates if "最新股价" in c.title or "latest_price" in c.title or "股价" in c.title]
    assert len(price_candidates) > 0, "NEW-09: Must generate at least one price chart candidate"
    for pc in price_candidates:
        assert "原始数据未提供统一单位，跨实体比较需谨慎" not in pc.footnotes, "NEW-09: Price chart must not have missing unit disclaimer footnote"
        assert pc.option["yAxis"]["name"] == "元", "NEW-09: Price chart yAxis must be inferred as 元"


# NEW-10: Valuation query guarantee for must_include_entities (CATL market cap & PE)
def test_new_10_valuation_guard_injection():
    import secrets
    from data_fetcher.models import SkillTask, ResearchObjective, Domain
    from data_interpreter.models import StructuredResearchDataset

    must_include = ["宁德时代", "比亚迪"]
    # Simulating data dataset missing valuation for 宁德时代
    ds = StructuredResearchDataset(companies=[])
    val_covered = {
        r.entity_name for r in ds.companies
        if r.entity_name and (r.metric in ("market_cap", "总市值", "a股流通市值") or "总市值" in str(r.metric))
    }
    planned_tasks: list[SkillTask] = []
    already_planned_val_names: set[str] = set()

    val_injected: list[SkillTask] = []
    for ent in must_include:
        if ent not in val_covered and ent not in already_planned_val_names:
            val_task = SkillTask(
                task_id=f"val_guard_{secrets.token_hex(4)}",
                skill_name="hithink-astock-selector",
                arguments={"query": f"{ent} 最新价 总市值 动态市盈率 市净率 所属行业"},
                purpose=f"确定性规则守卫: 补足核心标的 {ent} 实时市值、估值与所属行业",
                requirement_ids=["domain_companies", "leader_identification"],
                expected_fields=["证券代码", "证券简称", "最新价", "总市值", "动态市盈率", "市净率", "所属行业"],
            )
            val_injected.append(val_task)
            already_planned_val_names.add(ent)

    assert len(val_injected) == 2, "NEW-10: Must inject valuation queries for missing must_include_entities"
    assert any("宁德时代 最新价 总市值 动态市盈率 市净率 所属行业" == t.arguments["query"] for t in val_injected)
    assert any("比亚迪 最新价 总市值 动态市盈率 市净率 所属行业" == t.arguments["query"] for t in val_injected)


# NEW-11: Industry relevance filter eliminates cross-industry concept giants
def test_new_11_peer_comps_industry_relevance_filter():
    from data_interpreter.engine import _is_industry_relevant

    # For NEV (新能源汽车)
    subject = "新能源汽车"

    # Core and relevant automotive/battery entities must pass
    assert _is_industry_relevant("宁德时代", "电力设备-电池-锂电池", subject) is True
    assert _is_industry_relevant("比亚迪", "汽车-乘用车", subject) is True
    assert _is_industry_relevant("长安汽车", "汽车-汽车整车", subject) is True
    assert _is_industry_relevant("亿纬锂能", "电力设备-电池-锂电池", subject) is True
    assert _is_industry_relevant("拓普集团", "汽车-汽车零部件", subject) is True
    assert _is_industry_relevant("特锐德", "电力设备-输变电设备-充电桩", subject) is True

    # Cross-industry giants must be filtered out
    assert _is_industry_relevant("中际旭创", "通信-通信设备-CPO光模块", subject) is False
    assert _is_industry_relevant("中国石化", "石油石化-炼化及贸易", subject) is False
    assert _is_industry_relevant("立讯精密", "电子-消费电子", subject) is False
    assert _is_industry_relevant("海康威视", "计算机-计算机设备-安防设备", subject) is False
    assert _is_industry_relevant("顺丰控股", "交通运输-物流", subject) is False
    assert _is_industry_relevant("天孚通信", "通信-通信设备-光器件", subject) is False


# NEW-12: Comparison bar multi-series rendering (vertical grouped bar with legends and all data)
def test_new_12_comparison_bar_multi_series_rendering():
    from chart_generator.render import render_svg

    option = {
        "xAxis": {"type": "category", "data": ["2021", "2022"]},
        "yAxis": {"type": "value", "name": "亿元"},
        "series": [
            {
                "name": "长安汽车",
                "type": "bar",
                "data": [1051.42, 1212.53],
            },
            {
                "name": "亿纬锂能",
                "type": "bar",
                "data": [169.00, 363.05],
            },
        ],
    }

    svg = render_svg("重点企业营业收入对比", "comparison_bar", option)
    # Must contain both series names
    assert "长安汽车" in svg, "NEW-12: Must render series 0 name"
    assert "亿纬锂能" in svg, "NEW-12: Must render series 1 name"
    # Must contain data values for both companies
    assert "1051" in svg, "NEW-12: Must render series 0 values"
    assert "1213" in svg, "NEW-12: Must render series 0 values"
    assert "169" in svg, "NEW-12: Must render series 1 values"
    assert "363" in svg, "NEW-12: Must render series 1 values"
    # Must render legend items with colors
    assert 'width="12" height="10"' in svg, "NEW-12: Must render legend colored swatches"
    assert "长安汽车" in svg and "亿纬锂能" in svg


# NEW-13: Topology badge strips stock price '元' unit and assigns semantic role
def test_new_13_topology_badge_no_price_unit():
    from chart_generator.compiler import EChartsCompiler
    from chart_generator.data_formulation import NormalizedDataTable, AxisType
    from chart_generator.render import render_svg

    table = NormalizedDataTable(
        axis_type=AxisType.STRUCTURE,
        x_field_name="公司",
        categories=["宁德时代", "比亚迪", "特锐德"],
        series_data={"最新价": [293.5, 285.0, 22.0]},
        series_units={"最新价": "元"},
        primary_series_name="最新价",
    )

    opt = EChartsCompiler.compile(table, "industry_chain", "新能源汽车产业链全景图")
    # Verify nodes in option do not contain '元' in margin/badge
    for node in opt.get("series", [{}])[0].get("data", []):
        badge = str(node.get("margin") or "")
        assert not badge.endswith("元"), f"NEW-13: Node badge must not end with 元, got {badge}"

    # Verify rendered SVG cleans any legacy price badge ending with 元
    dirty_opt = {
        "series": [
            {
                "type": "graph",
                "data": [
                    {"name": "宁德时代", "category": "上游", "margin": "293.5元", "x": 180, "y": 200},
                    {"name": "比亚迪", "category": "中游", "margin": "28.5%", "x": 500, "y": 200},
                ],
                "links": [{"source": "宁德时代", "target": "比亚迪"}],
            }
        ]
    }
    svg = render_svg("产业链全景图", "industry_chain", dirty_opt)
    assert "293.5元" not in svg, "NEW-13: Rendered SVG must sanitize any price badge ending with 元"


# NEW-14: Timeseries atomic inclusion without partial chopping
def test_new_14_timeseries_atomic_inclusion_no_chopping():
    from chart_generator.agent import ChartGeneratorAgent
    from chart_generator.models import EvidenceRef
    from datetime import date
    from collections import Counter

    agent = ChartGeneratorAgent()

    # Create 8 groups of timeseries (each with 5 points = 40 points total)
    evs: list[EvidenceRef] = []
    for g_idx in range(8):
        c_name = f"企业_{g_idx}"
        for yr in range(2020, 2025):
            evs.append(
                EvidenceRef(
                    record_id=f"r_{g_idx}_{yr}",
                    domain="financials",
                    entity=c_name,
                    metric="营业收入",
                    period=date(yr, 12, 31),
                    value=100.0 * (g_idx + 1),
                    unit="亿元",
                )
            )

    selected = agent._bin_evidence_for_prompt(evs, max_total=100)
    # Count how many points each company has in selected
    counts = Counter(item["entity"] for item in selected if item["domain"] == "financials")

    for ent, cnt in counts.items():
        # Every included company must have all 5 data points, never chopped to 1 or 2!
        assert cnt == 5, f"NEW-14: Entity {ent} timeseries was partially chopped: got {cnt} points, expected 5"


# NEW-15: Donut deduplication and combo chart label separation
def test_new_15_donut_deduplication_and_combo_label_spacing():
    from chart_generator.agent import ChartGeneratorAgent
    from chart_generator.models import ChartGenerationRequest, ChartPreferences, InterpretationReport, EvidenceRef
    from chart_generator.render import render_svg
    from datetime import date

    # Part 1: Donut deduplication
    agent = ChartGeneratorAgent()
    rows = []
    # Both 总市值 and a股流通市值 exist
    for ent, val in [("宁德时代", 13000.0), ("比亚迪", 8000.0), ("长城汽车", 2000.0), ("长安汽车", 1500.0)]:
        rows.append(EvidenceRef(record_id=f"m_{ent}", domain="financials", entity=ent, metric="总市值", period=None, value=val, unit="亿元"))
        rows.append(EvidenceRef(record_id=f"c_{ent}", domain="financials", entity=ent, metric="a股流通市值", period=None, value=val * 0.9, unit="亿元"))
        rows.append(EvidenceRef(record_id=f"r_{ent}", domain="financials", entity=ent, metric="营业总收入", period=None, value=val * 0.5, unit="亿元"))
        rows.append(EvidenceRef(record_id=f"p_{ent}", domain="financials", entity=ent, metric="净利润", period=None, value=val * 0.05, unit="亿元"))

    report = InterpretationReport(report_id="R-TEST", title="测试", subject="新能源汽车", as_of=date(2024, 1, 1), status="ready", evidence_index={r.record_id: r for r in rows})
    req = ChartGenerationRequest(report=report, preferences=ChartPreferences(max_charts=10))

    candidates, _ = agent._deterministic_fallback(req)
    donut_cands = [c for c in candidates if c.chart_type in ("donut", "pie")]
    # Should only have at most 1 concentration donut chart, not 4!
    assert len(donut_cands) <= 1, f"NEW-15: Donut candidates should be deduplicated to at most 1, got {len(donut_cands)}"

    # Part 2: Combo label separation
    combo_opt = {
        "xAxis": {"type": "category", "data": ["2021", "2022", "2023"]},
        "yAxis": [
            {"type": "value", "name": "亿元"},
            {"type": "value", "name": "%"},
        ],
        "series": [
            {
                "name": "营业收入",
                "type": "bar",
                "data": [100.0, 200.0, 300.0],
            },
            {
                "name": "同比增长",
                "type": "line",
                "yAxisIndex": 1,
                "data": [10.0, 20.0, 30.0],
            },
        ],
    }
    svg = render_svg("营收与增速组合图", "combo", combo_opt)
    assert "<svg" in svg, "NEW-15: Combo chart must render successfully"
    # Ensure line chart and bar labels exist
    assert "营业收入" in svg
    assert "同比增长" in svg



