#!/usr/bin/env python3
"""渲染「机构版」全长度演示报告（文字量足以覆盖多页排版验收）。

与 `run_agent5_demo_report.py` 的区别（两者互不影响，本脚本不改动它）：
- 上游数据取自 `demo_industry_report_data.py`，正文为 7 章 21 节 63 段的完整篇幅；
- 版式使用新的 `layout="industry"`（机构版）；
- 直接构造 `ReportViewModel` 并在构造前用**真实 pydantic 契约**校验每一层，
  图表 SVG 由真实渲染器 `render_chart_svg` 产出，不手写 SVG。

⚠️ 所有数据为演示构造，仅用于版式验收；输出只写 `backend/output/`，
不写 artifacts、不产生 run、不进入生产链路。

运行：cd backend && .venv/bin/python scripts/run_industry_report_demo.py
输出：backend/output/report-industry-fulldemo.html / .pdf
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scripts.demo_industry_report_data as demo  # noqa: E402
from app.agents.chapter_writer.outline import OUTLINE_VERSION, REPORT_OUTLINE  # noqa: E402
from app.agents.report_fusion.visual import plan_visual_decision  # noqa: E402
from app.reporting.html import render_html  # noqa: E402
from app.reporting.svg import render_chart_svg  # noqa: E402
from app.schemas.chapter import ChapterDraft, ParagraphDraft, SectionDraft  # noqa: E402
from app.schemas.chart import ChartSpec  # noqa: E402
from app.schemas.report import (  # noqa: E402
    DataQualityIssue,
    DimensionCoverage,
    EmbeddedChart,
    EvidenceSourceEntry,
    ExecutiveSummary,
    FinancialConsistencyCheck,
    ReportConclusion,
    ReportQualityAppendix,
    ReportViewModel,
)

DEMO_RUN_ID = "demo-industry-fulldemo"
OUT_DIR = Path("output")
HTML_NAME = "report-industry-fulldemo.html"
PDF_NAME = "report-industry-fulldemo.pdf"
REVISION = 1

# 章节/小节标题一律取自权威大纲，避免自行发明章节结构
_SECTION_TITLES: dict[str, str] = {
    section.section_id: section.title
    for chapter in REPORT_OUTLINE
    for section in chapter.sections
}
_CHAPTER_TITLES: dict[str, str] = {c.chapter_id: c.title for c in REPORT_OUTLINE}


def build_chapters() -> list[ChapterDraft]:
    chapters: list[ChapterDraft] = []
    for spec in demo.CHAPTERS:
        chapter_id = spec["chapter_id"]
        assert spec["title"] == _CHAPTER_TITLES[chapter_id], (
            f"{chapter_id} 标题与权威大纲不一致：{spec['title']!r} != {_CHAPTER_TITLES[chapter_id]!r}"
        )
        sections: list[SectionDraft] = []
        for index, raw in enumerate(spec["sections"], start=1):
            section_id = raw["section_id"]
            assert section_id.endswith(f"-{index:02d}"), f"{chapter_id} 小节顺序异常：{section_id}"
            paragraphs = [
                ParagraphDraft(
                    paragraph_id=f"P-{chapter_id[-2:]}-{index:02d}-{p_index:02d}",
                    kind=kind,
                    text=text,
                    claim_ids=list(claim_ids),
                    evidence_ids=list(evidence_ids),
                )
                for p_index, (kind, text, claim_ids, evidence_ids) in enumerate(
                    raw["paragraphs"] + demo.EXTRA_PARAGRAPHS.get(section_id, ()), start=1
                )
            ]
            sections.append(
                SectionDraft(
                    section_id=section_id,
                    title=_SECTION_TITLES[section_id],
                    purpose=raw["purpose"],
                    key_points=list(raw["key_points"]),
                    paragraphs=paragraphs,
                    chart_ids=[raw["chart_id"]] if raw.get("chart_id") else [],
                    uncertainties=list(raw.get("uncertainty") or []),
                )
            )
        chapters.append(
            ChapterDraft(
                chapter_id=chapter_id,
                title=spec["title"],
                summary=spec["summary"],
                sections=sections,
                claim_ids=list(spec["claim_ids"]),
                evidence_ids=list(spec["evidence_ids"]),
                chart_ids=[raw["chart_id"] for raw in spec["sections"] if raw.get("chart_id")],
                revision=REVISION,
            )
        )
    return chapters


def build_charts() -> list[tuple[ChartSpec, str]]:
    out: list[tuple[ChartSpec, str]] = []
    for raw in demo.CHARTS:
        spec = ChartSpec(
            chart_id=raw["chart_id"],
            title=raw["title"],
            chart_type=raw["chart_type"],
            variant=raw["variant"],
            option=raw["option"],
            evidence_ids=list(raw["evidence_ids"]),
            data_fingerprint="a" * 64,
            dedupe_key=f"demo:{raw['chart_id'].lower()}",
        )
        out.append((spec, render_chart_svg(spec)))
    return out


def build_evidence_catalog() -> list[EvidenceSourceEntry]:
    return [
        EvidenceSourceEntry(citation_number=index, **source)
        for index, source in enumerate(demo.SOURCES, start=1)
    ]


def build_view(chapters: list[ChapterDraft], chart_pairs: list[tuple[ChartSpec, str]]) -> ReportViewModel:
    chart_to_section = {raw["chart_id"]: raw["placement_section_id"] for raw in demo.CHARTS}
    embedded = [
        EmbeddedChart(
            chart_id=spec.chart_id,
            title=spec.title,
            chart_type=spec.chart_type,
            evidence_ids=list(spec.evidence_ids),
            insight_goal=next(
                raw["insight_goal"] for raw in demo.CHARTS if raw["chart_id"] == spec.chart_id
            ),
            footnotes=list(
                next(raw["footnotes"] for raw in demo.CHARTS if raw["chart_id"] == spec.chart_id)
            ),
            placement_section_id=chart_to_section[spec.chart_id],
            svg=svg,
        )
        for spec, svg in chart_pairs
    ]
    scenario_names = {"base": "基准", "upside": "乐观", "downside": "悲观"}
    # 与 assembler 中同格式（保持观感一致）
    scenarios = [
        f"{scenario_names[item['name']]}情景：{item['transmission_path']}"
        f"；触发条件：{' / '.join(item['triggers'])}"
        for item in demo.SCENARIOS
    ]
    return ReportViewModel(
        report_id="REPORT-DEMOFULL-2026H1",
        title=f"{demo.INDUSTRY_TOPIC}研究报告",
        industry_topic=demo.INDUSTRY_TOPIC,
        research_as_of=date.fromisoformat(demo.RESEARCH_AS_OF),
        generated_at=datetime(2026, 9, 20, 7, 40, tzinfo=UTC),
        tone="professional",
        report_depth=demo.REPORT_DEPTH,
        delivery_status="ready_with_limits",
        executive_summary=ExecutiveSummary(
            headline=demo.HEADLINE,
            conclusions=[
                ReportConclusion(
                    claim_id=item["claim_id"],
                    text=item["text"],
                    evidence_ids=list(item["evidence_ids"]),
                    confidence=item["confidence"],
                    uncertainty=item["uncertainty"],
                )
                # 契约上限 8 条（生产侧同为 claims[:8]）；此处取前 7 条 + 1 条低置信度，
                # 以便版式上同时出现高/中/低三种置信度 chip。
                for item in (
                    list(demo.CLAIMS[:7])
                    + [c for c in demo.CLAIMS if c["claim_id"] == "C-CASH-01"]
                )
            ],
            scenarios=scenarios,
            risks=list(demo.RISKS),
            research_boundaries=list(demo.RESEARCH_BOUNDARIES),
        ),
        chapters=chapters,
        charts=embedded,
        disclaimer=(
            "本报告全部内容为演示构造数据，仅用于版式与排版验收，"
            "不构成证券投资建议、收益保证或交易邀约。"
        ),
        methodology_note=(
            f"报告由数据解读、图表生成与章节撰写智能体的结构化产出确定性组装（大纲版本 "
            f"{OUTLINE_VERSION}）；报告融合智能体不新增事实、不改写数据结论。"
            "本演示件的上游数据为人工构造，不代表任何真实取数结果。"
        ),
        release_mode=demo.RELEASE_MODE,
        unresolved_risks=list(demo.UNRESOLVED_RISKS),
        risk_acknowledged_at=None,
        quality_appendix=ReportQualityAppendix(
            data_quality_issues=[DataQualityIssue(**item) for item in demo.DATA_QUALITY_ISSUES],
            financial_consistency_checks=[
                FinancialConsistencyCheck(**item) for item in demo.FINANCIAL_CHECKS
            ],
            dimension_coverage=[DimensionCoverage(**item) for item in demo.DIMENSION_COVERAGE],
            skipped_chart_notes=[],
        ),
        evidence_catalog=build_evidence_catalog(),
        visual_decision=plan_visual_decision(
            chapters=chapters,
            charts=embedded,
            requested_style="auto",
            requested_density="balanced",
        ),
    )


async def export_pdf(html: str, target: Path) -> int:
    from app.reporting.pdf import render_pdf_with_toc_page_numbers, shutdown_pdf_renderer

    # 页码：Chromium 不支持 CSS @page margin box，只能走导出层模板
    footer = (
        '<div style="width:100%;font-size:9px;color:#98a2b3;text-align:center;'
        'font-family:PingFang SC,Helvetica,sans-serif;">'
        '<span class="pageNumber"></span></div>'
    )
    try:
        # 两遍导出：第一遍反查目录锚点所在页，回填页码后再导一遍
        pdf = await render_pdf_with_toc_page_numbers(html, page_footer=footer)
    finally:
        await shutdown_pdf_renderer()
    target.write_bytes(pdf)
    return len(pdf)


def main() -> None:
    chapters = build_chapters()
    chart_pairs = build_charts()
    view = build_view(chapters, chart_pairs)

    paragraphs = sum(len(s.paragraphs) for c in chapters for s in c.sections)
    body_chars = sum(
        len(p.text) for c in chapters for s in c.sections for p in s.paragraphs
    )
    print(
        f"[demo] 章 {len(chapters)} / 节 {sum(len(c.sections) for c in chapters)} / 段 {paragraphs} / "
        f"正文 {body_chars:,} 字 / 图表 {len(view.charts)} / 来源 {len(view.evidence_catalog)} 条"
    )
    print(f"[demo] 风格={view.visual_decision.effective_style} 密度={view.visual_decision.density}")

    html = render_html(view)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html_path = OUT_DIR / HTML_NAME
    html_path.write_text(html, encoding="utf-8")
    print(f"[demo] HTML：{html_path.resolve()}（{len(html):,} 字节）")

    pdf_size = asyncio.run(export_pdf(html, OUT_DIR / PDF_NAME))
    print(f"[demo] PDF ：{(OUT_DIR / PDF_NAME).resolve()}（{pdf_size:,} 字节）")


if __name__ == "__main__":
    main()
