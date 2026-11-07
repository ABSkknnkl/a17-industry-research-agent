"""Tests for the 5 commercial aerospace defects fixed in chapter-writer."""

import asyncio
import json
from pathlib import Path
import pytest

from chapter_writer.agent import (
    ChapterWriterAgent,
    extract_global_quantitative_anchor,
    format_global_facts_prompt,
)
from chapter_writer.models import (
    ChapterDraft,
    ChapterWritingRequest,
    ChartRef,
    ChartResult,
    InterpretationReport,
    ParagraphDraft,
    SectionDraft,
)
from chapter_writer.outline import DEFAULT_OUTLINE
from chapter_writer.retriever import DynamicEvidenceRetriever


class MissingLLM:
    is_available = False

    async def generate_json(self, *args, **kwargs):
        raise AssertionError("LLM should not be called in offline unit test")


def make_dummy_report(with_macro: bool = True) -> InterpretationReport:
    evidence = {
        "E-IND-01": {
            "record_id": "E-IND-01",
            "domain": "industry",
            "entity": "商业航天",
            "metric": "市场规模",
            "value": 1500,
            "unit": "亿元",
            "period": "2025-12-31",
        },
        "E-COMP-01": {
            "record_id": "E-COMP-01",
            "domain": "companies",
            "entity": "中国卫星",
            "metric": "营业收入",
            "value": 75.5,
            "unit": "亿元",
            "period": "2024-12-31",
        },
        "E-COMP-02": {
            "record_id": "E-COMP-02",
            "domain": "companies",
            "entity": "铖昌科技",
            "metric": "毛利率",
            "value": 72.68,
            "unit": "%",
            "period": "2024-12-31",
        },
    }
    if with_macro:
        evidence["E-MACRO-01"] = {
            "record_id": "E-MACRO-01",
            "domain": "macro",
            "entity": "宏观经济",
            "metric": "规模以上工业增加值累计同比",
            "value": 3.6,
            "unit": "%",
            "period": "2023-05-31",
        }
        evidence["E-MACRO-02"] = {
            "record_id": "E-MACRO-02",
            "domain": "macro",
            "entity": "宏观信用",
            "metric": "社会融资规模存量同比",
            "value": 10.3,
            "unit": "%",
            "period": "2022-10-31",
        }

    return InterpretationReport.model_validate({
        "report_id": "REP-TEST",
        "subject": "商业航天",
        "as_of": "2026-09-23",
        "status": "completed",
        "comps_matrix": {
            "comps": [
                {"company_name": "中国卫星", "market_cap": 300.0, "valuation_tier": "profitable"},
                {"company_name": "铖昌科技", "market_cap": 150.0, "valuation_tier": "profitable"},
                {"company_name": "早期测试企业", "market_cap": 50.0, "valuation_tier": "loss_or_high_multiple"},
            ],
            "total_market_cap": 22141.07,  # 2.21万亿
            "median_pe": 108.14,
            "median_pb": 4.16,
            "median_gross_margin": 34.15,
        },
        "industry_chain_segments": [
            {
                "segment_name": "上游：基础支撑与核心部件",
                "stage": "upstream",
                "representative_companies": ["铖昌科技", "中国卫星"],  # Duplicate in upstream
            },
            {
                "segment_name": "中游：制造总装与系统集成",
                "stage": "midstream",
                "representative_companies": ["中国卫星", "航天电子"],  # Duplicate in midstream
            },
        ],
        "key_metrics": [
            {"metric": "社会融资规模存量同比", "evidence_record_ids": ["E-MACRO-02"]},
            {"metric": "市场规模", "evidence_record_ids": ["E-IND-01"]},
        ],
        "evidence_index": evidence,
    })


def test_global_quantitative_anchor_extraction_and_scaling():
    """Defect 1: Extract global quantitative facts and format market cap."""
    report = make_dummy_report()
    anchor = extract_global_quantitative_anchor(report)

    assert anchor["market_cap_val"] == 22141.07
    assert anchor["market_cap_wan_yi"] == 2.21
    assert "22,141.07 亿元" in anchor["market_cap_str"]
    assert "2.21 万亿元" in anchor["market_cap_str"]

    # Canonical segment lock for 中国卫星 should be midstream
    assert "中游" in anchor["canonical_segments"]["中国卫星"]
    assert "上游" in anchor["canonical_segments"]["铖昌科技"]

    prompt_text = format_global_facts_prompt(anchor)
    assert "2.21 万亿元" in prompt_text
    assert "中国卫星: 中游" in prompt_text


def test_macro_evidence_filtered_in_non_macro_chapters():
    """Defect 5: Non-macro chapters (CH-02, CH-03) do not retrieve irrelevant macro evidence."""
    report = make_dummy_report(with_macro=True)
    req = ChapterWritingRequest(report=report)
    retriever = DynamicEvidenceRetriever(req)

    # CH-02 (市场规模与成长性): non-macro
    ch2 = next(c for c in DEFAULT_OUTLINE if c.chapter_id == "CH-02")
    ctx2 = retriever.retrieve("CH-02", ch2)
    assert "E-MACRO-01" not in ctx2["evidence"]
    assert "E-MACRO-02" not in ctx2["evidence"]
    assert "E-IND-01" in ctx2["evidence"]

    # CH-06 (驱动与宏观环境): macro relevant
    ch6 = next(c for c in DEFAULT_OUTLINE if c.chapter_id == "CH-06")
    ctx6 = retriever.retrieve("CH-06", ch6)
    assert "E-MACRO-01" in ctx6["evidence"] or "E-MACRO-02" in ctx6["evidence"]


def test_single_placement_lock_and_retriever_routing():
    """Defect 2: Strict chart routing to recommended_chapter_id and Single-Placement Lock."""
    report = make_dummy_report()
    charts = ChartResult(charts=[
        ChartRef(
            chart_id="CHART-01-CHAIN",
            title="产业链结构图",
            chart_type="industry_chain",
            status="ready",
            recommended_chapter_id="CH-03",
            evidence_ids=["E-COMP-02"],
        ),
        ChartRef(
            chart_id="CHART-02-VAL",
            title="估值对比图",
            chart_type="comps_bar",
            status="ready",
            recommended_chapter_id="CH-05",
            evidence_ids=["E-COMP-01"],
        ),
    ])
    req = ChapterWritingRequest(report=report, charts=charts)
    retriever = DynamicEvidenceRetriever(req)

    # CH-01 must NOT receive CHART-01-CHAIN or CHART-02-VAL
    ch1 = next(c for c in DEFAULT_OUTLINE if c.chapter_id == "CH-01")
    ctx1 = retriever.retrieve("CH-01", ch1)
    assert len(ctx1["charts"]) == 0

    # CH-03 must strictly receive CHART-01-CHAIN
    ch3 = next(c for c in DEFAULT_OUTLINE if c.chapter_id == "CH-03")
    ctx3 = retriever.retrieve("CH-03", ch3)
    assert len(ctx3["charts"]) == 1
    assert ctx3["charts"][0]["chart_id"] == "CHART-01-CHAIN"


def test_chart_placeholder_auto_injection_in_audit():
    """Defect 3: Section with chart_ids must have [CHART-xx] in text, auto-repaired if missing."""
    agent = ChapterWriterAgent(llm=MissingLLM())
    ready_charts = {
        "CHART-03-A": ChartRef(chart_id="CHART-03-A", title="测试图", chart_type="industry_chain", status="ready", recommended_chapter_id="CH-03")
    }
    sec = SectionDraft(
        section_id="SEC-03-01",
        title="产业链剖析",
        purpose="目的",
        key_points=["要点"],
        paragraphs=[
            ParagraphDraft(paragraph_id="P-03-01-01", kind="chart_readout", text="产业毛利率整体呈现上游高、中游平稳格局。")
        ],
        chart_ids=["CHART-03-A"],
    )
    ch = ChapterDraft(
        chapter_id="CH-03",
        title="产业链全景与价值链分工",
        summary="摘要",
        sections=[
            sec,
            SectionDraft(section_id="SEC-03-02", title="节2", paragraphs=[ParagraphDraft(paragraph_id="P-03-02-01", kind="analysis", text="内容2")]),
            SectionDraft(section_id="SEC-03-03", title="节3", paragraphs=[ParagraphDraft(paragraph_id="P-03-03-01", kind="analysis", text="内容3")]),
        ],
    )
    ch3_outline = next(c for c in DEFAULT_OUTLINE if c.chapter_id == "CH-03")

    # Before audit, paragraph lacks [CHART-03-A]
    assert "[CHART-03-A]" not in sec.paragraphs[0].text

    # Run audit
    agent._audit_chapter(ch, ch3_outline, set(), ready_charts)

    # After audit, paragraph must have [CHART-03-A] injected
    assert "[CHART-03-A]" in sec.paragraphs[0].text
    assert sec.paragraphs[0].text.startswith("如图 [CHART-03-A] 所示，")


def test_market_cap_consistency_repair_in_audit():
    """Defect 1 & 4: Erroneous 22.14万亿 is auto-corrected to 2.21万亿, and entity segment locked."""
    agent = ChapterWriterAgent(llm=MissingLLM())
    report = make_dummy_report()
    global_facts = extract_global_quantitative_anchor(report)

    sec = SectionDraft(
        section_id="SEC-01-01",
        title="行业定位",
        purpose="目的",
        key_points=["样本总市值达22.14万亿元，规模可观"],
        paragraphs=[
            ParagraphDraft(
                paragraph_id="P-01-01-01",
                kind="thesis",
                text="商业航天样本总市值达22.14万亿元。中国卫星等上游核心部件环节增速平稳。",
            )
        ],
    )
    ch = ChapterDraft(
        chapter_id="CH-01",
        title="行业定位与宏观全景",
        summary="样本总市值22.14万亿元，高估值与盈利错配。",
        sections=[
            sec,
            SectionDraft(section_id="SEC-01-02", title="节2", paragraphs=[ParagraphDraft(paragraph_id="P-01-02-01", kind="analysis", text="内容2")]),
            SectionDraft(section_id="SEC-01-03", title="节3", paragraphs=[ParagraphDraft(paragraph_id="P-01-03-01", kind="analysis", text="内容3")]),
        ],
    )
    ch1_outline = next(c for c in DEFAULT_OUTLINE if c.chapter_id == "CH-01")

    agent._audit_chapter(ch, ch1_outline, set(), {}, global_facts=global_facts)

    # Verify market cap was repaired to 2.21万亿元 in summary, key_points, and text
    assert "22.14" not in ch.summary
    assert "2.21万亿元" in ch.summary
    assert "22.14" not in sec.key_points[0]
    assert "2.21万亿元" in sec.key_points[0]
    assert "22.14" not in sec.paragraphs[0].text
    assert "2.21万亿元" in sec.paragraphs[0].text

    # Verify entity segment was repaired from 上游 to 中游总装
    assert "中国卫星等上游" not in sec.paragraphs[0].text
    assert "中国卫星等中游总装" in sec.paragraphs[0].text


def test_package_audit_single_placement_and_no_conflicts():
    """Defect 1 & 2: _audit_package enforces Single-Placement Lock and checks market cap consistency."""
    agent = ChapterWriterAgent(llm=MissingLLM())
    ready_charts = {
        "CHART-01": ChartRef(chart_id="CHART-01", title="图1", chart_type="comps_bar", status="ready", recommended_chapter_id="CH-01"),
        "CHART-03": ChartRef(chart_id="CHART-03", title="图3", chart_type="industry_chain", status="ready", recommended_chapter_id="CH-03"),
    }

    # Simulate bad LLM output: CHART-01 attached to both CH-01 and CH-07
    chapters = []
    for outline_ch in DEFAULT_OUTLINE:
        secs = []
        for s in outline_ch.sections:
            cids = []
            if outline_ch.chapter_id == "CH-01" and s.section_id.endswith("01"):
                cids = ["CHART-01"]
            elif outline_ch.chapter_id == "CH-07" and s.section_id.endswith("03"):
                cids = ["CHART-01"]  # Duplicate chart!
            secs.append(
                SectionDraft(
                    section_id=s.section_id,
                    title=s.title,
                    purpose=s.purpose,
                    paragraphs=[ParagraphDraft(paragraph_id=f"P-{s.section_id}-01", kind="analysis", text="正文")],
                    chart_ids=cids,
                )
            )
        chapters.append(
            ChapterDraft(chapter_id=outline_ch.chapter_id, title=outline_ch.title, summary="摘要", sections=secs)
        )

    # Run _audit_package
    issues = agent._audit_package(chapters, set(), ready_charts)

    # Check Single-Placement Lock: CHART-01 must only be in CH-01, removed from CH-07
    ch1 = next(c for c in chapters if c.chapter_id == "CH-01")
    ch7 = next(c for c in chapters if c.chapter_id == "CH-07")
    assert "CHART-01" in ch1.chart_ids
    assert "CHART-01" not in ch7.chart_ids

    # Also verify CHART-03 (recommended for CH-03) was automatically placed in CH-03
    ch3 = next(c for c in chapters if c.chapter_id == "CH-03")
    assert "CHART-03" in ch3.chart_ids
    assert any("[CHART-03]" in p.text for p in ch3.sections[0].paragraphs)


def test_aerospace_offline_regression_with_real_run_artifacts():
    """End-to-end regression using commercial aerospace dataset from run-20260923181514-452."""
    repo_root = Path(__file__).resolve().parents[3]
    run_dir = repo_root / "data/runs/run-20260923181514-452/artifacts"
    if not run_dir.exists():
        run_dir = Path("data/runs/run-20260923181514-452/artifacts")
    report_file = run_dir / "interpretation_report.json"
    charts_file = run_dir / "chart_result.json"

    if not report_file.exists() or not charts_file.exists():
        pytest.skip("Commercial aerospace run artifacts not found on disk")

    report_data = json.loads(report_file.read_text(encoding="utf-8"))
    charts_data = json.loads(charts_file.read_text(encoding="utf-8"))

    report = InterpretationReport.model_validate(report_data)
    charts = ChartResult.model_validate(charts_data)

    req = ChapterWritingRequest(report=report, charts=charts)
    agent = ChapterWriterAgent(llm=MissingLLM())
    result = asyncio.run(agent.run(req, save_artifacts=False))

    # 1. Structure check: exactly 7 chapters, 21 sections
    assert len(result.chapters) == 7
    assert sum(len(c.sections) for c in result.chapters) == 21

    # 2. Single-Placement Lock: every placed chart must appear exactly once in the entire report
    all_placed_cids = [cid for ch in result.chapters for s in ch.sections for cid in s.chart_ids]
    assert len(all_placed_cids) == len(set(all_placed_cids)), f"Duplicate chart placements: {all_placed_cids}"

    # 3. Chart CHART-01-DFD7148E (产业链结构) must be placed in CH-03, NOT displaced to CH-07
    ch3 = next(c for c in result.chapters if c.chapter_id == "CH-03")
    ch7 = next(c for c in result.chapters if c.chapter_id == "CH-07")
    assert "CHART-01-DFD7148E" in ch3.chart_ids
    assert "CHART-01-DFD7148E" not in ch7.chart_ids

    # 4. Figure text anchor closure: every section with chart_ids must contain [CHART-xx] in text
    for ch in result.chapters:
        for sec in ch.sections:
            for cid in sec.chart_ids:
                tag = f"[{cid}]"
                has_tag = any(tag in p.text for p in sec.paragraphs)
                assert has_tag, f"Section {sec.section_id} missing placeholder for chart {cid}"

    # 5. Market cap consistency: 22.14万亿 should not be present in any chapter
    all_text = " ".join(p.text for ch in result.chapters for s in ch.sections for p in s.paragraphs)
    all_summaries = " ".join(ch.summary for ch in result.chapters)
    assert "22.14万亿" not in all_text
    assert "22.14万亿" not in all_summaries
