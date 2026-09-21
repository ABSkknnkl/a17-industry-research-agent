"""实验中转：联网搜索产业链资料 → DeepSeek 生成提示词（对比不联网版）。

用法（backend 目录下）：
    .venv/bin/python scripts/research_chain_prompt_live.py --topic "手机产业链"

复用既有设施：bocha WebSearchClient（AGENT1_WEB_* 凭据）+ OpenAICompatiblePromptCompiler（LLM_*，即项目所用 DeepSeek 系模型）。

⚠ 这是 A/B 对比实验脚本，非生产链路。web 结果标记 web_unverified，仅用于提示词文本。
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend 根目录

from app.integrations.skillhub.models import SkillQueryArgs
from app.schemas.acquisition import SkillName
from app.core.config import Settings
from app.integrations.websearch.client import WebSearchClient
from app.integrations.visuals.openai_compatible import OpenAICompatiblePromptCompiler

RESEARCH_QUERIES = [
    "{topic} 上游 核心零部件 供应链 上市公司 名单",
    "{topic} 品牌 ODM 代工 组装 工厂 合作厂商",
    "{topic} 出货量 市场份额 渠道 销售 2026",
    "{topic} 回收 售后服务 以旧换新 软件生态",
]

SYSTEM_PROMPT = (
    "你是券商研究所的产业链信息图提示词设计师。你的任务：根据提供的「联网检索摘要」与主题，"
    "输出一份可直接投喂给生图模型的中文完整提示词（纯文本，不要 JSON、不要解释、不少于 700 字）。\n\n"
    "硬性要求：\n"
    "1. 结构：上游供给区（核心零部件）→ 中游制造与集成（品牌设计与整机制造）→ 下游产品与渠道（销售场景）→ 底部「配套与循环支撑」通栏。\n"
    "2. 每个卡片：节点名称 + 真实企业名（仅使用检索摘要中出现的或广为人知的真实企业，严禁编造企业或市场份额数字；不确凿的企业宁可留空）。\n"
    "3. 连线逐条列出：藏青实线=产品实物流（零部件供应/整机交付）；灰蓝虚线=服务/委外发包/软件/售后回收类关系。委外代工发包一律用灰蓝虚线。\n"
    "4. 单张卡片接入的连线不要超过 8 条；同方向同类连线合并为一行分组描述（例：上游8类零部件→整机（供给·藏青实线））。\n"
    "5. 售后、以旧换新、回收类节点放在底部「配套与循环支撑」通栏，不放下游销售区。\n"
    "6. 全图为纯2D扁平矢量白底信息图，禁止实拍照片、人物、3D渲染、坐标轴图表、乱码错别字、箭头交叉、大面积空白、金属质感、夸张光效。"
)


def build_runtime_prompt(topic: str, hits: list[dict]) -> str:
    lines = [f"主题：{topic}", "", "联网检索摘要："]
    for i, hit in enumerate(hits, 1):
        title = hit.get("title", "").strip()
        site = hit.get("site_name", "") or hit.get("domain", "")
        snippet = (hit.get("summary") or hit.get("snippet") or "")[:400]
        lines.append(f"[{i}] {title}（{site}）：{snippet}")
    lines.append("\n请依据以上摘要，输出该产业链全景图的完整生图提示词。")
    return "\n".join(lines)


def extract_hits(payload) -> list[dict]:
    """兼容 SkillPayload 与 dict 形态，抽取 title/site/snippet/summary。"""
    raw = payload
    rows = []
    if isinstance(raw, dict):
        rows = raw.get("rows") or raw.get("hits") or []
    else:
        rows = getattr(raw, "rows", None) or []
    result = []
    for row in rows:
        if isinstance(row, dict):
            result.append(row)
        elif hasattr(row, "model_dump"):
            result.append(row.model_dump())
    return result


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="手机产业链")
    parser.add_argument("--queries", type=int, default=4)
    parser.add_argument("--out-root", default="output/industry-chain-images")
    args = parser.parse_args()

    settings = Settings()
    if not settings.AGENT1_WEB_FALLBACK_ENABLED or settings.AGENT1_WEB_PROVIDER != "bocha":
        raise SystemExit("AGENT1_WEB_FALLBACK_ENABLED=false 或 provider 不是 bocha，本实验需要联网")

    api_key = settings.AGENT1_BOCHA_API_KEY.get_secret_value()
    client = WebSearchClient(
        api_key=api_key,
        base_url=settings.AGENT1_WEB_BASE_URL,
        timeout_seconds=settings.AGENT1_WEB_TIMEOUT_SECONDS,
    )
    compiler = OpenAICompatiblePromptCompiler(
        model_name=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY.get_secret_value(),
        base_url=settings.LLM_BASE_URL,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
    )

    queries = [q.format(topic=args.topic) for q in RESEARCH_QUERIES[: args.queries]]
    hits: list[dict] = []
    seen: set[str] = set()
    print("== 检索 ==")
    for q in queries:
        print("Q:", q)
        payload = await client.execute(
            skill_name=SkillName.WEB_SEARCH,
            args=SkillQueryArgs(query=q, limit=8),
        )
        for row in extract_hits(payload):
            key = (row.get("title") or "")[:60]
            url = row.get("url") or ""
            if key and key not in seen:
                seen.add(key)
                row["url"] = url
                hits.append(row)
    print(f"共 {len(hits)} 条去重命中\n")

    runtime = build_runtime_prompt(args.topic, hits)
    print("== DeepSeek 生成提示词中 ==")
    prompt_text = await compiler.compile_prompt(
        system_prompt=SYSTEM_PROMPT,
        runtime_prompt=runtime,
    )

    out_path = f"{args.out_root}/{args.topic}-research.prompt.txt"
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(prompt_text)
    with open(f"{args.out_root}/{args.topic}-research.hits.json", "w", encoding="utf-8") as fh:
        json.dump([{k: h.get(k, "") for k in ("title", "site_name", "url", "summary", "snippet")} for h in hits], fh, ensure_ascii=False, indent=1)

    print(f"提示词已保存：{out_path}")
    print("=" * 60)
    print(prompt_text)


if __name__ == "__main__":
    asyncio.run(main())