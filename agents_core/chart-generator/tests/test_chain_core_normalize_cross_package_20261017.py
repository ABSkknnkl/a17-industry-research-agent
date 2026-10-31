"""跨包一致性测试：A2 与 A3 两份「核心节点归一」实现必须同构（2026-10-17 P0-C）。

背景
----
产业链拓扑的 ``is_core`` 标记决定渲染器是否拆出「整机本体品牌」栏（模板最重要的视觉锚点）。
run-20261016232834 实测：模型把 ``is_core`` 标在「核心算法」（2 家企业）上，而真正的本体节点
「整机厂」挂着 7 家——渲染器 ``_use_core_body`` 要求 ``is_core 且企业 ≥3``，于是核心栏整列消失、
7 个品牌一家都没上图，统计行还算成了自相矛盾的「中游 2 环节」（画面上 3 张卡）。

修复必须在**两个包**各落一份：

- ``chart_generator/chain_topology.py``（智能体3，渲染前终审兜底）
- ``data_interpreter/agent.py``（智能体2，生产链路上游——落盘拓扑还会被审核门重建、
  被人工审阅、被图表库复用，源头标错则下游处处要兜）

两个智能体独立打包、无法互相 import，所以只能镜像复制（与既有的 ``_as_str_list``
双份约定一致）。**复制就会有漂移**，这个测试就是漂移的警报器：
对同一批 fixture 断言两份实现给出完全相同的判定结果。

⚠️ 以后任改一处而没改另一处，这里会红。
"""
import copy
import json
import os

import pytest

from chart_generator.chain_topology import (
    core_misplacement as a3_core_misplacement,
    normalize_core_node as a3_normalize_core_node,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures_real_topology.json")


def _n(nid, label, stage, *, core=False, companies=None, eids=None):
    return {"id": nid, "label": label, "stage": stage, "is_core": core,
            "companies": list(companies or []), "key_products": [], "description": "",
            "evidence_ids": list(eids or [])}


def _topo(nodes, edges, core_product=""):
    return {"title": "测试产业链", "subtitle": "", "core_product": core_product,
            "nodes": nodes, "edges": edges}


# ── 场景 1：核心挂在"企业少"的节点上，且存在明显更优的本体节点 → 必须纠正 ──────
CASE_MISPLACED = _topo(
    [_n("U1", "动力电池", "upstream", companies=["宁德时代", "亿纬锂能"]),
     _n("M1", "核心算法", "midstream", core=True, companies=["优刻得", "北纬科技"]),
     _n("M2", "整机厂", "midstream", companies=[
         "纵横股份", "万丰奥威", "沃飞长空", "亿航", "小鹏汇天", "峰飞航空"]),
     _n("D1", "物流配送", "downstream"),
     _n("S1", "运维回收", "support")],
    [{"source": "U1", "target": "M2", "label": "电池包", "flow": "material"},
     {"source": "M1", "target": "M2", "label": "算法授权", "flow": "technical"},
     {"source": "M2", "target": "D1", "label": "整机交付", "flow": "material"},
     {"source": "S1", "target": "M2", "label": "维护回收", "flow": "recycle"}],
    core_product="eVTOL/低空飞行器",
)

# ── 场景 2：核心已经是企业最多、名字像本体的节点 → 一个字都不许动 ────────────
CASE_ALREADY_RIGHT = _topo(
    [_n("U1", "动力电池", "upstream", companies=["宁德时代"]),
     _n("M1", "整机厂", "midstream", core=True, companies=[
         "纵横股份", "万丰奥威", "沃飞长空", "亿航", "小鹏汇天"]),
     _n("D1", "物流配送", "downstream")],
    [{"source": "U1", "target": "M1", "label": "电池包", "flow": "material"},
     {"source": "M1", "target": "D1", "label": "整机交付", "flow": "material"}],
    core_product="eVTOL",
)

# ── 场景 3：所有人企业数都不达标 → 无从判定更优，保持原样（不许乱换） ────────
CASE_ALL_SPARSE = _topo(
    [_n("U1", "动力电池", "upstream", companies=["宁德时代"]),
     _n("M1", "核心算法", "midstream", core=True, companies=["优刻得"]),
     _n("M2", "整机厂", "midstream", companies=["亿航"])],
    [{"source": "U1", "target": "M2", "label": "电池包", "flow": "material"},
     {"source": "M1", "target": "M2", "label": "算法授权", "flow": "technical"}],
    core_product="eVTOL",
)

# ── 场景 4：没有 is_core → 不越权指派（交给既有「缺少核心节点」规则） ───────
CASE_NO_CORE = _topo(
    [_n("U1", "动力电池", "upstream", companies=["宁德时代"]),
     _n("M2", "整机厂", "midstream", companies=["亿航", "小鹏汇天", "峰飞"])],
    [{"source": "U1", "target": "M2", "label": "电池包", "flow": "material"}],
    core_product="eVTOL",
)

CASES = [CASE_MISPLACED, CASE_ALREADY_RIGHT, CASE_ALL_SPARSE, CASE_NO_CORE]


def _load_a2():
    """A2 是独立包，测试环境里可直接 import；取不到就跳过（不阻断 A3 回归）。"""
    try:
        from data_interpreter.agent import DataInterpreterAgent
    except Exception:  # pragma: no cover - 环境缺依赖时
        return None
    return DataInterpreterAgent


A2 = _load_a2()

pytestmark = pytest.mark.skipif(A2 is None, reason="data_interpreter 包不可用")


def test_a2_has_mirror_implementation():
    """A2 侧必须存在同名能力的镜像实现，否则说明同步漏了。"""
    assert hasattr(A2, "_normalize_core_node")
    assert hasattr(A2, "_core_score")
    assert getattr(A2, "CORE_BODY_MIN_COMPANIES", None) == 3


@pytest.mark.parametrize("topo", CASES, ids=["misplaced", "already_right", "all_sparse", "no_core"])
def test_two_packages_agree(topo):
    """同一份拓扑，A2 与 A3 的归一化结果必须逐字节一致。"""
    a2_out, a2_notes = A2._normalize_core_node(copy.deepcopy(topo))
    a3_out, a3_notes = a3_normalize_core_node(copy.deepcopy(topo))

    a2_cores = [n["label"] for n in a2_out["nodes"] if n.get("is_core")]
    a3_cores = [n["label"] for n in a3_out["nodes"] if n.get("is_core")]
    assert a2_cores == a3_cores, f"核心节点判定不一致：A2={a2_cores} A3={a3_cores}"
    assert len(a2_cores) <= 1, "核心节点必须唯一"
    assert a2_notes == a3_notes, f"留痕文案不一致：\nA2={a2_notes}\nA3={a3_notes}"


def test_misplaced_core_is_moved_to_brand_heavy_node():
    """真实踩坑场景：核心算法(2 家) → 整机厂(6 家)。"""
    out, notes = A2._normalize_core_node(copy.deepcopy(CASE_MISPLACED))
    cores = [n for n in out["nodes"] if n.get("is_core")]
    assert len(cores) == 1
    assert cores[0]["label"] == "整机厂"
    assert len(cores[0]["companies"]) == 6
    assert any("重指派" in n for n in notes)


def test_normalization_is_idempotent():
    """跑两遍结果必须一样——否则审核门重建时会二次漂移。"""
    once, _ = A2._normalize_core_node(copy.deepcopy(CASE_MISPLACED))
    twice, notes_twice = A2._normalize_core_node(copy.deepcopy(once))
    assert [n["label"] for n in once["nodes"] if n.get("is_core")] == \
           [n["label"] for n in twice["nodes"] if n.get("is_core")]
    assert notes_twice == []


def test_real_fixture_normalization_matches_across_packages():
    """拿真实 LLM 落盘的拓扑再验一次跨包一致性。"""
    if not os.path.exists(FIXTURE):
        pytest.skip("真实拓扑 fixture 未生成")
    topo = json.loads(open(FIXTURE, encoding="utf-8").read())
    a2_out, a2_notes = A2._normalize_core_node(copy.deepcopy(topo))
    a3_out, a3_notes = a3_normalize_core_node(copy.deepcopy(topo))
    assert [n["id"] for n in a2_out["nodes"] if n.get("is_core")] == \
           [n["id"] for n in a3_out["nodes"] if n.get("is_core")]
    assert a2_notes == a3_notes
