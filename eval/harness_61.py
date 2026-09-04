"""61 条金融问句 L1 确定性层压测台（2026-09-01 方案 §4 复现工具）。

约束：不使用任何真实大模型。本脚本只跑 Agent 1 的确定性层
（build_intent_plan, decomposer=None）；L2 语义层由人工扮演另行验证。
遥测写临时目录，不污染生产日志。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from pathlib import Path

os.environ["ROUTING_TELEMETRY_DIR"] = tempfile.mkdtemp(prefix="agent1_61_")

from app.agents.data_fetcher.intent_merger import build_intent_plan  # noqa: E402
from app.agents.data_fetcher.deterministic_intent_parser import parse_intent  # noqa: E402

CAT = "动力电池行业"
ESS = "储能行业"
PV = "光伏组件行业"

# (id, group, topic, known_entities, text, expect)
# expect kinds:
#   route     —— 应锁定指定技能并可执行
#   derivative —— 禁用词表场景：forbidden 技能不得被锁定（静默误判一票否决）
#   gap       —— 真数据缺口：不得硬路由，应澄清/披露
#   judgment  —— 判断题：不得静默取数
#   ambiguous —— 歧义：不得强行硬选单一解释
CASES: list[tuple[str, str, str, list[str], str, dict]] = [
    ("1.1", "公司", CAT, ["宁德时代"], "宁德时代电池出货量是多少", {"kind": "route", "skill": "hithink_industry_query"}),
    ("1.2", "公司", CAT, ["宁德时代"], "宁德时代国内、海外出货量分别是多少", {"kind": "route", "skill": "hithink_industry_query"}),
    ("1.3", "公司", CAT, ["宁德时代"], "宁德时代工厂产能利用率现在多少", {"kind": "route", "skill": "hithink_industry_query"}),
    ("1.4", "公司", CAT, ["宁德时代"], "公司各基地产能利用率变化情况", {"kind": "route", "skill": "hithink_industry_query"}),
    ("1.5", "公司", CAT, ["宁德时代"], "宁德时代全球市场份额近几年变化", {"kind": "route", "skill": "hithink_stock_selector"}),
    ("1.6", "公司", CAT, ["宁德时代"], "这家企业有效产能、在建产能、规划产能分别多少", {"kind": "route", "skill": "hithink_industry_query"}),
    ("1.7", "公司", CAT, ["宁德时代"], "公司产能释放节奏如何", {"kind": "derivative", "forbidden": "hithink_industry_query"}),
    ("1.8", "公司", CAT, ["宁德时代"], "该公司产销率大概什么水平", {"kind": "gap"}),
    ("1.9", "公司", CAT, ["宁德时代"], "企业单位产能投资是多少", {"kind": "derivative", "forbidden": "hithink_industry_query"}),
    ("1.10", "公司", CAT, ["宁德时代"], "这家公司库存周转天数", {"kind": "route", "skill": "hithink_finance_query"}),
    ("1.11", "公司", CAT, ["宁德时代"], "公司产能扩张进度怎么样", {"kind": "derivative", "forbidden": "hithink_industry_query"}),
    ("1.12", "公司", CAT, ["宁德时代"], "它的外采比例、自给率大概多少", {"kind": "gap"}),
    ("1.13", "公司", CAT, ["宁德时代"], "该企业良率水平如何", {"kind": "gap"}),
    ("1.14", "公司", CAT, ["宁德时代"], "公司单瓦/单GWh成本变化趋势", {"kind": "gap"}),
    ("1.15", "公司", CAT, ["宁德时代"], "它在国内的市占率、全球市占率分别多少", {"kind": "route", "skill": "hithink_stock_selector"}),
    ("1.16", "公司", CAT, ["宁德时代"], "公司产能爬坡周期大概多久", {"kind": "derivative", "forbidden": "hithink_industry_query"}),
    ("1.17", "公司", CAT, ["宁德时代"], "这家企业开工率处于什么水平", {"kind": "route", "skill": "hithink_industry_query"}),
    ("1.18", "公司", CAT, ["宁德时代"], "公司外销占比有多少", {"kind": "route", "skill": "hithink_business_query"}),
    ("2.1", "行业", CAT, [], "动力电池行业整体出货量", {"kind": "route", "skill": "hithink_industry_query"}),
    ("2.2", "行业", ESS, [], "国内储能行业年度出货量", {"kind": "route", "skill": "hithink_industry_query"}),
    ("2.3", "行业", PV, [], "光伏组件行业产能利用率", {"kind": "route", "skill": "hithink_industry_query"}),
    ("2.4", "行业", PV, [], "行业整体开工率水平", {"kind": "route", "skill": "hithink_industry_query"}),
    ("2.5", "行业", CAT, [], "全球动力电池市场份额格局", {"kind": "route", "skill": "hithink_stock_selector"}),
    ("2.6", "行业", PV, [], "行业有效总产能、在建产能、规划产能规模", {"kind": "route", "skill": "hithink_industry_query"}),
    ("2.7", "行业", PV, [], "行业产能过剩程度怎么样", {"kind": "judgment", "forbidden": "hithink_industry_query"}),
    ("2.8", "行业", PV, [], "行业产销率大概多少", {"kind": "gap"}),
    ("2.9", "行业", PV, [], "国内行业自给率水平", {"kind": "gap"}),
    ("2.10", "行业", PV, [], "产业链各环节良率分别是多少", {"kind": "gap"}),
    ("2.11", "行业", PV, [], "行业库存周转处于什么位置", {"kind": "gap"}),
    ("2.12", "行业", PV, [], "各环节产能释放节奏", {"kind": "derivative", "forbidden": "hithink_industry_query"}),
    ("2.13", "行业", PV, [], "行业集中度CR3/CR5/CR10变化", {"kind": "route", "skill": "hithink_stock_selector"}),
    ("2.14", "行业", PV, [], "海外市场行业渗透率", {"kind": "gap"}),
    ("2.15", "行业", PV, [], "国内行业渗透率提升速度", {"kind": "gap"}),
    ("2.16", "行业", PV, [], "行业单位扩产成本大概是多少", {"kind": "gap"}),
    ("2.17", "行业", PV, [], "行业进口依赖度怎么样", {"kind": "gap"}),
    ("2.18", "行业", PV, [], "行业出口占比数据", {"kind": "gap", "caliber_risk": True}),
    ("3.1", "对比", CAT, ["宁德时代", "比亚迪"], "宁德时代和比亚迪的电池出货量对比", {"kind": "compare", "skill": "hithink_industry_query"}),
    ("3.2", "对比", CAT, [], "几家头部厂商产能利用率对比情况", {"kind": "compare", "skill": "hithink_industry_query"}),
    ("3.3", "对比", CAT, [], "国内外企业市场份额对比", {"kind": "compare", "skill": "hithink_stock_selector"}),
    ("3.4", "对比", CAT, [], "各企业产能扩张节奏有什么差异", {"kind": "derivative", "forbidden": "hithink_industry_query"}),
    ("3.5", "对比", CAT, [], "头部几家公司开工率差异多大", {"kind": "compare", "skill": "hithink_industry_query"}),
    ("3.6", "对比", PV, [], "国内与海外行业出货量对比", {"kind": "compare", "skill": "hithink_industry_query"}),
    ("3.7", "对比", PV, [], "不同技术路线之间市占率变化对比（比如TOPCon vs HJT渗透率）", {"kind": "compare", "skill": "hithink_stock_selector"}),
    ("3.8", "对比", CAT, [], "各家企业产销率差异", {"kind": "gap"}),
    ("4.1", "趋势", CAT, [], "近三年动力电池行业出货量变化", {"kind": "route", "skill": "hithink_industry_query"}),
    ("4.2", "趋势", PV, [], "2024-2025年各季度产能利用率走势", {"kind": "route", "skill": "hithink_industry_query"}),
    ("4.3", "趋势", CAT, [], "近五年头部企业市场份额变化趋势", {"kind": "route", "skill": "hithink_stock_selector"}),
    ("4.4", "趋势", PV, [], "今年上半年行业开工率同比去年变化", {"kind": "route", "skill": "hithink_industry_query"}),
    ("4.5", "趋势", PV, [], "过去几个季度产能释放情况", {"kind": "derivative", "forbidden": "hithink_industry_query"}),
    ("4.6", "趋势", PV, [], "未来两年行业规划产能增量预计多少", {"kind": "derivative", "forbidden": "hithink_industry_query"}),
    ("4.7", "趋势", PV, [], "近三年行业CR5集中度变化", {"kind": "route", "skill": "hithink_stock_selector"}),
    ("5.1", "口语", CAT, [], "电池厂现在开工到底怎么样？", {"kind": "gap"}),
    ("5.2", "口语", PV, [], "这个行业产能有没有过剩？", {"kind": "judgment", "forbidden": "hithink_industry_query"}),
    ("5.3", "口语", CAT, [], "各家厂子扩产落地进度如何？", {"kind": "gap"}),
    ("5.4", "口语", CAT, [], "海外那边国内厂商卖出去多少？", {"kind": "gap"}),
    ("5.5", "口语", PV, [], "行业大厂现在生产饱和吗？", {"kind": "gap"}),
    ("5.6", "口语", CAT, [], "现在行业谁家抢份额抢得最猛？", {"kind": "route", "skill": "hithink_stock_selector"}),
    ("5.7", "口语", PV, [], "新产能多久能跑满？", {"kind": "judgment", "forbidden": "hithink_industry_query"}),
    ("6.1", "歧义", PV, [], "光伏行业供给情况如何？", {"kind": "ambiguous"}),
    ("6.2", "歧义", CAT, [], "动力电池竞争格局怎么样？", {"kind": "ambiguous"}),
    ("6.3", "歧义", CAT, ["宁德时代"], "这家企业生产端情况怎么样？", {"kind": "ambiguous"}),
]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def run_case(case: tuple) -> dict:
    cid, group, topic, entities, text, expect = case
    parse = parse_intent(text, industry_topic=topic, known_entities=entities)
    plan = await build_intent_plan(
        text, industry_topic=topic, known_entities=entities or None
    )
    locked = {skill.value for skill in parse.locked_skills}
    routed_skills = {
        skill for sub in plan.sub_requirements for skill in sub.candidate_skills
    }
    metrics = sorted(
        {
            (metric.normalized_name or metric.original_name)
            for sub in plan.sub_requirements
            for metric in sub.metrics
        }
    )
    actionable = any(sub.candidate_skills for sub in plan.sub_requirements)
    result = {
        "id": cid,
        "group": group,
        "text": text,
        "expect": expect,
        "parse_metrics": parse.metric_names,
        "locked_skills": sorted(locked),
        "locked_skill_types": dict(parse.locked_skill_types),
        "routed_skills": sorted(routed_skills),
        "plan_metrics": metrics,
        "unresolved_metrics": list(plan.unresolved_metrics),
        "sub_count": len(plan.sub_requirements),
        "actionable": actionable,
        "requires_clarification": plan.requires_clarification,
        "warnings": list(plan.warnings),
        "analysis_notes": list(plan.analysis_notes),
    }
    result["verdict"] = classify(result)
    return result


def classify(r: dict) -> str:
    expect = r["expect"]
    kind = expect["kind"]
    locked = set(r["locked_skills"])
    if kind == "route" or kind == "compare":
        if expect["skill"] in locked and r["actionable"]:
            return "PASS_干净通过"
        if expect["skill"] in locked and not r["actionable"]:
            return "BUG_过度阻塞"
        if r["requires_clarification"]:
            return "BUG_路由丢失_澄清"
        return "BUG_路由丢失"
    if kind in ("derivative", "judgment"):
        if expect["forbidden"] in locked:
            return "BUG_静默误判"
        if r["requires_clarification"] or r["analysis_notes"] or r["unresolved_metrics"]:
            return "PASS_正确拦截"
        return "OBS_未拦截但也未锁定"
    if kind == "gap":
        # 语义优先仲裁后：缺口经 unresolved_metrics 披露通道留痕即为正确拦截
        # （关键词锁仅作披露型查询存在，不声称满足诉求）。
        if r["unresolved_metrics"] or r["requires_clarification"] or not r["actionable"]:
            return "PASS_正确拦截"
        if locked:
            return "BUG_缺口被硬路由"
        return "OBS_缺口被路由"
    if kind == "ambiguous":
        if r["requires_clarification"]:
            return "PASS_澄清门"
        if len(locked) >= 1 and r["actionable"]:
            return "OBS_强行硬选"
        return "OBS_其他"
    return "UNKNOWN"


async def main() -> None:
    results = [await run_case(case) for case in CASES]

    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    out = {
        "mode": "L1_DETERMINISTIC_NO_LLM",
        "total": len(results),
        "counts": counts,
        "results": results,
    }
    report = Path(tempfile.gettempdir()) / "agent1_61_l1_results.json"
    report.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"TOTAL {len(results)}")
    for verdict, count in sorted(counts.items()):
        print(f"  {verdict}: {count}")
    print("\n== BUG / OBS 明细 ==")
    for r in results:
        if not r["verdict"].startswith("PASS"):
            print(
                f"[{r['id']}] {r['verdict']} | {r['text']}\n"
                f"    locked={r['locked_skills']} metrics={r['parse_metrics']} "
                f"clarify={r['requires_clarification']} actionable={r['actionable']}"
            )
    print(f"\nreport saved: {report}")
    print(f"telemetry dir: {os.environ['ROUTING_TELEMETRY_DIR']}")


if __name__ == "__main__":
    asyncio.run(main())
