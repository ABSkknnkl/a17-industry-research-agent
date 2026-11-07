"""skill_policy.merge_selection 的单元测试。

覆盖：并集正确性、去重、强制技能优先级、limit 截断、来源标注、参数校验。
全部为纯函数测试，不消耗模型与数据配额。
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from skill_policy import (
    SOURCE_BOTH,
    SOURCE_MODEL,
    SOURCE_POLICY,
    admit_policy_skill,
    merge_selection,
    screen_policy_skills,
)


@dataclass
class FakeSkill:
    """模拟各层真实的技能对象（name + always 是四层共有的字段）。"""

    name: str
    always: bool = False


def names(result):
    return [s.name for s in result.final]


def test_union_keeps_model_and_adds_policy():
    """模型选 2 个、规则给 3 个（含 1 个重叠）→ 并集 4 个。"""
    model = [FakeSkill("a"), FakeSkill("b")]
    policy = [FakeSkill("b"), FakeSkill("c"), FakeSkill("d")]

    result = merge_selection(model, policy)

    assert names(result) == ["a", "b", "c", "d"]
    assert result.provenance == {"a": SOURCE_MODEL, "b": SOURCE_BOTH, "c": SOURCE_POLICY, "d": SOURCE_POLICY}
    assert result.added_by_policy == ["c", "d"]
    assert result.rescued_count == 2


def test_duplicate_skill_appears_once():
    """两侧同名技能只保留一份，标注为 both。"""
    model = [FakeSkill("same")]
    policy = [FakeSkill("same")]

    result = merge_selection(model, policy)

    assert names(result) == ["same"]
    assert result.provenance["same"] == SOURCE_BOTH
    assert result.added_by_policy == []


def test_forced_skills_survive_limit():
    """强制技能排在前面，截断时不会被丢掉。"""
    model = [FakeSkill("m1"), FakeSkill("m2")]
    policy = [FakeSkill("forced", always=True), FakeSkill("p1")]

    result = merge_selection(model, policy, limit=2)

    assert names(result) == ["forced", "m1"]
    assert "m2" in result.dropped_by_limit
    assert "p1" in result.dropped_by_limit


def test_limit_drops_from_tail_and_records():
    model = [FakeSkill("a"), FakeSkill("b")]
    policy = [FakeSkill("c"), FakeSkill("d")]

    result = merge_selection(model, policy, limit=3)

    assert names(result) == ["a", "b", "c"]
    assert result.dropped_by_limit == ["d"]


def test_limit_none_means_no_truncation():
    model = [FakeSkill("a")]
    policy = [FakeSkill("b")]

    result = merge_selection(model, policy)

    assert names(result) == ["a", "b"]
    assert result.dropped_by_limit == []


def test_empty_and_none_inputs():
    """模型不可用（None）时退化为纯规则结果；两侧都空则返回空。"""
    only_policy = merge_selection(None, [FakeSkill("p")])
    assert names(only_policy) == ["p"]
    assert only_policy.provenance == {"p": SOURCE_POLICY}
    assert only_policy.model_count == 0
    assert only_policy.policy_count == 1

    empty = merge_selection([], [])
    assert names(empty) == []
    assert empty.provenance == {}

    assert names(merge_selection(None, None)) == []


def test_negative_limit_raises():
    with pytest.raises(ValueError):
        merge_selection([], [], limit=-1)


def test_zero_limit_keeps_nothing():
    result = merge_selection([FakeSkill("a")], [FakeSkill("b")], limit=0)

    assert names(result) == []
    assert set(result.dropped_by_limit) == {"a", "b"}


def test_custom_accessors_for_layers_without_name_field():
    """允许用自定义取名字段适配不同层的技能对象形态。"""
    class Odd:
        def __init__(self, skill_id: str):
            self.skill_id = skill_id

    result = merge_selection(
        [Odd("x")],
        [Odd("y")],
        name_of=lambda s: s.skill_id,
    )

    assert [s.skill_id for s in result.final] == ["x", "y"]
    assert result.provenance == {"x": SOURCE_MODEL, "y": SOURCE_POLICY}


def test_custom_is_always_marks_forced():
    class NoAlwaysField:
        def __init__(self, name: str):
            self.name = name

    model = [NoAlwaysField("m")]
    policy = [NoAlwaysField("forced")]

    result = merge_selection(
        model,
        policy,
        limit=1,
        is_always=lambda s: s.name == "forced",
    )

    assert names(result) == ["forced"]
    assert result.dropped_by_limit == ["m"]


def test_forced_from_both_sides_not_duplicated():
    """两侧都给的同一个强制技能，只出现一次。"""
    model = [FakeSkill("qc", always=True)]
    policy = [FakeSkill("qc", always=True)]

    result = merge_selection(model, policy)

    assert names(result) == ["qc"]
    assert result.provenance["qc"] == SOURCE_BOTH


# ---------------------------------------------------------------------------
# 补入准入裁剪：通用技能无条件补，条件技能仅在意图命中信号时补
# ---------------------------------------------------------------------------


@dataclass
class RichSkill:
    """带信号门槛的技能对象，用于验证准入裁剪。"""

    name: str
    always: bool = False
    requires_signal: bool = False
    keywords: tuple = ()


def test_universal_skill_always_admitted():
    """不需要信号的技能属于通用，任何意图下都补入。"""
    ok, reason = admit_policy_skill(RichSkill("competitive-landscape-analysis"), "市场规模与增速")
    assert ok is True and reason == "universal"


def test_explicit_universal_admitted_even_if_requires_signal():
    """财报分析这类显式通用技能，即便带信号门槛也照常补入。"""
    skill = RichSkill("financial-statement-analysis", requires_signal=True, keywords=("财务",))
    ok, reason = admit_policy_skill(skill, "动力电池行业近5年市场规模、增速")
    assert ok is True and reason == "universal"


def test_conditional_skill_dropped_without_intent_signal():
    """问的是市场规模，没提 ESG —— 条件技能应被裁掉。"""
    skill = RichSkill(
        "esg-risk-analysis",
        requires_signal=True,
        keywords=("ESG", "环境", "社会责任", "治理", "碳排放"),
    )
    ok, reason = admit_policy_skill(skill, "动力电池行业近5年市场规模、增速")
    assert ok is False and reason == "conditional-without-intent-signal"


def test_conditional_skill_admitted_when_intent_mentions_it():
    """意图里明确问到 ESG，条件技能应准入。"""
    skill = RichSkill(
        "esg-risk-analysis",
        requires_signal=True,
        keywords=("ESG", "环境", "社会责任", "治理"),
    )
    ok, reason = admit_policy_skill(skill, "动力电池行业的环境治理与碳排放情况如何")
    assert ok is True and reason.startswith("signal:")


def test_conditional_extra_signals_table_extends_keywords():
    """登记表里的补充信号也能触发（即便技能自身 keywords 没写）。"""
    skill = RichSkill("esg-risk-analysis", requires_signal=True, keywords=())
    ok, _ = admit_policy_skill(skill, "该企业的绿色转型与可持续发展进展")
    assert ok is True


def test_no_intent_text_keeps_previous_behaviour():
    """没传意图文本时不裁剪，避免误杀（向后兼容）。"""
    skill = RichSkill("esg-risk-analysis", requires_signal=True, keywords=("ESG",))
    ok, reason = admit_policy_skill(skill, None)
    assert ok is True and reason == "no-intent-text"


def test_screen_policy_skills_splits_kept_and_dropped():
    kept, dropped = screen_policy_skills(
        [
            RichSkill("financial-statement-analysis", requires_signal=True, keywords=("财务",)),
            RichSkill("esg-risk-analysis", requires_signal=True, keywords=("ESG", "碳排放")),
            RichSkill("industry-chain-analysis"),
        ],
        "动力电池行业近5年市场规模、增速",
    )
    assert [s.name for s in kept] == ["financial-statement-analysis", "industry-chain-analysis"]
    assert dropped == ["esg-risk-analysis"]


def test_merge_selection_screens_policy_when_intent_given():
    """传入意图时，条件技能在补入前被裁掉，且记入 screened_out。"""
    model = [FakeSkill("industry-overview-analysis")]
    policy = [
        RichSkill("financial-statement-analysis", requires_signal=True, keywords=("财务",)),
        RichSkill("esg-risk-analysis", requires_signal=True, keywords=("ESG", "环境")),
    ]
    result = merge_selection(
        model, policy, limit=10, intent_text="动力电池行业近5年市场规模、增速"
    )
    # 顺序遵循「模型优先、规则只补漏」：模型选的在前，规则补的在后
    assert names(result) == ["industry-overview-analysis", "financial-statement-analysis"]
    assert result.screened_out == ["esg-risk-analysis"]
    assert result.added_by_policy == ["financial-statement-analysis"]


def test_merge_selection_without_intent_keeps_all_policy_skills():
    """不传意图时行为与改造前一致：条件技能照常补入。"""
    model = [FakeSkill("industry-overview-analysis")]
    policy = [RichSkill("esg-risk-analysis", requires_signal=True, keywords=("ESG",))]

    result = merge_selection(model, policy, limit=10)

    assert "esg-risk-analysis" in names(result)
    assert result.screened_out == []


def test_merge_selection_can_disable_screening():
    """显式关闭裁剪时退回旧行为。"""
    policy = [RichSkill("esg-risk-analysis", requires_signal=True, keywords=("ESG",))]
    result = merge_selection(
        [FakeSkill("x")], policy, limit=10,
        intent_text="市场规模", screen=False,
    )
    assert "esg-risk-analysis" in names(result)
