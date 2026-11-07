#!/usr/bin/env python3
"""
智能体 1（数据获取与清洗整合智能体 DataFetcherAgent）独立端到端深度测试与质量评估脚本
(Standalone Agent 1 Deep Benchmark & Iteration Test Suite)

功能：
1. 独立运行 DataFetcherAgent，全流程驱动真实的 LLM（如 deepseek-v4-flash）与问财网关；
2. 全程实时监控：意图解构 -> 逐轮观测 -> LLM 规划推理 -> DAG 调度 -> 3级自愈 -> 异构融合；
3. 输出量化评估报告：覆盖率得分、龙头估值召回、三表深度、研报资讯完整度、0召回率。
"""

import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

# 初始化 Python 路径
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "agents_core" / "data-fetcher"))

from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env", override=True)

from data_fetcher.agent import DataFetcherAgent
from data_fetcher.config import Settings
from data_fetcher.models import ResearchRequest


def format_elapsed(start_time: float) -> str:
    return f"{time.time() - start_time:.1f}s"


async def run_standalone_agent1(
    topic: str,
    focus_points: list[str] | None = None,
    must_include: list[str] | None = None,
    max_iterations: int = 4,
    max_skill_calls: int = 20,
) -> None:
    settings = Settings.from_env()
    print("=" * 90)
    print("🚀 启动智能体 1 (DataFetcherAgent) 独立运行与数据获取能力评估")
    print(f"⏰ 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🧠 大模型基座: {settings.llm_model} ({settings.llm_base_url})")
    print(f"🔑 问财活跃 Key 数: {len(settings.iwencai_api_keys)} 个 (首选: {settings.iwencai_api_keys[0][:18]}...{settings.iwencai_api_keys[0][-6:]})")
    print(f"🎯 研究行业主题: 【{topic}】")
    if must_include:
        print(f"📌 指定重点标的: {', '.join(must_include)}")
    print(f"⚙️ 轮次上限: {max_iterations} 轮, 调用上限: {max_skill_calls} 次, 并发限制: {settings.fetch_concurrency_limit}")
    print("=" * 90)

    start_t = time.time()
    all_events: list[dict[str, Any]] = []

    async def on_event(event_dict: dict[str, Any]) -> None:
        evt = event_dict.get("event")
        it = event_dict.get("iteration")
        details = event_dict.get("details", {})
        all_events.append(event_dict)

        prefix = f"[{format_elapsed(start_t)}]"
        if it is not None:
            prefix += f" [迭代 #{it}]"

        if evt == "agent_started":
            print(f"{prefix} 🟢 智能体启动，初始化投研请求...")
        elif evt == "objective_ready":
            domains = details.get("required_domains", [])
            print(f"{prefix} 🎯 意图理解完成: 激活 {len(domains)} 个分析领域 ({', '.join(domains)})")
        elif evt == "observation_ready":
            cov = details.get("coverage", 0.0)
            missing = details.get("missing", [])
            comps = details.get("companies", [])
            rem = details.get("remaining_skill_calls", 0)
            print(f"\n{prefix} 📊 状态观测: 覆盖率={cov*100:.1f}%, 剩余配额={rem}, 候选池企业数={len(comps)}")
            if missing:
                print(f"   ⚠️ 缺口领域: {', '.join(missing)}")
            if comps:
                top_names = [f"{c['name']}({c['code']})" for c in comps[:6]]
                print(f"   🏢 当前龙头候选: {', '.join(top_names)}")
        elif evt == "decision_ready":
            decision = details.get("decision")
            assessment = details.get("assessment", "")
            proposed = details.get("proposed_tasks", 0)
            print(f"{prefix} 💡 LLM 规划决策: 动作={decision}, 规划任务数={proposed}")
            if assessment:
                print(f"   💭 规划思考: {assessment[:120]}...")
        elif evt == "task_dispatched":
            tid = event_dict.get("task_id")
            sname = details.get("skill_name")
            query = details.get("query", "")
            print(f"   ⚡ 派发任务 [{tid}] ({sname}): \"{query}\"")
        elif evt == "task_completed":
            tid = event_dict.get("task_id")
            sname = details.get("skill_name")
            rows = details.get("row_count", 0)
            print(f"   ✅ 任务完成 [{tid}] ({sname}): 召回 {rows} 行数据")
        elif evt == "task_failed":
            tid = event_dict.get("task_id")
            sname = details.get("skill_name")
            err = details.get("error", "")
            print(f"   ❌ 任务失败 [{tid}] ({sname}): {err}")

    # 构造投研请求
    request = ResearchRequest(
        industry=topic,
        focus_points=focus_points or ["产业链", "龙头财务", "宏观政策", "行业规模"],
        must_include_entities=must_include or [],
        max_iterations=max_iterations,
        max_skill_calls=max_skill_calls,
        max_execution_seconds=settings.fetch_timeout_seconds * 10,
    )

    agent = DataFetcherAgent(settings=settings)
    print(f"\n🚀 开始执行 DataFetcherAgent.run()...")
    result = await agent.run(request, emit=on_event, save_artifacts=True)
    total_time = time.time() - start_t

    print("\n" + "=" * 90)
    print(f"🏁 智能体 1 运行完毕！状态: {result.status.upper()}, 停止原因: {result.stop_reason}, 耗时: {total_time:.1f}s")
    print(f"📈 最终覆盖率得分: {result.coverage.score * 100:.1f}%")
    print("=" * 90)

    # 质量深度体检与诊断
    dataset = result.dataset
    comps = dataset.companies if dataset else []
    fin = dataset.financials if dataset else []
    macro = dataset.macro if dataset else []
    news = dataset.news if dataset else []
    reports = dataset.reports if dataset else []
    chain = dataset.industry_chain if dataset else []

    print("\n📦 【数据集全景质量体检报告】:")
    print(f"  1. 覆盖上市公司数量: {len(comps)} 家")
    if comps:
        comp_names = list(dict.fromkeys(c.entity_name for c in comps if c.entity_name))
        print(f"     标的名单: {', '.join(comp_names[:10])}{' ...' if len(comp_names) > 10 else ''}")
        # 检查市值和估值召回
        has_market_cap = sum(1 for c in comps if "市值" in c.metric or "market_cap" in c.metric.lower())
        has_pe = sum(1 for c in comps if "pe" in c.metric.lower() or "市盈率" in c.metric)
        print(f"     估值覆盖: 市值数据点={has_market_cap}, 市盈率数据点={has_pe} (NEW-10 验收)")

    print(f"  2. 财务时序指标点数: {len(fin)} 条")
    if fin:
        fin_comps = list(dict.fromkeys(f.entity_name for f in fin if f.entity_name))
        print(f"     覆盖财务公司: {', '.join(fin_comps[:8])}")
        metrics_set = set(f.metric for f in fin)
        metric_aliases = {
            "营业收入": ("revenue", "营业收入", "营业总收入"),
            "归母净利润": ("parent_net_profit", "归母净利润", "净利润"),
            "销售毛利率": ("gross_margin", "销售毛利率", "毛利率"),
            "销售净利率": ("net_margin", "销售净利率", "净利率"),
            "ROE": ("roe", "ROE", "净资产收益率"),
            "资产负债率": ("debt_ratio", "资产负债率"),
            "经营现金流": ("operating_cash_flow", "经营活动产生的现金流量净额", "经营现金流"),
            "研发费用": ("rd_expense", "研发费用"),
        }
        covered_core = [
            label for label, aliases in metric_aliases.items()
            if any(any(a.casefold() in m.casefold() for a in aliases) for m in metrics_set)
        ]
        print(f"     核心三表及关键财务指标覆盖率: {len(covered_core)}/{len(metric_aliases)} ({', '.join(covered_core)})")

    print(f"  3. 宏观与中观周期指标: {len(macro)} 条")
    print(f"  4. 权威行业研报篇数: {len(reports)} 篇")
    if reports:
        for r in reports[:2]:
            pub_date = r.published_at or r.period_end or "最新"
            print(f"     - 研报示例: 《{r.metric}》({pub_date})")

    print(f"  5. 行业资讯与催化动态: {len(news)} 条")
    print(f"  6. 产业链环节构成条目: {len(chain)} 条")

    # 统计调用情况
    completed_tasks = [e for e in all_events if e.get("event") == "skill_completed"]
    failed_tasks = [e for e in all_events if e.get("event") == "skill_failed"]
    total_calls = len(completed_tasks) + len(failed_tasks)
    zero_rows_calls = sum(1 for e in completed_tasks if e.get("details", {}).get("record_count", 0) == 0)
    success_calls = len(completed_tasks) - zero_rows_calls

    print("\n🔍 【调用健康度与自愈审计】:")
    print(f"  - 总发出 API 调用: {total_calls} 次 (配额上限: {max_skill_calls})")
    print(f"  - 成功命中返回: {success_calls} 次 ({success_calls/total_calls*100:.1f}%)" if total_calls else "  - 无调用")
    print(f"  - 0 行数据查询: {zero_rows_calls} 次")
    print(f"  - 彻底报错失败: {len(failed_tasks)} 次")

    if result.artifact_dir:
        art_path = Path(result.artifact_dir)
        print(f"\n💾 真实运行工件已落盘至: {result.artifact_dir}")
        print(f"   - dataset.json ({Path(art_path / 'dataset.json').stat().st_size if (art_path / 'dataset.json').exists() else 0} bytes)")
        print(f"   - events.jsonl ({Path(art_path / 'events.jsonl').stat().st_size if (art_path / 'events.jsonl').exists() else 0} bytes)")

    print("=" * 90)


async def main():
    parser = argparse.ArgumentParser(description="智能体 1 独立运行与端到端优化评测")
    parser.add_argument("--topic", type=str, default="具身智能", help="研究主题 (如 具身智能 / 宠物经济 / 低空经济)")
    parser.add_argument("--focus-points", nargs="+", help="关注要点 (空格分隔)")
    parser.add_argument("--must-include", nargs="+", help="明确指定核心上市公司 (如 鸣志电器 绿的谐波 三花智控)")
    parser.add_argument("--max-iters", type=int, default=4, help="最大规划轮次")
    parser.add_argument("--max-calls", type=int, default=20, help="最大技能调用上限")
    args = parser.parse_args()

    await run_standalone_agent1(
        topic=args.topic,
        focus_points=args.focus_points,
        must_include=args.must_include,
        max_iterations=args.max_iters,
        max_skill_calls=args.max_calls,
    )


if __name__ == "__main__":
    asyncio.run(main())
