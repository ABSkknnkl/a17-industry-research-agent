"""Three offline A4 acceptance groups over the same rev1 A2/A3 pair.

Group 1: the packed final prompts carry the empty-chart annual gap in
SEC-02-01 and the monthly observation in CH-01; the annual gap survives a
tight context budget.
Group 2: a simulated compliant monthly/annual sentence survives audit.
Group 3: a deliberately wrong annual-period sentence is isolated.

Both full-report and targeted-rewrite instruction modes are exercised. This
script is deterministic and never calls a network model.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

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

APP_ROOT = Path(__file__).resolve().parents[2]
ROOT = APP_ROOT / "output/nev_rev1_acceptance_20261113"
TARGET = "R-2ae2e10425356de79f2a"
MONTHLY_CHART = "CHART-05-5ED7CC84"
ANNUAL_REQUIREMENT = "penetration_rate_series"
COMPLIANT = (
    "如图 [CHART-05-5ED7CC84] 所示，2025 年 12 月当月国内零售渗透率为 59.1%，"
    "2021—2025 年年度全口径缺少可比证据。"
)
WRONG = "如图 [CHART-05-5ED7CC84] 所示，2025 年全年为 59.1%。"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def chapter_context(
    report: InterpretationReport,
    charts: ChartResult,
    chapter_id: str,
    instruction: str | None,
) -> dict:
    request = ChapterWritingRequest(
        report=report,
        charts=charts,
        options=ChapterWritingOptions(instruction=instruction),
    )
    outline = next(item for item in DEFAULT_OUTLINE if item.chapter_id == chapter_id)
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


def pack(report, charts, chapter_id, instruction):
    payload = chapter_context(report, charts, chapter_id, instruction)
    text, details = prepare_chapter_context(payload, SYSTEM_PROMPT)
    return json.loads(text), details


def coverage_row(packed: dict, intent_id: str) -> dict:
    return next(
        (row for row in (packed["context"].get("question_coverage") or [])
         if isinstance(row, dict) and row.get("intent_id") == intent_id),
        {},
    )


def matrix_row(packed: dict, requirement_id: str) -> dict:
    return next(
        (row for row in packed["context"].get("requirement_evidence_matrix", [])
         if row.get("requirement", {}).get("requirement_id") == requirement_id),
        {},
    )


def chapter_with_text(outline, text: str) -> ChapterDraft:
    sections = []
    for index, section in enumerate(outline.sections, 1):
        sections.append({
            "section_id": section.section_id,
            "title": section.title,
            "purpose": section.purpose,
            "paragraphs": [{
                "paragraph_id": f"P-{index:02d}",
                "kind": "chart_readout" if index == 1 else "analysis",
                "text": text if index == 1 else f"本小节仅说明第 {index} 项背景边界。",
                "evidence_ids": [TARGET] if index == 1 else [],
                "assumption_note": None,
            }],
            "chart_ids": [MONTHLY_CHART] if index == 1 else [],
            "layout_hint": "chart_right" if index == 1 else "text_only",
        })
    return ChapterDraft.model_validate({
        "chapter_id": outline.chapter_id,
        "title": outline.title,
        "summary": "本节按月度与年度两个口径说明边界。",
        "sections": sections,
    })


class FakeLLM:
    is_available = True

    def __init__(self, chapter: ChapterDraft) -> None:
        self.chapter = chapter

    async def generate_json(self, system: str, user: str) -> dict:
        if "只返回修复后的单个段落 JSON" in system:
            return self.chapter.sections[0].paragraphs[0].model_dump(mode="json")
        if "interpretation" in system:
            return {"interpretation": ""}
        return self.chapter.model_dump(mode="json")


async def no_record(*args, **kwargs) -> None:
    return None


def generate(report, charts, chapter, instruction):
    request = ChapterWritingRequest(
        report=report,
        charts=charts,
        options=ChapterWritingOptions(instruction=instruction),
    )
    outline = next(item for item in DEFAULT_OUTLINE if item.chapter_id == "CH-01")
    context = chapter_context(report, charts, "CH-01", instruction)["context"]
    ready = {item.chart_id: item for item in charts.charts}
    return asyncio.run(
        ChapterWriterAgent(llm=FakeLLM(chapter))._generate_audited_chapter(
            request, outline, context, ready, context["global_facts"], no_record, [],
        )
    )


def main() -> None:
    report = InterpretationReport.model_validate(
        load(ROOT / "a2/interpretation_report.json")
    )
    charts = ChartResult.model_validate(
        load(ROOT / "a3/runs/charts-20261113102720-41cf400e/chart_result.json")
    )
    instructions = {
        "full": None,
        "targeted": "单章定向重写：只保留有同口径证据的月度与年度边界。",
    }
    prompts = {}
    for mode, instruction in instructions.items():
        ch1, _ = pack(report, charts, "CH-01", instruction)
        ch2, _ = pack(report, charts, "CH-02", instruction)
        prompts[mode] = {
            "CH-01": {
                "monthly_coverage": coverage_row(ch1, "nev.q1.monthly"),
                "annual_coverage_in_ch1": coverage_row(ch1, "nev.q1.annual_penetration"),
                "charts": [chart.get("chart_id") for chart in ch1["context"].get("charts", [])],
                "target_record_present": TARGET in json.dumps(ch1["context"], ensure_ascii=False),
            },
            "CH-02": {
                "annual_coverage": coverage_row(ch2, "nev.q1.annual_penetration"),
                "annual_matrix": matrix_row(ch2, ANNUAL_REQUIREMENT),
                "monthly_coverage_in_ch2": coverage_row(ch2, "nev.q1.monthly"),
            },
        }

    old_budget = os.environ.get("RESEARCH_CONTEXT_MAX_BYTES")
    os.environ["RESEARCH_CONTEXT_MAX_BYTES"] = "140000"
    try:
        tight_ch2, tight_details = pack(report, charts, "CH-02", None)
    finally:
        if old_budget is None:
            os.environ.pop("RESEARCH_CONTEXT_MAX_BYTES", None)
        else:
            os.environ["RESEARCH_CONTEXT_MAX_BYTES"] = old_budget

    annual_tight = matrix_row(tight_ch2, ANNUAL_REQUIREMENT)
    checks = {
        "full_monthly_in_ch01": bool(prompts["full"]["CH-01"]["monthly_coverage"])
        and prompts["full"]["CH-01"]["monthly_coverage"].get("chart_ids") == [MONTHLY_CHART],
        "full_annual_gap_in_sec0201": prompts["full"]["CH-02"]["annual_matrix"].get("section_id")
        == "SEC-02-01"
        and prompts["full"]["CH-02"]["annual_matrix"].get("coverage", {}).get("passed") is False,
        "full_annual_chart_ids_empty": prompts["full"]["CH-02"]["annual_coverage"].get("chart_ids") == [],
        "full_monthly_not_in_ch02": not prompts["full"]["CH-02"]["monthly_coverage_in_ch2"],
        "targeted_monthly_in_ch01": bool(prompts["targeted"]["CH-01"]["monthly_coverage"])
        and prompts["targeted"]["CH-01"]["monthly_coverage"].get("chart_ids") == [MONTHLY_CHART],
        "targeted_annual_gap_in_sec0201": prompts["targeted"]["CH-02"]["annual_matrix"].get("section_id")
        == "SEC-02-01"
        and prompts["targeted"]["CH-02"]["annual_matrix"].get("coverage", {}).get("passed") is False,
        "targeted_annual_chart_ids_empty": prompts["targeted"]["CH-02"]["annual_coverage"].get("chart_ids") == [],
        "targeted_monthly_not_in_ch02": not prompts["targeted"]["CH-02"]["monthly_coverage_in_ch2"],
        "tight_budget_annual_gap_preserved": annual_tight.get("section_id") == "SEC-02-01"
        and annual_tight.get("coverage", {}).get("passed") is False,
        "tight_budget_question_coverage_dropped": "context.question_coverage"
        in tight_details.get("omitted_sections", []),
    }

    audit = {}
    for mode, instruction in instructions.items():
        outline = DEFAULT_OUTLINE[0]
        compliant_chapter = chapter_with_text(outline, COMPLIANT)
        compliant, compliant_fallback, _ = generate(
            report, charts, compliant_chapter, instruction,
        )
        compliant_text = compliant.sections[0].paragraphs[0].text
        wrong_chapter = chapter_with_text(outline, WRONG)
        wrong, _, _ = generate(report, charts, wrong_chapter, instruction)
        wrong_paragraph_texts = [
            paragraph.text for section in wrong.sections for paragraph in section.paragraphs
        ]
        audit[mode] = {
            "compliant_text_retained": COMPLIANT in compliant_text,
            "compliant_fallback": compliant_fallback,
            "wrong_text_absent_from_paragraphs": all(WRONG not in text for text in wrong_paragraph_texts),
            "wrong_disposition": [
                item.get("disposition") for item in wrong.content_audit
                if item.get("section_id") == "SEC-01-01"
            ],
            "wrong_original_retained_only_in_audit": any(
                item.get("original") == WRONG for item in wrong.content_audit
            ),
        }

    checks.update({
        "full_compliant_retained": audit["full"]["compliant_text_retained"]
        and audit["full"]["compliant_fallback"] is None,
        "full_wrong_isolated": audit["full"]["wrong_text_absent_from_paragraphs"]
        and "isolated" in audit["full"]["wrong_disposition"],
        "targeted_compliant_retained": audit["targeted"]["compliant_text_retained"]
        and audit["targeted"]["compliant_fallback"] is None,
        "targeted_wrong_isolated": audit["targeted"]["wrong_text_absent_from_paragraphs"]
        and "isolated" in audit["targeted"]["wrong_disposition"],
    })
    result = {
        "batch": "nev-rev1-20261113-a4-coverage",
        "source_report_id": report.report_id,
        "checks": checks,
        "audit": audit,
        "prompts": prompts,
        "tight_budget": {
            "annual_matrix": annual_tight,
            "question_coverage": tight_ch2["context"].get("question_coverage"),
            "omitted_sections": tight_details.get("omitted_sections", []),
        },
        "notes": [
            "年度缺口通过 penetration_rate_series 的需求归属进入 SEC-02-01；"
            "即使 chart_ids=[] 也不依赖图表交集。",
            "月度 59.1% 通过 CHART-05 的实际挂接进入 CH-01，引用 rev1 月度记录。",
            "紧预算先裁 question_coverage，年度缺口仍在 requirement_evidence_matrix。",
        ],
    }
    (ROOT / "a4_coverage_acceptance.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
