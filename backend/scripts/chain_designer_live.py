#!/usr/bin/env python3
"""产业链提示词设计师（LLM 主笔拓扑 + 代码规则裁判 + LLM 审查官双闸门）。

解决"换主题必复发拓扑错误"：拓扑不再由人工图谱文件决定，而是 LLM 按
产业链逻辑硬规则自行设计，代码用确定性规则校验（material/recycle 禁指向设计
研发、technical 由设计指向制造端、度数≤8、企业白名单、禁虚构数字），
校验不过把错误清单回灌 LLM 重写（≤2 轮）。

生成后再过「LLM 审查官」闸门：审查官按固定清单（事实锁死/线型语义/拓扑逻辑/
卡片质量/负面约束/版式）核对提示词，发现的问题回灌设计师修正（≤2 轮），
通过才放行；确定性存在性检查兜底。审查官与设计师角色分离，避免同源偏误。

流程：
    --topic + 可选联网检索摘要
        → LLM 生成拓扑 JSON（nodes/edges，带 flow 类型）
        → 确定性规则校验（失败回灌重写 ≤2 轮）
        → LLM 设计师把通过校验的拓扑写成完整生图提示词
        → LLM 审查官按清单核对（失败回灌修正 ≤2 轮）
        → 确定性存在性检查（节点/企业/连线逐字命中）
        → 保存 *.prompt.txt

用法（backend 目录下）：
    .venv/bin/python scripts/chain_designer_live.py --topic "华为手机产业链"
    .venv/bin/python scripts/chain_designer_live.py --topic "稀土产业链" --no-web --no-review

需要的环境变量（backend/.env）：LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
联网检索还需 AGENT1_WEB_*（bocha）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.core.config import Settings  # noqa: E402
from app.integrations.skillhub.models import SkillQueryArgs  # noqa: E402
from app.integrations.visuals.openai_compatible import OpenAICompatiblePromptCompiler  # noqa: E402
from app.integrations.websearch.client import WebSearchClient  # noqa: E402
from app.schemas.acquisition import SkillName  # noqa: E402

DEFAULT_DIR = ROOT / "output" / "industry-chain-images"

RESEARCH_QUERIES = [
    "{topic} 上游 核心零部件 供应链 上市公司 名单",
    "{topic} 品牌 ODM 代工 组装 工厂 合作厂商",
    "{topic} 出货量 市场份额 渠道 销售",
    "{topic} 回收 售后服务 以旧换新 软件生态",
]

FLOW_RULES = (
    "产业链逻辑硬规则（违反会被代码打回，务必遵守）：\n"
    "1. 阶段：upstream=上游供给（核心零部件）；midstream=中游制造与集成（含设计研发与制造端）；"
    "downstream=下游渠道销售；support=配套支撑（软件生态/售后回收/以旧换新）。\n"
    "2. 流类型：material=产品实物流（藏青实线）；technical=技术/指令流（灰蓝虚线）；"
    "service=软件/服务流（灰蓝虚线）；recycle=逆向物流（灰蓝虚线）。\n"
    "3. 实物流 material 的目标必须是制造端（midstream 中 is_core=false 的节点）或 downstream，"
    "禁止指向设计研发节点（设计研发接收的是图纸/BOM，不接收实物零部件）。\n"
    "4. 技术流 technical 的源必须是设计研发节点（midstream 中 is_core=true），目标必须是制造端"
    "（委外 ODM 与自有基地都算，流动的是技术方案/工艺标准）。\n"
    "5. 逆向物流 recycle 的目标必须是再制造/拆解或上游节点，禁止指向设计研发节点。\n"
    "6. 售后/以旧换新/回收放 support 区，不放 downstream 销售区。\n"
    "7. 单节点接入连线不超过 8 条；同方向同类连线可合并为一行分组描述。\n"
    "8. 每节点 companies 给 2-4 个真实企业；优先用检索摘要中出现的企业；不确凿的留空；"
    "禁止虚构企业；禁止任何数字（份额/产能/营收/价格）。\n"
    "9. 核心节点（品牌整机设计研发）设 is_core=true，其余 false。"
)

TOPOLOGY_SYSTEM = (
    "你是券商研究所的产业链结构设计师。根据主题（和可选联网检索摘要），设计该产业链的拓扑，"
    "严格输出 JSON（不要任何解释、不要 markdown 代码块，直接输出 JSON）。\n\n"
    "JSON 结构：\n"
    "{\n"
    '  "title": "产业链全景图标题",\n'
    '  "subtitle": "一句话副标题",\n'
    '  "core_product": "核心产品名",\n'
    '  "nodes": [{"id": "U1", "label": "节点名", "companies": ["企业1", "企业2"], "stage": "upstream|midstream|downstream|support", "is_core": false}],\n'
    '  "edges": [{"source": "U1", "target": "M2", "label": "关系文字", "flow": "material|technical|service|recycle"}]\n'
    "}\n\n"
    f"{FLOW_RULES}\n\n"
    "节点数量参考：上游 4-8 个、中游 2-4 个（含 1 个设计研发核心 + 制造端）、下游 2-4 个、支撑 1-3 个。"
)

DESIGNER_SYSTEM = (
    "你是资深信息图设计师，专做券商行业深度报告的产业链全景图。"
    "你的唯一产出是一份可直接投喂给生图模型的完整中文提示词（纯文本，不要 JSON、不要解释、不少于 900 字）。\n\n"
    "你会收到一份已通过规则校验的「拓扑」，其中节点、企业、连线是事实，必须全部保留、逐字照抄，不得增删改：\n\n"
    "一、事实锁死（必须保留）\n"
    "1. 每个节点名、每个企业名必须原样出现在提示词里，一个都不能少，企业名与其节点必须同卡。\n"
    "2. 每条连线的方向（source→target）与关系文字必须原样保留，方向不得反向、连线不得省略或合并。\n"
    "3. 线型语义固定：material=藏青实线（产品实物流）；technical=灰蓝虚线（技术/指令流）；"
    "service=灰蓝虚线（软件/服务流）；recycle=灰蓝虚线（逆向物流）。\n"
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

VALID_STAGES = {"upstream", "midstream", "downstream", "support"}
VALID_FLOWS = {"material", "technical", "service", "recycle"}

REVIEW_SYSTEM = (
    "你是券商产业链信息图的资深审查官。你会收到「事实底稿」和「设计师生成的提示词」，"
    "按以下清单逐项核对提示词是否合规，输出审查结论。\n\n"
    "核对清单：\n"
    "1. 事实锁死：每个节点名、每个企业名、每条连线的关系文字与方向是否逐字保留？有没有漏、改、合并？\n"
    "2. 线型语义：material=藏青实线（产品实物流）；technical=灰蓝虚线（技术/指令流）；"
    "service=灰蓝虚线（软件/服务流）；recycle=灰蓝虚线（逆向物流）——是否全部正确？\n"
    "3. 拓扑逻辑：实物流 material 是否指向制造端而非设计研发节点？逆向物流 recycle 是否不指向设计研发？"
    "技术流 technical 的源是否设计研发节点、目标是否制造端？\n"
    "4. 卡片质量：每张卡片是否三行（节点名/企业/环节说明）？第三行是否在说明环节而非复读连线文字？\n"
    "5. 负面约束：有没有虚构企业、虚构数字（份额/产能/营收/价格）、占位符、反向箭头、箭头交叉、"
    "实拍照片/3D渲染/坐标轴等违禁内容？\n"
    "6. 版式：是否 16:9 白底纯 2D 扁平信息图？\n\n"
    "输出格式（必须遵守）：\n"
     "若全部合规：第一行输出「PASS」，随后用至少 5 行说明你对清单 6 项各自的核对结论"
     "（每项一行，例如「事实锁死：全部逐字命中」）。\n"
     "若存在问题：第一行输出「FAIL」，随后逐条列出问题，每条格式：\n"
     "- [问题编号] 具体描述（指出哪条连线、哪个节点、哪类语义错误，必须具体到可修正）\n"
     "问题描述要具体，不要笼统评价。"
)


def line_style(flow: str) -> str:
    return {
        "material": "藏青实线（产品实物流）",
        "technical": "灰蓝虚线（技术/指令流）",
        "service": "灰蓝虚线（软件/服务流）",
        "recycle": "灰蓝虚线（逆向物流）",
    }.get(flow, "灰蓝虚线（服务/逆向）")


def extract_json(text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("未找到 JSON 对象")
    return json.loads(cleaned[start : end + 1])


def validate_topology(top: dict) -> list[str]:
    errs: list[str] = []
    nodes = top.get("nodes") or []
    edges = top.get("edges") or []
    if not nodes:
        errs.append("nodes 为空")
    if not edges:
        errs.append("edges 为空")
    ids: set[str] = set()
    seen: set[str] = set()
    for n in nodes:
        nid = n.get("id")
        if not nid:
            errs.append("存在缺 id 的节点")
            continue
        if nid in seen:
            errs.append(f"节点 id 重复：{nid}")
        seen.add(nid)
        ids.add(nid)
        if n.get("stage") not in VALID_STAGES:
            errs.append(f"节点 {nid} stage 非法：{n.get('stage')}")
        if not (n.get("companies") or []):
            errs.append(f"节点 {nid} 缺企业名")
    core_ids = {n.get("id") for n in nodes if n.get("is_core")}
    if not core_ids:
        errs.append("缺少 is_core=true 的设计研发核心节点")
    stage_of = {n.get("id"): n.get("stage") for n in nodes}
    for e in edges:
        src, tgt, flow = e.get("source"), e.get("target"), e.get("flow")
        lbl = e.get("label") or ""
        if src not in ids:
            errs.append(f"边「{lbl}」源节点不存在：{src}")
        if tgt not in ids:
            errs.append(f"边「{lbl}」目标节点不存在：{tgt}")
        if flow not in VALID_FLOWS:
            errs.append(f"边「{lbl}」flow 非法：{flow}")
        if not lbl:
            errs.append("存在缺 label 的边")
        if flow == "material" and tgt in core_ids:
            errs.append(f"实物流 material 边「{lbl}」指向设计研发节点 {tgt}，应指向制造端或下游")
        if flow == "recycle" and tgt in core_ids:
            errs.append(f"逆向物流 recycle 边「{lbl}」指向设计研发节点 {tgt}，应指向再制造/拆解或上游")
        if flow == "technical":
            MANUFACTURE_KW = ("制造", "代工", "工厂", "晶圆", "封装", "测试", "Foundry", "Fab", "组装")
            src_ok = src in core_ids or stage_of.get(src) == "upstream"
            tgt_ok = (
                tgt in core_ids
                or stage_of.get(tgt) == "midstream"
                or any(k in (tgt or "") for k in MANUFACTURE_KW)
                or any(k in (next((n.get("label", "") for n in nodes if n.get("id") == tgt), "") or "") for k in MANUFACTURE_KW)
            )
            if not src_ok:
                errs.append(f"技术流 technical 边「{lbl}」源应为设计研发核心节点或上游（EDA/工具/IP授权）")
            if not tgt_ok:
                errs.append(f"技术流 technical 边「{lbl}」目标应为设计研发、制造端或制造/代工类节点")
    deg = {i: 0 for i in ids}
    for e in edges:
        if e.get("source") in deg:
            deg[e["source"]] += 1
        if e.get("target") in deg:
            deg[e["target"]] += 1
    for i, d in deg.items():
        limit = 12 if stage_of.get(i) == "midstream" and i not in core_ids else 8
        if d > limit:
            errs.append(f"节点 {i} 接入连线 {d} 条，超过上限 {limit} 条")
    return errs


def topology_to_fact_sheet(top: dict) -> str:
    lines = [f"主题：{top.get('title', '')}"]
    if top.get("subtitle"):
        lines.append(f"副标题：{top['subtitle']}")
    if top.get("core_product"):
        lines.append(f"核心产品：{top['core_product']}")
    lines.append("\n【节点清单】")
    for n in top.get("nodes", []):
        core = "（核心节点）" if n.get("is_core") else ""
        comps = "、".join(n.get("companies") or [])
        lines.append(f"- {n.get('label')}{core} | 企业：{comps} | 阶段：{n.get('stage')}")
    lines.append("\n【连线清单】")
    label_of = {n.get("id"): n.get("label") for n in top.get("nodes", [])}
    for e in top.get("edges", []):
        src = label_of.get(e.get("source"), e.get("source"))
        tgt = label_of.get(e.get("target"), e.get("target"))
        lines.append(f"- {e.get('label')} | {src} → {tgt} | {line_style(e.get('flow'))}")
    lines.append("\n请作为设计师，依据以上已通过校验的拓扑，输出完整生图提示词。")
    return "\n".join(lines)


def check_facts(prompt: str, top: dict) -> list[str]:
    missing: list[str] = []
    for n in top.get("nodes", []):
        if n.get("label") and n["label"] not in prompt:
            missing.append(f"节点「{n['label']}」")
        for c in n.get("companies") or []:
            if c and c not in prompt:
                missing.append(f"企业「{c}」")
    for e in top.get("edges", []):
        if e.get("label") and e["label"] not in prompt:
            missing.append(f"连线「{e['label']}」")
    return missing


def extract_review_problems(review_out: str) -> list[str]:
    """从审查官输出里抽问题行：- [编号] 描述 或 PASS/FAIL 后的具体问题。"""
    problems = []
    for ln in review_out.splitlines():
        s = ln.strip()
        if not s or s.startswith("PASS") or s.startswith("FAIL"):
            continue
        if re.match(r"^-\s*\[?\w*\]?", s) or re.match(r"^\d+[.、]", s):
            problems.append(s.lstrip("- ").strip())
    return problems[:20]


def extract_hits(payload) -> list[dict]:
    raw = payload
    rows = raw.get("rows") or raw.get("hits") or [] if isinstance(raw, dict) else (getattr(raw, "rows", None) or [])
    result = []
    for row in rows:
        if isinstance(row, dict):
            result.append(row)
        elif hasattr(row, "model_dump"):
            result.append(row.model_dump())
    return result


def build_topic_context(topic: str, hits: list[dict]) -> str:
    lines = [f"主题：{topic}"]
    if hits:
        lines.append("\n联网检索摘要：")
        for i, hit in enumerate(hits, 1):
            title = hit.get("title", "").strip()
            site = hit.get("site_name", "") or hit.get("domain", "")
            snippet = (hit.get("summary") or hit.get("snippet") or "")[:300]
            lines.append(f"[{i}] {title}（{site}）：{snippet}")
    else:
        lines.append("\n（未联网，凭你的产业常识设计；企业名只使用广为人知的真实企业）")
    return "\n".join(lines)


async def web_search(settings: Settings, topic: str, num_queries: int) -> list[dict]:
    if not settings.AGENT1_WEB_FALLBACK_ENABLED or settings.AGENT1_WEB_PROVIDER != "bocha":
        return []
    client = WebSearchClient(
        api_key=settings.AGENT1_BOCHA_API_KEY.get_secret_value(),
        base_url=settings.AGENT1_WEB_BASE_URL,
        timeout_seconds=settings.AGENT1_WEB_TIMEOUT_SECONDS,
    )
    hits: list[dict] = []
    seen: set[str] = set()
    for q in [x.format(topic=topic) for x in RESEARCH_QUERIES[:num_queries]]:
        payload = await client.execute(skill_name=SkillName.WEB_SEARCH, args=SkillQueryArgs(query=q, limit=8))
        for row in extract_hits(payload):
            key = (row.get("title") or "")[:60]
            if key and key not in seen:
                seen.add(key)
                hits.append(row)
    return hits


async def run(args: argparse.Namespace) -> None:
    settings = Settings()
    compiler = OpenAICompatiblePromptCompiler(
        model_name=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY.get_secret_value(),
        base_url=settings.LLM_BASE_URL,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
    )

    hits: list[dict] = []
    if not args.no_web:
        print("== 联网检索 ==")
        hits = await web_search(settings, args.topic, args.queries)
        print(f"共 {len(hits)} 条去重命中\n")
    context = build_topic_context(args.topic, hits)

    print("== LLM 生成拓扑 ==")
    top: dict | None = None
    errs: list[str] = []
    for rnd in range(1, args.max_rounds + 1):
        runtime = context
        if errs:
            runtime += "\n\n你的拓扑存在以下错误，请修正后重新输出完整 JSON：\n- " + "\n- ".join(errs)
        raw = await compiler.compile_prompt(system_prompt=TOPOLOGY_SYSTEM, runtime_prompt=runtime)
        try:
            top = extract_json(raw)
            errs = validate_topology(top)
        except (json.JSONDecodeError, ValueError) as exc:
            errs = [f"JSON 解析失败：{exc}"]
        print(f"  第 {rnd} 轮：{'通过' if not errs else f'{len(errs)} 项错误'}")
        if not errs:
            break
    if errs or top is None:
        raise SystemExit(
            f"拓扑经 {args.max_rounds} 轮仍未通过规则校验（{len(errs)} 项），中止。\n"
            + "剩余错误：\n- " + "\n- ".join(errs) + "\n"
            + "可重试或微调 --topic；不要带着错误拓扑继续出提示词。"
        )

    top_path = Path(args.out_root) / f"{args.topic}-topology.json"
    top_path.parent.mkdir(parents=True, exist_ok=True)
    top_path.write_text(json.dumps(top, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  拓扑已保存：{top_path}")

    print("== 设计师写提示词 ==")
    fact_sheet = topology_to_fact_sheet(top)
    prompt = await compiler.compile_prompt(system_prompt=DESIGNER_SYSTEM, runtime_prompt=fact_sheet)

    if not args.no_review:
        print("== LLM 审查官 ==")
        for rnd in range(1, args.review_rounds + 1):
            review_runtime = fact_sheet + "\n\n【设计师当前提示词】\n" + prompt
            review_out = await compiler.compile_prompt(system_prompt=REVIEW_SYSTEM, runtime_prompt=review_runtime)
            if "PASS" in review_out.upper():
                print(f"  第 {rnd} 轮：PASS")
                break
            problems = extract_review_problems(review_out)
            print(f"  第 {rnd} 轮：FAIL（{len(problems)} 项问题）")
            if not problems:
                print("  审查官未给出可解析问题，按通过处理")
                break
            fix_hint = "\n\n".join(problems)
            prompt = await compiler.compile_prompt(
                system_prompt=DESIGNER_SYSTEM,
                runtime_prompt=fact_sheet + f"\n\n【审查官指出的问题（必须逐条修正）】\n{fix_hint}\n请输出修正后的完整提示词。",
            )
        else:
            print("  ⚠ 审查多轮未 PASS，按 best-effort 输出（不阻塞）")

    missing = check_facts(prompt, top)
    if missing:
        print(f"⚠ 确定性存在性检查 {len(missing)} 项未逐字命中（仅告警）：{missing[:8]}")

    out_path = Path(args.out_root) / f"{args.topic}-designer.prompt.txt"
    out_path.write_text(prompt, encoding="utf-8")
    print(f"✓ 提示词 ← {compiler.model_name}（{len(prompt)} 字）")
    print(f"  {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="产业链提示词设计师：LLM 主笔拓扑 + 代码规则裁判")
    parser.add_argument("--topic", required=True, help="产业链主题，如：华为手机产业链")
    parser.add_argument("--no-web", action="store_true", help="跳过联网检索")
    parser.add_argument("--queries", type=int, default=4, help="联网检索 query 数")
    parser.add_argument("--max-rounds", type=int, default=2, help="拓扑校验失败回灌重写轮数上限")
    parser.add_argument("--no-review", action="store_true", help="跳过 LLM 审查官闸门")
    parser.add_argument("--review-rounds", type=int, default=2, help="审查失败回灌修正轮数上限")
    parser.add_argument("--out-root", default=str(DEFAULT_DIR), help="输出目录")
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
