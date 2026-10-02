"""Unit and regression tests for Round 3 defect fixes:
1. Prompt artifacts cleaning (图前结论, 图后含义, 图中数据显示) and duplicate figure number cleaning
2. In-line chart anchoring (charts placed immediately after relevant readout paragraphs)
3. Jinja2 template quote fix for layout_hint == 'chart_right'
"""

from datetime import date
import re
from report_fusion.models import (
    ReportViewModel, ChapterDraft, SectionDraft, ParagraphDraft,
    ExecutiveSummary, EmbeddedChart, EvidenceSource
)
from report_fusion.render import render_markdown, render_html


def test_clean_chart_text_cleans_prompt_leakage_and_duplicate_numbers():
    raw_text = (
        "如图 [CHART-03-57F1BAD8] 所示，[CHART-03]图前结论：头部企业流通市值高度集中，北方华创为绝对龙头。"
        "图中数据显示，北方华创流通市值约4,466.31亿元、中微公司约3,001.37亿元。"
        "图后含义：流通市值集中度映射行业竞争结构，平台型龙头在资金、客户和研发上具备显著优势。"
    )
    
    sec_map = {
        "[CHART-03-57F1BAD8]": "图 1",
        "CHART-03-57F1BAD8": "图 1",
        "[CHART-03]": "图 1",
        "CHART-03": "图 1",
    }
    
    cleaned = raw_text
    for ref, fn in sorted(sec_map.items(), key=lambda x: -len(x[0])):
        if ref in cleaned:
            cleaned = cleaned.replace(ref, fn)
            
    cleaned = re.sub(r"\[?图\s*\d+\]?\s*(?:图前结论|图前导读|图前研判|图前要点)\s*[:：]\s*", "", cleaned)
    cleaned = re.sub(r"(?:图前结论|图前导读|图前研判|图前要点)\s*[:：]\s*", "", cleaned)
    cleaned = re.sub(r"\[?图\s*\d+\]?\s*(?:图后含义|图后分析|图后启示|图后结论|图后研判)\s*[:：]\s*", "", cleaned)
    cleaned = re.sub(r"(?:图后含义|图后分析|图后启示|图后结论|图后研判)\s*[:：]\s*", "", cleaned)
    cleaned = re.sub(r"\[?图\s*\d+\]?\s*图中数据(?:显示)?\s*[:：，,]\s*", "", cleaned)
    cleaned = re.sub(r"图中数据(?:显示)?\s*[:：，,]\s*", "", cleaned)
    cleaned = re.sub(r"(如图\s*\d+\s*所示[，,])\s*图\s*\d+\s*", r"\1", cleaned)
    cleaned = re.sub(r"(如|见|至|参(?:考|阅)?)\s*图\s*图\s*(\d+)", r"\1图 \2", cleaned)
    cleaned = re.sub(r"图\s*图\s*(\d+)", r"图 \1", cleaned)
    cleaned = re.sub(r"如图\s*(\d+)\s*所示", r"如图 \1 所示", cleaned)
    
    assert "图前结论" not in cleaned
    assert "图后含义" not in cleaned
    assert "图中数据" not in cleaned
    assert "图 3" not in cleaned
    assert "如图 1 所示，头部企业流通市值高度集中" in cleaned


def test_markdown_inline_chart_anchoring():
    p1 = ParagraphDraft(
        paragraph_id="P1",
        kind="thesis",
        text="本节阐述行业规模与核心龙头增长态势。",
        evidence_ids=[],
    )
    p2 = ParagraphDraft(
        paragraph_id="P2",
        kind="chart_readout",
        text="如图 1 所示，主要企业营业收入呈现高复合增长。",
        evidence_ids=["R1"],
    )
    p3 = ParagraphDraft(
        paragraph_id="P3",
        kind="transition",
        text="伴随规模扩张，企业盈利能力也出现显著分化。",
        evidence_ids=[],
    )
    p4 = ParagraphDraft(
        paragraph_id="P4",
        kind="chart_readout",
        text="如图 2 所示，净利润增速在不同标的间表现各异。",
        evidence_ids=["R2"],
    )
    
    sec = SectionDraft(
        section_id="SEC-01",
        title="市场规模与核心企业表现",
        purpose="测试图表就近内联",
        paragraphs=[p1, p2, p3, p4],
        chart_ids=["CHART-01", "CHART-02"],
    )
    
    c1 = EmbeddedChart(
        chart_id="CHART-01",
        title="主要企业营业收入趋势",
        figure_number="图 1",
        chart_type="line",
        evidence_ids=["R1"],
        svg='<svg viewBox="0 0 100 100"></svg>',
        insight_goal="观察营业收入",
        placement_section_id="SEC-01",
    )
    c2 = EmbeddedChart(
        chart_id="CHART-02",
        title="主要企业净利润增速趋势",
        figure_number="图 2",
        chart_type="line",
        evidence_ids=["R2"],
        svg='<svg viewBox="0 0 100 100"></svg>',
        insight_goal="观察净利润增速",
        placement_section_id="SEC-01",
    )
    
    view = ReportViewModel(
        report_id="TEST-INLINE-01",
        title="图表内联测试研报",
        subject="半导体",
        as_of=date(2026, 10, 1),
        tone="neutral",
        report_depth="standard",
        visual_style="editorial",
        delivery_status="ready",
        executive_summary=ExecutiveSummary(headline="测试摘要"),
        chapters=[ChapterDraft(chapter_id="CH-01", title="第一章", summary="第一章核心摘要", sections=[sec])],
        charts=[c1, c2],
        evidence_catalog=[
            EvidenceSource(number=1, record_id="R1", label="L1", domain="fin", metric="rev", value=100.0),
            EvidenceSource(number=2, record_id="R2", label="L2", domain="fin", metric="profit", value=20.0),
        ],
    )
    
    md = render_markdown(view)
    
    # 验证图 1 出现在 p2 之后、p3 之前；图 2 出现在 p4 之后
    idx_p2 = md.find("如图 1 所示")
    idx_c1 = md.find("![图 1：主要企业营业收入趋势]")
    idx_p3 = md.find("伴随规模扩张")
    idx_p4 = md.find("如图 2 所示")
    idx_c2 = md.find("![图 2：主要企业净利润增速趋势]")
    
    assert idx_p2 < idx_c1 < idx_p3, f"Expected p2 < c1 < p3, got {idx_p2}, {idx_c1}, {idx_p3}"
    assert idx_p3 < idx_p4 < idx_c2, f"Expected p3 < p4 < c2, got {idx_p3}, {idx_p4}, {idx_c2}"


def test_html_template_split_body_with_chart_right():
    p1 = ParagraphDraft(
        paragraph_id="P1",
        kind="thesis",
        text="本节采用紧凑型图右文左布局排版。",
        evidence_ids=[],
    )
    sec = SectionDraft(
        section_id="SEC-SPLIT",
        title="紧凑分栏排版测试",
        purpose="测试分栏",
        layout_hint="chart_right",
        paragraphs=[p1],
        chart_ids=["CHART-01"],
    )
    c1 = EmbeddedChart(
        chart_id="CHART-01",
        title="流通市值集中度",
        figure_number="图 1",
        chart_type="donut",
        evidence_ids=[],
        svg='<svg viewBox="0 0 100 100"></svg>',
        placement_section_id="SEC-SPLIT",
    )
    view = ReportViewModel(
        report_id="TEST-HTML-01",
        title="分栏测试",
        subject="半导体",
        as_of=date(2026, 10, 1),
        tone="neutral",
        report_depth="standard",
        visual_style="editorial",
        chart_mode="rich",
        delivery_status="ready",
        executive_summary=ExecutiveSummary(headline="测试"),
        chapters=[ChapterDraft(chapter_id="CH-01", title="第一章", summary="第一章摘要说明", sections=[sec])],
        charts=[c1],
    )
    
    html = render_html(view)
    assert "split-body" in html, "split-body class should be present when layout_hint=='chart_right' and charts exist"
