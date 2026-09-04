"""全链路流程评测驱动（EVALUATION_PLAN V6 §1/§2.6/§5 执行层）。

本轮（record 模式）执行方式（严格对齐用户指令）：
- Record 快照录制：每条用例执行完成后，用 eval.transport.save_trace 把完整
  trace（stage 流转 + SkillHub 调用流水 + intent_routing 摘要 + verdict）
  保存到 ./eval/traces/（目录自动创建）。是「真实执行 + 录制」，不是 Replay。
- SkillHub：MockSkillHubClient（provider_mode="mock"，仅用于历史确定性测试），
  经 TraceRecordingClient 包装录制每次 execute 调用。
- LLM：--llm real 时，Agent 1 意图拆解器接项目真实大模型（settings.LLM_*，
  ResearchIntentDecomposer，超时/校验失败自动回退规则层）；Agent 2/4 仍为
  确定性 Mock 模型（保五阶段流程可跑通，意图层结果是本轮归因变量）。
  --llm mock（默认）时全部确定性，不调用任何大模型。
- 用例级隔离（§2.6）：每条用例独立 thread + asyncio 超时 + 有限 resume 轮次；
  单条阻断/超时不终止整套测试（不伪造成功，如实记录状态）。
- 审阅决策自动化：REINPUT_REQUIRED 错误 → cancel（合法拦截）；有决策包 →
  accept_with_risks（带 decision_id + risk_snapshot_sha256 + accepted_risk_codes，
  对齐 §6.2 风险确认校验）；FAILED → regenerate 一次再 cancel；其余 → approve。
- grades 落盘 transcript/{run_id}/grades.jsonl（big-finance-benchmark 式）。
- 默认跳过上一轮已真实通过的用例（PASSSED_LAST_ROUND），重点测未通过用例。

用法：
    python -m eval.run_pipeline_eval --llm mock            # 历史确定性测试
    python -m eval.real_runner --case E-05                 # 纯真实五阶段评测
    python -m eval.run_pipeline_eval --include-passed      # 全量重跑
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.agents.chapter_writer.service import ChapterWriterAgent  # noqa: E402
from app.agents.chart_generator.service import ChartGeneratorAgent  # noqa: E402
from app.agents.data_fetcher.executor import RetrievalExecutor  # noqa: E402
from app.agents.data_fetcher.planner import QueryPlanner  # noqa: E402
from app.agents.data_fetcher.service import DataFetcherAgent  # noqa: E402
from app.agents.data_interpreter.service import DataInterpreterAgent  # noqa: E402
from app.agents.report_fusion.service import ReportFusionAgent  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.integrations.llm.mock import MockAnalysisModel, MockChapterWritingModel  # noqa: E402
from app.integrations.skillhub.mock import MockSkillHubClient  # noqa: E402
from app.integrations.skillhub.registry import create_skillhub_gateway  # noqa: E402
from app.runtime.tool_gateway import ToolExecutionError  # noqa: E402
from app.schemas.acquisition import SkillName  # noqa: E402
from app.schemas.workflow import StageName, StageStatus  # noqa: E402
from app.security.agent_guard import SecuredStageAgent  # noqa: E402
from app.workflow.graph import REINPUT_REQUIRED_ERRORS, build_pipeline_graph  # noqa: E402
from app.workflow.stages import StageRegistry  # noqa: E402
from app.workflow.state import create_pipeline_state  # noqa: E402

from eval.conftest import load_json_cases  # noqa: E402
from eval.transport import save_trace  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "test_output" / "eval_full_pipeline"
ARTIFACTS_DIR = OUTPUT_DIR / "artifacts"
TRACES_DIR = Path(__file__).resolve().parent / "traces"  # ./eval/traces/
MAX_RESUME_ROUNDS = 8
CASE_TIMEOUT_S = 240.0

# 上一轮（20260820T202353Z，mock 全链路）真实通过（五阶段零error+产物齐全）的用例，
# 本轮默认跳过不重复测试；--include-passed 可强制全量。
PASSED_LAST_ROUND = frozenset({"E-01", "E-06", "E-13", "E-31", "E-43", "T-05"})


class SelectivelyFailingClient(MockSkillHubClient):
    """T-07/T-08 历史构造：指定 mock skill 调用失败。"""

    provider_mode = "mock"

    def __init__(self, failing_skills: set[SkillName]) -> None:
        super().__init__()
        self._failing_skills = failing_skills

    async def execute(self, skill_name, args):
        if skill_name in self._failing_skills:
            self.calls.append((skill_name, args))
            raise ToolExecutionError("provider_unavailable", retryable=False)
        return await super().execute(skill_name, args)


class TraceRecordingClient:
    """record 模式：包装 SkillHub 客户端，录制每次 execute 的完整调用流水。

    不改变被包装客户端的任何行为（成功/失败原样透传），只在旁路记录
    skill / query / page / 返回行数 / raw_sha256 / 耗时 / 错误，供 trace 落盘。
    """

    def __init__(self, inner: MockSkillHubClient) -> None:
        self._inner = inner
        self.provider_mode = inner.provider_mode
        self.calls: list[dict[str, object]] = []

    async def execute(self, skill_name, args):
        started = time.monotonic()
        entry: dict[str, object] = {
            "skill": skill_name.value,
            "query": args.query,
            "page": args.page,
            "limit": args.limit,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            payload = await self._inner.execute(skill_name, args)
        except Exception as exc:
            entry.update(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:300],
                    "duration_ms": round((time.monotonic() - started) * 1000, 1),
                }
            )
            self.calls.append(entry)
            raise
        entry.update(
            {
                "ok": True,
                "rows": len(payload.rows),
                "total_count": payload.total_count,
                "raw_sha256": payload.raw_sha256,
                "source_name": payload.source_name,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
            }
        )
        self.calls.append(entry)
        return payload


def build_registry(client: TraceRecordingClient, *, decomposer) -> StageRegistry:
    """生产同构装配；意图拆解器可注入真实 LLM（--llm real）。"""
    return StageRegistry(
        [
            DataFetcherAgent(
                planner=QueryPlanner(),
                executor=RetrievalExecutor(create_skillhub_gateway(client)),
                provider_mode=client.provider_mode,
                intent_decomposer=decomposer,
            ),
            SecuredStageAgent(DataInterpreterAgent(model=MockAnalysisModel())),
            ChartGeneratorAgent(
                prompt_compiler=None,
                image_generator=None,
                generate_industry_chain_images=False,
            ),
            SecuredStageAgent(ChapterWriterAgent(model=MockChapterWritingModel())),
            ReportFusionAgent(),
        ]
    )


def build_real_decomposer():
    """从 settings 构造项目真实大模型意图拆解器（失败自动回退规则层）。"""
    from app.agents.data_fetcher.semantic_router import ResearchIntentDecomposer

    api_key = settings.LLM_API_KEY.get_secret_value() if settings.LLM_API_KEY else None
    if not api_key or not settings.LLM_BASE_URL:
        raise RuntimeError("live_llm_configuration_missing")
    return ResearchIntentDecomposer(
        model_name=settings.LLM_MODEL,
        api_key=api_key,
        base_url=settings.LLM_BASE_URL,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
    )


def _base_input(case: dict) -> dict:
    return {
        "industry_topic": case.get("industry_topic", "动力电池"),
        "market_scope": ["中国内地"],
        "security_types": ["普通股"],
        "reporting_currency": "CNY",
        "research_as_of": "2026-08-11",
        "focus_questions": [case["input"]],
        "evidence_items": [],
        "analysis_depth": "standard",
        "risk_preference": "balanced",
        "research_brief": {},
    }


async def _drive(graph, state, config) -> dict:
    """执行一条用例并自动处理审阅 interrupt，返回最终 graph state。"""
    result = await graph.ainvoke(state, config)
    for _round in range(MAX_RESUME_ROUNDS):
        interrupts = result.get("__interrupt__")
        if not interrupts:
            return result
        info = interrupts[0].value
        stage_result = info.get("result", {}) or {}
        error = stage_result.get("error")
        dp = (stage_result.get("data", {}) or {}).get("decision_package", {}) or {}
        expected_revision = info.get("revision", 1)

        # BUG-002 regression guard: a clarification block is a legal
        # human-in-the-loop stop. Approving it would push empty data through
        # all five stages and fabricate a "pass" verdict.
        if (
            error in REINPUT_REQUIRED_ERRORS
            or error == "intent_clarification_required"
        ):
            decision = {
                "action": "cancel",
                "expected_revision": expected_revision,
                "comment": "测试驱动：数据不可得属合法拦截，取消任务。",
            }
        elif stage_result.get("status") == "FAILED":
            decision = {"action": "regenerate", "expected_revision": expected_revision}
        elif dp:
            accepted = dp.get("acknowledgement_required_codes", [])
            decision = {
                "action": "accept_with_risks",
                "expected_revision": expected_revision,
                "decision_id": dp.get("decision_id", ""),
                "risk_snapshot_sha256": dp.get("risk_snapshot_sha256", ""),
                "accepted_risk_codes": accepted,
                "comment": "测试驱动：接受风险继续，验证全链路。",
            }
        else:
            decision = {
                "action": "approve",
                "expected_revision": expected_revision,
                "comment": "测试驱动：自动批准以继续全链路。",
            }
        try:
            result = await graph.ainvoke(Command(resume=decision), config)
        except ValueError:
            # 审阅校验拒绝（如 failed stage 不能 approve）→ 兜底 cancel，保证不卡死
            try:
                result = await graph.ainvoke(
                    Command(
                        resume={
                            "action": "cancel",
                            "expected_revision": result.get("revision", expected_revision),
                            "comment": "测试驱动：审阅校验拒绝，兜底取消。",
                        }
                    ),
                    config,
                )
            except Exception:
                return result
    return result


def _classify(case: dict, final: dict) -> tuple[str, str]:
    """把最终状态归类为 pass / intercept(合法拦截) / fail / blocked。"""
    status = final.get("status")
    stage_results = final.get("stage_results", {})
    last_stage = final.get("current_stage")
    last_result = stage_results.get(last_stage.value if last_stage else "", {}) or {}
    error = last_result.get("error")

    if status == StageStatus.COMPLETED:
        return "pass", "五阶段全部完成"
    if status == StageStatus.CANCELLED:
        if error in REINPUT_REQUIRED_ERRORS or error in {
            "required_data_unavailable",
            "requested_calculation_data_unavailable",
            "intent_clarification_required",
        }:
            return "intercept", f"合法拦截（{error}）"
        return "intercept", f"任务取消（{error or 'review'}）"
    if status == StageStatus.WAITING_REVIEW:
        # 区分：负向用例的预期拦截 vs 流程卡死
        if case.get("negative") and error:
            return "intercept", f"负向用例按预期拦截（{error}）"
        return "fail", f"停在 {last_stage.value if last_stage else '?'}（{error or 'WAITING_REVIEW'}）"
    if status == StageStatus.FAILED:
        return "fail", f"阶段失败 {last_stage.value if last_stage else '?'}（{error}）"
    return "blocked", f"异常状态 {status}"


def _intent_summary(final: dict) -> dict:
    """从 data_fetch 结果提取 intent_routing 摘要（本轮归因核心变量）。"""
    fetch = final.get("stage_results", {}).get("data_fetch", {}) or {}
    routing = (fetch.get("data", {}) or {}).get("intent_routing", {}) or {}
    plans = routing.get("plans", {}) or {}
    summary: dict[str, object] = {
        "enabled": routing.get("enabled", False),
        "strategy": routing.get("strategy", ""),
        "clarification_required": routing.get("clarification_required", []),
        "warnings": (routing.get("warnings", []) or [])[:20],
    }
    plan_digest: list[dict[str, object]] = []
    for question, plan in plans.items():
        plan_digest.append(
            {
                "question": question,
                "parser_mode": plan.get("parser_mode"),
                "complexity": plan.get("complexity"),
                "locked_skills": plan.get("locked_skills"),
                "accepted_skills": plan.get("accepted_skills"),
                "rejected_skills": plan.get("rejected_skills"),
                "requires_clarification": plan.get("requires_clarification"),
                "sub_requirements": [
                    {
                        "text": sub.get("normalized_text", "")[:120],
                        "skills": sub.get("candidate_skills"),
                        "source": sub.get("source"),
                        "clarify": sub.get("requires_clarification", False),
                    }
                    for sub in plan.get("sub_requirements", []) or []
                ],
            }
        )
    summary["plans"] = plan_digest
    return summary


def _stage_trace(final: dict) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for name, item in (final.get("stage_results", {}) or {}).items():
        out.append(
            {
                "stage": name,
                "status": item.get("status"),
                "error": item.get("error"),
            }
        )
    return out


async def run_case(case: dict, inner_client: MockSkillHubClient | None = None, *, decomposer) -> dict:
    """跑单条全链路用例（record 模式），返回 grades 一行。"""
    run_id = f"run-{case['id'].lower()}-{int(time.time())}"
    client = TraceRecordingClient(inner_client or MockSkillHubClient())
    registry = build_registry(client, decomposer=decomposer)
    graph = build_pipeline_graph(registry, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": run_id}}
    state = create_pipeline_state(
        project_id="eval-pipeline",
        run_id=run_id,
        input_data=_base_input(case),
    )

    started = time.monotonic()
    fault: str | None = None
    try:
        final = await asyncio.wait_for(_drive(graph, state, config), timeout=CASE_TIMEOUT_S)
    except TimeoutError:
        final = {"status": "blocked", "stage_results": {}, "current_stage": None}
        fault = f"case_timeout_{CASE_TIMEOUT_S}s"
    except Exception as exc:
        final = {"status": "blocked", "stage_results": {}, "current_stage": None}
        fault = f"driver_exception:{type(exc).__name__}:{exc}"

    elapsed = round(time.monotonic() - started, 2)
    verdict, reason = _classify(case, final)
    fusion = final.get("stage_results", {}).get("report_fusion", {})
    report_artifacts = [
        {"kind": a.get("kind"), "uri": a.get("uri")}
        for a in (fusion.get("artifacts", []) or [])
    ]
    fetch_data = (final.get("stage_results", {}).get("data_fetch", {}) or {}).get("data", {}) or {}
    return {
        "case_id": case["id"],
        "group": case.get("group", ""),
        "input": case["input"],
        "industry_topic": case.get("industry_topic", ""),
        "verdict": verdict,
        "reason": fault or reason,
        "status": str(final.get("status")),
        "elapsed_s": elapsed,
        "stages": {
            name: {"status": item.get("status"), "error": item.get("error")}
            for name, item in (final.get("stage_results", {}) or {}).items()
        },
        "report_artifacts": report_artifacts,
        "evidence_count": len(fetch_data.get("evidence_items", []) or []),
        "task_count": len((fetch_data.get("retrieval_plan", {}) or {}).get("tasks", []) or []),
        "skill_call_count": len(client.calls),
        "llm_mode": "real" if decomposer is not None else "mock",
        "skillhub_mode": client.provider_mode,
        "run_id": run_id,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "_final": final,
        "_skill_calls": client.calls,
    }


# 特殊构造用例（T 类构造语义 → 真实可执行输入/客户端）
def _synthetic_overrides(case_id: str) -> dict | None:
    if case_id == "T-05":
        return {"input": None, "focus_questions": ["宁德时代营业收入", "宁德时代营业收入"]}
    if case_id == "T-06":
        return {
            "input": None,
            "focus_questions": [
                "请结合动力电池行业近三年市场规模、增速、竞争格局、CR5集中度、"
                "龙头公司营收净利润毛利率、各项费用率、海外收入占比、产能利用率、"
                "产业链上游中下游盈利、碳酸锂期货价格、社融数据、板块估值分位、"
                "相关政策新闻以及机构评级变化做全面分析"
            ],
        }
    return None


async def run_all(
    limit: int | None = None,
    only_ids: list[str] | None = None,
    *,
    include_passed: bool = False,
    llm_mode: str = "mock",
) -> tuple[list[dict], int, int]:
    """跑用例并录制 trace。返回 (grades行, trace成功数, trace失败数)。"""
    cases = [c for c in load_json_cases("cases_v1.json")]
    # 只跑有真实用户输入的 E2E 与 T 类；S-* 专项构造类不在全链路驱动范围。
    cases = [c for c in cases if not c["id"].startswith("S-")]
    if only_ids:
        cases = [c for c in cases if c["id"] in only_ids]
    elif not include_passed:
        cases = [c for c in cases if c["id"] not in PASSED_LAST_ROUND]
    if limit:
        cases = cases[:limit]

    decomposer = build_real_decomposer() if llm_mode == "real" else None

    results: list[dict] = []
    trace_saved = 0
    trace_failed = 0
    for case in cases:
        cid = case["id"]
        client: MockSkillHubClient | None = None
        if cid == "T-07":
            client = SelectivelyFailingClient({SkillName.INSTITUTIONAL_RESEARCH})
        elif cid == "T-08":
            client = SelectivelyFailingClient({SkillName.MACRO, SkillName.FINANCE})
        elif cid == "T-12":
            # 轨迹构造类：需要按调用顺序注入错调轨迹，全链路驱动无法构造，
            # 如实标记 blocked 而非伪造通过。
            results.append(
                {
                    "case_id": cid,
                    "group": case.get("group", ""),
                    "input": case["input"],
                    "verdict": "blocked",
                    "reason": "轨迹构造类用例（先错调再补调）需专用轨迹注入器，本轮未实现",
                    "status": "-",
                    "elapsed_s": 0,
                    "stages": {},
                    "report_artifacts": [],
                    "evidence_count": 0,
                    "task_count": 0,
                    "skill_call_count": 0,
                    "llm_mode": llm_mode,
                    "run_id": "-",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            print(f"[SKIP-BLOCKED] {cid}")
            continue

        try:
            row = await run_case(case, inner_client=client, decomposer=decomposer)
        except Exception as exc:  # 用例级隔离：绝不因单条崩溃终止整套测试
            row = {
                "case_id": cid,
                "group": case.get("group", ""),
                "input": case.get("input", ""),
                "industry_topic": case.get("industry_topic", ""),
                "verdict": "blocked",
                "reason": f"isolated_fault:{type(exc).__name__}:{exc}",
                "status": "-",
                "elapsed_s": 0,
                "stages": {},
                "report_artifacts": [],
                "evidence_count": 0,
                "task_count": 0,
                "skill_call_count": 0,
                "llm_mode": llm_mode,
                "run_id": "-",
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }

        # ---- record 模式：trace 快照落盘 ./eval/traces/ ----
        final = row.pop("_final", {})
        skill_calls = row.pop("_skill_calls", [])
        trace = {
            "case_id": cid,
            "run_id": row["run_id"],
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "mode": "record",
            "llm_mode": llm_mode,
            "input": {
                "text": row.get("input", ""),
                "industry_topic": row.get("industry_topic", ""),
                "focus_questions": [row.get("input", "")],
            },
            "verdict": {"verdict": row["verdict"], "reason": row["reason"], "elapsed_s": row["elapsed_s"]},
            "stages": _stage_trace(final),
            "intent_routing": _intent_summary(final),
            "skill_calls": skill_calls,
            "skill_call_count": len(skill_calls),
            "evidence_count": row["evidence_count"],
            "task_count": row["task_count"],
            "report_artifacts": row["report_artifacts"],
        }
        try:
            path = save_trace(
                trace,
                traces_dir=TRACES_DIR,
                filename=f"{cid}__{row['run_id']}.json",
            )
            row["trace_file"] = str(path)
            trace_saved += 1
        except Exception as exc:
            row["trace_file"] = None
            row["trace_error"] = f"{type(exc).__name__}:{exc}"
            trace_failed += 1

        results.append(row)
        icon = {"pass": "PASS", "intercept": "INTRC", "fail": "FAIL", "blocked": "BLK"}[
            row["verdict"]
        ]
        print(
            f"[{icon}] {row['case_id']:6s} {row['elapsed_s']:6.1f}s "
            f"mode={row['stages'].get('data_fetch', {}).get('error') or 'ok' if row['stages'] else '-'} "
            f"{row['reason'][:70]}"
        )
    return results, trace_saved, trace_failed


def write_grades(results: list[dict], run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "grades.jsonl").open("w", encoding="utf-8") as fh:
        for row in results:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only", type=str, default=None, help="逗号分隔用例ID")
    parser.add_argument("--include-passed", action="store_true", help="包含上轮已通过用例")
    parser.add_argument("--llm", choices=["mock", "real"], default="mock", help="Agent 1 意图拆解器用真实大模型")
    args = parser.parse_args(argv)

    if args.llm == "real":
        parser.error("此 runner 含 Mock SkillHub/Agent2/Agent4；真实评测请使用 python -m eval.real_runner")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    settings.ARTIFACT_ROOT = ARTIFACTS_DIR
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    only_ids = args.only.split(",") if args.only else None
    results, trace_saved, trace_failed = asyncio.run(
        run_all(
            limit=args.limit,
            only_ids=only_ids,
            include_passed=args.include_passed,
            llm_mode=args.llm,
        )
    )

    run_dir = OUTPUT_DIR / "transcript" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_grades(results, run_dir)

    counts: dict[str, int] = {}
    for row in results:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    summary = {
        "llm_mode": args.llm,
        "mode": "record",
        "total": len(results),
        "pass": counts.get("pass", 0),
        "intercept": counts.get("intercept", 0),
        "fail": counts.get("fail", 0),
        "blocked": counts.get("blocked", 0),
        "trace_saved": trace_saved,
        "trace_failed": trace_failed,
        "traces_dir": str(TRACES_DIR),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("\n===== 全链路评测汇总（record 模式） =====")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"grades: {run_dir / 'grades.jsonl'}")
    print(f"traces: {TRACES_DIR}（成功 {trace_saved} 条 / 失败 {trace_failed} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
