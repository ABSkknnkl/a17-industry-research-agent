#!/usr/bin/env python3
"""Agent 1 真实调用：LLM 意图拆解 + SkillHub 降级链，4 个新能源汽车查询。"""

import asyncio
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

# 先加载 .env
env_file = BACKEND / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from app.core.config import get_settings
from app.agents.data_fetcher.factory import create_data_fetcher_agent
from app.schemas.workflow import StageName, StageResult

QUERIES = [
    {
        "id": "NEV-01",
        "input": "新能源汽车整车行业2023年至2026年销量及渗透率变化趋势",
        "industry_topic": "新能源汽车",
    },
    {
        "id": "NEV-02",
        "input": "比亚迪、特斯拉、理想、蔚来销量及国内市场份额对比",
        "industry_topic": "新能源汽车",
    },
    {
        "id": "NEV-03",
        "input": "主要整车企业营业收入、净利润及毛利率变化趋势",
        "industry_topic": "新能源汽车整车",
    },
    {
        "id": "NEV-04",
        "input": "新能源汽车海外出口规模及主要出口区域分布",
        "industry_topic": "新能源汽车出口",
    },
]


def build_input(q: dict) -> dict:
    return {
        "industry_topic": q["industry_topic"],
        "market_scope": ["中国内地"],
        "security_types": ["普通股"],
        "reporting_currency": "CNY",
        "research_as_of": "2026-09-14",
        "focus_questions": [q["input"]],
        "evidence_items": [],
        "analysis_depth": "standard",
        "risk_preference": "balanced",
        "research_brief": {},
        "data_fetch_options": {},
    }


async def main():
    settings = get_settings()
    print(f"LLM: {settings.LLM_MODEL} @ {settings.LLM_BASE_URL}")
    print(f"SkillHub: {settings.IWENCAI_BASE_URL}")
    print(f"降级链: {settings.AGENT1_FALLBACK_CHAIN} (depth={settings.AGENT1_FALLBACK_MAX_DEPTH}, budget={settings.AGENT1_FALLBACK_CALL_BUDGET})")
    print(f"联网兜底: {settings.AGENT1_WEB_FALLBACK_ENABLED}")
    print(f"意图拆解: {settings.AGENT1_INTENT_DECOMPOSER_ENABLED}")
    print(f"语义路由: {settings.AGENT1_SEMANTIC_ROUTER_ENABLED}")
    print()

    agent = create_data_fetcher_agent(settings)
    print(f"Agent1 已组装: provider_mode={agent._provider_mode}")
    print()

    all_results = {}
    for q in QUERIES:
        print(f"{'='*70}")
        print(f"[{q['id']}] {q['input']}")
        print(f"{'='*70}")

        class FakeContext:
            def __init__(self):
                self.owner_id = "local-test"
                self.project_id = "byd-nev-research"
                self.run_id = f"run-{q['id'].lower()}"
                self.revision = 1
                self.input_data = build_input(q)
                self.previous_results = {}
                self.review_feedback = None
                self.rejected_claim_ids = []
                self.runtime = None

        ctx = FakeContext()
        try:
            result = await agent.run(ctx)
            status = result.status.value if hasattr(result.status, "value") else str(result.status)
            error = result.error or ""
            data = result.data or {}

            print(f"  状态: {status}")
            if error:
                print(f"  错误: {error[:120]}")

            evidence = data.get("evidence_items", [])
            datasets = data.get("chart_datasets", [])
            degradations = data.get("acquisition_degradation", {})
            plan = data.get("retrieval_plan", {})
            notes = data.get("analysis_notes", [])

            print(f"  证据条数: {len(evidence)}")
            print(f"  数据集: {len(datasets)}")
            print(f"  分析笔记: {len(notes)}")

            if degradations:
                levels = degradations.get("levels_used", {})
                web = degradations.get("web_fallback_used", False)
                print(f"  降级层级: {levels}  联网兜底: {web}")

            if plan:
                tasks = plan.get("tasks", [])
                skills = [t.get("skill", "?") for t in tasks if isinstance(t, dict)]
                print(f"  取数计划: {len(tasks)} 个任务, skills={skills[:8]}")

            # 展示前 5 条证据
            for i, ev in enumerate(evidence[:5]):
                if isinstance(ev, dict):
                    metric = ev.get("metric_name", ev.get("metric", "?"))
                    value = ev.get("value", ev.get("raw_value", "?"))
                    unit = ev.get("unit", "")
                    entity = ev.get("entity", ev.get("entity_name", ""))
                    period = ev.get("period_end", ev.get("period", ""))
                    eid = ev.get("evidence_id", "")[:16]
                    print(f"    [{i+1}] {entity} | {metric} = {value} {unit} | {period} | {eid}")

            all_results[q["id"]] = {
                "input": q["input"],
                "status": status,
                "error": error,
                "evidence_count": len(evidence),
                "dataset_count": len(datasets),
                "note_count": len(notes),
                "degradation": degradations,
                "plan_task_count": len(plan.get("tasks", [])) if plan else 0,
                "evidence_sample": evidence[:20],
                "notes_sample": notes[:10],
            }

        except Exception as e:
            print(f"  异常: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            all_results[q["id"]] = {"input": q["input"], "error": f"{type(e).__name__}: {e}"}

        print()

    out = Path(__file__).resolve().parent / "nev_agent1_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    print(f"结果已保存: {out}")

    # 汇总
    print(f"\n{'='*70}")
    print("汇总")
    print(f"{'='*70}")
    for qid, r in all_results.items():
        if "error" in r and "status" not in r:
            print(f"  {qid}: ❌ {r['error'][:60]}")
        else:
            print(f"  {qid}: {r.get('status','?')} | 证据 {r.get('evidence_count',0)} 条 | 数据集 {r.get('dataset_count',0)} 个")


asyncio.run(main())
