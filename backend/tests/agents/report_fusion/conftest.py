from datetime import date

import pytest

from app.agents.chapter_writer.outline import OUTLINE_VERSION, REPORT_OUTLINE
from app.schemas.analysis import AnalysisResult
from app.schemas.chapter import (
    ChapterDraft,
    ChapterQualityReport,
    ChapterWritingResult,
    ParagraphDraft,
    SectionDraft,
)
from app.schemas.chart import (
    ChartGenerationResult,
    ChartQualityReport,
    ChartReference,
    ChartSpec,
)


@pytest.fixture
def report_analysis() -> AnalysisResult:
    return AnalysisResult.model_validate(
        {
            "headline": "<script>alert('x')</script>光伏行业仍需跟踪供需再平衡。",
            "overall_confidence": "medium",
            "financial_quality": "differences_pending_verification",
            "claims": [
                {
                    "claim_id": "C-001",
                    "claim_type": "fact",
                    "text": "样本企业收入同比增长12%。",
                    "evidence_ids": ["E-001"],
                    "confidence": "medium",
                    "uncertainty": "样本覆盖范围有限。",
                    "status": "confirmed",
                }
            ],
            "dimensions": [
                {"name": name, "summary": "待持续跟踪。", "claim_ids": ["C-001"]}
                for name in ("competition", "growth", "macro_policy", "industry_chain", "risk")
            ],
            "validation_cards": [
                {
                    "name": name,
                    "status": "pending_verification",
                    "summary": "数据口径待复核。",
                    "evidence_ids": ["E-001"],
                }
                for name in (
                    "scope_comparability",
                    "financial_quality",
                    "valuation_expectation",
                )
            ],
            "scenarios": [
                {
                    "name": name,
                    "assumptions": ["当前口径不变"],
                    "triggers": ["供需数据更新"],
                    "transmission_path": "供需变化→价格变化→盈利重估",
                    "evidence_ids": ["E-001"],
                    "disconfirming_conditions": ["新证据与当前方向冲突"],
                    "monitoring_indicators": ["收入增速"],
                }
                for name in ("base", "upside", "downside")
            ],
            "risks": ["样本偏差可能影响结论。"],
            "chart_candidates": [
                {
                    "title": title,
                    "chart_type": chart_type,
                    "evidence_ids": ["E-001"],
                }
                for title, chart_type in (
                    ("行业规模趋势", "line"),
                    ("样本企业收入增速", "bar"),
                    ("市场份额构成", "pie"),
                    ("企业竞争力评分", "radar"),
                    ("光伏产业链", "industry_chain"),
                )
            ],
            "industry_topic": "中国光伏制造行业",
            "market_scope": ["中国内地"],
            "security_types": ["普通股"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-06-30",
            "version": 1,
            "prompt": {"version": "analysis-v1", "sha256": "1" * 64},
            "model_name": "mock-analysis",
            "quality": {"passed": True, "evidence_coverage": 1, "revision_count": 0},
        }
    )


@pytest.fixture
def report_charts() -> ChartGenerationResult:
    base = {
        "animation": False,
        "aria": {"enabled": True},
        "color": ["#2563eb", "#0f766e", "#d97706"],
    }
    specs = [
        ChartSpec(
            chart_id="CHART-REPORT-LINE",
            title="行业规模趋势",
            chart_type="line",
            variant="line",
            option={
                **base,
                "title": {"text": "行业规模趋势"},
                "xAxis": {"type": "category", "data": ["2023", "2024", "2025"]},
                "yAxis": {"type": "value", "name": "亿元"},
                "series": [{"name": "行业规模", "type": "line", "data": [80, 100, 112]}],
            },
            evidence_ids=["E-001"],
            data_fingerprint="1" * 64,
            dedupe_key="trend:sample",
        ),
        ChartSpec(
            chart_id="CHART-REPORT-BAR",
            title="样本企业收入增速",
            chart_type="bar",
            variant="vertical",
            option={
                **base,
                "title": {"text": "样本企业收入增速"},
                "xAxis": {"type": "category", "data": ["甲企业", "乙企业"]},
                "yAxis": {"type": "value", "name": "%"},
                "series": [{"name": "收入增速", "type": "bar", "data": [8, 12]}],
            },
            evidence_ids=["E-001"],
            data_fingerprint="2" * 64,
            dedupe_key="comparison:sample",
        ),
        ChartSpec(
            chart_id="CHART-REPORT-PIE",
            title="市场份额构成",
            chart_type="pie",
            variant="pie",
            option={
                **base,
                "title": {"text": "市场份额构成"},
                "series": [
                    {
                        "type": "pie",
                        "data": [
                            {"name": "头部企业", "value": 58},
                            {"name": "其他企业", "value": 42},
                        ],
                    }
                ],
            },
            evidence_ids=["E-001"],
            data_fingerprint="3" * 64,
            dedupe_key="composition:sample",
        ),
        ChartSpec(
            chart_id="CHART-REPORT-RADAR",
            title="企业竞争力评分",
            chart_type="radar",
            variant="radar",
            option={
                **base,
                "title": {"text": "企业竞争力评分"},
                "radar": {
                    "indicator": [
                        {"name": "技术", "min": 0, "max": 100},
                        {"name": "成本", "min": 0, "max": 100},
                        {"name": "渠道", "min": 0, "max": 100},
                    ]
                },
                "series": [
                    {"type": "radar", "data": [{"name": "样本企业", "value": [82, 76, 70]}]}
                ],
            },
            evidence_ids=["E-001"],
            data_fingerprint="4" * 64,
            dedupe_key="scoring:sample",
        ),
        ChartSpec(
            chart_id="CHART-REPORT-CHAIN",
            title="光伏产业链",
            chart_type="industry_chain",
            variant="graph",
            option={
                **base,
                "title": {"text": "光伏产业链"},
                "series": [
                    {
                        "type": "graph",
                        "data": [
                            {"id": "up", "name": "硅料", "category": 0},
                            {"id": "mid", "name": "电池片", "category": 1},
                            {"id": "down", "name": "电站", "category": 2},
                        ],
                        "links": [
                            {"source": "up", "target": "mid"},
                            {"source": "mid", "target": "down"},
                        ],
                    }
                ],
            },
            evidence_ids=["E-001"],
            data_fingerprint="5" * 64,
            dedupe_key="relationship:sample",
        ),
    ]
    return ChartGenerationResult(
        charts=[
            ChartReference(
                chart_id=spec.chart_id,
                title=spec.title,
                chart_type=spec.chart_type,
                status="ready",
                evidence_ids=spec.evidence_ids,
                artifact_id=f"ARTIFACT-{spec.chart_id}",
            )
            for spec in specs
        ],
        chart_specs=specs,
        quality=ChartQualityReport(
            passed=True,
            ready_count=len(specs),
            suppressed_count=0,
        ),
    )


@pytest.fixture
def report_chapters() -> ChapterWritingResult:
    chapters: list[ChapterDraft] = []
    chapter_chart_ids = {
        "CH-02": ["CHART-REPORT-LINE", "CHART-REPORT-BAR"],
        "CH-03": ["CHART-REPORT-CHAIN"],
        "CH-04": ["CHART-REPORT-PIE", "CHART-REPORT-RADAR"],
    }
    for chapter_config in REPORT_OUTLINE:
        sections = []
        for index, section_config in enumerate(chapter_config.sections):
            available_chart_ids = chapter_chart_ids.get(chapter_config.chapter_id, [])
            chart_ids = [available_chart_ids[index]] if index < len(available_chart_ids) else []
            sections.append(
                SectionDraft(
                    section_id=section_config.section_id,
                    title=section_config.title,
                    purpose=section_config.purpose,
                    key_points=["样本企业收入同比增长12%。"],
                    paragraphs=[
                        ParagraphDraft(
                            paragraph_id=(
                                f"P-{chapter_config.chapter_id.removeprefix('CH-')}-"
                                f"{index + 1:02d}-01"
                            ),
                            kind="analysis",
                            text="样本企业收入同比增长12%，但样本覆盖范围有限。",
                            claim_ids=["C-001"],
                            evidence_ids=["E-001"],
                        )
                    ],
                    chart_ids=chart_ids,
                    uncertainties=["需继续核验更大样本。"],
                )
            )
        chapters.append(
            ChapterDraft(
                chapter_id=chapter_config.chapter_id,
                title=chapter_config.title,
                summary="本章仅基于已核验的结构化结论。",
                sections=sections,
                claim_ids=["C-001"],
                evidence_ids=["E-001"],
                chart_ids=chapter_chart_ids.get(chapter_config.chapter_id, []),
                revision=1,
            )
        )
    return ChapterWritingResult(
        industry_topic="中国光伏制造行业",
        research_as_of=date(2026, 6, 30),
        chapters=chapters,
        chart_requests=[
            ChartReference(
                chart_id=chart_id,
                title=title,
                chart_type=chart_type,
                status="ready",
                evidence_ids=["E-001"],
                artifact_id=f"ARTIFACT-{chart_id}",
            )
            for chart_id, title, chart_type in (
                ("CHART-REPORT-LINE", "行业规模趋势", "line"),
                ("CHART-REPORT-BAR", "样本企业收入增速", "bar"),
                ("CHART-REPORT-CHAIN", "光伏产业链", "industry_chain"),
                ("CHART-REPORT-PIE", "市场份额构成", "pie"),
                ("CHART-REPORT-RADAR", "企业竞争力评分", "radar"),
            )
        ],
        outline_version=OUTLINE_VERSION,
        prompt_version="chapter-v1",
        prompt_sha256="3" * 64,
        model_name="mock-chapter",
        quality=ChapterQualityReport(passed=True, evidence_coverage=1),
    )
