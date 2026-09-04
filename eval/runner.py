"""评测 CLI 入口（EVALUATION_PLAN §1/§11，mikiships/pytest-agentcontract 式）。

用法：
    python -m eval.runner --case I-C01                    # 跑单条意图用例
    python -m eval.runner --group intent_routing          # 跑整组
    python -m eval.runner --k 3 --case I-C15              # 稳定性连跑
    python -m eval.runner --mode replay --case E-13       # E2E（复用 test_agent 装配）

I 类意图评测直接断言 ``build_intent_plan`` 输出（不调真实 LLM、不耗配额），
用注入的 FakeDecomposer 模拟 LLM 五态（deterministic/llm_ok/llm_fallback/llm_illegal/stability）。

E2E/T/专项评测复用 backend/tests 的 StageContext 装配（test_agent.py 模式），
由 Agent 1 数据获取 + L1 规则判定（scorers/rules.run_l1_checks）完成。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.agents.data_fetcher.intent_merger import build_intent_plan  # noqa: E402
from app.agents.data_fetcher.intent_models import (  # noqa: E402
    IntentEntity,
    IntentMetric,
    IntentSubRequirement,
    IntentTimeRange,
    ResearchIntentPlan,
)
from eval.conftest import CASES_DIR, load_json_cases  # noqa: E402
from eval.scorers.intent import evaluate_intent_case  # noqa: E402
from eval.scorers.rules import run_l1_checks  # noqa: E402

FINANCE = "hithink_finance_query"
STOCK_SELECTOR = "hithink_stock_selector"


class FakeDecomposer:
    """注入预置 ResearchIntentPlan 或异常，模拟 LLM 各态。"""

    def __init__(self, plan: ResearchIntentPlan | None = None, exc: Exception | None = None) -> None:
        self.plan = plan
        self.exc = exc

    async def decompose(self, **kwargs: object) -> ResearchIntentPlan:
        if self.exc is not None:
            raise self.exc
        assert self.plan is not None
        return self.plan


def _llm_plan(case: dict) -> ResearchIntentPlan:
    intent = case["intent"]
    skills = intent.get("required_skills", [])
    entities = intent.get("entities", [])
    metrics = intent.get("metrics_in", [])
    time_tokens = intent.get("expect_time_tokens", [])
    time_raw = time_tokens[0] if time_tokens else None
    sub = IntentSubRequirement(
        requirement_id="SUB-LLM-01",
        original_text=case["input"],
        normalized_text=case["input"],
        entities=[
            IntentEntity(name=n, entity_type="company", confidence=0.98) for n in entities
        ],
        metrics=[
            IntentMetric(original_name=m, normalized_name=m, metric_type="financial", confidence=0.98)
            for m in metrics
        ],
        time_range=IntentTimeRange(raw_text=time_raw, granularity="year", confidence=0.98)
        if time_raw
        else None,
        intent_type="financial_query",
        candidate_skills=list(skills),
        confidence=0.98,
        reason="LLM语义拆解结果。",
        source="llm",
    )
    return ResearchIntentPlan(
        original_input=case["input"],
        normalized_input=case["input"],
        complexity=intent.get("complexity", "simple"),
        sub_requirements=[sub],
        parser_mode="hybrid",
    )


def _decomposer_for(case: dict) -> FakeDecomposer | None:
    mode = case["intent"].get("mode", "deterministic")
    if mode == "deterministic":
        return None
    if mode == "llm_ok":
        return FakeDecomposer(plan=_llm_plan(case))
    if mode == "llm_fallback":
        return FakeDecomposer(exc=TimeoutError("provider timeout"))
    if mode == "llm_illegal":
        illegal = _llm_plan(case)
        illegal = illegal.model_copy(
            update={
                "sub_requirements": [
                    illegal.sub_requirements[0].model_copy(update={"candidate_skills": ["fabricated-skill"]})
                ]
            }
        )
        return FakeDecomposer(plan=illegal)
    if mode == "stability":
        return FakeDecomposer(plan=_llm_plan(case))
    return None


async def run_intent_case(case: dict, *, k: int = 3) -> dict:
    """跑单条 I 类用例，返回 grades 一行。"""
    mode = case["intent"].get("mode", "deterministic")

    async def once() -> dict:
        decomposer = _decomposer_for(case)
        plan = await build_intent_plan(
            case["input"],
            industry_topic=case.get("industry_topic", "动力电池"),
            known_entities=list(case["intent"].get("entities", [])),
            decomposer=decomposer,
        )
        checks = evaluate_intent_case(plan, case)
        # I7 回退：llm_fallback 模式须 parser_mode=fallback
        if mode == "llm_fallback":
            checks["I7"] = plan.parser_mode == "fallback"
        # I8 稳定性：单次签名可注入供外部聚合
        checks["_parser_mode"] = plan.parser_mode
        checks["_signature"] = (
            plan.complexity,
            tuple(sorted(plan.locked_skills)),
            tuple(sorted({s for sub in plan.sub_requirements for s in sub.candidate_skills})),
            plan.parser_mode,
        )
        return {k: v for k, v in checks.items() if isinstance(v, bool)}

    if mode == "stability":
        # I8：连跑 k 次，比较能力签名一致性（签名从 once 的 _signature 抽取）
        sigs: set[tuple] = set()
        for _ in range(k):
            decomposer = _decomposer_for(case)
            plan = await build_intent_plan(
                case["input"],
                industry_topic=case.get("industry_topic", "动力电池"),
                known_entities=list(case["intent"].get("entities", [])),
                decomposer=decomposer,
            )
            sigs.add(
                (
                    plan.complexity,
                    tuple(sorted(plan.locked_skills)),
                    tuple(sorted({s for sub in plan.sub_requirements for s in sub.candidate_skills})),
                    plan.parser_mode,
                )
            )
        return {"passed": len(sigs) == 1, "signatures": len(sigs), "case_id": case["id"]}

    checks = await once()
    passed = all(checks.values())
    return {"case_id": case["id"], "passed": passed, "checks": checks, "parser_mode": _get_parser_mode(case)}


def _get_parser_mode(case: dict) -> str:
    return ""


def _run_intent_group(group: str | None) -> int:
    cases = load_json_cases("intent_golden.json")
    if group:
        cases = [c for c in cases if c.get("group") == group]
    results = [asyncio.run(run_intent_case(c)) for c in cases]
    passed = [r for r in results if r.get("passed")]
    for r in results:
        print(f"[{'PASS' if r.get('passed') else 'FAIL'}] {r.get('case_id')} {r.get('checks', '')}")
    print(f"\n意图评测：{len(passed)}/{len(results)} 通过")
    return 0 if len(passed) == len(results) else 1


def _run_e2e_case(case: dict) -> dict:
    """E2E/T/专项：装配 Agent 1 数据获取，跑 L1 规则判定。

    复用 backend/tests test_agent.py 的装配模式（MockSkillHubClient + QueryPlanner
    + RetrievalExecutor）。生产评测时改用 SnapshotTransport 注入快照。
    """
    from app.agents.data_fetcher.executor import RetrievalExecutor
    from app.agents.data_fetcher.planner import QueryPlanner
    from app.agents.data_fetcher.service import DataFetcherAgent
    from app.integrations.skillhub.mock import MockSkillHubClient
    from app.integrations.skillhub.registry import create_skillhub_gateway
    from app.workflow.stages import StageContext

    client = MockSkillHubClient()
    client.provider_mode = "live"
    agent = DataFetcherAgent(
        planner=QueryPlanner(),
        executor=RetrievalExecutor(create_skillhub_gateway(client)),
        provider_mode=client.provider_mode,
    )
    context = StageContext(
        project_id="eval",
        run_id="eval-run",
        revision=1,
        input_data={
            "industry_topic": case.get("industry_topic", "动力电池"),
            "market_scope": ["中国内地"],
            "security_types": ["普通股"],
            "reporting_currency": "CNY",
            "research_as_of": "2026-08-11",
            "focus_questions": [case["input"]],
            "evidence_items": [],
            "analysis_depth": "standard",
            "risk_preference": "balanced",
            "research_brief": {
                "focus_companies": case["intent"].get("entities", [])
                if "intent" in case
                else []
            },
        },
    )
    result = asyncio.run(agent.run(context))
    artifacts = {
        "retrieval_plan": result.data.get("retrieval_plan", {}),
        "fetch_result": result.data,
    }
    checks = run_l1_checks(artifacts, case, checks=case.get("checks"))
    passed = all(c.passed for c in checks)
    return {
        "case_id": case["id"],
        "passed": passed,
        "checks": {c.check_id: c.passed for c in checks},
    }


def _write_grades(results: list[dict], run_id: str) -> None:
    transcript_dir = Path(__file__).parent / "transcript" / run_id
    transcript_dir.mkdir(parents=True, exist_ok=True)
    with (transcript_dir / "grades.jsonl").open("w", encoding="utf-8") as fh:
        for r in results:
            r = dict(r)
            r["_run_id"] = run_id
            r["_at"] = datetime.now(timezone.utc).isoformat()
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="同花顺多智能体评测 runner")
    parser.add_argument("--case", help="单条用例 ID（如 I-C01 / E-13 / T-09）")
    parser.add_argument("--group", help="用例组（intent_routing/core_calc/intercept/tool_planning/full）")
    parser.add_argument("--mode", default="replay", choices=["record", "replay", "mutate"])
    parser.add_argument("--k", type=int, default=3, help="采样/连跑次数")
    args = parser.parse_args(argv)

    if args.case and args.case.startswith("I-C"):
        case = next(c for c in load_json_cases("intent_golden.json") if c["id"] == args.case)
        result = asyncio.run(run_intent_case(case, k=args.k))
        _write_grades([result], f"intel-{args.case.lower()}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("passed") else 1

    if args.group == "intent_routing" or (args.case is None and args.group is None):
        return _run_intent_group(args.group)

    # E2E/T/专项
    cases = load_json_cases("cases_v1.json")
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    elif args.group:
        cases = [c for c in cases if c.get("group") == args.group]
    results = [_run_e2e_case(c) for c in cases]
    _write_grades(results, "e2e")
    for r in results:
        print(f"[{'PASS' if r['passed'] else 'FAIL'}] {r['case_id']} {r['checks']}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())