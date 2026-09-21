#!/usr/bin/env python3
"""英伟达显卡产业链：建图谱 → 真实 LLM compile_chain_prompt → 落盘提示词。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.agents.chart_generator.industry_chain import (  # noqa: E402
    build_prompt_runtime_payload,
    build_verified_chain_graph,
    compile_chain_prompt,
    select_chain_template,
    validate_chain_prompt,
)
from app.core.config import settings  # noqa: E402
from app.integrations.visuals.factory import create_prompt_compiler  # noqa: E402
from app.schemas.chart import ChainEdge, ChainNode, ChartDataset  # noqa: E402

OUT = ROOT / "output" / "industry-chain-images"
OUT.mkdir(parents=True, exist_ok=True)
SLUG = "nvidia-gpu"


def n(nid, label, stage, *, companies=None, core=False, kind="component", logos=None):
    return ChainNode(
        node_id=nid,
        label=label,
        stage=stage,
        node_kind=kind,
        companies=companies or [],
        logo_names=logos if logos is not None else [],
        is_core=core,
        evidence_ids=["E-DEMO"],
    )


def build_graph():
    # 显卡 product_decomposition / 亦可 horizontal_flow：metric 含「显卡」→ 偏 product
    # 用户要产业链全景，hint 明确 horizontal_flow 更稳
    nodes = [
        n("U1", "GPU 芯片设计", "upstream", companies=["英伟达"], logos=["英伟达"], kind="manufacturing"),
        n("U2", "先进制程晶圆代工", "upstream", companies=["台积电"], logos=["台积电"], kind="manufacturing"),
        n("U3", "HBM/显存", "upstream", companies=["SK海力士", "三星", "美光"], kind="component"),
        n("U4", "封装测试", "upstream", companies=["日月光", "安靠"], kind="component"),
        n("U5", "PCB/供电/散热材料", "upstream", companies=["高多层PCB", "MOS/电感", "均热板/硅脂"], kind="material"),
        n("M1", "显卡整板制造", "midstream", companies=["AIC 合作板卡厂"], core=True, kind="manufacturing"),
        n("M2", "GeForce / 专业卡品牌整卡", "midstream", companies=["英伟达 Founders Edition", "华硕", "微星", "技嘉"], logos=["英伟达"], kind="product"),
        n("D1", "游戏与消费 PC", "downstream", companies=["电竞整机与 DIY"], kind="application"),
        n("D2", "数据中心与 AI 训练", "downstream", companies=["云厂商", "智算中心"], kind="application"),
        n("D3", "专业可视化/内容创作", "downstream", companies=["设计/影视工作站"], kind="application"),
        n("S1", "驱动与 CUDA 软件栈", "support", companies=["驱动", "CUDA"], kind="software"),
        n("S2", "渠道分销与售后", "support", companies=["分销/电商", "售后网点"], kind="service"),
    ]
    by = {x.node_id: x for x in nodes}
    pairs = [
        ("U1", "M1", "供给"),
        ("U2", "U1", "供给"),
        ("U3", "M1", "供给"),
        ("U4", "M1", "供给"),
        ("U5", "M1", "供给"),
        ("M1", "M2", "配套"),
        ("M2", "D1", "交付"),
        ("M2", "D2", "交付"),
        ("M2", "D3", "交付"),
        ("S1", "D1", "软件"),
        ("S1", "D2", "软件"),
        ("S2", "M2", "支撑"),
    ]
    edges = []
    for a, b, lab in pairs:
        if lab == "供给":
            ft = "supply"
        elif lab in ("配套", "交付"):
            ft = "value" if lab == "配套" else "application"
        else:
            ft = "software" if lab == "软件" else "support"
        edges.append(
            ChainEdge(
                source=a,
                target=b,
                label=lab,
                flow_type=ft,
                evidence_ids=list(dict.fromkeys([*by[a].evidence_ids, *by[b].evidence_ids])),
            )
        )
    ds = ChartDataset(
        dataset_id="DS-CHAIN-NVIDIA-GPU",
        kind="industry_chain",
        metric_name="英伟达显卡产业链全景",
        core_product_name="英伟达 GeForce/专业显卡",
        chain_template_hint="horizontal_flow",
        chart_subtitle=(
            "上游GPU设计、晶圆代工、HBM显存、封测与PCB散热→中游AIC板卡与整卡→"
            "下游游戏PC、数据中心AI与专业可视化，驱动CUDA与渠道售后支撑"
        ),
        nodes=nodes,
        edges=edges,
        evidence_ids=["E-DEMO"],
        business_linked=True,
    )
    ctx = {
        "industry_topic": "英伟达显卡产业链全景",
        "focus_questions": ["英伟达显卡上中下游与软件生态如何？"],
    }
    template = select_chain_template(ds, ctx)
    graph = build_verified_chain_graph(
        title="英伟达显卡产业链全景（演示）",
        dataset=ds,
        request_context=ctx,
        template=template,
    )
    return graph, template, ds


async def main() -> None:
    graph, template, _ds = build_graph()
    graph_path = OUT / f"{SLUG}.graph.json"
    runtime_path = OUT / f"{SLUG}.runtime.json"
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    runtime_path.write_text(
        build_prompt_runtime_payload(graph, template), encoding="utf-8"
    )
    print(f"[graph] template={template} nodes={len(graph['nodes'])} edges={len(graph['edges'])}")
    print(f"[graph] {graph_path}")

    compiler = create_prompt_compiler(settings)
    print(f"[llm] compiler={compiler.model_name} mock={settings.LLM_USE_MOCK}")
    prompt = await compile_chain_prompt(compiler=compiler, graph=graph, template=template)
    problems = validate_chain_prompt(prompt, graph)
    out = OUT / f"{SLUG}.live.prompt.txt"
    out.write_text(prompt, encoding="utf-8")
    print(f"[prompt] chars={len(prompt)} problems={len(problems)} path={out}")
    if problems:
        print("[warn]", problems[:8])
    print("---PROMPT---")
    print(prompt)
    print("---END---")


if __name__ == "__main__":
    asyncio.run(main())
