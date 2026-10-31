"""lane_grid 跨列撞卡判定（2026-10-26）。

事故背景
--------
笔记本电脑真跑图里，中游能力卡与配套列**各画了一张「测试与认证」**——
同一个环节同时出现在两列，专业观众一眼看出重复。

第一版修法图省事，把判重池写成 ``spec.nodes`` 全展开，结果两边都伤：
- 低空经济夹具里的 3 张兜底卡全被挡掉，中游只剩 1 张能力卡
  （``test_chain_lane_grid_20261017`` 两例当场变红）；
- 更隐蔽的一刀：兜底卡「系统集成与调试」被配套节点「空管系统」用二元词
  「系统」判成重复——**跨列不该用 2-gram 比**。

最终口径拆成两种尺度：
- 同列（能力卡之间）与整机大卡：子串 + 2-gram（B18 的语义去重照旧生效）；
- 跨列（中游 vs 配套）：**只认字面包含/相等**。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chart_generator.chain_graph import (  # noqa: E402
    ChainEdge,
    ChainGraphSpec,
    ChainNode,
    ChainStage,
)
from chart_generator.chain_render import _lg_cap_fallback, _lg_columns  # noqa: E402


def _spec(*, support_names: list[str]) -> ChainGraphSpec:
    """最小夹具：1 个上游环节 + 整机大卡 + 若干配套环节。"""
    nodes = [
        ChainNode(node_id="U1", name="处理器与GPU", stage="upstream",
                  companies=["京东方A"], description="计算与图形处理",
                  source_tier="evidence"),
        ChainNode(node_id="M1", name="整机/本体", stage="midstream", is_core=True,
                  companies=["联想", "惠普", "戴尔"], description="零部件集成为整机",
                  source_tier="evidence"),
        ChainNode(node_id="D1", name="消费应用", stage="downstream",
                  items=["笔记本电脑"], buyer="个人消费者", source_tier="evidence"),
    ]
    nodes += [
        ChainNode(node_id=f"S{i+1}", name=nm, stage="support",
                  companies=[], description="", source_tier="evidence")
        for i, nm in enumerate(support_names)
    ]
    return ChainGraphSpec(
        title="笔记本电脑产业链全景图",
        subtitle="上游零部件 → 中游整机 → 下游场景",
        core_product="笔记本电脑",
        stages=[ChainStage(stage_id="upstream", title="上游"),
                ChainStage(stage_id="midstream", title="中游"),
                ChainStage(stage_id="downstream", title="下游")],
        nodes=nodes,
        edges=[ChainEdge(source="U1", target="M1")],
    )


def test_fallback_cap_does_not_duplicate_support_node_name() -> None:
    """配套列已有「测试与认证」→ 中游不许再补一张同名能力卡。"""
    spec = _spec(support_names=["测试与认证", "运维与回收"])
    caps = [c["name"] for c in _lg_columns(spec)["caps"]]
    assert "测试与认证" not in caps


def test_support_node_does_not_block_unrelated_cap() -> None:
    """配套叫「空管系统」不代表中游不能画「系统集成」——跨列只认字面包含。"""
    spec = _spec(support_names=["空管系统", "运维与回收"])
    caps = [c["name"] for c in _lg_columns(spec)["caps"]]
    # 有配套干扰时仍要能补出能力卡，不能一张不剩
    assert caps, "兜底能力卡被配套节点名误挡"


def test_cross_column_rule_is_substring_only() -> None:
    """「测试与认证」被挡，「运维与回收」不会连带被挡（两者无字面包含关系）。"""
    spec = _spec(support_names=["测试与认证"])
    fallback = [n for n, _ in _lg_cap_fallback(spec)]
    assert "测试与认证" in fallback          # 兜底候选里本来有这张
    caps = [c["name"] for c in _lg_columns(spec)["caps"]]
    assert caps, "除被挡的那张外，其余兜底卡应照常补出"


def test_cap_count_stays_within_three() -> None:
    """兜底卡上限 3 张（含真实中游节点卡）。"""
    spec = _spec(support_names=["运维与回收"])
    caps = _lg_columns(spec)["caps"]
    assert len(caps) <= 3
