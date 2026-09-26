from datetime import date
import pytest

from report_fusion.agent import ReportFusionAgent
from report_fusion.models import (
    ChapterDraft,
    ChapterResult,
    InterpretationReport,
    ParagraphDraft,
    ReportFusionRequest,
    SectionDraft,
)


def test_dynamic_reconciliation_for_arbitrary_market_cap():
    agent = ReportFusionAgent()
    # Assume arbitrary industry total market cap = 4.56万亿元 (45600 亿元)
    report = InterpretationReport.model_validate({
        "report_id": "REP-DYN",
        "subject": "合成生物",
        "as_of": "2026-09-25",
        "status": "completed",
        "comps_matrix": {
            "total_market_cap": 45600.0,
        },
    })

    chapters = [
        ChapterDraft(
            chapter_id="CH-01",
            title="行业概貌",
            summary="总市值达45.60万亿元",  # 10x scale error
            sections=[
                SectionDraft(
                    section_id="SEC-01-01",
                    title="概览",
                    paragraphs=[
                        ParagraphDraft(paragraph_id="P1", text="样本总市值达45.60万亿元。")
                    ]
                )
            ]
        ),
        ChapterDraft(
            chapter_id="CH-02",
            title="规模测算",
            summary="规模可观",
            sections=[
                SectionDraft(
                    section_id="SEC-02-01",
                    title="规模",
                    paragraphs=[
                        ParagraphDraft(paragraph_id="P2", text="行业总市值约为4.56万亿元，增速良好。")
                    ]
                )
            ]
        ),
    ]

    req = ReportFusionRequest(
        report=report,
        chapters=ChapterResult(
            run_id="run-test",
            subject="合成生物",
            as_of=date(2026, 9, 25),
            status="completed",
            chapters=chapters,
        ),
    )

    issues: list[str] = []
    warnings: list[str] = []
    agent._audit_cross_chapter_consistency(req, issues, warnings)
    assert any("总市值数量级冲突" in w for w in warnings)

    agent._reconcile_market_cap_consistency(chapters, req)
    assert "4.56万亿元" in chapters[0].summary
    assert "4.56万亿元" in chapters[0].sections[0].paragraphs[0].text
