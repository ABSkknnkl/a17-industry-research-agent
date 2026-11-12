"""智能体3 · LLM 选图调用（真实 API，配置沿用项目 .env）。

职责边界
--------
* 本脚本只做「选图」：由 A3 的大模型决定**图表清单及具体数量**。
* 候选图卡由 A1/A2 证据确定性生成，模型只做语义匹配与数量决策。
* 模型只返回 chart_id 列表与理由；不返回数值、evidence_id、ECharts option。
* 输出落盘 llm_selection_result.json，供下一阶段逐张生成严格消费。

输入：A1 dataset.json、A2 interpretation_report.json、chart_plan.json（候选卡池）
输出：llm_selection_result.json（含原始响应、模型、耗时、校验结果与最终清单）
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent
APP = WORKSPACE / "a17-industry-research-agent"
ENV_PATH = APP / ".env"
DATASET_PATH = (
    APP / "output/a1_five_industry_probe/新能源汽车/runs/"
    "run-20261110013520-220857d7/dataset.json"
)
REPORT_PATH = (
    APP / "output/a2_industry_review/runs/a2-review-220857d7/artifacts/"
    "interpretation_report.json"
)
PLAN_PATH = ROOT / "chart_plan.json"
OUT_PATH = ROOT / "llm_selection_result.json"

VALID_CHART_TYPES = {
    "line", "bar", "comparison_bar", "horizontal_bar", "diverging_bar", "pie", "donut",
    "radar", "industry_chain", "combo", "area", "scatter", "bubble", "heatmap",
    "boxplot", "treemap",
}


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def build_upstream_brief() -> dict:
    """从 A1/A2 真实产物确定性抽取上游事实摘要（不含单条原始数值）。"""
    d1 = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    d2 = json.loads(REPORT_PATH.read_text(encoding="utf-8"))

    availability = {}
    for dom in ("industry", "financials", "macro", "industry_chain"):
        rows = d1.get(dom, [])
        metrics: dict[str, dict] = {}
        for r in rows:
            m = str(r.get("metric") or "")
            if not m:
                continue
            slot = metrics.setdefault(m, {"count": 0, "periods": set(), "entities": set()})
            slot["count"] += 1
            if r.get("period_end"):
                slot["periods"].add(str(r["period_end"])[:4])
            if r.get("entity_name"):
                slot["entities"].add(str(r["entity_name"]))
        availability[dom] = {
            "records": len(rows),
            "metrics": {
                m: {
                    "count": s["count"],
                    "years": sorted(s["periods"]),
                    "entity_count": len(s["entities"]),
                }
                for m, s in sorted(metrics.items())
            },
        }

    insights = []
    for x in d2.get("insights", []):
        if isinstance(x, dict):
            insights.append({
                "id": x.get("id") or x.get("insight_id"),
                "statement": str(x.get("statement") or x.get("text") or x.get("title") or "")[:180],
            })

    facts = {
        "subject": d1.get("subject") or d2.get("subject"),
        "a1_research_as_of": d1.get("research_as_of"),
        "a1_availability": availability,
        "a1_conflicts": len(d1.get("conflicts", [])),
        "a2_insights": insights,
        "a2_warnings": [str(w)[:200] for w in d2.get("warnings", [])],
        "a2_evidence_index_count": len(d2.get("evidence_index", {})),
        "a2_chapter_outline": [
            {"heading": c.get("heading"), "purpose": str(c.get("purpose") or "")[:140]}
            for c in d2.get("content_outline", [])
            if isinstance(c, dict)
        ],
    }
    return facts


def build_candidate_cards() -> list[dict]:
    """候选图卡：只发元数据，不发数值、不发证据 ID 全文（方案 5.6）。"""
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    cards = []
    for s in plan["charts"]:
        b = s.get("data_binding", {})
        cards.append({
            "chart_id": s["chart_id"],
            "chart_type": s["chart_type"],
            "title": s["title"],
            "insight_goal": s["insight_goal"],
            "chapter": s.get("recommended_chapter_id"),
            "domain": b.get("domain"),
            "metrics": b.get("metrics"),
            "periods": b.get("periods"),
            "unit": b.get("unit"),
            "evidence_count": len(s.get("evidence_ids", [])),
            "footnote_count": len(s.get("footnotes", [])),
        })
    return cards


SYSTEM_PROMPT = """你是研报流水线中的智能体3（ChartGeneratorAgent）选型大模型。
本轮你的唯一职责是「选图」：结合上游 A1 取数结果与 A2 分析结论，从给定的候选图卡中，
自主决定**本轮要生成哪些图表、以及一共生成几张**。数量必须由你独立判断，禁止为了凑数全选。

【硬约束】
1. 只能从候选卡中选择，禁止发明新图型、新 chart_id，禁止修改 chart_type / title / 数据绑定。
2. 严禁输出任何数值、派生值、evidence_id、ECharts option 或任何配置字典。
3. 每张候选卡最多选一次，选中顺序由你按研报叙事逻辑决定。
4. 事实依据（Grounding）：只选上游 A1 有充分证据支撑、且 A2 结论确实需要的图。
   - A2 已明确认定的质量问题（估值结论越界、研发费用率缺指标、渗透率仅 2025 单年、
     产业链 200 条为行情/概念不构成环节归属、2026 前三季度与 2025 全年不得混期）必须尊重。
   - 若某张卡的证据不足或表达越界，不要选它，并写入 suppressed 说明原因。
5. 图表多样性：避免整批只保留柱类图；趋势、构成、分布、多维对比等形态尽量兼顾。
6. 章节分布：选中图不要全堆在同一章；覆盖 CH-01~CH-06 为宜。
7. 宏观域配额：候选池中 macro 域图至多 1 张。
8. 数量完全由你决定：请给出你认为「证据支撑得住、且研报确实需要」的张数，
   不设下限也不设上限（不得超过候选卡总数）。

【输出格式】只输出一个 JSON 对象，不要输出任何解释文字或 Markdown 代码块：
{
  "chart_count": <整数，必须严格等于 charts 数组长度>,
  "rationale": "<一句话说明为什么定这个张数>",
  "charts": [
    {"chart_id": "Cxx", "chart_type": "<必须与候选卡一致>", "reason": "<为什么需要这张图>"}
  ],
  "suppressed": [
    {"chart_id": "Cxx", "reason_code": "insufficient_evidence|out_of_scope|macro_quota_exceeded|redundant|other",
     "reason": "<为什么抑制>"}
  ]
}
选中项与抑制项的 chart_id 合起来必须恰好覆盖全部候选卡，且不重复。
"""


def user_prompt(facts: dict, cards: list[dict]) -> str:
    return (
        "请基于以下上游产物完成本轮选图。\n\n"
        "=== A1 取数结果 / A2 分析结论（事实摘要） ===\n"
        + json.dumps(facts, ensure_ascii=False, indent=2)
        + "\n\n=== 候选图卡（系统按证据确定性生成，共 "
        + str(len(cards)) + " 张；只含元数据） ===\n"
        + json.dumps(cards, ensure_ascii=False, indent=2)
        + "\n\n请自主决定本轮图表清单与具体数量，严格按上述 JSON 格式输出。"
    )


def strip_think(text: str) -> dict:
    t = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.IGNORECASE).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            return json.loads(t[start : end + 1])
        raise


def validate(result: dict, cards: list[dict]) -> list[str]:
    errors: list[str] = []
    by_id = {c["chart_id"]: c for c in cards}
    charts = result.get("charts")
    suppressed = result.get("suppressed")
    count = result.get("chart_count")
    if not isinstance(charts, list) or not isinstance(suppressed, list):
        return ["charts / suppressed 必须是数组"]
    if not isinstance(count, int) or count != len(charts):
        errors.append(f"chart_count={count!r} 与 charts 长度 {len(charts)} 不一致")
    seen = []
    for c in charts:
        cid = c.get("chart_id")
        seen.append(cid)
        if cid not in by_id:
            errors.append(f"未知名候选卡 {cid!r}")
        elif c.get("chart_type") != by_id[cid]["chart_type"]:
            errors.append(f"{cid} chart_type 与候选卡不一致")
        elif c.get("chart_type") not in VALID_CHART_TYPES:
            errors.append(f"{cid} 图型不在白名单")
    if len(seen) != len(set(seen)):
        errors.append("选中项存在重复 chart_id")
    all_ids = seen + [s.get("chart_id") for s in suppressed]
    if len(all_ids) != len(set(all_ids)):
        errors.append("选中项与抑制项存在重复 chart_id")
    if set(all_ids) != set(by_id):
        errors.append(f"选中+抑制未覆盖全部候选卡: {sorted(set(by_id) - set(all_ids))}")
    macro_selected = [c["chart_id"] for c in charts if by_id.get(c["chart_id"], {}).get("domain") == "macro"]
    if len(macro_selected) > 1:
        errors.append(f"macro 域超出 1 张配额: {macro_selected}")
    return errors


def main() -> None:
    env = load_env()
    key, base, model = env.get("LLM_API_KEY"), env.get("LLM_BASE_URL"), env.get("LLM_MODEL")
    if not (key and base and model):
        raise RuntimeError("A3 模型配置缺失：LLM_API_KEY / LLM_BASE_URL / LLM_MODEL")

    facts = build_upstream_brief()
    cards = build_candidate_cards()
    up = user_prompt(facts, cards)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": up},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
    }
    if env.get("LLM_REASONING_EFFORT"):
        payload["reasoning_effort"] = env["LLM_REASONING_EFFORT"]

    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"A3 选图 LLM 调用失败 HTTP {e.code}: {e.read().decode()[:500]}") from e
    elapsed = round(time.time() - started, 2)

    raw = body["choices"][0]["message"]["content"] or ""
    parsed = strip_think(raw)
    errors = validate(parsed, cards)

    record = {
        "stage": "A3_LLM_SELECTION",
        "model": model,
        "base_url": base,
        "elapsed_seconds": elapsed,
        "prompt_sha256": hashlib.sha256((SYSTEM_PROMPT + up).encode("utf-8")).hexdigest()[:16],
        "candidate_card_count": len(cards),
        "usage": body.get("usage"),
        "validation_errors": errors,
        "selection": parsed,
        "raw_response": raw,
    }
    OUT_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[A3 选图] model={model} elapsed={elapsed}s candidates={len(cards)}")
    print(f"[A3 选图] LLM 决定 chart_count={parsed.get('chart_count')} / 实际选中={len(parsed.get('charts', []))}")
    print(f"[A3 选图] rationale={parsed.get('rationale')}")
    for i, c in enumerate(parsed.get("charts", []), 1):
        print(f"  {i:02d}. {c.get('chart_id')} {c.get('chart_type')}")
    print(f"[A3 选图] 抑制 {len(parsed.get('suppressed', []))} 张: "
          + ", ".join(str(s.get("chart_id")) for s in parsed.get("suppressed", [])))
    print(f"[A3 选图] 校验错误: {errors or '无'}")
    if errors:
        raise RuntimeError(f"选图结果校验未通过: {errors}")


if __name__ == "__main__":
    main()
