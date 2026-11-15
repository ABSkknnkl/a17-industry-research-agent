"""P3：跨章同键结论只报告，不把不同口径误判为冲突。"""

from chapter_writer.agent import _cross_chapter_claim_audit
from chapter_writer.models import ChapterDraft, ParagraphDraft, SectionDraft


def chapter(chapter_id: str, text: str) -> ChapterDraft:
    sections = [
        SectionDraft(section_id=f"SEC-{chapter_id[-2:]}-0{i}", title=f"节{i}", paragraphs=[
            ParagraphDraft(paragraph_id=f"P-{chapter_id}-{i}", text=text if i == 1 else "本节说明背景。")
        ])
        for i in (1, 2, 3)
    ]
    return ChapterDraft(chapter_id=chapter_id, title=chapter_id, sections=sections)


def test_same_key_conflict_is_recorded_without_rewriting_text():
    left = chapter("CH-03", "2025年全年中国市场毛利率为 22.5%。")
    right = chapter("CH-05", "2025年全年中国市场毛利率为 18.0%。")
    conflicts = _cross_chapter_claim_audit([left, right])
    assert len(conflicts) == 1
    assert conflicts[0]["code"] == "cross_chapter_claim_conflict"
    assert left.sections[0].paragraphs[0].text == "2025年全年中国市场毛利率为 22.5%。"
    assert right.sections[0].paragraphs[0].text == "2025年全年中国市场毛利率为 18.0%。"
    assert [row["code"] for row in left.content_audit] == ["cross_chapter_claim_conflict"]
    assert [row["code"] for row in right.content_audit] == ["cross_chapter_claim_conflict"]


def test_different_period_or_scope_is_not_a_conflict():
    left = chapter("CH-03", "2025年全年中国市场毛利率为 22.5%。")
    different_period = chapter("CH-05", "2024年全年中国市场毛利率为 18.0%。")
    different_scope = chapter("CH-07", "2025年全年全球市场毛利率为 15.0%。")
    assert _cross_chapter_claim_audit([left, different_period, different_scope]) == []
    assert left.content_audit == []


def test_number_must_be_adjacent_to_its_metric():
    """别家公司的数字不能被前文指标“认领”为同键冲突。"""
    left = chapter("CH-02", "宁德时代2025年净利率18.1%，毛利率26.3%。")
    right = chapter(
        "CH-07",
        "宁德时代2025年净利率18.12%，显著高于亿纬锂能（7.00%）和整车组，"
        "毛利率可能进一步被压缩。",
    )
    assert _cross_chapter_claim_audit([left, right]) == []
    assert left.content_audit == []


def test_rounding_tolerance_is_not_a_conflict():
    left = chapter("CH-03", "2025年全年中国市场毛利率为 22.5%。")
    rounded = chapter("CH-05", "2025年全年中国市场毛利率为 22%。")
    assert _cross_chapter_claim_audit([left, rounded]) == []
