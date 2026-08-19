"""Agent 1 复杂意图识别与多技能路由 — 路由金标准评测。

评测口径（RUNLOG 阶段二/10.4）：
- 每条金标准用例给出期望 Skill 集合；预测集合取自 ResearchIntentPlan 全部子需求 candidate_skills。
- Precision = |预测∩期望| / |预测|；Recall = |预测∩期望| / |期望|；F1 为两者调和平均；
  Exact Match = 预测集合与期望集合完全一致。
- 澄清用例校验 requires_clarification；安全用例校验规则锁定/非法拒绝/超时回退。
- 本评测不调用项目 LLM：ScriptedDecomposer 中的输出由充当 Agent 1 大模型的
  评测者预先书写（模拟合法 LLM 结构化输出），用于验证 hybrid 合并链路。

运行：cd backend && python tests/agents/data_fetcher/eval_intent_routing_golden.py
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from app.agents.data_fetcher.intent_merger import build_intent_plan
from app.agents.data_fetcher.intent_models import ResearchIntentPlan
from app.schemas.acquisition import SkillName

S = SkillName


@dataclass(slots=True)
class GoldenCase:
    case_id: str
    text: str
    industry_topic: str
    expected_skills: set[str]
    known_entities: list[str] = field(default_factory=list)
    expected_complexity: str = "compound"


class ScriptedDecomposer:
    """评测者充当 Agent 1 大模型：返回预先书写的合法结构化拆解。"""

    def __init__(self, responses: dict[str, list[dict]]) -> None:
        self._responses = responses
        self.calls = 0

    async def decompose(self, **kwargs) -> ResearchIntentPlan:
        self.calls += 1
        user_text = kwargs["user_text"]
        subs = self._responses[user_text]
        return ResearchIntentPlan(
            original_input=user_text,
            normalized_input=user_text,
            complexity="compound",
            sub_requirements=subs,
            parser_mode="hybrid",
        )


def _llm_sub(index: int, text_value: str, intent_type: str, skills: list[str], confidence: float) -> dict:
    return {
        "requirement_id": f"SUB-LLM-{index:02d}",
        "original_text": text_value,
        "normalized_text": text_value,
        "intent_type": intent_type,
        "candidate_skills": skills,
        "confidence": confidence,
        "reason": "金标准评测：评测者充当LLM给出的拆解。",
        "source": "llm",
    }


GOLDEN_CASES: list[GoldenCase] = [
    GoldenCase("E-24", "光伏逆变器国内外厂商市占率及海外政策影响", "光伏逆变器",
               {S.STOCK_SELECTOR.value, S.NEWS.value}),
    GoldenCase("E-27", "宁德时代2024年营业收入、净利率，以及主营业务构成", "动力电池",
               {S.FINANCE.value, S.BUSINESS.value}, known_entities=["宁德时代"]),
    GoldenCase("E-42", "比亚迪最新的业绩预告和增发事件", "新能源汽车",
               {S.EVENT.value, S.ANNOUNCEMENT.value}, known_entities=["比亚迪"]),
    GoldenCase("E-43", "筛选动力电池板块成分股并按营收排序", "动力电池",
               {S.SECTOR.value, S.STOCK_SELECTOR.value}),
    GoldenCase("E-44", "机构对宁德时代的盈利预测与评级变化", "动力电池",
               {S.INSTITUTIONAL_RESEARCH.value}, known_entities=["宁德时代"]),
    GoldenCase("E-50", "宁德时代机构一致预期和主要分歧点", "动力电池",
               {S.INSTITUTIONAL_RESEARCH.value, S.REPORT.value}, known_entities=["宁德时代"]),
    GoldenCase("T-09", "碳酸锂期货价格走势以及最新社融数据", "动力电池",
               {S.FUTURES.value, S.MACRO.value}),
    GoldenCase("T-11", "对比宁德时代、比亚迪近三年的营业收入和净利率", "动力电池",
               {S.FINANCE.value}, known_entities=["宁德时代", "比亚迪"]),
]

LLM_RESPONSES: dict[str, list[dict]] = {
    "光伏逆变器国内外厂商市占率及海外政策影响": [
        _llm_sub(1, "光伏逆变器国内外厂商市占率", "competition_query", [S.STOCK_SELECTOR.value], 0.96),
        _llm_sub(2, "光伏逆变器海外政策影响", "policy_query", [S.NEWS.value], 0.95),
    ],
    "宁德时代2024年营业收入、净利率，以及主营业务构成": [
        _llm_sub(1, "宁德时代2024年营业收入、净利率", "financial_query", [S.FINANCE.value], 0.97),
        _llm_sub(2, "宁德时代主营业务构成", "business_query", [S.BUSINESS.value], 0.96),
    ],
    "比亚迪最新的业绩预告和增发事件": [
        _llm_sub(1, "比亚迪最新的业绩预告", "event_query", [S.EVENT.value], 0.95),
        _llm_sub(2, "比亚迪增发事件", "event_query", [S.EVENT.value, S.ANNOUNCEMENT.value], 0.93),
    ],
    "筛选动力电池板块成分股并按营收排序": [
        _llm_sub(1, "动力电池板块成分股", "industry_query", [S.SECTOR.value], 0.95),
        _llm_sub(2, "按营收排序", "competition_query", [S.STOCK_SELECTOR.value], 0.94),
    ],
    "机构对宁德时代的盈利预测与评级变化": [
        _llm_sub(1, "宁德时代盈利预测与评级变化", "research_query", [S.INSTITUTIONAL_RESEARCH.value], 0.96),
    ],
    "宁德时代机构一致预期和主要分歧点": [
        _llm_sub(1, "宁德时代机构一致预期", "research_query", [S.INSTITUTIONAL_RESEARCH.value], 0.95),
        _llm_sub(2, "宁德时代主要分歧点", "research_query", [S.REPORT.value], 0.93),
    ],
    "碳酸锂期货价格走势以及最新社融数据": [
        _llm_sub(1, "碳酸锂期货价格走势", "commodity_query", [S.FUTURES.value], 0.96),
        _llm_sub(2, "最新社融数据", "macro_query", [S.MACRO.value], 0.95),
    ],
    "对比宁德时代、比亚迪近三年的营业收入和净利率": [
        _llm_sub(1, "宁德时代、比亚迪近三年营业收入和净利率对比", "comparison", [S.FINANCE.value], 0.96),
    ],
}


class _ExplodingDecomposer:
    async def decompose(self, **kwargs) -> ResearchIntentPlan:
        raise TimeoutError("llm_timeout")


def _predicted_skills(plan: ResearchIntentPlan) -> set[str]:
    return {skill for sub in plan.sub_requirements for skill in sub.candidate_skills}


async def run_routing_cases() -> list[dict]:
    rows: list[dict] = []
    decomposer = ScriptedDecomposer(LLM_RESPONSES)
    for case in GOLDEN_CASES:
        plan = await build_intent_plan(
            case.text,
            industry_topic=case.industry_topic,
            known_entities=case.known_entities,
            decomposer=decomposer,
        )
        predicted = _predicted_skills(plan)
        true_positive = len(predicted & case.expected_skills)
        precision = true_positive / len(predicted) if predicted else 0.0
        recall = true_positive / len(case.expected_skills) if case.expected_skills else 1.0
        f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
        rows.append(
            {
                "case_id": case.case_id,
                "text": case.text,
                "complexity": plan.complexity,
                "parser_mode": plan.parser_mode,
                "expected": sorted(case.expected_skills),
                "predicted": sorted(predicted),
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "exact_match": predicted == case.expected_skills,
                "complexity_ok": plan.complexity == case.expected_complexity,
                "sub_requirement_count": len(plan.sub_requirements),
            }
        )
    return rows


async def run_clarification_cases() -> list[dict]:
    rows: list[dict] = []
    ambiguous = await build_intent_plan(
        "那家公司最近怎么样",
        industry_topic="动力电池",
        known_entities=["宁德时代"],
    )
    rows.append(
        {
            "case_id": "C-01-模糊主体",
            "text": "那家公司最近怎么样",
            "requires_clarification": ambiguous.requires_clarification,
            "complexity": ambiguous.complexity,
            "passed": ambiguous.requires_clarification and ambiguous.complexity == "ambiguous",
        }
    )
    unsupported = await build_intent_plan(
        "光伏逆变器板块近期市场情绪与资金流向",
        industry_topic="光伏逆变器",
    )
    flow_blocked = any(
        "资金流向" in sub.normalized_text
        and sub.candidate_skills == []
        and sub.requires_clarification
        for sub in unsupported.sub_requirements
    )
    rows.append(
        {
            "case_id": "C-02-无能力子需求",
            "text": "光伏逆变器板块近期市场情绪与资金流向",
            "requires_clarification": unsupported.requires_clarification,
            "flow_sub_blocked": flow_blocked,
            "passed": unsupported.requires_clarification and flow_blocked,
        }
    )
    return rows


async def run_safety_cases() -> list[dict]:
    rows: list[dict] = []

    class _MaliciousDecomposer:
        async def decompose(self, **kwargs) -> ResearchIntentPlan:
            return ResearchIntentPlan(
                original_input=kwargs["user_text"],
                normalized_input=kwargs["user_text"],
                complexity="compound",
                sub_requirements=[
                    {
                        "requirement_id": "SUB-LLM-01",
                        "original_text": "光伏逆变器厂商份额",
                        "normalized_text": "光伏逆变器厂商份额",
                        "intent_type": "competition_query",
                        "candidate_skills": ["SUPER_SKILL", "hithink_fake_query", "report_search"],
                        "confidence": 0.95,
                        "reason": "越权输出",
                        "source": "llm",
                    }
                ],
                parser_mode="hybrid",
            )

    locked_plan = await build_intent_plan(
        "光伏逆变器国内外厂商市占率及海外政策影响",
        industry_topic="光伏逆变器",
        decomposer=_MaliciousDecomposer(),
    )
    locked_values = {str(item.value if hasattr(item, "value") else item) for item in locked_plan.locked_skills}
    predicted = _predicted_skills(locked_plan)
    rows.append(
        {
            "case_id": "S-01-规则锁定不可删除",
            "locked_preserved": {S.STOCK_SELECTOR.value, S.NEWS.value} <= locked_values
            and {S.STOCK_SELECTOR.value, S.NEWS.value} <= predicted,
            "illegal_rejected": "SUPER_SKILL" in locked_plan.rejected_skills
            and "hithink_fake_query" in locked_plan.rejected_skills,
            "illegal_absent": "SUPER_SKILL" not in predicted and "hithink_fake_query" not in predicted,
            "valid_supplement_accepted": S.REPORT.value in predicted,
        }
    )
    rows[-1]["passed"] = all(
        rows[-1][key] for key in ("locked_preserved", "illegal_rejected", "illegal_absent", "valid_supplement_accepted")
    )

    fallback_plan = await build_intent_plan(
        "碳酸锂期货价格走势以及最新社融数据",
        industry_topic="动力电池",
        decomposer=_ExplodingDecomposer(),
    )
    fallback_skills = _predicted_skills(fallback_plan)
    rows.append(
        {
            "case_id": "S-02-LLM超时安全回退",
            "parser_mode": fallback_plan.parser_mode,
            "warning_recorded": any("TimeoutError" in warning for warning in fallback_plan.warnings),
            "routing_intact": {S.FUTURES.value, S.MACRO.value} <= fallback_skills,
        }
    )
    rows[-1]["passed"] = (
        fallback_plan.parser_mode == "fallback" and rows[-1]["warning_recorded"] and rows[-1]["routing_intact"]
    )

    class _CountingDecomposer:
        def __init__(self) -> None:
            self.calls = 0

        async def decompose(self, **kwargs) -> ResearchIntentPlan:
            self.calls += 1
            raise AssertionError("simple request must not call the LLM")

    counter = _CountingDecomposer()
    simple_plan = await build_intent_plan(
        "查询宁德时代近四年营业收入",
        industry_topic="动力电池",
        known_entities=["宁德时代"],
        decomposer=counter,
    )
    rows.append(
        {
            "case_id": "S-03-简单请求不调用LLM",
            "complexity": simple_plan.complexity,
            "parser_mode": simple_plan.parser_mode,
            "llm_calls": counter.calls,
            "passed": simple_plan.complexity == "simple"
            and simple_plan.parser_mode == "deterministic"
            and counter.calls == 0,
        }
    )
    return rows


async def main() -> None:
    routing_rows = await run_routing_cases()
    clarification_rows = await run_clarification_cases()
    safety_rows = await run_safety_cases()

    total = len(routing_rows)
    exact_matches = sum(1 for row in routing_rows if row["exact_match"])
    macro_precision = sum(row["precision"] for row in routing_rows) / total
    macro_recall = sum(row["recall"] for row in routing_rows) / total
    macro_f1 = sum(row["f1"] for row in routing_rows) / total
    expected_total = sum(len(row["expected"]) for row in routing_rows)
    predicted_total = sum(len(row["predicted"]) for row in routing_rows)
    true_positive_total = sum(
        len(set(row["expected"]) & set(row["predicted"])) for row in routing_rows
    )
    micro_precision = true_positive_total / predicted_total if predicted_total else 0.0
    micro_recall = true_positive_total / expected_total if expected_total else 0.0
    micro_f1 = (
        0.0
        if micro_precision + micro_recall == 0
        else 2 * micro_precision * micro_recall / (micro_precision + micro_recall)
    )
    summary = {
        "case_count": total,
        "exact_match_count": exact_matches,
        "exact_match_rate": round(exact_matches / total, 4),
        "macro_precision": round(macro_precision, 4),
        "macro_recall": round(macro_recall, 4),
        "macro_f1": round(macro_f1, 4),
        "micro_precision": round(micro_precision, 4),
        "micro_recall": round(micro_recall, 4),
        "micro_f1": round(micro_f1, 4),
        "clarification_passed": all(row["passed"] for row in clarification_rows),
        "safety_passed": all(row["passed"] for row in safety_rows),
    }
    report = {
        "summary": summary,
        "routing_cases": routing_rows,
        "clarification_cases": clarification_rows,
        "safety_cases": safety_rows,
    }
    output_dir = Path(__file__).resolve().parents[3] / "test_output" / "agent1_intent_routing"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "golden_eval_report.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== 路由金标准评测 ===")
    for row in routing_rows:
        flag = "OK " if row["exact_match"] else "BAD"
        print(
            f"[{flag}] {row['case_id']} mode={row['parser_mode']} subs={row['sub_requirement_count']} "
            f"P={row['precision']:.2f} R={row['recall']:.2f} F1={row['f1']:.2f} "
            f"expected={row['expected']} predicted={row['predicted']}"
        )
    for row in clarification_rows:
        print(f"[{'OK ' if row['passed'] else 'BAD'}] {row['case_id']} -> {row}")
    for row in safety_rows:
        print(f"[{'OK ' if row['passed'] else 'BAD'}] {row['case_id']} -> {row}")
    print("=== 汇总 ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"报告已写入: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
