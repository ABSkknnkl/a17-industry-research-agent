"""P-10 下游收口：A4 只引用 A2 已核验净现比，落盘前改写自算断言。"""
from __future__ import annotations

import pytest

from chapter_writer.models import (
    CalloutDraft, ChapterDraft, ComparisonTableDraft, MetricCardDraft, ParagraphDraft, SectionDraft,
)
from chapter_writer.net_cash_ratio import (
    GAP_CLAUSE, apply_net_cash_ratio_guard, build_net_cash_ratio_policy,
)


def _report(rows: list[dict], evidence: list[str] | None = None) -> dict:
    return {
        "evidence_index": {rid: {"record_id": rid} for rid in (evidence or [])},
        "financial_ratios": rows,
    }


def _missing_byd() -> dict:
    return _report([{
        "company": "比亚迪",
        "cash_to_net_profit": None,
        "calculations": {},
        "period_warning": "缺少同主体、同期间、同范围和币种的可比输入，净现比不可计算",
    }])


def _verified_byd(value: float = 0.8) -> dict:
    return _report([{
        "company": "比亚迪",
        "cash_to_net_profit": value,
        "calculations": {
            "cash_to_net_profit": {
                "value": value,
                "formula": "operating_cash_flow/parent_net_profit",
                "input_record_ids": ["R-OCF", "R-PNP"],
                "period_end": "2025-12-31",
                "denominator_metric": "parent_net_profit",
            },
        },
        "period_warning": None,
    }], evidence=["R-OCF", "R-PNP"])


def _chapter(text: str, *, card: MetricCardDraft | None = None,
             table: ComparisonTableDraft | None = None) -> ChapterDraft:
    def section(sid: str, paragraph_text: str, **kwargs) -> SectionDraft:
        return SectionDraft(
            section_id=sid, title=sid, paragraphs=[
                ParagraphDraft(paragraph_id=f"P-{sid}-01", kind="analysis",
                               text=paragraph_text, evidence_ids=["R-OCF"]),
            ], **kwargs,
        )
    return ChapterDraft(
        chapter_id="CH-03", title="财务质量", summary="本章讨论现金流质量。",
        sections=[
            section("SEC-03-01", text, metric_cards=[card] if card else [],
                    comparison_table=table),
            section("SEC-03-02", "其他小节。"),
            section("SEC-03-03", "其他小节。"),
        ],
    )


def test_by_draft_claim_is_rewritten_to_gap_before_persist():
    policy = build_net_cash_ratio_policy(_missing_byd())
    chapter = _chapter("比亚迪2025年经营现金流591亿元，净利润326亿元，净现比约1.8倍，现金流质量较好。")
    corrections = apply_net_cash_ratio_guard([chapter], policy)

    text = chapter.sections[0].paragraphs[0].text
    assert "1.8" not in text
    assert GAP_CLAUSE in text or "净现比无法计算" in text
    assert "591亿元" in text and "326亿元" in text
    assert corrections and corrections[0]["disposition"] == "corrected"
    assert chapter.content_audit[-1]["code"] == "net_cash_ratio_correction"


def test_verified_ratio_is_kept_and_cited():
    policy = build_net_cash_ratio_policy(_verified_byd())
    chapter = _chapter("比亚迪2025年净现比0.80倍，经营现金流对归母净利润覆盖良好。")
    corrections = apply_net_cash_ratio_guard([chapter], policy)

    text = chapter.sections[0].paragraphs[0].text
    assert "净现比0.80倍" in text
    assert not corrections
    assert set(chapter.sections[0].paragraphs[0].evidence_ids) == {"R-OCF", "R-PNP"}


def test_wrong_value_when_verified_exists_is_corrected():
    policy = build_net_cash_ratio_policy(_verified_byd(0.8))
    chapter = _chapter("比亚迪净现比约1.8倍。")
    apply_net_cash_ratio_guard([chapter], policy)
    assert "1.8" not in chapter.sections[0].paragraphs[0].text
    assert GAP_CLAUSE in chapter.sections[0].paragraphs[0].text


def test_unverified_metric_card_is_removed():
    policy = build_net_cash_ratio_policy(_missing_byd())
    chapter = _chapter("现金流讨论。",
                       card=MetricCardDraft(label="净现比", value="1.8", unit="倍", evidence_ids=["R-OCF"]))
    apply_net_cash_ratio_guard([chapter], policy)
    assert chapter.sections[0].metric_cards == []


def test_verified_metric_card_is_kept():
    policy = build_net_cash_ratio_policy(_verified_byd(0.8))
    chapter = _chapter("现金流讨论。",
                       card=MetricCardDraft(label="净现比", value="0.80", unit="倍", evidence_ids=["R-OCF", "R-PNP"]))
    apply_net_cash_ratio_guard([chapter], policy)
    assert len(chapter.sections[0].metric_cards) == 1


def test_unverified_table_cell_is_rewritten():
    policy = build_net_cash_ratio_policy(_missing_byd())
    table = ComparisonTableDraft(title="现金流", columns=["公司", "净现比"], rows=[["比亚迪", "1.8倍"]])
    chapter = _chapter("现金流讨论。", table=table)
    apply_net_cash_ratio_guard([chapter], policy)
    assert chapter.sections[0].comparison_table.rows[0][1] == GAP_CLAUSE


def test_policy_prompt_lists_only_verified_and_gap():
    policy = build_net_cash_ratio_policy(_verified_byd(0.8))
    assert "0.80 倍" in policy["prompt"]
    assert "R-OCF" in policy["prompt"]
    assert "缺少同口径归母净利润" not in policy["prompt"]

    missing_policy = build_net_cash_ratio_policy(_missing_byd())
    assert "没有任何已核验的净现比" in missing_policy["prompt"]
    assert "比亚迪" in missing_policy["prompt"]


def test_legacy_ratio_without_denominator_is_not_referenceable():
    legacy = _report([{
        "company": "比亚迪",
        "cash_to_net_profit": 1.8,
        "calculations": {"cash_to_net_profit": {"input_record_ids": ["R-OCF", "R-PNP"]}},
    }], evidence=["R-OCF", "R-PNP"])
    policy = build_net_cash_ratio_policy(legacy)
    assert policy["verified"] == []
    assert any(item["company"] == "比亚迪" for item in policy["missing"])


def test_wrong_period_is_not_cited_even_when_value_matches():
    policy = build_net_cash_ratio_policy(_verified_byd(0.8))
    chapter = _chapter("比亚迪2024年净现比0.80倍。")
    apply_net_cash_ratio_guard([chapter], policy)
    assert GAP_CLAUSE in chapter.sections[0].paragraphs[0].text
