"""第二刀验收（2026-09-01 方案 §2 第二刀 / §4.4）：
L1 派生词否定表 + 最长匹配优先。

子串包含本身没错，错在命中即 ``conf=1.0`` 锁死。两道后校验：

1. 最长匹配优先——“在建产能”赢“产能”，长 alias 命中后短 alias 不再
   独立命中（顺带治第三刀的口径合并丢失）；
2. 派生词否定表——命中 alias 后扫描原文 ±8 字符窗口，检出派生词
   （投资/爬坡/过剩/跑满…）则不 lock，标 ``derivative_suspected``
   降级给 L2 判。

否定表外置在 ``backend/config/metric_derivative_blacklist.yaml``，测试用
``METRIC_DERIVATIVE_BLACKLIST_PATH`` 覆盖路径，验证热修能力。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agents.data_fetcher.deterministic_intent_parser import parse_intent
from app.agents.data_fetcher.intent_merger import build_intent_plan
from app.agents.data_fetcher.metric_registry import get_metric_spec
from app.schemas.acquisition import SkillName


def _locked_values(text: str, *, topic: str = "光伏组件") -> set[str]:
    parse = parse_intent(text, industry_topic=topic, known_entities=[topic])
    return {skill.value for skill in parse.locked_skills}


def test_capacity_investment_derivative_not_locked() -> None:
    """「单位产能投资」问的是投资额（财务口径），不是产能——
    派生词「投资」命中后不得 lock INDUSTRY（治 9 条静默误判之首）。"""

    locked = _locked_values("企业单位产能投资是多少")
    assert SkillName.INDUSTRY.value not in locked


def test_derivative_family_not_locked() -> None:
    """否定表全族：爬坡/过剩/跑满检出即降级，不得静默取产能数据。"""

    for text in (
        "光伏组件产能爬坡周期一般多长",
        "光伏组件行业产能有没有过剩",
        "新产能多久能跑满",
    ):
        locked = _locked_values(text)
        assert SkillName.INDUSTRY.value not in locked, text


def test_longest_alias_wins_over_generic_capacity() -> None:
    """最长匹配优先：「在建产能」命中独立口径，泛化「产能」不再叠加命中。"""

    spec = get_metric_spec("在建产能")
    assert spec is not None and spec.key == "under_construction_capacity"

    parse = parse_intent("光伏行业在建产能有多少", industry_topic="光伏行业")
    assert "在建产能" in parse.metric_names
    # 泛化口径不得重复计数（最长匹配吃掉短 alias）。
    assert parse.metric_names.count("产能") == 0


def test_blacklist_loaded_from_external_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """否定表外置生效：改配置即行为变化，不发版。"""

    # 默认词表不含「销量→指引」：原行为会 lock BUSINESS。
    baseline = _locked_values("宁德时代销量指引是多少", topic="宁德时代")
    assert SkillName.BUSINESS.value in baseline

    custom = tmp_path / "blacklist.yaml"
    custom.write_text("销量:\n  - 指引\n", encoding="utf-8")
    monkeypatch.setenv("METRIC_DERIVATIVE_BLACKLIST_PATH", str(custom))

    locked = _locked_values("宁德时代销量指引是多少", topic="宁德时代")
    assert SkillName.BUSINESS.value not in locked


def test_window_no_false_positive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """窗口外派生词不误伤：±8 字符之外的派生词不触发降级。"""

    # 「产能利用率」是独立注册指标（更长 alias），正常 lock。
    locked = _locked_values("光伏组件行业产能利用率是多少")
    assert SkillName.INDUSTRY.value in locked

    # 「投资」距离「产能」超过 8 字符 → 产能正常命中。
    locked = _locked_values("光伏行业产能情况怎么样，整个产业链投资强度如何")
    assert SkillName.INDUSTRY.value in locked


def test_empty_blacklist_keeps_legacy_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """否定表为空时行为与旧版一致：子串命中即 lock（回归底线）。"""

    empty = tmp_path / "empty.yaml"
    empty.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("METRIC_DERIVATIVE_BLACKLIST_PATH", str(empty))

    locked = _locked_values("企业单位产能投资是多少")
    assert SkillName.INDUSTRY.value in locked


@pytest.mark.asyncio
async def test_derivative_downgrade_writes_telemetry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """降级事件写 ``derivative_suspected`` 遥测（miss 回流闭环的输入）。"""

    monkeypatch.setenv("ROUTING_TELEMETRY_DIR", str(tmp_path / "telemetry"))
    await build_intent_plan(
        "企业单位产能投资是多少",
        industry_topic="光伏组件",
    )

    events = [
        json.loads(line)
        for file in (tmp_path / "telemetry").glob("*.jsonl")
        for line in file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(record.get("event") == "derivative_suspected" for record in events)


# ---------------------------------------------------------------------------
# 业务裁决（2026-09-01）：预测类诉求 + 产能爬坡语义拆分
# ---------------------------------------------------------------------------


def test_predictive_words_demote_metric_lock() -> None:
    """裁决 1：含「增量/预计/预测/前瞻」的问句统一判派生诉求——
    指标锁降级，禁止用历史指标查询替代预测结果。"""

    locked = _locked_values("未来两年行业规划产能增量预计多少", topic="光伏组件行业")
    assert SkillName.INDUSTRY.value not in locked


@pytest.mark.asyncio
async def test_ramp_progress_boundary_term_goes_clarification() -> None:
    """裁决 2：「爬坡进度/爬坡周期」为研究边界词——不走指标取数，
    命中即披露并走澄清门；「释放/落地/扩张」维持派生否定表。"""

    plan = await build_intent_plan(
        "各家厂商爬坡进度如何",
        industry_topic="光伏组件行业",
    )

    assert all(
        "hithink_industry_query" not in sub.candidate_skills
        for sub in plan.sub_requirements
    )
    assert plan.requires_clarification or plan.unresolved_metrics

    locked = _locked_values("各家厂子扩产落地进度如何", topic="光伏组件行业")
    assert SkillName.INDUSTRY.value not in locked
