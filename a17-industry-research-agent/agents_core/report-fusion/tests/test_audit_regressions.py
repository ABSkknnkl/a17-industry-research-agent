"""Market-cap reconciliation must respect the owner of each financial fact."""

from datetime import date

import pytest

from report_fusion.agent import ReportFusionAgent
from report_fusion.models import (ChapterDraft, ChapterResult, InterpretationReport,
    MetricCardDraft, ParagraphDraft, ReportFusionRequest, SectionDraft)


def request_with_text(text, cards=None):
    chapters = [ChapterDraft(chapter_id="CH-01", title="概览", summary=text,
        sections=[SectionDraft(section_id="SEC-01-01", title="市值",
            paragraphs=[ParagraphDraft(paragraph_id="P1", text=text)], metric_cards=cards or [])])]
    return ReportFusionRequest(
        report=InterpretationReport(report_id="audit", subject="测试行业", as_of=date(2026, 10, 30),
            status="completed", comps_matrix={"total_market_cap": 100000}),
        chapters=ChapterResult(run_id="audit", subject="测试行业", as_of=date(2026, 10, 30),
            status="completed", chapters=chapters),
    )


@pytest.mark.parametrize("text", [
    "样本证券池总市值10万亿元，其中龙头公司市值1万亿元。",
    "龙头公司总市值1万亿元，样本证券池总市值10万亿元。",
    "行业市场规模1万亿元，样本总市值10万亿元。",
    "样本总市值10万亿元，龙头公司拥有1万亿元的市值。",
    "龙头公司：总市值1万亿元，样本总市值10万亿元。",
    "龙头公司财务概览，总市值1万亿元，样本总市值10万亿元。",
    "公司甲\n总市值1万亿元。",
])
def test_reconciliation_keeps_individual_and_unrelated_values(text):
    request = request_with_text(text)
    ReportFusionAgent()._reconcile_market_cap_consistency(request.chapters.chapters, request)
    assert request.chapters.chapters[0].summary == text
    assert request.chapters.chapters[0].sections[0].paragraphs[0].text == text


def test_reconciliation_fixes_explicit_sample_total_only():
    request = request_with_text("样本总市值100万亿元，其中龙头公司总市值1万亿元。")
    ReportFusionAgent()._reconcile_market_cap_consistency(request.chapters.chapters, request)
    assert request.chapters.chapters[0].summary == "样本总市值10.0万亿元，其中龙头公司总市值1万亿元。"


def test_reconciliation_keeps_company_card_and_fixes_sample_card():
    request = request_with_text("市值分布", [
        MetricCardDraft(label="龙头公司总市值", value="1万亿元"),
        MetricCardDraft(label="样本总市值", value="100万亿元"),
    ])
    ReportFusionAgent()._reconcile_market_cap_consistency(request.chapters.chapters, request)
    cards = request.chapters.chapters[0].sections[0].metric_cards
    assert [card.value for card in cards] == ["1万亿元", "10.0万亿元"]


def test_legitimate_company_caps_do_not_raise_sample_total_conflict_warning():
    request = request_with_text("样本证券池总市值10万亿元，其中龙头公司市值1万亿元。")
    issues, warnings = [], []
    ReportFusionAgent()._audit_cross_chapter_consistency(request, issues, warnings)
    assert not any("总市值数量级冲突" in warning for warning in warnings)


def test_ambiguous_total_is_flagged_for_review_without_rewriting():
    text = "公司甲：总市值1万亿元。"
    request = request_with_text(text)
    agent = ReportFusionAgent()
    issues, warnings = [], []
    agent._audit_cross_chapter_consistency(request, issues, warnings)
    assert any("总市值归属不明确" in warning for warning in warnings)
    agent._reconcile_market_cap_consistency(request.chapters.chapters, request)
    assert request.chapters.chapters[0].sections[0].paragraphs[0].text == text
