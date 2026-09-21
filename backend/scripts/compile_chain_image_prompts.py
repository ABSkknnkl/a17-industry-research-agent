#!/usr/bin/env python3
"""用 Agent3 产业链生图协议编译 4 条 horizontal_flow 提示词（不渲染代码图）。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.chart_generator.industry_chain import (  # noqa: E402
    build_chain_image_prompt_body,
    build_prompt_runtime_payload,
    build_verified_chain_graph,
    finalize_chain_prompt,
    select_chain_template,
)
from app.schemas.chart import ChainEdge, ChainNode, ChartDataset  # noqa: E402

CWD = Path(__file__).resolve().parents[2]
OUT = CWD / "output" / "industry-chain-images"
OUT.mkdir(parents=True, exist_ok=True)


def n(nid, label, stage, *, companies=None, core=False, kind="component", ev="E-DEMO"):
    return ChainNode(
        node_id=nid,
        label=label,
        stage=stage,
        node_kind=kind,
        companies=companies or [],
        logo_names=[c for c in (companies or []) if "演示" not in c][:3],
        is_core=core,
        evidence_ids=[ev],
    )


def dataset(metric, subtitle, core_name, nodes, edge_pairs):
    by = {x.node_id: x for x in nodes}
    edges = [
        ChainEdge(
            source=a,
            target=b,
            label=lab,
            flow_type="supply" if lab in ("供给", "供货") else "application",
            evidence_ids=list(dict.fromkeys([*by[a].evidence_ids, *by[b].evidence_ids])),
        )
        for a, b, lab in edge_pairs
    ]
    return ChartDataset(
        dataset_id=f"DS-CHAIN-{metric[:8]}",
        kind="industry_chain",
        metric_name=metric,
        core_product_name=core_name,
        chain_template_hint="horizontal_flow",
        chart_subtitle=subtitle,
        nodes=nodes,
        edges=edges,
        evidence_ids=["E-DEMO"],
        business_linked=True,
    )


THEMES = []

# 1 人形机器人
nodes = [
    n("U1", "减速器/丝杠", "upstream", companies=["绿的谐波（演示）", "双环传动（演示）"]),
    n("U2", "电机/伺服", "upstream", companies=["步科", "鸣志电器（演示）", "空心杯电机"]),
    n("U3", "力矩传感器/IMU", "upstream", companies=["柯力传感（演示）"]),
    n("U4", "算力芯片/模组", "upstream", companies=["英伟达", "地平线（演示）"]),
    n("U5", "电池与轻量化材料", "upstream", companies=["电池模组", "碳纤维结构件"]),
    n("M1", "人形机器人本体与集成", "midstream", companies=["宇树", "优必选", "智元（演示）"], core=True, kind="manufacturing"),
    n("M2", "关节模组/灵巧手", "midstream", companies=["关节模组厂商（演示）"]),
    n("D1", "工业制造", "downstream", companies=["汽车/3C工厂"], kind="application"),
    n("D2", "仓储物流", "downstream", companies=["仓储搬运"], kind="application"),
    n("D3", "商用服务", "downstream", companies=["接待/巡检"], kind="application"),
    n("D4", "科研教育", "downstream", companies=["高校实验室"], kind="application"),
    n("S1", "具身智能算法/仿真", "support", companies=["大模型+运动控制"], kind="software"),
    n("S2", "运维与系统集成", "support", companies=["集成商（演示）"], kind="service"),
]
pairs = []
for u in ["U1", "U2", "U3", "U4", "U5"]:
    pairs.append((u, "M1", "供给"))
pairs += [("M1", "M2", "配套"), ("M2", "D1", "交付"), ("M2", "D2", "交付"), ("M2", "D3", "交付"), ("M2", "D4", "交付"),
          ("S1", "M1", "软件"), ("S2", "D1", "支撑"), ("S2", "D3", "支撑")]
THEMES.append({
    "slug": "humanoid-robot",
    "title": "人形机器人产业链全景（演示）",
    "ds": dataset(
        "人形机器人产业链全景",
        "上游核心零部件与算力→中游本体与关节模组→下游工业/物流/服务/科研，算法与集成支撑",
        "人形机器人整机",
        nodes,
        pairs,
    ),
})

# 2 固态电池
nodes = [
    n("U1", "锂资源/关键金属", "upstream", companies=["锂盐厂（演示）"], kind="material"),
    n("U2", "固态电解质", "upstream", companies=["硫化物/氧化物/聚合物路线"], kind="material"),
    n("U3", "正负极材料", "upstream", companies=["高镍正极", "硅基负极"], kind="material"),
    n("U4", "制造与检测设备", "upstream", companies=["叠片/等静压设备（演示）"], kind="equipment"),
    n("M1", "固态电芯与系统", "midstream", companies=["电池厂（演示）", "车企电池部门"], core=True, kind="manufacturing"),
    n("M2", "电池包/BMS", "midstream", companies=["系统集成（演示）"]),
    n("D1", "新能源汽车", "downstream", companies=["高端车型试点"], kind="application"),
    n("D2", "消费电子", "downstream", companies=["穿戴/无人机"], kind="application"),
    n("D3", "低空飞行器", "downstream", companies=["eVTOL/无人机"], kind="application"),
    n("D4", "储能试点", "downstream", companies=["示范项目"], kind="application"),
    n("S1", "检测认证", "support", companies=["安全/循环测试"], kind="service"),
    n("S2", "回收与材料再生", "support", companies=["回收网络"], kind="service"),
]
pairs = [(u, "M1", "供给") for u in ["U1", "U2", "U3", "U4"]]
pairs += [("M1", "M2", "配套")]
pairs += [("M2", d, "交付") for d in ["D1", "D2", "D3", "D4"]]
pairs += [("S1", "M1", "支撑"), ("S2", "M1", "回收")]
THEMES.append({
    "slug": "solid-state-battery",
    "title": "固态电池产业链全景（演示）",
    "ds": dataset(
        "固态电池产业链全景",
        "上游电解质与材料设备→中游电芯与系统→下游车/消费电子/低空/储能，检测回收支撑",
        "固态电池电芯",
        nodes,
        pairs,
    ),
})

# 3 低空经济
nodes = [
    n("U1", "动力电池/电芯", "upstream", companies=["高能量密度电芯"], kind="component"),
    n("U2", "电机电控/电推", "upstream", companies=["航空电推（演示）"]),
    n("U3", "碳纤维复材/结构件", "upstream", companies=["复材供应商（演示）"], kind="material"),
    n("U4", "飞控/航电/感知", "upstream", companies=["飞控芯片", "毫米波/视觉"]),
    n("M1", "eVTOL与工业无人机", "midstream", companies=["亿航", "峰飞", "小鹏汇天（演示）"], core=True, kind="manufacturing"),
    n("M2", "动力系统/任务载荷", "midstream", companies=["电推与载荷厂商"]),
    n("D1", "城市空中交通UAM", "downstream", companies=["空中出租/通勤"], kind="application"),
    n("D2", "物流配送", "downstream", companies=["支线/末端配送"], kind="application"),
    n("D3", "农林植保/巡检", "downstream", companies=["植保/电力巡检"], kind="application"),
    n("D4", "应急与文旅", "downstream", companies=["救援/低空旅游"], kind="application"),
    n("S1", "空管与低空智联网", "support", companies=["UTM/通信导航"], kind="software"),
    n("S2", "起降场/运维/保险", "support", companies=["基建与服务"], kind="service"),
]
pairs = [(u, "M1", "供给") for u in ["U1", "U2", "U3", "U4"]]
pairs += [("M1", "M2", "配套")]
pairs += [("M2", d, "交付") for d in ["D1", "D2", "D3", "D4"]]
pairs += [("S1", "D1", "支撑"), ("S1", "D2", "支撑"), ("S2", "M1", "配套")]
THEMES.append({
    "slug": "low-altitude-evtol",
    "title": "低空经济产业链全景（演示）",
    "ds": dataset(
        "低空经济产业链全景",
        "上游三电与复材航电→中游eVTOL/无人机整机→下游UAM物流植保应急，空管与起降支撑",
        "eVTOL/工业无人机",
        nodes,
        pairs,
    ),
})

# 4 AI算力
# 业务链路修正（2026-09-21）：光模块原先被放在服务器之后、并负责向下游交付，
# 导致出图出现「服务器生产光模块、光模块卖给云厂商」的错误拓扑。真实关系：
#   光芯片 → 光模块 →（装进）AI服务器/算力集群 → 云与智算 / 大模型 / 行业AI
# 液冷与供电是服务器的配套，箭头指向服务器，不参与交付。
nodes = [
    n("U1", "AI芯片/GPU", "upstream", companies=["英伟达", "国产AI芯片（演示）"], kind="component"),
    n("U2", "HBM/存储", "upstream", companies=["HBM/DDR（演示）"]),
    n("U3", "光芯片与光器件", "upstream", companies=["光芯片", "光器件（演示）"], kind="component"),
    n("U4", "光模块与高速互连", "upstream", companies=["光模块厂（演示）"], kind="component"),
    n("U5", "PCB/电源/铜缆", "upstream", companies=["高多层PCB", "服务器电源"]),
    n("M1", "AI服务器与算力集群", "midstream", companies=["浪潮/新华三（演示）", "ODM", "数据中心交换机"], core=True, kind="manufacturing"),
    n("M2", "液冷与机房供电", "midstream", companies=["液冷方案", "机房供电"], kind="equipment"),
    n("D1", "云与智算中心", "downstream", companies=["云厂商/国资智算"], kind="application"),
    n("D2", "大模型训练推理", "downstream", companies=["模型厂商"], kind="application"),
    n("D3", "行业AI应用", "downstream", companies=["金融/制造/政务"], kind="application"),
    n("S1", "能源与电力保障", "support", companies=["电力供给"], kind="equipment"),
    n("S2", "集群调度与运维", "support", companies=["集群运维"], kind="software"),
]
pairs = [(u, "M1", "供给") for u in ["U1", "U2", "U5"]]
pairs += [("U3", "U4", "供给")]  # 光芯片 → 光模块
pairs += [("U4", "M1", "供给")]  # 光模块装进 AI 服务器 / 网络设备
pairs += [("M2", "M1", "配套")]  # 液冷与供电配套服务器，不参与交付
pairs += [("M1", d, "交付") for d in ["D1", "D2", "D3"]]
pairs += [("S1", "M1", "支撑"), ("S2", "M1", "软件")]
THEMES.append({
    "slug": "ai-compute",
    "title": "AI算力产业链全景（演示）",
    "ds": dataset(
        "AI算力产业链全景",
        "上游芯片存储与光互连→中游AI服务器与算力集群→下游云智算/大模型/行业AI，液冷供电与运维支撑",
        "AI服务器/算力集群",
        nodes,
        pairs,
    ),
})


def compile_prompt(theme) -> str:
    ds = theme["ds"]
    ctx = {"industry_topic": theme["title"], "focus_questions": ["产业链上中下游结构如何？"]}
    template = select_chain_template(ds, ctx)
    graph = build_verified_chain_graph(
        title=theme["title"], dataset=ds, request_context=ctx, template=template
    )
    runtime = build_prompt_runtime_payload(graph, template)
    # 交付生图模型的正文改用共享构造器：纯文字、版式/配色/负面约束取自模板单一真相，
    # 不再手写、也不再回带 PROMPT_COMPILER_SYSTEM（系统规则是给 LLM 编译器看的，生图模型不需要）。
    body = build_chain_image_prompt_body(graph, template)
    # 拓扑由确定性代码补齐，不再写「nodes=N edges=N」计数：
    # 计数对生图模型无意义，反而诱导它自行编造流向（实测出现箭头反向、节点压扁、企业名错配）。
    prompt, _missing = finalize_chain_prompt(body, graph)
    path = OUT / f"{theme['slug']}.prompt.txt"
    path.write_text(prompt, encoding="utf-8")
    (OUT / f"{theme['slug']}.graph.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / f"{theme['slug']}.runtime.json").write_text(runtime, encoding="utf-8")
    return prompt


def main() -> None:
    index = []
    for theme in THEMES:
        prompt = compile_prompt(theme)
        print(f"[ok] {theme['slug']} prompt_chars={len(prompt)}")
        index.append(theme["slug"])
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[out] {OUT}")


if __name__ == "__main__":
    main()
