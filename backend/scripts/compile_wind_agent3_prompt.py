#!/usr/bin/env python3
"""Agent3 编译风电产业链生图提示词。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.agents.chart_generator.industry_chain import (
    build_chain_image_prompt_body,
    build_prompt_runtime_payload,
    build_verified_chain_graph,
    finalize_chain_prompt,
    select_chain_template,
)
from app.schemas.chart import ChainEdge, ChainNode, ChartDataset

OUT = ROOT / "output" / "industry-chain-images"
OUT.mkdir(parents=True, exist_ok=True)


def n(nid, label, stage, companies=None, core=False, kind="component"):
    return ChainNode(
        node_id=nid,
        label=label,
        stage=stage,
        node_kind=kind,
        companies=companies or [],
        logo_names=[],
        is_core=core,
        evidence_ids=["E-DEMO"],
    )


nodes = [
    n("U1", "稀土永磁", "upstream", ["永磁材料供应商"], kind="material"),
    n("U2", "特钢/铸件", "upstream", ["特钢/铸件厂"], kind="material"),
    n("U3", "叶片", "upstream", ["叶片制造商"], kind="component"),
    n("U4", "齿轮箱/轴承", "upstream", ["齿轮箱/轴承厂"], kind="component"),
    n("U5", "塔筒/海缆", "upstream", ["塔筒/海缆厂商"], kind="component"),
    n("M1", "整机制造", "midstream", ["风电整机厂"], core=True, kind="manufacturing"),
    n("D1", "陆上风电场", "downstream", ["陆上风电运营商"], kind="application"),
    n("D2", "海上风电场", "downstream", ["海上风电运营商"], kind="application"),
    n("S1", "风电运维", "support", ["运维服务商"], kind="service"),
]
pairs = [
    ("U1", "M1", "供给"),
    ("U2", "M1", "供给"),
    ("U3", "M1", "供给"),
    ("U4", "M1", "供给"),
    ("U5", "M1", "供给"),
    ("M1", "D1", "交付"),
    ("M1", "D2", "交付"),
    ("S1", "D1", "运维"),
    ("S1", "D2", "运维"),
    ("D1", "S1", "闭环"),
    ("D2", "S1", "闭环"),
    ("S1", "M1", "反馈"),
]
edges = [
    ChainEdge(
        source=a,
        target=b,
        label=lab,
        flow_type=(
            "supply"
            if lab == "供给"
            else ("support" if lab in ("运维", "反馈", "闭环") else "application")
        ),
        evidence_ids=["E-DEMO"],
    )
    for a, b, lab in pairs
]
ds = ChartDataset(
    dataset_id="DS-CHAIN-WIND",
    kind="industry_chain",
    metric_name="风电产业链全景",
    core_product_name="风电整机",
    chain_template_hint="horizontal_flow",
    chart_subtitle=(
        "上游稀土永磁/特钢铸件/叶片/齿轮箱轴承/塔筒海缆→中游整机制造→"
        "下游陆上与海上风电场，服务端风电运维闭环"
    ),
    nodes=nodes,
    edges=edges,
    evidence_ids=["E-DEMO"],
    business_linked=True,
)
ctx = {
    "industry_topic": "风电产业链全景",
    "focus_questions": ["风电上中下游与运维闭环？"],
}
template = select_chain_template(ds, ctx)
graph = build_verified_chain_graph(
    title="风电产业链全景（演示）",
    dataset=ds,
    request_context=ctx,
    template=template,
)
runtime = build_prompt_runtime_payload(graph, template)
# 交付生图模型的正文改用共享构造器：纯文字、版式/配色/负面约束取自模板单一真相，
# 不再手写、也不再回带 PROMPT_COMPILER_SYSTEM（系统规则是给 LLM 编译器看的，生图模型不需要）。
body = build_chain_image_prompt_body(graph, template)

# 拓扑由确定性代码补齐，不再写「nodes=N edges=N」计数（计数无量纲信息，且会诱导模型自编流向）
prompt, _missing = finalize_chain_prompt(body, graph)

(OUT / "wind-power-agent3.prompt.txt").write_text(prompt, encoding="utf-8")
(OUT / "wind-power-agent3.graph.json").write_text(
    json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
)
(OUT / "wind-power-agent3.runtime.json").write_text(runtime, encoding="utf-8")
print(prompt)
print("---")
print("template", template, "nodes", len(graph["nodes"]), "edges", len(graph["edges"]))
print("out", OUT)
