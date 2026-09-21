#!/usr/bin/env python3
"""代打产业链生图：宇树科技（Unitree）产业链图。

数据来源边界：
- 节点/公司名参考宇树官网公开产品线与通用机器人产业链常识；
- 结构与「代表企业」为演示捏造，标注 DEMO，不构成投资事实；
- 走真实 Agent3 代码：ChartDataset → build_industry_chain_option → render_chart_svg；
- 「生图模型代打」：按 industry_chain.horizontal_flow 模板规则渲染信息图 HTML。

运行：cd backend && .venv/bin/python scripts/run_unitree_chain_chart.py
输出：cwd/output/unitree-chain/
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.chart_generator.builders import build_industry_chain_option  # noqa: E402
from app.agents.chart_generator.industry_chain import (  # noqa: E402
    build_chain_image_prompt_body,
    build_prompt_runtime_payload,
    build_verified_chain_graph,
    finalize_chain_prompt,
    select_chain_template,
)
from app.agents.chart_generator.quality import build_quality_report, validate_option  # noqa: E402
from app.agents.chart_generator.router import route_chart  # noqa: E402
from app.reporting.svg import render_chart_svg  # noqa: E402
from app.schemas.analysis import ChartCandidate  # noqa: E402
from app.schemas.chart import (  # noqa: E402
    ChainEdge,
    ChainNode,
    ChartDataset,
    ChartSpec,
)

CWD = Path(__file__).resolve().parents[2]
OUT_DIR = CWD / "output" / "unitree-chain"
INDEX_PATH = OUT_DIR / "index.html"

EV = {
    "site": "E-UNITREE-SITE",
    "joint": "E-UNITREE-JOINT",
    "lidar": "E-UNITREE-LIDAR",
    "up": "E-CHAIN-UP",
    "mid": "E-CHAIN-MID",
    "down": "E-CHAIN-DOWN",
    "sup": "E-CHAIN-SUP",
}


def node(
    node_id: str,
    label: str,
    stage: str,
    *,
    kind: str = "component",
    companies: list[str] | None = None,
    logos: list[str] | None = None,
    core: bool = False,
    group: str | None = None,
    evidence: list[str] | None = None,
) -> ChainNode:
    return ChainNode(
        node_id=node_id,
        label=label,
        stage=stage,  # type: ignore[arg-type]
        group=group,
        node_kind=kind,  # type: ignore[arg-type]
        companies=companies or [],
        logo_names=logos or [],
        is_core=core,
        evidence_ids=evidence or [EV["up"] if stage == "upstream" else EV["mid"]],
    )


def build_dataset() -> ChartDataset:
    """捏造产业链数据集（演示）：上游零部件 → 中游宇树整机与核心部件 → 下游场景；支撑层软件/算法。"""
    nodes = [
        # 上游
        node(
            "N-UP-MOTOR",
            "关节电机/伺服",
            "upstream",
            kind="component",
            companies=["宇树自研关节", "步科", "鸣志电器（演示）"],
            logos=["宇树科技"],
            group="动力与驱动",
            evidence=[EV["joint"], EV["up"]],
        ),
        node(
            "N-UP-REDUCER",
            "减速器/丝杠",
            "upstream",
            kind="component",
            companies=["绿的谐波（演示）", "双环传动（演示）"],
            group="传动",
            evidence=[EV["up"]],
        ),
        node(
            "N-UP-SENSOR",
            "4D 激光雷达/感知",
            "upstream",
            kind="component",
            companies=["宇树 4D LiDAR L1/L2", "奥比中光（演示）"],
            logos=["宇树科技"],
            group="感知",
            evidence=[EV["lidar"], EV["up"]],
        ),
        node(
            "N-UP-SOC",
            "计算模组/芯片",
            "upstream",
            kind="component",
            companies=["英伟达 Jetson（演示）", "地平线（演示）"],
            group="算力",
            evidence=[EV["up"]],
        ),
        node(
            "N-UP-BAT",
            "电池与电控",
            "upstream",
            kind="component",
            companies=["宁德时代（演示）", "亿纬锂能（演示）"],
            group="能源",
            evidence=[EV["up"]],
        ),
        node(
            "N-UP-MAT",
            "轻量化材料/结构件",
            "upstream",
            kind="material",
            companies=["碳纤维/铝合金供应商（演示）"],
            group="材料",
            evidence=[EV["up"]],
        ),
        # 中游核心
        node(
            "N-MID-UNITREE",
            "宇树科技（足式+人形整机）",
            "midstream",
            kind="manufacturing",
            companies=["宇树科技（Yushu Technology）"],
            logos=["宇树科技"],
            core=True,
            group="整机制造",
            evidence=[EV["site"], EV["mid"]],
        ),
        node(
            "N-MID-QUAD",
            "四足机器人",
            "midstream",
            kind="product",
            companies=["Go2 / As2 / A2 / B2 / B1"],
            group="产品线",
            evidence=[EV["site"], EV["mid"]],
        ),
        node(
            "N-MID-HUMAN",
            "人形机器人",
            "midstream",
            kind="product",
            companies=["G1 / H1 / H1-2 / H2 / R1"],
            group="产品线",
            evidence=[EV["site"], EV["mid"]],
        ),
        node(
            "N-MID-ARM",
            "机械臂与灵巧手",
            "midstream",
            kind="product",
            companies=["Z1 / D1-T / Dex 系列"],
            group="操作",
            evidence=[EV["site"], EV["mid"]],
        ),
        node(
            "N-MID-COMP",
            "自研核心部件外供",
            "midstream",
            kind="component",
            companies=["GO-M8010 电机", "SV1-25 伺服", "防水关节 B1-16"],
            group="部件",
            evidence=[EV["joint"], EV["mid"]],
        ),
        # 下游
        node(
            "N-DOWN-EDU",
            "科研教育",
            "downstream",
            kind="application",
            companies=["高校实验室", "竞赛/开发者"],
            group="场景",
            evidence=[EV["down"]],
        ),
        node(
            "N-DOWN-IND",
            "工业巡检",
            "downstream",
            kind="application",
            companies=["电力巡检", "工厂巡检"],
            group="场景",
            evidence=[EV["down"]],
        ),
        node(
            "N-DOWN-RESP",
            "应急消防",
            "downstream",
            kind="application",
            companies=["消防救援", "危险作业"],
            group="场景",
            evidence=[EV["down"]],
        ),
        node(
            "N-DOWN-PERF",
            "文娱展演",
            "downstream",
            kind="application",
            companies=["春晚/亚运展演（公开案例）"],
            group="场景",
            evidence=[EV["site"], EV["down"]],
        ),
        node(
            "N-DOWN-EMB",
            "具身智能研发",
            "downstream",
            kind="application",
            companies=["高校/大厂机器人实验室"],
            group="场景",
            evidence=[EV["down"]],
        ),
        # 支撑
        node(
            "N-SUP-ALGO",
            "运控/RL 算法与 SDK",
            "support",
            kind="software",
            companies=["宇树 SDK/开源生态"],
            group="软件",
            evidence=[EV["site"], EV["sup"]],
        ),
        node(
            "N-SUP-SVC",
            "集成方案与运维服务",
            "support",
            kind="service",
            companies=["系统集成商（演示）"],
            group="服务",
            evidence=[EV["sup"]],
        ),
    ]
    by_id = {n.node_id: n for n in nodes}

    def edge(src: str, dst: str, label: str, flow: str = "supply") -> ChainEdge:
        ev = list(dict.fromkeys([*by_id[src].evidence_ids, *by_id[dst].evidence_ids]))
        return ChainEdge(
            source=src,
            target=dst,
            label=label,
            flow_type=flow,  # type: ignore[arg-type]
            evidence_ids=ev,
        )

    upstream = ["N-UP-MOTOR", "N-UP-REDUCER", "N-UP-SENSOR", "N-UP-SOC", "N-UP-BAT", "N-UP-MAT"]
    mids = ["N-MID-QUAD", "N-MID-HUMAN", "N-MID-ARM", "N-MID-COMP"]
    downs = ["N-DOWN-EDU", "N-DOWN-IND", "N-DOWN-RESP", "N-DOWN-PERF", "N-DOWN-EMB"]
    supports = ["N-SUP-ALGO", "N-SUP-SVC"]

    edges: list[ChainEdge] = []
    for u in upstream:
        edges.append(edge(u, "N-MID-UNITREE", "供给", "supply"))
    for m in mids:
        edges.append(edge("N-MID-UNITREE", m, "产品/部件", "value"))
        if m != "N-MID-COMP":
            for d in downs:
                edges.append(edge(m, d, "交付", "application"))
    for s in supports:
        edges.append(edge(s, "N-MID-UNITREE", "软件/服务", "software"))
        for d in downs:
            edges.append(edge(s, d, "支撑", "support"))

    return ChartDataset(
        dataset_id="DS-CHAIN-UNITREE-DEMO",
        kind="industry_chain",
        metric_name="宇树科技产业链全景",
        core_product_name="宇树足式/人形机器人",
        chain_template_hint="horizontal_flow",
        chart_subtitle=(
            "上游关节电机、减速器、4D雷达与算力电芯 → 中游宇树整机与自研部件 → "
            "下游科研教育/工业巡检/应急消防/文娱展演/具身智能（演示结构）"
        ),
        nodes=nodes,
        edges=edges,
        evidence_ids=list(EV.values()),
        data_as_of=date(2026, 9, 20),
        business_linked=True,
    )


def agent3_render(dataset: ChartDataset) -> tuple[ChartSpec, str, list[str]]:
    title = "宇树科技产业链全景（演示）"
    candidate = ChartCandidate(
        title=title,
        chart_type="industry_chain",
        insight_goal=(
            "展示宇树科技产业链：上游零部件供给、中游整机与自研部件、"
            "下游应用场景与软件服务支撑"
        ),
        evidence_ids=list(dataset.evidence_ids),
        priority=1,
        user_requested=True,
        chapter_hint="CH-03",
    )
    route = route_chart(candidate.chart_type, dataset)
    if not route.accepted:
        raise RuntimeError(f"route rejected: {route.reason_code} {route.reason}")
    option = build_industry_chain_option(title, dataset, theme="finance_dashboard")
    option_issues = validate_option(option)
    if option_issues:
        raise RuntimeError(f"option invalid: {option_issues}")
    spec = ChartSpec(
        chart_id="CHART-UNITREE-CHAIN",
        user_requested=True,
        title=title,
        chart_type=route.chart_type or "industry_chain",
        requested_chart_type="industry_chain",
        variant=route.variant,
        option=option,
        evidence_ids=list(dataset.evidence_ids),
        insight_goal=candidate.insight_goal,
        footnotes=[
            "演示数据：节点与代表企业为公开产品线+通用产业链结构捏造，非经审计供应链清单。",
            "数据口径：官网产品线观察 + 机器人产业链常识结构，research_as_of=2026-09-20。",
        ],
        data_fingerprint=("a" * 64),
        dedupe_key="industry_chain:unitree:demo",
        render_mode="echarts",
        quality_issue_ids=[],
    )
    quality = build_quality_report(
        candidate_count=1,
        specs=[spec],
        suppressed=[],
        risk_notices=[],
    )
    svg = render_chart_svg(spec)
    notices = list(quality.issues or [])
    print(f"[quality] passed={quality.passed} issues={notices}")
    return spec, svg, notices


def surrogate_prompt(dataset: ChartDataset) -> tuple[str, dict, str]:
    """代打生图模型：先按项目规则编译提示词，再产出信息图（不改写图谱事实）。"""
    request_context = {
        "industry_topic": "宇树科技产业链",
        "focus_questions": ["宇树科技上中下游与代表应用场景如何？"],
    }
    template = select_chain_template(dataset, request_context)
    graph = build_verified_chain_graph(
        title="宇树科技产业链全景",
        dataset=dataset,
        request_context=request_context,
        template=template,
    )
    payload = build_prompt_runtime_payload(graph, template)
    # 走与其他代打脚本同一套确定性构造：
    # 版式/配色/语义色/绘制规则/负面约束全部取自 template_specification，
    # 节点按阶段分组列出，拓扑由 finalize_chain_prompt 逐条补齐。
    # 此前此处手写提示词，只给了「节点数/连线数」计数，连节点名与边都没写进产物。
    prompt_text, _missing = finalize_chain_prompt(
        build_chain_image_prompt_body(graph, template), graph
    )
    return template, graph, prompt_text


def render_surrogate_html(dataset: ChartDataset, template: str, prompt_text: str, graph: dict) -> str:
    stage_meta = {
        "upstream": ("上游供给", "#1F3A5F", "#E8F0F8"),
        "midstream": ("中游制造与集成", "#2C6CAE", "#D8E8FF"),
        "downstream": ("下游场景与需求", "#1E8449", "#E8F4EF"),
        "support": ("配套与软件支撑", "#A9853F", "#FFF2D8"),
    }

    def cards(stage: str) -> str:
        items = [n for n in dataset.nodes if n.stage == stage]
        rows = []
        for n in items:
            core = n.is_core
            company = "、".join(n.companies[:3]) if n.companies else "—"
            style = (
                "border-color:#1F3A5F;background:#1F3A5F;color:#fff;"
                if core
                else f"border-color:{stage_meta[stage][1]};background:{stage_meta[stage][2]};"
            )
            title_color = "#fff" if core else "#1F3A5F"
            body_color = "#D7E4F5" if core else "#33425C"
            rows.append(
                f'<div class="node" style="{style}">'
                f'<div class="n-t" style="color:{title_color}">{n.label}'
                f'{"<span class=core>核心</span>" if core else ""}</div>'
                f'<div class="n-c" style="color:{body_color}">{company}</div></div>'
            )
        return "".join(rows)

    stage_html = []
    for stage in ("upstream", "midstream", "downstream"):
        title, color, bg = stage_meta[stage]
        stage_html.append(
            f'<section class="stage" style="border-top:4px solid {color}">'
            f'<h2 style="color:{color}">{title}</h2>'
            f'<div class="nodes">{cards(stage)}</div></section>'
        )
    support_html = (
        f'<section class="support" style="border-top:3px solid {stage_meta["support"][1]}">'
        f'<h2 style="color:{stage_meta["support"][1]}">{stage_meta["support"][0]}</h2>'
        f'<div class="nodes support-nodes">{cards("support")}</div></section>'
    )

    edge_summary = f"{len(dataset.edges)} 条供给/价值/应用连线（演示）"
    companies_all = sorted({c for n in dataset.nodes for c in n.companies})
    logo_line = " · ".join(companies_all[:12]) + (" …" if len(companies_all) > 12 else "")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>宇树科技产业链全景 · 代打生图</title>
<style>
:root {{ --navy:#1F3A5F; --blue:#2C6CAE; --ink:#16233B; --ink2:#33425C; --ink3:#5B6880;
  --line:#DFE4EC; --paper:#F5F7FA; --card:#fff; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:#EEF1F5; color:var(--ink);
  font:13px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif; }}
.wrap {{ width:min(1180px,96vw); margin:24px auto 48px; }}
.banner {{ background:var(--navy); color:#fff; padding:20px 26px; border-radius:10px 10px 0 0; }}
.banner h1 {{ margin:0 0 6px; font-family:"Songti SC",serif; font-size:24px; letter-spacing:1px; }}
.banner p {{ margin:0; opacity:.85; font-size:12.5px; }}
.meta {{ background:#fff; border:1px solid var(--line); border-top:0;
  padding:12px 26px 16px; color:var(--ink3); font-size:12px; }}
.flow {{ display:grid; grid-template-columns:1.2fr 1.3fr 1.2fr; gap:14px; margin-top:14px; }}
@media (max-width:960px) {{ .flow {{ grid-template-columns:1fr; }} }}
.stage {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 14px 16px; }}
.stage h2 {{ margin:0 0 12px; font-family:"Songti SC",serif; font-size:16px; font-weight:700; }}
.nodes {{ display:flex; flex-direction:column; gap:8px; }}
.node {{ border:1.5px solid; border-radius:8px; padding:10px 12px; min-height:58px; }}
.n-t {{ font-weight:700; font-size:14px; margin-bottom:4px; }}
.n-t .core {{ display:inline-block; margin-left:8px; font-size:10px; font-weight:600;
  background:#A9853F; color:#fff; padding:1px 6px; border-radius:3px; vertical-align:middle; }}
.n-c {{ font-size:12px; line-height:1.45; }}
.support {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
  margin-top:14px; padding:14px 16px 16px; }}
.support h2 {{ margin:0 0 10px; font-family:"Songti SC",serif; font-size:15px; }}
.support-nodes {{ display:grid; grid-template-columns:1fr 1fr; gap:8px; }}
@media (max-width:700px) {{ .support-nodes {{ grid-template-columns:1fr; }} }}
.arrows {{ text-align:center; color:var(--ink3); font-size:12px; margin:8px 0 0; letter-spacing:2px; }}
.footer {{ margin-top:14px; background:#fff; border:1px dashed var(--line); padding:14px 16px;
  color:var(--ink3); font-size:12px; line-height:1.7; }}
.footer h3 {{ margin:0 0 6px; color:var(--navy); font-size:13px; }}
.prompt {{ margin-top:12px; background:#F8FAFC; border:1px solid var(--line); padding:12px;
  white-space:pre-wrap; color:var(--ink2); font-size:12px; font-family:ui-monospace,Menlo,monospace; }}
a.btn {{ display:inline-block; margin-top:10px; color:var(--blue); font-size:12.5px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="banner">
    <h1>宇树科技产业链全景（演示）</h1>
    <p>代打生图模型 · horizontal_flow · Agent3 确定性图谱同源数据 · 非投资建议</p>
  </div>
  <div class="meta">
    模板：<b>{template}</b>　·　连线：{edge_summary}　·　research_as_of：2026-09-20　·　
    代表主体：{logo_line}<br/>
    数据边界：产品线节点参考宇树官网公开信息；供应链代表企业为<strong>演示捏造</strong>，不作审计清单。
  </div>

  <div class="flow">
    {stage_html[0]}
    {stage_html[1]}
    {stage_html[2]}
  </div>
  <div class="arrows">上游零部件 / 感知算力 → 整机与自研部件 → 场景交付　|　算法与服务纵向支撑</div>
  {support_html}

  <div class="footer">
    <h3>代打生图说明（对齐 Agent3 产业链生图约束）</h3>
    本页为「生图模型代打」输出：只使用图谱内节点/公司名，不补市场份额、产能、营收等未提供数字；
    版式按 horizontal_flow（白底、藏青、卡片+箭头、无实拍）。同数据已通过
    <code>build_industry_chain_option + render_chart_svg</code> 产出确定性 SVG（见旁路文件）。
    <div class="prompt">{prompt_text}</div>
    <a class="btn" href="./unitree-chain-agent3.svg">Agent3 确定性 SVG</a>
    ·
    <a class="btn" href="./unitree-chain-echarts-option.json">ECharts option JSON</a>
    ·
    <a class="btn" href="./unitree-chain-verified-graph.json">verified_chain_graph</a>
  </div>
</div>
</body>
</html>
"""


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dataset = build_dataset()
    print(f"[data] nodes={len(dataset.nodes)} edges={len(dataset.edges)}")

    spec, svg, notices = agent3_render(dataset)
    print(f"[agent3] chart_type={spec.chart_type} notices={notices}")
    (OUT_DIR / "unitree-chain-agent3.svg").write_text(svg, encoding="utf-8")
    (OUT_DIR / "unitree-chain-echarts-option.json").write_text(
        json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    template, graph, prompt_text = surrogate_prompt(dataset)
    print(f"[surrogate] template={template} logos={graph['allowed_logo_names']}")
    (OUT_DIR / "unitree-chain-verified-graph.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "unitree-chain-image-prompt.txt").write_text(prompt_text, encoding="utf-8")

    html = render_surrogate_html(dataset, template, prompt_text, graph)
    index_path = OUT_DIR / "index.html"
    index_path.write_text(html, encoding="utf-8")
    print(f"[out] {index_path}")
    print(f"[out] {OUT_DIR / 'unitree-chain-agent3.svg'}")
    print(f"[done] ok")


if __name__ == "__main__":
    main()
