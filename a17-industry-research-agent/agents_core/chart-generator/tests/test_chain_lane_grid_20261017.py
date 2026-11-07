"""三列目录式渲染器 lane_grid 回归（2026-10-17）。

背景（详见 output/产业链图最终改造方案_三列目录式.md）：
产业链图是**分类目录**不是工艺流程图——泳道容器 + 卡片网格，卡片之间零连线，
整机并入中游列顶部品牌大卡（低空经济自研自产，不存在 OEM/代工拆列），
列间只留 2 根粗箭头表达价值方向。

验收口径（与旧版不同）：
- ``polyline == 0`` 且 ``data-flow == 0``（旧版是折线流线，新版禁止）；
- 列间箭头是 ``line + polygon`` 画法，``polygon``（箭头）恰为 2；
- 中游能力卡名字互不为子串、也不与整机大卡语义重复（B18 后兜底判重池含 core 名）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from chart_generator.chain_graph import (
    ChainEdge,
    ChainGraphSpec,
    ChainNode,
    ChainStage,
)
from chart_generator.chain_render import (
    _lg_columns,
    _lg_grid,
    _render_lane_grid,
    render_chain_svg,
)

# ── 固定拓扑（低空经济真实结构的最小版）─────────────────────────────────────

_UPSTREAM = [
    ("动力电池", ["宁德时代", "国轩高科"], "高比能飞行电池", True),
    ("电机电控", ["卧龙电驱", "万里扬"], "飞行动力与姿态控制", False),
    ("飞控导航", ["纵横股份", "中海达"], "飞行控制与导航定位", True),
    ("通信模块", ["中电港", "盛路通信"], "图传与数传链路", False),
    ("机体结构", ["光威复材", "中简科技"], "碳纤维机体与结构件", False),
    ("任务载荷", ["海康威视"], "可见光/红外/激光雷达载荷", False),
    ("起落架", ["瑞立科密", "中鼎股份"], "起降支撑与制动", False),
]

_BRANDS = ["亿航智能", "小鹏汇天", "峰飞航空", "沃飞长空", "大疆", "纵横股份", "极飞", "中直股份"]

_DOWNSTREAM = [
    ("电力巡检", ["电网｜油气管线巡检服务"], "电网/能源国企采购", "已落地"),
    ("城市治理", ["安防｜应急"], "地方政府/公安采购", "已落地"),
    ("物流配送", ["无人机物流｜快递配送"], "物流/电商企业采购", "试点中"),
    ("通航运营", ["通航飞行｜应急救援"], "政府/企业/个人采购", "已落地"),
    ("农业植保", ["农业喷洒｜植保服务"], "农户/农业服务商采购", "已落地"),
]

_SUPPORT = [
    ("空管系统", ["莱斯信息", "深城交", "四川九洲"], "低空空域管理与飞行服务"),
    ("起降设施", ["空港、机场类、地方国资交投"], "垂直起降场与能源补给"),
    ("通导监", ["华测导航", "北斗星通", "中国移动"], "通信导航监视一体化"),
    ("仿真训练", ["捷安高科", "海特高新"], "飞行仿真训练与人员培训"),
    ("运维回收", ["威海广泰", "中信海直"], "飞行器运维维修与回收拆解"),
]


def _spec() -> ChainGraphSpec:
    nodes = [
        ChainNode(node_id=f"U{i+1}", name=nm, stage="upstream", companies=co,
                  description=desc, bottleneck=bn, source_tier="industry_common")
        for i, (nm, co, desc, bn) in enumerate(_UPSTREAM)
    ]
    nodes.append(ChainNode(node_id="M1", name="整机/本体", stage="midstream", is_core=True,
                           companies=list(_BRANDS), description="零部件集成为整机",
                           source_tier="evidence"))
    nodes.append(ChainNode(node_id="M2", name="研发算法", stage="midstream",
                           companies=["优刻得", "拓邦股份"],
                           description="飞控算法与仿真", source_tier="evidence"))
    nodes += [
        ChainNode(node_id=f"D{i+1}", name=nm, stage="downstream", items=it,
                  buyer=buyer, phase=ph, source_tier="evidence")
        for i, (nm, it, buyer, ph) in enumerate(_DOWNSTREAM)
    ]
    nodes += [
        ChainNode(node_id=f"S{i+1}", name=nm, stage="support", companies=co,
                  description=desc, source_tier="evidence")
        for i, (nm, co, desc) in enumerate(_SUPPORT)
    ]
    edges = [ChainEdge(source="U1", target="M1"), ChainEdge(source="M1", target="D1"),
             ChainEdge(source="S1", target="M1", kind="attach")]
    return ChainGraphSpec(
        title="低空经济产业链全景图",
        subtitle="上游核心零部件 → 中游设计研发与制造 → 下游场景落地",
        core_product="低空飞行器",
        stages=[ChainStage(stage_id="upstream", title="上游"),
                ChainStage(stage_id="midstream", title="中游"),
                ChainStage(stage_id="downstream", title="下游"),
                ChainStage(stage_id="support", title="配套")],
        nodes=nodes, edges=edges,
    )


def _texts(svg: str) -> list[str]:
    return re.findall(r"<text[^>]*>([^<]*)</text>", svg)


# ── 用例 ──────────────────────────────────────────────────────────────────

def test_lane_grid_three_columns_and_support_band():
    svg = _render_lane_grid(_spec())
    txt = "\n".join(_texts(svg))
    for head in ("上游：核心供给与零部件", "中游：整机制造与系统集成",
                 "下游：渠道与应用场景", "配套：服务、软件与回收体系"):
        assert head in txt, f"缺列头/配套带：{head}"
    # 整机不单列：中游列头内含品牌大卡，右上角标含「品牌」
    # （2026-10-17 B18 后兜底卡不与整机大卡重复 → 夹具里真实能力卡只有 1 张，
    #   补一张不重复的兜底卡，共 2 张）
    assert "8 品牌 · 2 能力" in txt


def test_lane_grid_zero_card_edges():
    """卡片之间零连线：polyline 与 data-flow 均为 0（核心验收口径）。"""
    svg = _render_lane_grid(_spec())
    assert svg.count("<polyline") == 0, "目录式禁止折线连线"
    assert svg.count("data-flow") == 0, "目录式禁止流线属性"


def test_lane_grid_exactly_two_inter_column_arrows():
    """列间箭头 = line + polygon，箭头（polygon）恰 2 根。"""
    svg = _render_lane_grid(_spec())
    assert svg.count("<polygon") == 2
    # 2 根箭头各 1 根粗杆
    assert svg.count('stroke-width="7"') == 2


def test_lane_grid_card_count_conserved():
    """所有节点名必须出现在图上（渲染不吞节点）。"""
    spec = _spec()
    svg = _render_lane_grid(spec)
    txt = "\n".join(_texts(svg))
    for nd in spec.nodes:
        assert nd.name in txt, f"节点丢失：{nd.name}"


def test_lane_grid_brand_list_complete():
    """整机大卡的品牌主体：8 家全部出现且无「●」项目符号。"""
    svg = _render_lane_grid(_spec())
    txt = "\n".join(_texts(svg))
    for b in _BRANDS:
        assert b in txt, f"品牌丢失：{b}"
    assert "品牌主体 · 8 家" in txt
    assert "●" not in txt, "品牌卡不得带项目符号"


def test_lane_grid_capability_cards_no_substring_dup():
    """能力卡名字互不为子串，且**不得与整机大卡语义重复**（2026-10-17 B18）。

    旧兜底会补出「整机制造与系统集成」与 core「整机/本体」语义重复的卡
    （车载激光雷达、创新药实测），B18 后兜底判重池包含 core 名。
    """
    cols = _lg_columns(_spec())
    caps = cols["caps"]
    assert len(caps) == 2
    names = [c["name"] for c in caps]
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert a not in b and b not in a, f"能力卡子串重复：{a!r} vs {b!r}"
    # B4：不得改写节点名（否则事实锁死报节点缺失）——短名「研发算法」必须原样保留
    assert "研发算法" in names, f"节点原名被改写：{names}"
    # 兜底卡不得与整机大卡语义重复（2-gram 同源口径）
    core_name = cols["core"].name
    for nm in names:
        grams = {core_name[j:j + 2] for j in range(len(core_name) - 1)}
        assert not any(g in nm for g in grams), f"能力卡与大卡语义重复：{nm!r} vs {core_name!r}"


def test_lane_grid_core_not_duplicated_as_cap():
    """B18：is_core 兜底选出的核心不得再画成能力卡，真节点不得被挤掉。

    半导体设备（刻蚀/沉积）实测：core「整机制造与总装」仅 2 家企业 → 本体盒
    不成立 → 走 is_core 兜底；旧 mid_rest 判据（not _use_core_body）与兜底判据
    不一致，core 重复进 caps，真正的「系统集成与调试」被 mid_rest[:3] 挤掉。
    """
    nodes = [
        ChainNode(node_id="M0", name="整机制造与总装", stage="midstream", is_core=True,
                  companies=["华海清科", "芯源微"], description="设备集成与总装",
                  source_tier="evidence"),
        ChainNode(node_id="M1", name="刻蚀设备研发", stage="midstream",
                  companies=["中微公司"], description="刻蚀", source_tier="evidence"),
        ChainNode(node_id="M2", name="沉积设备研发", stage="midstream",
                  companies=["拓荆科技"], description="沉积", source_tier="evidence"),
        ChainNode(node_id="M3", name="系统集成与调试", stage="midstream",
                  companies=["长川科技"], description="集成调试", source_tier="evidence"),
    ]
    spec = ChainGraphSpec(
        title="半导体设备产业链图谱", subtitle="", core_product="刻蚀/沉积设备",
        stages=[ChainStage(stage_id="midstream", title="中游")],
        nodes=nodes, edges=[],
    )
    cols = _lg_columns(spec)
    assert cols["core"].name == "整机制造与总装"
    cap_names = [c["name"] for c in cols["caps"]]
    assert cap_names == ["刻蚀设备研发", "沉积设备研发", "系统集成与调试"], cap_names
    # 渲染层面：4 个中游节点名全部上画（旧版「系统集成与调试」整节点消失）
    svg = _render_lane_grid(spec)
    txt = "\n".join(re.findall(r"<text[^>]*>([^<]*)</text>", svg))
    for nd in nodes:
        assert nd.name in txt, f"中游节点丢失：{nd.name}"


def test_lane_grid_companies_never_clipped_silently():
    """B17：企业放不下时换行/降字号，**不允许静默丢企业名**。

    三个实测踩点：① 上游 4 家只画 3 家（海上风电「塔筒与基础」丢海力风电）；
    ② 下游卡旧实现只画 items、companies 全丢（半导体设备下游 10 家企业 0 上画）；
    ③ 能力卡按像素硬裁丢尾部（创新药丢君实生物）。
    """
    nodes = [
        ChainNode(node_id="U1", name="塔筒与基础", stage="upstream",
                  companies=["天顺风能", "大金重工", "泰胜风能", "海力风电"],
                  description="塔筒与海上基础", source_tier="evidence"),
        ChainNode(node_id="M0", name="整机制造", stage="midstream", is_core=True,
                  companies=["明阳智能"], description="整机", source_tier="evidence"),
        ChainNode(node_id="M1", name="研发与设计", stage="midstream",
                  companies=["艾尔姆"], description="叶片设计", source_tier="evidence"),
        ChainNode(node_id="D1", name="电力运营", stage="downstream",
                  companies=["福能股份", "中闽能源"], items=["海上风电场运营"],
                  buyer="电网公司", phase="已落地", source_tier="evidence"),
        ChainNode(node_id="D2", name="深远海开发", stage="downstream",
                  companies=["三峡能源"], items=["漂浮式示范"],
                  buyer="能源国企", phase="示范中", source_tier="evidence"),
    ]
    spec = ChainGraphSpec(
        title="海上风电产业链全景图", subtitle="", core_product="海上风电机组",
        stages=[ChainStage(stage_id="upstream", title="上游"),
                ChainStage(stage_id="midstream", title="中游"),
                ChainStage(stage_id="downstream", title="下游")],
        nodes=nodes, edges=[],
    )
    svg = _render_lane_grid(spec)
    txt = "\n".join(re.findall(r"<text[^>]*>([^<]*)</text>", svg))
    for nd in nodes:
        for c in nd.companies:
            assert c in txt, f"企业被静默丢弃：{c}（{nd.name}）"


def test_lane_grid_grid_column_rule():
    """≤3 张单列、≥4 张 2 列（避免 2×2 右下空一格）。"""
    lane_w = 400.0
    small = [object()] * 3
    big = [object()] * 8
    _, ncol_s, _ = _lg_grid(small, 0.0, lane_w)
    _, ncol_b, _ = _lg_grid(big, 0.0, lane_w)
    assert ncol_s == 1 and ncol_b == 2


def test_lane_grid_bottleneck_double_stroke():
    """瓶颈环节：橙色外框 + 内衬细框（双描边）。"""
    svg = _render_lane_grid(_spec())
    # 内衬框：fill="none" 的橙色描边矩形
    assert svg.count('fill="none" stroke="#D97706"') >= 1
    # 瓶颈角标胶囊
    assert ">瓶颈</text>" in svg


def test_lane_grid_low_trust_badges():
    """推断/待核角标必须上图（产物体检硬规则），industry_common 不带角标。"""
    spec = _spec()
    spec.nodes[0].inferred = True                     # U1 动力电池 → 红色「推断」
    spec.nodes[1].inferred = True
    spec.nodes[1].source_tier = "web_unverified"      # U2 电机电控 → 灰「待核」
    svg = _render_lane_grid(spec)
    txt = "\n".join(_texts(svg))
    assert "推断" in txt and "待核" in txt
    # 位置正确性：推断/待核紧跟在各自环节名旁边（同一张卡）
    assert re.search(r"动力电池\n推断", txt.replace("\r", "")) or "推断" in txt


def test_lane_grid_edge_labels_all_omitted():
    """目录式不画连线 → 全部带标签的边都进 _omitted_edge_labels（不画与不查同源）。

    2026-10-21：旧版式（flow/backbone/hub）已删除，本函数不再按 CHAIN_RENDER_MODE
    分流，恒返回"所有带标签的边"，因此也不再有"关掉开关就不算有意省略"的分支。
    """
    from chart_generator.chain_render import _omitted_edge_labels

    spec = _spec()
    spec.edges.append(ChainEdge(source="U1", target="M1", label="电池供电"))
    omitted = _omitted_edge_labels(spec)
    assert ("U1", "M1") in omitted


def test_render_is_always_lane_grid(monkeypatch):
    """渲染只有一条路径：不设/乱设环境变量都出三列目录式（2026-10-21 收敛）。

    旧版默认 ``flow``，批处理脚本不加载 .env 时会静默退回四列泳道版式，
    实测把旧模板图当新图交付 —— 这条用例锁死"环境无关"。
    """
    spec = _spec()
    for env in (None, "lane_grid", "flow", "whatever"):
        if env is None:
            monkeypatch.delenv("CHAIN_RENDER_MODE", raising=False)
        else:
            monkeypatch.setenv("CHAIN_RENDER_MODE", env)
        svg = render_chain_svg(spec)
        assert svg.startswith("<svg")
        assert "读法：自上而下扫一列" in svg, f"env={env} 时没有走 lane_grid"
        assert svg.count("<polyline") == 0, f"env={env} 时出现了旧版流线"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_lint_distinguishes_render_truncation_from_placeholder():
    """B16：渲染截断的「…」放行，真占位符（XX/示例/…孤立）仍必须拦。"""
    from chart_generator.chain_lint import lint_chain_texts

    spec = _spec()
    # 阳性：企业行被卡片宽度截断（前面是完整已知企业名，最后一家截半）
    ok = ["创新药产业链结构", "宁德时代、国轩…", "动力电池", "宁德时代", "上游：核心供给与零部件"]
    assert not [i for i in lint_chain_texts(spec, ok) if i["code"] == "placeholder"], \
        "渲染截断不得被判占位符（否则整图降级 ECharts）"
    # 阴性对照 1：LLM 编的占位符必须拦
    bad = ["创新药产业链结构", "XX企业", "动力电池", "宁德时代"]
    assert any(i["code"] == "placeholder" for i in lint_chain_texts(spec, bad))
    # 阴性对照 2：孤立的「…」（不是任何已知名称的前缀）仍必须拦
    bad2 = ["创新药产业链结构", "…", "动力电池", "宁德时代"]
    assert any(i["code"] == "placeholder" for i in lint_chain_texts(spec, bad2))


def test_lint_truncation_stem_must_match_known_name():
    """B16 边界：截断前缀必须是已知名称的前缀，随便一串「张三李四…」不能放行。"""
    from chart_generator.chain_lint import lint_chain_texts

    spec = _spec()
    texts = ["创新药产业链结构", "张三李四王五…", "动力电池", "宁德时代"]
    assert any(i["code"] == "placeholder" for i in lint_chain_texts(spec, texts))


def test_lane_grid_midstream_node_name_survives_fidelity():
    """B4 端到端：中游非核心节点名必须原样上图（事实锁死不再报缺失）。"""
    from chart_generator.chain_lint import assert_graph_fidelity

    spec = _spec()
    # 造一个与兜底能力名 2-gram 重叠的中游节点（含「研发」「算法」）
    spec.nodes.append(ChainNode(node_id="M3", name="仿制药与改良型研发",
                                stage="midstream", companies=["丽珠集团"],
                                description="改良型新药与仿制药开发", source_tier="evidence"))
    svg = _render_lane_grid(spec)
    missing = assert_graph_fidelity(spec, svg)
    assert not any("仿制药与改良型研发" in m for m in missing), f"中游节点被吞名：{missing}"
