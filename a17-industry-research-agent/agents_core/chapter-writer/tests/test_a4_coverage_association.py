"""A4 coverage routing for the monthly and annual penetration pair.

The annual series has no chart (``chart_ids=[]``), so its gap must travel
through the requirement owner (``SEC-02-01``), not through chart intersection.
The monthly chart travels through its actual chart id and placement (``CH-01``).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from chapter_writer.agent import (
    DEFAULT_OUTLINE,
    SYSTEM_PROMPT,
    ChapterWriterAgent,
    extract_global_quantitative_anchor,
    format_global_facts_prompt,
    prepare_chapter_context,
)
from chapter_writer.models import (
    ChapterDraft,
    ChapterWritingOptions,
    ChapterWritingRequest,
    ChartResult,
    InterpretationReport,
)
from chapter_writer.retriever import DynamicEvidenceRetriever

APP_ROOT = Path(__file__).resolve().parents[3]
REV1_ROOT = APP_ROOT / "output/nev_rev1_acceptance_20261113"
TARGET_RECORD_ID = "R-2ae2e10425356de79f2a"
MONTHLY_CHART_ID = "CHART-05-5ED7CC84"


@pytest.fixture(scope="module")
def rev1() -> tuple[InterpretationReport, ChartResult]:
    report = InterpretationReport.model_validate(
        json.loads((REV1_ROOT / "a2/interpretation_report.json").read_text(encoding="utf-8"))
    )
    charts = ChartResult.model_validate(
        json.loads(
            (
                REV1_ROOT
                / "a3/runs/charts-20261113102720-41cf400e/chart_result.json"
            ).read_text(encoding="utf-8")
        )
    )
    return report, charts


def _request(
    report: InterpretationReport,
    charts: ChartResult,
    *,
    instruction: str | None = None,
) -> ChapterWritingRequest:
    return ChapterWritingRequest(
        report=report,
        charts=charts,
        options=ChapterWritingOptions(instruction=instruction),
    )


def _chapter_context(
    report: InterpretationReport,
    charts: ChartResult,
    chapter_id: str,
    *,
    instruction: str | None = None,
) -> dict:
    request = _request(report, charts, instruction=instruction)
    outline = next(chapter for chapter in DEFAULT_OUTLINE if chapter.chapter_id == chapter_id)
    context = DynamicEvidenceRetriever(request).retrieve(chapter_id, outline)
    facts = extract_global_quantitative_anchor(report)
    context["global_facts"] = facts
    context["global_facts_prompt"] = format_global_facts_prompt(facts)
    return {
        "outline": outline.model_dump(mode="json"),
        "subject": report.subject,
        "as_of": report.as_of.isoformat(),
        "audience": request.options.audience,
        "style": request.options.style,
        "target_length": request.options.target_length,
        "instruction": request.options.instruction,
        "context": context,
        "global_facts": context["global_facts_prompt"],
        "previous_errors": [],
    }


def _packed(
    report: InterpretationReport,
    charts: ChartResult,
    chapter_id: str,
    *,
    instruction: str | None = None,
) -> tuple[dict, dict]:
    payload = _chapter_context(report, charts, chapter_id, instruction=instruction)
    text, details = prepare_chapter_context(payload, SYSTEM_PROMPT)
    return json.loads(text), details


def _coverage_rows(packed: dict, intent_id: str) -> list[dict]:
    return [
        row
        for row in (packed["context"].get("question_coverage") or [])
        if isinstance(row, dict) and row.get("intent_id") == intent_id
    ]


def _matrix_row(packed: dict, requirement_id: str) -> dict:
    return next(
        row
        for row in packed["context"]["requirement_evidence_matrix"]
        if row["requirement"]["requirement_id"] == requirement_id
    )


def _chapter_with_text(outline, text: str, *, with_chart: bool = True) -> ChapterDraft:
    sections = []
    for index, section in enumerate(outline.sections, 1):
        paragraph_text = text if index == 1 else f"本小节仅说明第 {index} 项背景边界。"
        sections.append({
            "section_id": section.section_id,
            "title": section.title,
            "purpose": section.purpose,
            "paragraphs": [{
                "paragraph_id": f"P-{index:02d}",
                "kind": "chart_readout" if index == 1 and with_chart else "analysis",
                "text": paragraph_text,
                "evidence_ids": [TARGET_RECORD_ID] if index == 1 else [],
                "assumption_note": None,
            }],
            "chart_ids": [MONTHLY_CHART_ID] if index == 1 and with_chart else [],
            "layout_hint": "chart_right" if index == 1 and with_chart else "text_only",
        })
    return ChapterDraft.model_validate({
        "chapter_id": outline.chapter_id,
        "title": outline.title,
        "summary": "本节按月度与年度两个口径说明边界。",
        "sections": sections,
    })


class _CompliantLLM:
    is_available = True

    def __init__(self, chapter: ChapterDraft) -> None:
        self.chapter = chapter
        self.prompts: list[str] = []

    async def generate_json(self, system: str, user: str) -> dict:
        self.prompts.append(user)
        if "只返回修复后的单个段落 JSON" in system:
            return self.chapter.sections[0].paragraphs[0].model_dump(mode="json")
        if "interpretation" in system:
            return {"interpretation": ""}
        return self.chapter.model_dump(mode="json")


async def _no_record(*args, **kwargs) -> None:
    return None


def _run_generated(
    report: InterpretationReport,
    charts: ChartResult,
    chapter_id: str,
    chapter: ChapterDraft,
    *,
    instruction: str | None = None,
) -> tuple[ChapterDraft, str | None, str | None]:
    request = _request(report, charts, instruction=instruction)
    outline = next(item for item in DEFAULT_OUTLINE if item.chapter_id == chapter_id)
    context = _chapter_context(report, charts, chapter_id, instruction=instruction)["context"]
    ready = {item.chart_id: item for item in charts.charts}
    agent = ChapterWriterAgent(llm=_CompliantLLM(chapter))
    return asyncio.run(
        agent._generate_audited_chapter(
            request, outline, context, ready, context["global_facts"], _no_record, [],
        )
    )


@pytest.mark.parametrize("mode", ["full", "targeted"])
def test_prompt_routes_monthly_to_ch01_and_annual_gap_to_sec0201(rev1, mode):
    report, charts = rev1
    instruction = "单章定向重写：只保留有同口径证据的月度与年度边界。" if mode == "targeted" else None
    ch1, _ = _packed(report, charts, "CH-01", instruction=instruction)
    ch2, _ = _packed(report, charts, "CH-02", instruction=instruction)

    monthly_rows = _coverage_rows(ch1, "nev.q1.monthly")
    assert monthly_rows
    assert monthly_rows[0]["chart_ids"] == [MONTHLY_CHART_ID]
    assert MONTHLY_CHART_ID in {
        chart["chart_id"] for chart in ch1["context"]["charts"]
    }
    assert TARGET_RECORD_ID in json.dumps(ch1["context"]["charts"], ensure_ascii=False)
    assert "period_type\": \"month\"" in json.dumps(ch1["context"]["charts"], ensure_ascii=False)
    assert not _coverage_rows(ch1, "nev.q1.annual_penetration")

    annual_rows = _coverage_rows(ch2, "nev.q1.annual_penetration")
    assert annual_rows
    assert annual_rows[0]["chart_ids"] == []
    annual_matrix = _matrix_row(ch2, "penetration_rate_series")
    assert annual_matrix["section_id"] == "SEC-02-01"
    assert annual_matrix["coverage"]["passed"] is False
    assert not _coverage_rows(ch2, "nev.q1.monthly")


def test_annual_gap_survives_tight_context_budget(rev1, monkeypatch):
    report, charts = rev1
    monkeypatch.setenv("RESEARCH_CONTEXT_MAX_BYTES", "140000")
    packed, details = _packed(report, charts, "CH-02")
    assert "context.question_coverage" in details["omitted_sections"]
    annual_matrix = _matrix_row(packed, "penetration_rate_series")
    assert annual_matrix["section_id"] == "SEC-02-01"
    assert annual_matrix["coverage"]["passed"] is False


COMPLIANT_TEXT = (
    "如图 [CHART-05-5ED7CC84] 所示，2025 年 12 月当月国内零售渗透率为 59.1%，"
    "2021—2025 年年度全口径缺少可比证据。"
)
WRONG_PERIOD_TEXT = "如图 [CHART-05-5ED7CC84] 所示，2025 年全年为 59.1%。"


def test_compliant_monthly_statement_survives_audit(rev1):
    report, charts = rev1
    outline = DEFAULT_OUTLINE[0]
    chapter = _chapter_with_text(outline, COMPLIANT_TEXT)
    context = _chapter_context(report, charts, "CH-01")["context"]
    ready = {item.chart_id: item for item in charts.charts}
    issues = ChapterWriterAgent()._audit_chapter(
        chapter, outline, set(report.evidence_index), ready, context, None,
    )
    assert issues == []
    assert COMPLIANT_TEXT in chapter.sections[0].paragraphs[0].text


@pytest.mark.parametrize("mode", ["full", "targeted"])
def test_compliant_statement_survives_full_and_targeted_generation(rev1, mode):
    report, charts = rev1
    outline = DEFAULT_OUTLINE[0]
    chapter = _chapter_with_text(outline, COMPLIANT_TEXT)
    instruction = "单章定向重写：只保留有同口径证据的月度与年度边界。" if mode == "targeted" else None
    generated, fallback, _ = _run_generated(
        report, charts, "CH-01", chapter, instruction=instruction,
    )
    assert fallback is None
    assert COMPLIANT_TEXT in generated.sections[0].paragraphs[0].text


@pytest.mark.parametrize("mode", ["full", "targeted"])
def test_wrong_annual_statement_is_isolated(rev1, mode):
    report, charts = rev1
    outline = DEFAULT_OUTLINE[0]
    chapter = _chapter_with_text(outline, WRONG_PERIOD_TEXT)
    instruction = "单章定向重写：只保留有同口径证据的月度与年度边界。" if mode == "targeted" else None
    generated, _, _ = _run_generated(
        report, charts, "CH-01", chapter, instruction=instruction,
    )
    # The audit trail may retain the rejected original for traceability; the
    # published paragraph text must not retain it.
    assert all(
        WRONG_PERIOD_TEXT not in paragraph.text
        for section in generated.sections
        for paragraph in section.paragraphs
    )
    assert any(
        item.get("disposition") == "isolated" and item.get("section_id") == "SEC-01-01"
        for item in generated.content_audit
    )


def test_audit_places_annual_gap_in_owner_section(rev1):
    report, charts = rev1
    outline = DEFAULT_OUTLINE[1]
    chapter = _chapter_with_text(outline, "已核对可比期间。")
    context = _chapter_context(report, charts, "CH-02")["context"]
    agent = ChapterWriterAgent()
    agent._audit_chapter(chapter, outline, set(report.evidence_index), {}, context)
    owner = next(section for section in chapter.sections if section.section_id == "SEC-02-01")
    assert "年度全口径渗透率缺少完整的同口径证据。" in owner.uncertainties
