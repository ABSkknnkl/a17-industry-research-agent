"""研报级产业链模板字段回归（2026-10-16）。

对齐 scratch/chain_redesign/人形机器人产业链全景图.svg 成品图与 template_anatomy.json：
四段泳道 / 三行卡片 / 瓶颈橙框角标 / 下游落地阶段+采购方 / 整机本体品牌列表 /
右上统计行 / 图例含瓶颈。新增字段必须同时过「产物体检」与「事实锁死」。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chart_generator.chain_graph import (
    ChainEdge,
    ChainGraphSpec,
    ChainNode,
    ChainStage,
    MAX_BOTTLENECK,
    MAX_BRANDS,
)
from chart_generator.chain_lint import assert_graph_fidelity, lint_chain_svg
from chart_generator.chain_render import render_chain_svg
from chart_generator.chain_topology import (
    repair_topology,
    topology_to_spec,
    validate_topology,
)

_UPSTREAM = [
    ("行星滚柱丝杠", ["贝斯特", "恒立液压", "哈默纳科"], "腿部直线关节核心传动，承载与精度关键", True),
    ("谐波 / RV 减速器", ["绿的谐波", "双环传动", "哈默纳科"], "旋转关节减速，决定转矩密度与回差", True),
    ("无框力矩电机", ["步科股份", "鸣志电器", "Maxon"], "关节直接驱动源，高转矩密度要求", False),
    ("执行器总成", ["拓普集团", "三花智控", "双林股份"], "丝杠、电机与减速器的集成总成部件", False),
    ("六维力传感器", ["柯力传感", "坤维科技", "宇立仪器"], "末端力控与柔顺操作的关键感知", True),
    ("灵巧手与触觉传感", ["兆威机电", "鸣志电器", "因时机器人"], "决定抓取能力与操作精细度", False),
    ("视觉感知", ["禾赛科技", "速腾聚创", "奥比中光"], "激光雷达、深度相机与 IMU 融合", False),
    ("电池与电源系统", ["宁德时代", "比亚迪", "亿纬锂能"], "决定续航，半固态电池为核心路线", False),
    ("轻量化结构件", ["旭升集团", "爱柯迪", "文灿股份"], "镁铝合金与 PEEK 降低整机自重", False),
    ("算力芯片", ["英伟达 Jetson", "地平线", "华为昇腾"], "承载端侧大模型推理的计算平台", False),
]

_DOWNSTREAM = [
    ("工业制造", "汽车总装 / 3C 上下料 / 物流仓储", "当前最先落地的商业化场景",
     "已落地", "汽车 / 3C / 物流头部企业"),
    ("商业服务", "展厅导览 / 零售配送 / 政务大厅", "验证人机交互与服务能力",
     "试点中", "商业地产 / 政务 / 零售连锁"),
    ("特种作业", "电力巡检 / 灾难救援 / 核电站运维", "替代人工进入高危环境",
     "示范期", "电网 / 应急 / 能源国企"),
    ("家庭服务", "陪伴护理 / 家务整理 / 教育陪读", "空间最大但技术门槛最高",
     "远期", "终端消费者"),
]

_SUPPORT = [
    ("仿真训练与数据集", ["英伟达 Omniverse", "特斯拉数据闭环"], "为大脑提供仿真环境与训练语料，支撑算法迭代"),
    ("运维与回收", ["整机厂自营", "第三方服务商"], "保养、维修与退役再制造，构成全生命周期闭环"),
    ("渠道与集成", ["系统集成商", "行业大客户", "出口欧美"], "把整机交付到真实场景，承担方案落地与售后"),
]

_EDGES = [
    ("U1", "M2", "零部件供给", "material"),
    ("U2", "M2", "零部件供给", "material"),
    ("U3", "M2", "电机模组", "material"),
    ("U4", "M2", "执行器总成", "material"),
    ("U5", "M1", "力感知数据", "technical"),
    ("U6", "M1", "触觉数据", "technical"),
    ("U7", "M1", "视觉感知", "technical"),
    ("U10", "M1", "算力支撑", "technical"),
    ("M1", "B1", "运动控制算法", "technical"),
    ("M2", "B1", "总装制造", "material"),
    ("B1", "D1", "整机交付", "material"),
    ("B1", "D2", "整机交付", "material"),
    ("B1", "D3", "整机交付", "material"),
    ("B1", "D4", "整机交付", "material"),
    ("S1", "M1", "仿真数据", "service"),
    ("S2", "B1", "运维回收", "service"),
    ("B1", "S3", "整机出货", "service"),
    ("D4", "S2", "退役回收", "recycle"),
]


def _full_spec() -> ChainGraphSpec:
    nodes: list[ChainNode] = []
    for i, (name, comps, desc, bn) in enumerate(_UPSTREAM, start=1):
        nodes.append(ChainNode(node_id=f"U{i}", name=name, stage="upstream",
                               companies=comps, description=desc, bottleneck=bn))
    nodes.append(ChainNode(node_id="M1", name="AI 大模型与运动控制", stage="midstream",
                           companies=["特斯拉 FSD", "Figure Helix", "智元 GO-1", "银河通用"],
                           description="定义自由度配置与全身运动决策算法"))
    nodes.append(ChainNode(node_id="M2", name="整机组装与测试产线", stage="midstream",
                           companies=["富士康", "立讯精密", "比亚迪电子"],
                           description="总装、标定与出厂测试，决定量产良率"))
    nodes.append(ChainNode(node_id="B1", name="整机本体品牌", stage="midstream", is_core=True,
                           companies=["特斯拉 Optimus", "Figure AI", "波士顿动力 Atlas",
                                      "宇树科技", "智元机器人", "优必选", "1X Technologies"],
                           description="承接全部零部件与算法，向四大场景交付整机"))
    for i, (name, sub, desc, phase, buyer) in enumerate(_DOWNSTREAM, start=1):
        nodes.append(ChainNode(node_id=f"D{i}", name=name, stage="downstream", items=[sub],
                               description=desc, phase=phase, buyer=buyer))
    for i, (name, comps, desc) in enumerate(_SUPPORT, start=1):
        nodes.append(ChainNode(node_id=f"S{i}", name=name, stage="support",
                               companies=comps, description=desc))
    edges = [ChainEdge(source=s, target=t, label=l, flow=f) for s, t, l, f in _EDGES]
    return ChainGraphSpec(
        title="人形机器人产业链全景图",
        subtitle="核心零部件供给 → 大脑与本体集成 → 场景落地 · 配套服务闭环",
        core_product="人形机器人",
        stages=[ChainStage(stage_id="upstream", title="上游 · 核心零部件"),
                ChainStage(stage_id="midstream", title="中游 · 大脑 + 制造"),
                ChainStage(stage_id="downstream", title="下游 · 场景落地"),
                ChainStage(stage_id="support", title="配套 · 服务与渠道")],
        nodes=nodes, edges=edges, source="llm",
    )


def _texts(svg: str) -> list[str]:
    import xml.etree.ElementTree as ET
    root = ET.fromstring(svg)
    return ["".join(el.itertext()).strip() for el in root.iter("{http://www.w3.org/2000/svg}text")
            if "".join(el.itertext()).strip()]


def test_template_signatures_all_render():
    """模板签名全量渲染：瓶颈角标/阶段徽标/采购方/本体品牌列表/统计行/图例。"""
    spec = _full_spec()
    svg = render_chain_svg(spec)
    texts = _texts(svg)
    blob = "".join(texts)

    # 瓶颈角标（3 个瓶颈节点 → 图上至少 3 个「瓶颈」）
    assert blob.count("瓶颈") >= 3
    # 下游阶段与采购方
    for _n, _s, _d, phase, buyer in _DOWNSTREAM:
        assert phase in blob, f"落地阶段「{phase}」未上图"
        assert buyer in blob, f"采购方「{buyer}」未上图"
    # 整机本体品牌列表：一家一行
    for brand in ["特斯拉 Optimus", "波士顿动力 Atlas", "1X Technologies"]:
        assert brand in blob, f"品牌「{brand}」未上图"
    # 统计行 + 图例
    assert any("上游" in t and "环节" in t for t in texts), "右上统计行缺失"
    # 2026-10-21：图例随版式换成三列目录式的读法提示（旧「卡脖子瓶颈环节 / 产品实物流」
    # 属已删除的四列流线版式）。断言语义不变：瓶颈与价值方向都必须有图例说明。
    assert any("瓶颈环节" in t for t in texts), "图例缺瓶颈项"
    assert any("2 根箭头表达价值方向" in t for t in texts), "图例缺价值方向说明"

    # 体检与事实锁死都必须零问题
    assert [i for i in lint_chain_svg(spec, svg) if i["level"] == "error"] == []
    assert assert_graph_fidelity(spec, svg) == []


def test_missing_optional_fields_degrade_not_crash():
    """phase/buyer 缺失 → 不渲染但不报错、不锁死失败（画面信息缺口表达）。"""
    spec = _full_spec()
    for nd in spec.nodes:
        if nd.stage == "downstream":
            nd.phase, nd.buyer = "", ""
    svg = render_chain_svg(spec)
    assert [i for i in lint_chain_svg(spec, svg) if i["level"] == "error"] == []
    assert assert_graph_fidelity(spec, svg) == []


def test_bottleneck_rules_and_repair():
    """瓶颈只能在上游、全图 ≤3；裁判打回后确定性修复能救回。"""
    bad = {
        "title": "t", "subtitle": "", "core_product": "x",
        "nodes": [
            {"id": "U1", "label": "芯片", "stage": "upstream", "companies": [], "bottleneck": True},
            {"id": "U2", "label": "材料", "stage": "upstream", "companies": [], "bottleneck": True},
            {"id": "U3", "label": "器件", "stage": "upstream", "companies": [], "bottleneck": True},
            {"id": "U4", "label": "传感器", "stage": "upstream", "companies": [], "bottleneck": True},
            {"id": "D1", "label": "场景", "stage": "downstream", "companies": [], "bottleneck": True},
            {"id": "M1", "label": "整机厂", "stage": "midstream", "is_core": True, "companies": ["A"]},
            {"id": "M2", "label": "组装产线", "stage": "midstream", "companies": ["B"]},
        ],
        "edges": [{"source": "U1", "target": "M2", "label": "供料", "flow": "material"}],
    }
    errs = validate_topology(bad)
    assert any("瓶颈" in e for e in errs), "瓶颈超限/错段应被裁判打回"

    fixed, repairs = repair_topology(bad)
    assert validate_topology(fixed) == [], f"修复后仍不过：{validate_topology(fixed)}"
    assert len([n for n in fixed["nodes"] if n.get("bottleneck")]) <= MAX_BOTTLENECK
    assert all(n["stage"] == "upstream" for n in fixed["nodes"] if n.get("bottleneck"))
    assert any("瓶颈" in r for r in repairs), "修复必须留痕"
    # 修复后能正常出 spec 与图
    spec = topology_to_spec(fixed)
    assert len(render_chain_svg(spec).encode()) > 500


def test_topology_to_spec_passes_template_fields():
    """LLM 拓扑 JSON → spec：新字段透传，非法取值按缺失处理。"""
    top = {
        "title": "t", "subtitle": "s", "core_product": "p",
        "nodes": [
            {"id": "U1", "label": "芯片", "stage": "upstream", "companies": ["A", "B"],
             "bottleneck": True, "phase": "已落地"},
            {"id": "D1", "label": "场景", "stage": "downstream", "companies": [],
             "phase": "胡说", "buyer": "电网 / 应急"},
            {"id": "M1", "label": "整机厂", "stage": "midstream", "is_core": True,
             "companies": ["A", "B", "C", "D", "E", "F"]},
        ],
        "edges": [{"source": "U1", "target": "M1", "label": "供料", "flow": "material"}],
    }
    spec = topology_to_spec(top)
    by = {n.name: n for n in spec.nodes}
    assert by["芯片"].bottleneck is True
    assert by["芯片"].phase == ""            # 上游节点不吃 phase（只对下游场景有意义）
    assert by["场景"].phase == ""             # 非法取值清空
    assert by["场景"].buyer == "电网 / 应急"   # 合法文本透传
    assert by["整机厂"].is_core is True


def test_core_body_needs_five_brands():
    """本体盒门槛：核心节点 ≥5 个品牌才竖排；不足走普通卡片（不硬撑）。"""
    spec = _full_spec()
    core = next(n for n in spec.nodes if n.is_core and len(n.companies) >= 5)
    svg_body = render_chain_svg(spec)
    assert core.name in "".join(_texts(svg_body))

    thin = _full_spec()
    for nd in thin.nodes:
        if nd.node_id == "B1":
            nd.companies = ["A", "B"]        # 不足 5 个 → 普通卡片
    svg_thin = render_chain_svg(thin)
    assert assert_graph_fidelity(thin, svg_thin) == []
    assert [i for i in lint_chain_svg(thin, svg_thin) if i["level"] == "error"] == []


def test_single_core_node_enforced():
    """核心节点必须唯一：多个 is_core 被裁判打回，修复后只留企业最多的那个。"""
    bad = {
        "title": "t", "subtitle": "", "core_product": "x",
        "nodes": [
            {"id": "U1", "label": "芯片", "stage": "upstream", "companies": ["A", "B"]},
            {"id": "M1", "label": "研发中心", "stage": "midstream", "is_core": True, "companies": ["A"]},
            {"id": "M2", "label": "整机厂", "stage": "midstream", "is_core": True,
             "companies": ["A", "B", "C", "D", "E"]},
            {"id": "D1", "label": "场景", "stage": "downstream", "companies": [], "buyer": "电网"},
        ],
        "edges": [{"source": "U1", "target": "M2", "label": "供料", "flow": "material"}],
    }
    errs = validate_topology(bad)
    assert any("is_core" in e for e in errs), "多核心应被裁判打回"
    fixed, repairs = repair_topology(bad)
    assert validate_topology(fixed) == []
    cores = [n for n in fixed["nodes"] if n.get("is_core")]
    assert len(cores) == 1 and cores[0]["label"] == "整机厂", "应保留企业最多的核心节点"
    assert any("核心" in r for r in repairs)


def test_companies_as_string_normalized_in_spec():
    """A3 侧同源归一化：companies/key_products 是字符串也不能逐字拆（P0 复发防线）。"""
    top = {
        "title": "t", "subtitle": "s", "core_product": "p",
        "nodes": [
            {"id": "U1", "label": "芯片", "stage": "upstream", "companies": "中芯国际 · 华虹",
             "key_products": "晶圆 / 封测", "evidence_ids": ["R1"]},
            {"id": "D1", "label": "场景", "stage": "downstream", "companies": [],
             "phase": "已落地", "buyer": "电网", "evidence_ids": []},
            {"id": "M1", "label": "整机厂", "stage": "midstream", "is_core": True,
             "companies": ["A", "B", "C"], "evidence_ids": ["R1"]},
        ],
        "edges": [{"source": "U1", "target": "M1", "label": "供料", "flow": "material"}],
    }
    spec = topology_to_spec(top)
    by = {n.name: n for n in spec.nodes}
    assert by["芯片"].companies == ["中芯国际", "华虹"], by["芯片"].companies
    assert by["芯片"].items == ["晶圆", "封测"], by["芯片"].items
    svg = render_chain_svg(spec)
    assert "中芯国际" in svg and "华虹" in svg
    assert assert_graph_fidelity(spec, svg) == []


def test_unbound_company_is_stripped_not_whole_topology_dropped():
    """企业不在白名单 → 摘除该企业、保住整张图（真实运行 50 项违规废掉 15 节点图的教训）。"""
    bad = {
        "title": "t", "subtitle": "", "core_product": "x",
        "nodes": [
            {"id": "U1", "label": "电池", "stage": "upstream",
             "companies": ["宁德时代", "幻影集团"], "evidence_ids": ["R1"]},
            {"id": "M1", "label": "整机厂", "stage": "midstream", "is_core": True,
             "companies": ["A", "B", "C"], "evidence_ids": ["R1"]},
            {"id": "D1", "label": "场景", "stage": "downstream", "companies": [],
             "phase": "已落地", "buyer": "电网", "evidence_ids": []},
        ],
        "edges": [{"source": "U1", "target": "M1", "label": "供料", "flow": "material"}],
    }
    errs = validate_topology(bad, allowed_companies={"宁德时代", "A", "B", "C"})
    assert any("幻影集团" in e for e in errs), "不在白名单的企业应被裁判发现"

    fixed, repairs = repair_topology(bad, allowed_companies={"宁德时代", "A", "B", "C"})
    assert validate_topology(fixed, allowed_companies={"宁德时代", "A", "B", "C"}) == []
    # 2026-10-18 F1：真名（数据源没召回的行业常识）**降级保留、不再删除**。
    # 旧行为摘掉它，实测把海上风电整机节点的 8 家正确龙头（金风/明阳/远景/运达）删成 0 家。
    assert fixed["nodes"][0]["companies"] == ["宁德时代", "幻影集团"], "真名不得删除"
    assert fixed["nodes"][0]["source_tier"] == "industry_common", "须降级为行业通识层"
    assert any("降级" in r for r in repairs), "降级必须留痕"
    spec = topology_to_spec(fixed)
    svg = render_chain_svg(spec)
    assert "宁德时代" in svg
    assert assert_graph_fidelity(spec, svg) == []


def test_company_in_evidence_text_is_traceable():
    """2026-10-16：企业出现在证据原文里即算可追溯（白名单只收 entity 字段太窄）。

    真实运行踩坑：LLM 从研报摘要"推荐标的：宁德时代、亿纬锂能"读到公司名，
    而这些名字不在 evidence_index 的 entity 里，旧白名单把它们全判成"编造"。
    """
    top = {
        "title": "t", "subtitle": "", "core_product": "x",
        "nodes": [
            {"id": "U1", "label": "动力电池", "stage": "upstream",
             "companies": ["宁德时代", "亿纬锂能"], "evidence_ids": ["R1"]},
            {"id": "M1", "label": "整机厂", "stage": "midstream", "is_core": True,
             "companies": ["A", "B", "C"], "evidence_ids": ["R1"]},
            {"id": "M2", "label": "总装产线", "stage": "midstream",
             "companies": ["E", "F"], "evidence_ids": ["R1"]},
            {"id": "D1", "label": "场景", "stage": "downstream", "companies": [],
             "phase": "已落地", "buyer": "电网", "evidence_ids": []},
        ],
        "edges": [{"source": "U1", "target": "M2", "label": "供料", "flow": "material"}],
    }
    ev_text = "上游材料与零部件配套需求增加，推荐标的：宁德时代、亿纬锂能，相关标的：英搏尔"
    # 故意不含宁德时代/亿纬锂能；E/F 给「总装产线」用，避免与整机厂的 A/B/C 撞车
    # （2026-10-17 起「企业跨节点唯一性」是硬规则，fixture 不能让同一家出现在两个节点）
    whitelist = {"A", "B", "C", "E", "F"}

    errs = validate_topology(top, allowed_companies=whitelist, evidence_text=ev_text)
    assert errs == [], f"证据原文里的企业不该被判编造: {errs}"

    # 真编造的名字（原文里没有）仍要被拦
    bad = json.loads(json.dumps(top))
    bad["nodes"][0]["companies"] = ["宁德时代", "幻影集团"]
    errs2 = validate_topology(bad, allowed_companies=whitelist, evidence_text=ev_text)
    assert any("幻影集团" in e for e in errs2), "原文里没有的名字必须拦住"

    # repair 保住宁德时代；幻影集团按 F1 降级保留（真名不删）
    fixed, _ = repair_topology(bad, allowed_companies=whitelist, evidence_text=ev_text)
    assert fixed["nodes"][0]["companies"] == ["宁德时代", "幻影集团"], fixed["nodes"][0]["companies"]
    assert fixed["nodes"][0]["source_tier"] == "industry_common"

    # 短名字不允许蹭长名字（"宁德" 不该搭 "宁德时代" 的车）
    short = json.loads(json.dumps(top))
    short["nodes"][0]["companies"] = ["宁德"]
    assert any("宁德" in e for e in validate_topology(short, allowed_companies={"A", "B", "C"},
                                                      evidence_text=ev_text))


def test_template_anatomy_asset_exists():
    """模板解剖资产存在且与人形机器人成品图同源（提示词的事实来源）。"""
    p = Path(__file__).resolve().parents[3] / "scratch" / "chain_redesign" / "template_anatomy.json"
    if not p.exists():
        pytest.skip("模板解剖资产未随仓库分发")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["real_data_example"]["downstream"][0][3] in {"已落地", "试点中", "示范期", "远期"}


def test_technical_edge_from_support_downgraded_to_service():
    """2026-10-16 真实运行踩坑（run-20261016232834）：repair 只修了技术流的
    目标端违规，源端违规（配套节点发「数据反馈」标 technical）修不了 →
    一条边废掉整张 17 节点拓扑。源端违规同理降级 service：配套 → 设计研发
    的数据回传本质是服务/数据流，不是 EDA/工具/IP 授权。
    """
    top = {
        "title": "t", "subtitle": "", "core_product": "x",
        "nodes": [
            {"id": "U1", "label": "动力电池", "stage": "upstream",
             "companies": ["宁德时代"], "evidence_ids": ["R1"]},
            {"id": "M1", "label": "整机厂", "stage": "midstream", "is_core": True,
             "companies": ["A", "B", "C"], "evidence_ids": ["R1"]},
            {"id": "D1", "label": "场景", "stage": "downstream", "companies": [],
             "phase": "已落地", "buyer": "电网", "evidence_ids": []},
            {"id": "S1", "label": "数据服务", "stage": "support",
             "companies": ["D"], "evidence_ids": []},
        ],
        "edges": [
            {"source": "U1", "target": "M1", "label": "供电芯", "flow": "material"},
            {"source": "M1", "target": "D1", "label": "整机交付", "flow": "material"},
            # 违规边：support → 设计研发核心，标成 technical
            {"source": "S1", "target": "M1", "label": "数据反馈", "flow": "technical"},
        ],
    }
    errs = validate_topology(top, allowed_companies={"宁德时代", "A", "B", "C", "D"})
    assert any("数据反馈" in e for e in errs), "裁判应发现源端违规"

    fixed, repairs = repair_topology(top, allowed_companies={"宁德时代", "A", "B", "C", "D"})
    assert validate_topology(fixed, allowed_companies={"宁德时代", "A", "B", "C", "D"}) == [], \
        "修复后必须过审（这是本次踩坑的验收标准）"
    edge = next(e for e in fixed["edges"] if e["label"] == "数据反馈")
    assert edge["flow"] == "service", "配套→设计研发的数据回传应降级为 service"
    assert any("数据反馈" in r and "service" in r for r in repairs), "降级必须留痕"
