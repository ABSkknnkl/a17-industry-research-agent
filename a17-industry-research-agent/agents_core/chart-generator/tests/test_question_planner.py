"""A3 用户问题驱动选图 · question_planner 回归（方案第 6 节）。

全部用离线夹具，不调用真实模型、不触发渲染或发布门禁。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from chart_generator import question_planner as qp
from chart_generator.models import QuestionBrief


FOUR_QUESTIONS = [
    "2021—2025 年销量及市场渗透率如何变化？请比较比亚迪、长安汽车和赛力斯的营收、毛利率及经营现金流，并分析整车与动力电池产业链关系，形成含数据表、趋势图、产业链结构与证据来源的完整行业研究报告。",
    "2021—2025 年中国新能源汽车销量、渗透率及出口量如何变化？不同统计口径（汽车总量、乘用车等）会如何影响结论？",
    "比亚迪、长安汽车、赛力斯 2023—2025 年的营收、毛利率及经营现金流如何分化？能否对整车业务单独比较？",
    "宁德时代、亿纬锂能与整车企业在研发强度、利润率及现金流方面有何差异？为什么应按动力电池与整车环节分组分析？",
]


def _chart(cid: str, ctype: str, metrics=("销量",), entities=("中国",)):
    return SimpleNamespace(
        chart_id=cid,
        chart_type=ctype,
        title=f"图 {cid}",
        data_contract={"points": [
            {"metric": m, "entity": e, "period": "2025-12-31", "unit": "万辆"}
            for m in metrics for e in entities
        ]},
        evidence_ids=["R-1", "R-2"],
    )


def _report():
    refs = {}
    for i, metric in enumerate(("销量", "出口量", "毛利率", "渗透率")):
        refs[f"R-{i}"] = SimpleNamespace(
            metric=metric, entity="中国", domain="industry",
            scope="consolidated", period="2025-12-31",
        )
    return SimpleNamespace(evidence_index=refs)


class StubLLM:
    def __init__(self, payload: dict | None = None, fail: bool = False):
        self.payload = payload
        self.fail = fail
        self.calls = 0

    async def select_cards(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        if self.fail:
            raise TimeoutError("simulated timeout")
        return json.dumps(self.payload or {}, ensure_ascii=False)


# ---------------------------------------------------------------- 题面与上下文
def test_parse_question_briefs_keeps_original_text_and_system_ids():
    briefs = qp.parse_question_briefs(FOUR_QUESTIONS)
    assert [b.question_id for b in briefs] == ["Q-1", "Q-2", "Q-3", "Q-4"]
    assert briefs[1].text == FOUR_QUESTIONS[1]
    assert "趋势" in briefs[1].relation_tags
    assert "口径" in briefs[1].relation_tags
    assert "分组" in briefs[3].relation_tags
    assert 2021 in briefs[1].years and 2025 in briefs[1].years


def test_priority_is_rule_based_not_llm_generated():
    briefs = qp.parse_question_briefs(FOUR_QUESTIONS)
    assert briefs[1].priority == "P0"   # 趋势 + 口径
    assert briefs[3].priority == "P0"   # 分组
    assert briefs[0].sub_questions      # 综合题被拆出子问题


def test_global_no_chart_and_single_question_forbidden():
    none_mode = qp.parse_question_briefs(FOUR_QUESTIONS, chart_mode="none")
    assert all(b.chart_forbidden for b in none_mode)
    assert all(not b.requests_chart for b in none_mode)
    zero = qp.parse_question_briefs(FOUR_QUESTIONS, requested_chart_count=0)
    assert all(b.chart_forbidden for b in zero)
    mixed = qp.parse_question_briefs(["销量趋势如何变化？请配趋势图", "这个问题不需要图，仅文字说明"])
    assert mixed[0].requests_chart is True
    assert mixed[1].chart_forbidden is True


def test_defaulted_focus_is_not_treated_as_user_requirement():
    briefs = qp.parse_question_briefs(["产业链"], defaulted_focus=True)
    assert briefs[0].defaulted_focus is True
    assert briefs[0].requests_chart is False


def test_question_contract_hash_is_stable():
    briefs = qp.parse_question_briefs(FOUR_QUESTIONS)
    payload = qp.question_contract_payload(briefs, subject="新能源汽车", as_of="2026-11-09")
    assert qp.question_contract_sha256(payload) == qp.question_contract_sha256(
        qp.question_contract_payload(qp.parse_question_briefs(FOUR_QUESTIONS),
                                     subject="新能源汽车", as_of="2026-11-09")
    )
    assert len(payload["questions"]) == 4


# ---------------------------------------------------------------- 证据召回与候选卡
def test_recall_evidence_filters_by_year_and_does_not_pull_unrelated():
    report = _report()
    brief = QuestionBrief(question_id="Q-2", text="2021—2025 年销量与出口量如何变化",
                          metrics=["销量", "出口量"], years=[2025])
    ids = qp.recall_evidence(report, brief)
    assert set(ids) == {"R-0", "R-1"}
    out_of_range = qp.recall_evidence(
        report, QuestionBrief(question_id="Q-9", text="销量", metrics=["销量"], years=[2019]))
    assert out_of_range == []


def test_candidate_cards_come_from_published_charts_and_keep_gap():
    briefs = qp.parse_question_briefs(FOUR_QUESTIONS)
    charts = [_chart("CH-1", "combo"), _chart("CH-2", "line"), _chart("CH-3", "industry_chain")]
    cards = qp.build_candidate_cards(charts, briefs, _report())
    assert {c.candidate_ref for c in cards} == {"CH-1", "CH-2", "CH-3"}
    assert all(c.ideal_role for c in cards)
    assert all(c.feasible_expression in {"combo", "line", "industry_chain"} for c in cards)
    assert all(c.gap is None for c in cards)


# ---------------------------------------------------------------- 选卡与回退
def test_validate_selection_rejects_bad_cards_and_cross_question_refs():
    briefs = qp.parse_question_briefs(FOUR_QUESTIONS[:2])
    cards = qp.build_candidate_cards([_chart("CH-1", "combo"), _chart("CH-2", "line")], briefs, _report())
    raw = {"selections": [
        {"question_id": "Q-1", "needs_chart": True, "primary_card_ids": ["CARD-NOPE"]},
        {"question_id": "Q-2", "needs_chart": True, "primary_card_ids": [cards[0].card_id]},
    ]}
    items, errors = qp.validate_selection(raw, briefs, cards)
    assert any("invalid_or_cross_card" in e for e in errors)
    legal = {c.card_id for c in cards}
    assert all(cid in legal for cid in items[0].primary_card_ids)
    assert items[0].selection_source == "deterministic_fallback"
    assert "逐题确定性回退" in (items[0].fallback_reason or "")
    assert any("missing_question" in e for e in errors) is False  # 两题都在


def test_explicit_chart_request_cannot_be_cancelled_by_llm():
    briefs = qp.parse_question_briefs(["销量趋势如何变化？请配趋势图"])
    cards = qp.build_candidate_cards([_chart("CH-1", "line")], briefs, _report())
    items, errors = qp.validate_selection(
        {"selections": [{"question_id": "Q-1", "needs_chart": False, "primary_card_ids": []}]},
        briefs, cards,
    )
    assert items[0].needs_chart is True
    assert any("explicit_chart_cancelled" in e for e in errors)


def test_missing_question_falls_back_to_highest_ranked_candidate():
    briefs = qp.parse_question_briefs(FOUR_QUESTIONS[:2])
    cards = qp.build_candidate_cards([_chart("CH-1", "combo")], briefs, _report())
    items, errors = qp.validate_selection({"selections": []}, briefs, cards)
    assert len(items) == 2
    assert all(i.selection_source == "deterministic_fallback" for i in items)
    assert any("missing_question" in e for e in errors)


def test_missing_required_metric_is_backfilled_from_legal_candidates():
    briefs = qp.parse_question_briefs(
        ["宁德时代、亿纬锂能与整车企业在研发强度、利润率方面有何差异？为什么应按环节分组分析？"])
    assert {"研发强度", "利润率"} <= set(briefs[0].metrics)
    charts = [
        _chart("CH-1", "bar", metrics=("毛利率",)),
        _chart("CH-2", "bar", metrics=("rd_ratio_derived",)),
    ]
    cards = qp.build_candidate_cards(charts, briefs, _report())
    selected = next(c for c in cards if c.candidate_ref == "CH-1")
    items, _ = qp.validate_selection(
        {"selections": [{"question_id": "Q-1", "needs_chart": True,
                         "primary_card_ids": [selected.card_id]}]},
        briefs, cards,
    )
    refs = items[0].supporting_card_ids
    assert any(r.endswith("CH-2") for r in refs), "研发强度未被覆盖时应补位研发费用率图"
    assert items[0].uncovered == []


def test_uncovered_requirement_is_recorded_not_silently_dropped():
    briefs = qp.parse_question_briefs(["比亚迪的销量与出口量如何变化？"])
    cards = qp.build_candidate_cards([_chart("CH-1", "line", metrics=("销量",))], briefs, _report())
    items, errors = qp.validate_selection(
        {"selections": [{"question_id": "Q-1", "needs_chart": True,
                         "primary_card_ids": [cards[0].card_id]}]},
        briefs, cards,
    )
    assert "出口量" in items[0].uncovered
    assert any("requirement_uncovered" in e for e in errors)


def test_build_plan_llm_failure_uses_deterministic_fallback():
    briefs = qp.parse_question_briefs(FOUR_QUESTIONS[:2])
    cards = qp.build_candidate_cards([_chart("CH-1", "combo")], briefs, _report())
    plan = asyncio.run(qp.build_question_plan(
        briefs, cards, mode="apply", llm=StubLLM(fail=True)))
    assert all(i.selection_source == "deterministic_fallback" for i in plan.questions)
    assert all("LLM 调用失败" in (i.fallback_reason or "") for i in plan.questions)


def test_candidate_budget_trim_is_recorded_not_silent():
    briefs = qp.parse_question_briefs(FOUR_QUESTIONS[:1])
    charts = [_chart(f"CH-{i}", "line") for i in range(60)]
    cards = qp.build_candidate_cards(charts, briefs, _report())
    plan = asyncio.run(qp.build_question_plan(briefs, cards, mode="observe"))
    assert any("candidate_budget_trimmed" in g for g in plan.capability_gaps)
    assert len(plan.questions) == 1


def test_build_plan_off_and_observe_never_call_llm():
    briefs = qp.parse_question_briefs(FOUR_QUESTIONS[:1])
    cards = qp.build_candidate_cards([_chart("CH-1", "combo")], briefs, _report())
    stub = StubLLM()
    for mode in ("off", "observe"):
        plan = asyncio.run(qp.build_question_plan(briefs, cards, mode=mode, llm=stub))
        assert plan.mode == mode
    assert stub.calls == 0


def test_build_plan_apply_calls_llm_at_most_once():
    briefs = qp.parse_question_briefs(FOUR_QUESTIONS[:2])
    cards = qp.build_candidate_cards([_chart("CH-1", "combo"), _chart("CH-2", "line")], briefs, _report())
    stub = StubLLM({"selections": [
        {"question_id": "Q-1", "needs_chart": True, "primary_card_ids": [cards[0].card_id]},
        {"question_id": "Q-2", "needs_chart": True, "primary_card_ids": [cards[1].card_id]},
    ]})
    plan = asyncio.run(qp.build_question_plan(briefs, cards, mode="apply", llm=stub))
    assert stub.calls == 1
    assert all(i.selection_source == "llm" for i in plan.questions)


# ---------------------------------------------------------------- 执行与覆盖
def test_apply_plan_reorders_without_adding_charts():
    briefs = qp.parse_question_briefs(FOUR_QUESTIONS[:2])
    charts = [_chart("CH-1", "bar"), _chart("CH-2", "combo")]
    cards = qp.build_candidate_cards(charts, briefs, _report())
    plan = qp.QuestionChartPlan(
        mode="apply",
        questions=[qp.QuestionPlanItem(question_id="Q-1", priority="P0",
                                       primary_card_ids=[cards[1].card_id])],
    )
    ordered = qp.apply_plan_to_charts(plan, charts)
    assert [c.chart_id for c in ordered] == ["CH-2"]
    assert ordered[0].chart_id == "CH-2"


def test_settle_coverage_uses_actual_published_charts():
    briefs = qp.parse_question_briefs(FOUR_QUESTIONS[:2])
    charts = [_chart("CH-1", "combo"), _chart("CH-2", "line")]
    cards = qp.build_candidate_cards(charts, briefs, _report())
    plan = qp.QuestionChartPlan(mode="apply", questions=[
        qp.QuestionPlanItem(question_id="Q-1", needs_chart=True,
                            primary_card_ids=[cards[0].card_id, cards[1].card_id]),
        qp.QuestionPlanItem(question_id="Q-2", needs_chart=False,
                            selection_source="not_needed"),
    ])
    settled = qp.settle_coverage(plan, charts[:1], cards)
    assert settled.coverage[0].status == "partially_published"
    assert settled.coverage[1].status == "not_needed"
    legacy = qp.legacy_question_coverage(settled)
    assert legacy[0]["question_id"] == "Q-1"
    assert legacy[0]["status"] == "partially_published"


def test_zero_candidate_records_evidence_gap():
    briefs = qp.parse_question_briefs(FOUR_QUESTIONS[:1])
    plan = asyncio.run(qp.build_question_plan(briefs, [], mode="apply", llm=StubLLM()))
    settled = qp.settle_coverage(plan, [], [])
    assert settled.coverage[0].status == "evidence_gap"


def test_selection_prompt_excludes_values_and_evidence_ids():
    briefs = qp.parse_question_briefs(FOUR_QUESTIONS[:1])
    cards = qp.build_candidate_cards([_chart("CH-1", "combo")], briefs, _report())
    system, user = qp.build_selection_prompt(briefs, cards, max_cards=6)
    assert "R-1" not in user
    assert "万辆" not in user
    assert "Q-1" in user and "CARD-CH-1" in user
    assert "不得判定为无需图" in system
