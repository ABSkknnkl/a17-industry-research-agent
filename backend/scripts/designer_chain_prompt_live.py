#!/usr/bin/env python3
"""设计师模式：事实锁死 + 设计自由，一版直接产出可投喂生图模型的提示词。

与 `compile_chain_prompt_live.py`（填空器）的区别：
    - 填空器：把图谱填入固定模板，所有卡片/分区/措辞由模板决定。
    - 设计师：图谱当「事实底稿」，布局选型、卡片文案、密度、视觉层次由大模型按设计师身份自由设计。

事实锁死（三不可改）：
    - 节点名、企业名、连线方向与关系文字：逐字原样保留。
    - 线型语义：藏青实线=产品实物流；灰蓝虚线=服务/委外/软件/售后回收。
    - 核心节点视觉强调。

无验收闭环：生成即用。仅保留「确定性存在性检查」（字符串匹配，非大模型审核），
缺项只告警不阻塞，提示词直接可用。

用法（backend 目录下）：
    .venv/bin/python scripts/designer_chain_prompt_live.py --graph ../output/industry-chain-images/huawei.graph.json --slug huawei-designer

需要的环境变量（backend/.env）：LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.core.config import Settings  # noqa: E402
from app.integrations.visuals.openai_compatible import OpenAICompatiblePromptCompiler  # noqa: E402

DEFAULT_DIR = ROOT / "output" / "industry-chain-images"

SOLID = "藏青实线（产品实物流）"
DASHED = "灰蓝虚线（服务/委外/软件/售后回收）"

LINE_STYLE = {
    "supply": SOLID,
    "application": SOLID,
    "outsourcing": DASHED,
    "software": DASHED,
    "recycle": DASHED,
    "service": DASHED,
    "feedback": DASHED,
}

SYSTEM_PROMPT = (
    "你是资深信息图设计师，专做券商行业深度报告的产业链全景图。"
    "你的唯一产出是一份可直接投喂给生图模型的完整中文提示词（纯文本，不要 JSON、不要解释、不少于 900 字）。\n\n"
    "你会收到一份「事实底稿」，其中节点、企业、连线三点是事实，必须全部保留、逐字照抄，不得增删改：\n\n"
    "一、事实锁死（必须保留）\n"
    "1. 每个节点名、每个企业名必须原样出现在提示词里，一个都不能少，企业名与其节点必须同卡。\n"
    "2. 每条连线的方向（source→target）与关系文字必须原样保留，方向不得反向、连线不得省略或合并。\n"
    "3. 线型语义固定：藏青实线=产品实物流（供给/整机交付/产品销售）；灰蓝虚线=服务/委外发包/软件/售后回收类关系。\n"
    "4. 核心节点必须视觉强调（深藏青强调框/更大面积/居中锚点），公司名或Logo位于该节点底部。\n\n"
    "二、设计自由（由你决定）\n"
    "1. 布局选型：横向分区、核心居中放射、环形、瀑布流等，按节点数与关系自选最合适的，并在提示词中描述清楚每个区域的位置关系。\n"
    "2. 每张卡片写满三行：第一行节点名，第二行企业或细分项，第三行一句「这个环节提供什么、支撑什么」的说明，不要复读连线关系文字。\n"
    "3. 信息密度：全图铺满网格，留白不超过 12%，单张卡片接入连线不超过 8 条，同方向同类连线合并为一行分组描述。\n"
    "4. 视觉层次：核心产品/核心节点最突出，其余逐级弱化；可用分区底色块区分上中下游与支撑区，但不得与线型语义冲突。\n\n"
    "三、禁止出现\n"
    "虚构企业、虚构数字（份额/产能/营收/价格/型号串）、改动节点名或企业名、改变连线方向、省略或合并连线、"
    "占位符（XX/示例/…）、箭头交叉或穿过卡片、实拍照片/人物/3D渲染/坐标轴/图表、金属质感/发光光晕/复杂渐变/厚重投影、"
    "错别字、反向箭头记号。\n\n"
    "四、输出格式\n"
    "纯文本完整提示词，依次包含【标题】【副标题】【版式】【配色】【节点与分区】（逐卡列出节点名+企业名+第三行说明）"
    "【连接关系】（逐条列出，注明线型）【负面约束】。全图 16:9、白底、纯 2D 扁平矢量信息图。"
)


def line_style(flow_type: str) -> str:
    return LINE_STYLE.get(flow_type, DASHED)


def build_fact_sheet(graph: dict) -> str:
    lines = [f"主题：{graph.get('title', '')}"]
    if graph.get("subtitle"):
        lines.append(f"副标题：{graph['subtitle']}")
    if graph.get("core_product_name"):
        lines.append(f"核心产品：{graph['core_product_name']}")
    lines.append("\n【节点清单】")
    for n in graph.get("nodes", []):
        core = "（核心节点）" if n.get("is_core") else ""
        companies = "、".join(n.get("companies") or [])
        lines.append(f"- {n.get('label')}{core} | 企业：{companies} | 阶段：{n.get('stage')}")
    lines.append("\n【连线清单】")
    for e in graph.get("edges", []):
        src = next((n["label"] for n in graph["nodes"] if n["node_id"] == e["source"]), e["source"])
        tgt = next((n["label"] for n in graph["nodes"] if n["node_id"] == e["target"]), e["target"])
        lines.append(f"- {e.get('label')} | {src} → {tgt} | {line_style(e.get('flow_type'))}")
    allow = graph.get("allowed_company_names") or []
    if allow:
        lines.append("\n【企业白名单】" + "、".join(allow))
    lines.append("\n请作为设计师，依据以上事实底稿输出完整生图提示词。")
    return "\n".join(lines)


def check_facts(prompt: str, graph: dict) -> list[str]:
    """确定性存在性检查（字符串匹配，非大模型审核）。"""
    missing: list[str] = []
    labels = {n.get("label") for n in graph.get("nodes", [])}
    for lbl in sorted(labels):
        if lbl and lbl not in prompt:
            missing.append(f"节点「{lbl}」")
    allow = graph.get("allowed_company_names") or []
    for name in allow:
        if name and name not in prompt:
            missing.append(f"企业「{name}」")
    for e in graph.get("edges", []):
        if e.get("label") and e["label"] not in prompt:
            missing.append(f"连线「{e.get('label')}」")
    return missing


async def run(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else DEFAULT_DIR / f"{args.slug}.graph.json"
    if not graph_path.is_file():
        raise SystemExit(f"图谱文件不存在：{graph_path}")
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    slug = args.slug or graph_path.stem

    settings = Settings()
    compiler = OpenAICompatiblePromptCompiler(
        model_name=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY.get_secret_value(),
        base_url=settings.LLM_BASE_URL,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
    )

    fact_sheet = build_fact_sheet(graph)
    prompt = await compiler.compile_prompt(system_prompt=SYSTEM_PROMPT, runtime_prompt=fact_sheet)

    missing = check_facts(prompt, graph)
    if missing:
        print(f"⚠ 确定性检查：{len(missing)} 项未逐字出现（仅告警，不阻塞）：{missing[:8]}")

    out_path = Path(args.out_root) / f"{slug}.designer.prompt.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(prompt, encoding="utf-8")
    print(f"✓ 设计师提示词 ← {compiler.model_name}（{len(prompt)} 字）")
    print(f"  {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="设计师模式：事实锁死 + 设计自由，一版出提示词")
    parser.add_argument("--slug", default="", help="图谱 slug，读 <slug>.graph.json")
    parser.add_argument("--graph", default="", help="直接指定 graph.json 路径")
    parser.add_argument("--out-root", default=str(DEFAULT_DIR), help="输出目录")
    args = parser.parse_args()
    if not args.slug and not args.graph:
        parser.error("至少要给 --slug 或 --graph")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
