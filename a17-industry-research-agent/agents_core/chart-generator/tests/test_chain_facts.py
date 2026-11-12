"""Guards for reviewed full-chain structure facts (A2 analysis / A3 chart / A4 text)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from chart_generator.chain_facts import (
    ChainFacts,
    ChainSegmentFact,
    chain_knowledge_facts,
    try_load_chain_facts,
)

_FACTS_DIR = Path(__file__).resolve().parents[1] / "chart_profiles" / "_chain_facts"


def _segment(stage: str, companies: list[str] | None = None, **kwargs: object) -> ChainSegmentFact:
    """Build a valid segment fact with sensible defaults."""
    return ChainSegmentFact(
        stage=stage,
        name=f"{stage} segment",
        companies=companies or [],
        **kwargs,
    )


def _valid_facts(**overrides: object) -> ChainFacts:
    """Build a minimal reviewed full-chain card."""
    payload: dict[str, object] = {
        "profile_key": "vehicle",
        "status": "reviewed",
        "frame": "full_chain",
        "segments": [
            _segment("upstream", sample_status="not_in_sample", gap_declaration="未纳入样本"),
            _segment("midstream", ["宁德时代", "亿纬锂能"]),
            _segment("downstream", ["比亚迪", "长安汽车", "赛力斯"]),
        ],
        "comparison_groups": [
            {"group": "电池组", "members": ["宁德时代", "亿纬锂能"]},
            {"group": "整车组", "members": ["比亚迪", "长安汽车", "赛力斯"]},
        ],
    }
    payload.update(overrides)
    return ChainFacts.model_validate(payload)


def test_vehicle_card_is_reviewed_full_chain() -> None:
    facts = try_load_chain_facts("新能源汽车")
    assert facts is not None
    assert facts.profile_key == "vehicle"
    assert facts.status == "reviewed"
    assert facts.frame == "full_chain"
    assert [seg.stage for seg in facts.segments] == ["upstream", "midstream", "downstream"]
    assert facts.review_errors() == []
    assert facts.attribution_basis.startswith("chain_facts:vehicle@")


def test_five_sample_companies_are_grouped_correctly() -> None:
    facts = try_load_chain_facts("新能源汽车")
    assert facts is not None
    mid = next(seg for seg in facts.segments if seg.stage == "midstream")
    down = next(seg for seg in facts.segments if seg.stage == "downstream")
    assert mid.companies == ["宁德时代", "亿纬锂能"]
    assert down.companies == ["比亚迪", "长安汽车", "赛力斯"]
    assert not (set(mid.companies) & set(down.companies))


def test_unreviewed_industry_yields_no_facts() -> None:
    """No card for other industries: downstream must emit a gap, never invent facts."""
    assert try_load_chain_facts("白酒") is None
    assert not (_FACTS_DIR / "liquor.json").exists()


def test_review_errors_reject_draft_wrong_frame_and_duplicate_groups() -> None:
    assert any("status" in e for e in _valid_facts(status="draft").review_errors())
    assert any("frame" in e for e in _valid_facts(frame="vehicle_centric").review_errors())
    assert any("more than one" in e for e in _valid_facts(comparison_groups=[
        {"group": "A", "members": ["宁德时代"]},
        {"group": "B", "members": ["宁德时代"]},
    ]).review_errors())
    assert any("gap declaration" in e for e in _valid_facts(segments=[
        _segment("upstream", sample_status="not_in_sample"),
        _segment("midstream", ["宁德时代"]),
        _segment("downstream", ["比亚迪"]),
    ]).review_errors())


def test_knowledge_facts_match_typed_schema_and_mark_hypotheses() -> None:
    from data_interpreter.models import KnowledgeFact

    facts = try_load_chain_facts("新能源汽车")
    assert facts is not None
    rows = chain_knowledge_facts(facts)
    predicates = {row["predicate"] for row in rows}
    assert {"硬性分析规则", "口径限制", "合并报表口径差异", "数据缺口"} <= predicates
    assert any("待验证假设" in p for p in predicates)
    assert all(row["category"] == "industry_chain" for row in rows)
    assert any(row["confidence"] == "low" for row in rows), "hypotheses must be low confidence"
    for row in rows:
        KnowledgeFact.model_validate(row)


def test_topology_prompt_injects_full_chain_frame() -> None:
    from chart_generator.chain_topology import topology_system

    prompt = topology_system("新能源汽车")
    assert "已审定全链三段骨架" in prompt
    assert "宁德时代" in prompt
    assert "不得据此判定环节归属" in prompt


def _record(entity: str, metric: str, record_id: str) -> SimpleNamespace:
    """Minimal duck-typed A1 record; only fields used by the builder matter."""
    return SimpleNamespace(
        record_id=record_id,
        domain="industry_chain",
        entity_name=entity,
        entity_code=None,
        metric=metric,
        value=None,
        raw_fields={},
    )


class _FakeDataset:
    """A1-shaped dataset with the five sample companies and business evidence."""

    def all_records(self) -> list[SimpleNamespace]:
        rows = [
            _record("宁德时代", "latest_price", "R-quote-1"),
            _record("宁德时代", "主营产品", "R-biz-catl"),
            _record("亿纬锂能", "主营产品", "R-biz-evl"),
            _record("比亚迪", "主营产品", "R-biz-byd"),
            _record("长安汽车", "经营范围", "R-biz-ca"),
            _record("赛力斯", "主营产品", "R-biz-sl"),
            _record("中国中车", "industry_name", "R-cross-1"),
        ]
        return rows


def test_a2_segments_follow_reviewed_card() -> None:
    from data_interpreter.engine import DeterministicAnalysisEngine

    facts = try_load_chain_facts("新能源汽车")
    assert facts is not None
    engine = object.__new__(DeterministicAnalysisEngine)
    segments = engine.build_segments_from_chain_facts(facts, _FakeDataset(), None)

    by_stage = {seg.stage: seg for seg in segments}
    assert set(by_stage) == {"upstream", "midstream", "downstream"}

    up, mid, down = by_stage["upstream"], by_stage["midstream"], by_stage["downstream"]
    assert up.representative_companies == []
    assert up.source_tier == "gap"
    assert "未纳入样本" in up.gap_declaration
    assert mid.representative_companies == ["宁德时代", "亿纬锂能"]
    assert down.representative_companies == ["比亚迪", "长安汽车", "赛力斯"]
    assert mid.source_tier == down.source_tier == "reviewed_profile"
    assert all(seg.attribution_basis == facts.attribution_basis for seg in segments)
    assert mid.comparison_group == "电池组"
    assert down.comparison_group == "整车组"

    all_refs = [rid for seg in segments for rid in seg.evidence_record_ids]
    assert len(all_refs) == len(set(all_refs)), "one record id must not back two segments"
    assert "R-quote-1" not in all_refs, "quotes are not attribution evidence"
    assert "R-cross-1" not in all_refs, "cross-industry companies must not leak in"
    assert mid.comparison_rules and mid.non_comparable_reasons and mid.forbidden


def test_a4_gate_rejects_industry_common_but_accepts_reviewed() -> None:
    from chapter_writer.agent import extract_global_quantitative_anchor

    def _report(tier: str, basis: str, refs: list[str]) -> SimpleNamespace:
        return SimpleNamespace(
            comps_matrix=None,
            evidence_index={"R-1": SimpleNamespace(entity="宁德时代")},
            industry_chain_segments=[{
                "segment_name": "上游：基础支撑",
                "stage": "upstream",
                "representative_companies": ["宁德时代"],
                "evidence_record_ids": refs,
                "source_tier": tier,
                "attribution_basis": basis,
            }],
        )

    # Quote/classification evidence must NOT unlock a legacy attribution.
    blocked = extract_global_quantitative_anchor(_report("industry_common", "", ["R-1"]))
    assert blocked["canonical_segments"] == {}
    assert "宁德时代" in blocked["pending_attribution"]

    # A reviewed card is the basis itself: A1 has no business-attribute
    # records for the five sample companies, so refs are legitimately empty.
    allowed = extract_global_quantitative_anchor(
        _report("reviewed_profile", "chain_facts:vehicle@2026-11-09", [])
    )
    assert allowed["canonical_segments"].get("宁德时代") == "上游：基础支撑"


@pytest.mark.parametrize("subject", ["", "白酒行业", "光伏产业链"])
def test_no_card_for_other_subjects(subject: str) -> None:
    """Only the reviewed industry may produce attribution facts."""
    assert try_load_chain_facts(subject) is None


def test_reviewed_card_drives_a3_structure_skeleton() -> None:
    from chart_generator.chain_structure import detect_structure

    spec = detect_structure("新能源汽车")
    assert spec.key == "reviewed_vehicle"
    assert [s.stage for s in spec.stages] == ["upstream", "midstream", "downstream"]
    assert any(s.is_core for s in spec.stages)
    # Industries without a card keep the original decision tree.
    assert not detect_structure("白酒").key.startswith("reviewed_")


def test_guards_isolate_valuation_judgements() -> None:
    from data_interpreter.analysis_guard import apply_guards
    from datetime import date

    summary, insights, log = apply_guards(
        executive_summary="行业规模扩大。",
        insights=[
            {"insight_id": "I-1", "title": "销量增长", "conclusion": "2025 年销量上升"},
            {"insight_id": "I-2", "title": "行业估值处于高位",
             "conclusion": "PE 30.5 倍，市场预期或已透支，存在回调风险"},
        ],
        as_of=date(2026, 11, 9),
    )
    assert len(insights) == 1 and insights[0]["insight_id"] == "I-1"
    assert any(x["action"] == "isolated_valuation_judgement" for x in log)
    assert summary == "行业规模扩大。"


def test_guards_annotate_mixed_periods() -> None:
    from datetime import date

    from data_interpreter.analysis_guard import apply_guards

    _, insights, log = apply_guards(
        executive_summary="",
        insights=[{"insight_id": "I-3", "title": "出口趋势",
                   "conclusion": "2021-2025 出口增长，2026 年前三季度同比 130%"}],
        as_of=date(2026, 11, 9),
    )
    assert "不与已完成年度并列" in insights[0]["conclusion"]
    assert any(x["action"] == "period_boundary_annotated" for x in log)


def test_insight_title_rewrite_keeps_entity_and_metric() -> None:
    from data_interpreter.analysis_guard import normalize_insight_title

    title = ("中国2021-12-31（ytd_month，合并报表）新能源汽车:销量:累计值为3.521e+06辆；"
             "中国2022-12-31销量为6.887e+06辆；中国2023-12-31销量为9.5e+06辆")
    result = normalize_insight_title(title, "呈上升趋势，方向一致率高")
    assert "中国" in result and "销量" in result and "上升" in result
    assert "e+06" not in result
    assert len(result) <= 40


def test_executive_summary_dedupes_boilerplate() -> None:
    from data_interpreter.analysis_guard import dedupe_executive_summary

    boiler = "2025-01-01至2025-12-31（年度，合并报表，CNY）已覆盖样本5家，营业收入最高为比亚迪；"
    summary = "行业销量高速增长。" + boiler * 4 + "毛利率整体分化。"
    cleaned = dedupe_executive_summary(summary)
    assert cleaned.count("已覆盖样本") == 1
    assert cleaned.startswith("行业销量高速增长。")


def test_group_comparison_never_overclaims_hypotheses() -> None:
    from datetime import date

    from data_interpreter.analysis_guard import build_group_comparison

    rows = []
    for year in (2023, 2024, 2025):
        for company, gm in (("宁德时代", 19.0), ("亿纬锂能", 17.0),
                            ("比亚迪", 20.0), ("长安汽车", 15.0), ("赛力斯", 10.0)):
            rows.append(SimpleNamespace(
                entity_name=company, period_end=date(year, 12, 31),
                metric="gross_margin", value=gm + year - 2023,
                record_id=f"R-gm-{company}-{year}",
            ))
        for company in ("宁德时代", "亿纬锂能"):
            for metric, value in (("rd_expense", 1.8e10), ("revenue", 3.6e11)):
                rows.append(SimpleNamespace(
                    entity_name=company, period_end=date(year, 12, 31),
                    metric=metric, value=value, record_id=f"R-{metric}-{company}-{year}",
                ))
    dataset = SimpleNamespace(all_records=lambda: rows)
    facts = try_load_chain_facts("新能源汽车")
    assert facts is not None

    result = build_group_comparison(dataset, facts, as_of=date(2026, 11, 9))
    assert result["completed_years"] == [2023, 2024, 2025]
    assert set(result["groups"]) == {"电池组", "整车组"}
    battery = result["groups"]["电池组"]["series"]
    vehicle = result["groups"]["整车组"]["series"]
    assert "group_mean" in battery["rd_ratio_derived"]
    assert "gap" in vehicle["rd_ratio_derived"], "must not borrow rd_expense across groups"
    assert "cash_profit_sync" in battery
    verdicts = {v["hypothesis_id"]: v["verdict"] for v in result["hypothesis_verdicts"]}
    assert verdicts["H2"] == "insufficient_evidence", \
        "gross margin cannot validate vertical integration / multi-sourcing"
    assert verdicts["H1"] in {"sequence_consistent", "partially_supported"}
    assert all("仅用于讨论产业链利润分配" in x["note"] for x in result["cross_group"])
