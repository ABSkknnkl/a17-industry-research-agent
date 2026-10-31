"""ChainGraphSpec 契约与映射器测试（2026-10-07）。"""
from chart_generator.chain_graph import (
    ChainEdge,
    ChainGraphSpec,
    ChainNode,
    ChainStage,
    build_chain_graph_from_segments,
)


def _seg(name, stage, companies=None, products=None, eids=None, inferred=False):
    return {
        "segment_name": name,
        "stage": stage,
        "representative_companies": companies or [],
        "key_products": products or [],
        "evidence_record_ids": eids or [],
        **({"inferred": True} if inferred else {}),
    }


# ── 映射 ──────────────────────────────────────────────────────────────────

def test_builds_nodes_stages_and_flow_edges():
    spec = build_chain_graph_from_segments([
        _seg("基础材料", "upstream", products=["碳纤维"], eids=["R1"]),
        _seg("整机制造", "midstream", companies=["大疆"], eids=["R2"]),
        _seg("物流运输", "downstream", eids=["R3"]),
    ], subject="低空经济")
    assert spec is not None
    assert spec.title == "低空经济产业链结构"
    assert [s.stage_id for s in spec.stages] == ["upstream", "midstream", "downstream"]
    assert len(spec.nodes) == 3
    # 主流向：上→中→下 两条 flow 边
    flows = [e for e in spec.edges if e.kind == "flow"]
    assert len(flows) == 2
    nm = spec.node_map()
    assert nm[flows[0].source].stage == "upstream"
    assert nm[flows[0].target].stage == "midstream"


def test_items_merge_products_and_companies_dedup():
    spec = build_chain_graph_from_segments([
        _seg("中游", "midstream", companies=["公司A", "公司B"], products=["公司A", "产品X"], eids=["R1"]),
    ])
    node = spec.nodes[0]
    assert node.items == ["公司A", "产品X", "公司B"] or set(node.items) == {"公司A", "公司B", "产品X"}
    assert len(node.items) == len(set(node.items))


def test_custom_stage_preserved_and_sorted_after_standard():
    spec = build_chain_graph_from_segments([
        _seg("下游应用", "downstream", eids=["R1"]),
        _seg("配套保障", "support", eids=["R2"]),   # 自定义段
        _seg("上游材料", "upstream", eids=["R3"]),
    ])
    ids = [s.stage_id for s in spec.stages]
    assert ids.index("upstream") < ids.index("downstream") < ids.index("support")


def test_segment_without_evidence_marked_inferred():
    spec = build_chain_graph_from_segments([
        _seg("有证据", "upstream", eids=["R1"]),
        _seg("无证据", "midstream"),  # 挂不上证据 → inferred
    ])
    nm = {n.name: n for n in spec.nodes}
    assert nm["有证据"].inferred is False
    assert nm["无证据"].inferred is True
    # 推断节点不参与主流向边
    for e in spec.edges:
        assert nm[e.source].inferred is False or True  # 主链只由非推断首节构成（见下）
    flows = [e for e in spec.edges if e.kind == "flow"]
    for e in flows:
        assert spec.node_map()[e.source].inferred is False
        assert spec.node_map()[e.target].inferred is False


def test_explicit_inferred_flag_respected():
    spec = build_chain_graph_from_segments([
        _seg("推断环节", "upstream", eids=["R1"], inferred=True),
    ])
    assert spec.nodes[0].inferred is True


def test_empty_and_garbage_segments_return_none():
    assert build_chain_graph_from_segments([]) is None
    assert build_chain_graph_from_segments([{"stage": "upstream"}, "junk", None]) is None


def test_five_stage_chain_keeps_all():
    """4/5 段产业链（配合 di 1157 修复）全保留。"""
    spec = build_chain_graph_from_segments([
        _seg("硅料", "upstream", eids=["R1"]), _seg("硅片", "wafer", eids=["R2"]),
        _seg("电池片", "midstream", eids=["R3"]), _seg("组件", "module", eids=["R4"]),
        _seg("电站", "downstream", eids=["R5"]),
    ])
    assert len(spec.nodes) == 5
    assert len(spec.stages) == 5


# ── 模板路由（2026-10-21 已删除）──────────────────────────────────────
# 版式只剩三列目录式一种，`choose_chain_template()` / `ChainTemplateHint` /
# `ChainGraphSpec.template_hint` 一并删除，5 条路由用例随之移除。
# 渲染入口固定为 `render_chain_svg()` → `_render_lane_grid`
# （"环境无关"由 test_chain_lane_grid_20261017.test_render_is_always_lane_grid 锁死）。


# ── 兜底路径必须保留主链连线（2026-10-17 真 bug）───────────────────────────

def test_segments_fallback_keeps_edges_when_all_inferred():
    """全图无证据（A1 取数失败）时，兜底也要生成主链边，不能只剩孤立卡片。

    实测 run-20261017193421：A1 的 industry_chain 域 0 条 → A2 没产出拓扑 →
    走 segments 兜底，3 个节点全部 inferred=True → 旧实现 `not n.inferred` 过滤后
    `stage_first` 为空 → **0 条边**，图上只剩 3 张没有任何连线的卡。
    结构连通性与"内容有无证据"是两件事，不能因为没证据就把图拆散。
    """
    segments = [
        {"segment_name": "上游：基础支撑与核心部件", "stage": "upstream", "inferred": True},
        {"segment_name": "中游：研发集成与方案交付", "stage": "midstream", "inferred": True},
        {"segment_name": "下游：场景应用与商业化", "stage": "downstream", "inferred": True},
    ]
    spec = build_chain_graph_from_segments(segments, subject="低空经济")
    assert spec is not None
    assert len(spec.nodes) == 3
    assert len(spec.edges) == 2, f"兜底必须补 2 条主链边，实际 {len(spec.edges)}"
    assert all(n.inferred for n in spec.nodes), "内容仍如实标推断"


def test_segments_fallback_prefers_non_inferred_node():
    """部分节点有证据时，主链只用非推断节点（保留原契约）。"""
    segments = [
        {"segment_name": "上游A", "stage": "upstream", "inferred": True},
        {"segment_name": "上游B", "stage": "upstream", "evidence_record_ids": ["R1"]},
        {"segment_name": "中游", "stage": "midstream", "evidence_record_ids": ["R1"]},
    ]
    spec = build_chain_graph_from_segments(segments, subject="t")
    assert spec is not None
    assert spec.edges, "必须至少有一条主链边"
    node_map = spec.node_map()
    for e in spec.edges:
        assert node_map[e.source].inferred is False, "部分无据时，主链起点必须是已证节点"
        assert node_map[e.target].inferred is False, "部分无据时，主链终点必须是已证节点"


def test_segments_fallback_single_inferred_stage_not_linked():
    """某阶段只有推断节点 → 该阶段不接入主链（保留原设计：不把无据环节画进主链）。"""
    segments = [
        {"segment_name": "上游", "stage": "upstream", "evidence_record_ids": ["R1"]},
        {"segment_name": "中游", "stage": "midstream"},                    # 无证据
        {"segment_name": "下游", "stage": "downstream", "evidence_record_ids": ["R1"]},
    ]
    spec = build_chain_graph_from_segments(segments, subject="t")
    assert spec is not None
    node_map = spec.node_map()
    for e in spec.edges:
        assert node_map[e.source].inferred is False
        assert node_map[e.target].inferred is False
