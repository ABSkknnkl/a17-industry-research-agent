"""Live-only five-agent evaluation runner with dedupe cache and trace archive.

This module deliberately does not import any Mock provider.  It is the only
entry point for paid evaluation runs; legacy replay/mock runners remain useful
for historical developer tests but cannot label their output as a live trace.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.chapter_writer.service import ChapterWriterAgent
from app.agents.chart_generator.service import ChartGeneratorAgent
from app.agents.data_fetcher.executor import RetrievalExecutor
from app.agents.data_fetcher.planner import QueryPlanner
from app.agents.data_fetcher.semantic_router import (
    OpenAICompatibleSemanticRouter,
    ResearchIntentDecomposer,
)
from app.agents.data_fetcher.service import DataFetcherAgent
from app.agents.data_interpreter.service import DataInterpreterAgent
from app.agents.report_fusion.service import ReportFusionAgent
from app.core.config import settings
from app.integrations.llm.openai_compatible import (
    OpenAICompatibleAnalysisModel,
    OpenAICompatibleChapterModel,
)
from app.integrations.skillhub.client import IwencaiSkillClient
from app.integrations.skillhub.registry import create_skillhub_gateway
from app.runtime.model_gateway import RuntimeAwareAnalysisModel, RuntimeAwareChapterWritingModel
from app.runtime.models import RuntimePolicy
from app.schemas.workflow import StageName
from app.security.agent_guard import SecuredStageAgent
from app.workflow.graph import REINPUT_REQUIRED_ERRORS, build_pipeline_graph
from app.workflow.stages import StageRegistry
from app.workflow.state import create_pipeline_state

from eval.case_schema import load_case_suite, validate_case_suite
from eval.harness import build_gate_record, evaluate_terminal_state, target_stage_for
from eval.provider_mode import ProviderModeError, validate_provider_identity
from eval.scorers.intent import evaluate_intent_case
from eval.scorers.rules import registered_check_ids, run_l1_checks
from eval.scorers.stages import score_expected_stages, score_handoffs
from eval.transport import (
    EvaluationStop,
    LiveContentAddressedTransport,
    StopController,
)
from eval.triage import BugRecord, BugSummary, ErrorSignals, RootCause, classify_by_signal


MAX_RESUME_ROUNDS = 8
CACHE_DIR = ROOT / "eval" / "cache" / "live_content_addressed"
TRANSCRIPT_ROOT = ROOT / "eval" / "transcript"


class LiveConfigurationError(RuntimeError):
    pass


@dataclass
class LiveRun:
    root: Path
    traces_file: Path
    grades_file: Path
    manifest_file: Path
    bugs_file: Path

    @classmethod
    def create(cls) -> "LiveRun":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        root = TRANSCRIPT_ROOT / f"real_run_{stamp}"
        root.mkdir(parents=True, exist_ok=False)
        return cls(
            root=root,
            traces_file=root / "traces.jsonl",
            grades_file=root / "grades.jsonl",
            manifest_file=root / "run_manifest.json",
            bugs_file=root / "BUGS.md",
        )

    def append_jsonl(self, path: Path, item: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

    def write_manifest(self, item: dict[str, Any]) -> None:
        self.manifest_file.write_text(
            json.dumps(item, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )


class RecordingSkillClient:
    """Records real SkillHub executions without changing their actual result."""

    provider_mode = "live"

    def __init__(self, inner: IwencaiSkillClient) -> None:
        self._inner = inner
        validate_provider_identity(
            declared_mode=self.provider_mode,
            implementation_path=f"{type(inner).__module__}.{type(inner).__name__}",
        )
        self.calls: list[dict[str, Any]] = []

    async def execute(self, skill_name, args):
        started = time.monotonic()
        row: dict[str, Any] = {
            "skill": skill_name.value,
            "query": args.query,
            "page": args.page,
            "limit": args.limit,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            payload = await self._inner.execute(skill_name, args)
        except Exception as exc:
            row.update(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                    "duration_ms": round((time.monotonic() - started) * 1000, 1),
                }
            )
            self.calls.append(row)
            raise
        row.update(
            {
                "ok": True,
                "rows": len(payload.rows),
                "total_count": payload.total_count,
                "raw_sha256": payload.raw_sha256,
                "trace_id": payload.trace_id,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
            }
        )
        self.calls.append(row)
        return payload


def _secret_value(secret: Any) -> str | None:
    return secret.get_secret_value() if secret is not None else None


def assert_real_configuration() -> None:
    if settings.LLM_USE_MOCK:
        raise LiveConfigurationError("LLM_USE_MOCK=true: live evaluation is forbidden")
    if settings.SKILLHUB_USE_MOCK:
        raise LiveConfigurationError("SKILLHUB_USE_MOCK=true: live evaluation is forbidden")
    if not _secret_value(settings.LLM_API_KEY) or not settings.LLM_BASE_URL:
        raise LiveConfigurationError("live_llm_configuration_missing")
    if not _secret_value(settings.IWENCAI_API_KEY or settings.SKILLHUB_API_KEY):
        raise LiveConfigurationError("live_skillhub_configuration_missing")


def _live_chat(transport: LiveContentAddressedTransport) -> tuple[ChatOpenAI, httpx.AsyncClient]:
    api_key = _secret_value(settings.LLM_API_KEY)
    client = httpx.AsyncClient(
        transport=transport,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        trust_env=False,
    )
    kwargs: dict[str, Any] = {
        "model": settings.LLM_MODEL,
        "api_key": api_key,
        "base_url": settings.LLM_BASE_URL,
        "temperature": 0,
        "timeout": settings.LLM_TIMEOUT_SECONDS,
        "max_retries": 0,
        "model_kwargs": {"max_tokens": settings.LLM_MAX_OUTPUT_TOKENS},
        "http_async_client": client,
    }
    if settings.LLM_MODEL.lower().startswith("deepseek-"):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    return ChatOpenAI(**kwargs), client


def build_live_registry(
    *,
    skill_transport: LiveContentAddressedTransport,
    llm_transport: LiveContentAddressedTransport,
) -> tuple[StageRegistry, RecordingSkillClient, httpx.AsyncClient]:
    """Construct the production stages with only live, intercepted providers."""
    assert_real_configuration()
    skill_client = RecordingSkillClient(
        IwencaiSkillClient(
            api_key=_secret_value(settings.IWENCAI_API_KEY or settings.SKILLHUB_API_KEY),
            base_url=settings.IWENCAI_BASE_URL,
            timeout_seconds=settings.TOOL_TIMEOUT_SECONDS,
            max_retries=0,
            transport=skill_transport,
        )
    )
    gateway = create_skillhub_gateway(
        skill_client,
        runtime_policy=RuntimePolicy(
            tool_timeout_seconds=settings.TOOL_TIMEOUT_SECONDS,
            max_tool_calls=settings.MAX_TOOL_CALLS_PER_RUN,
            max_tool_result_chars=settings.MAX_TOOL_RESULT_CHARS,
        ),
    )
    chat, async_client = _live_chat(llm_transport)
    semantic_router = None
    if settings.AGENT1_SEMANTIC_ROUTER_ENABLED:
        # Mirror the production factory: long-tail metric routing goes through
        # the shared cached chat model so every LLM call stays deduplicated.
        semantic_router = OpenAICompatibleSemanticRouter(
            model_name=settings.LLM_MODEL,
            api_key=_secret_value(settings.LLM_API_KEY) or "",
            base_url=settings.LLM_BASE_URL or "",
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
            chat_model=chat,
        )
    decomposer = ResearchIntentDecomposer(
        model_name=settings.LLM_MODEL,
        api_key=_secret_value(settings.LLM_API_KEY) or "",
        base_url=settings.LLM_BASE_URL or "",
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        chat_model=chat,
    )
    analysis = OpenAICompatibleAnalysisModel(
        model_name=settings.LLM_MODEL,
        chat_model=chat,
        segmented_threshold_chars=settings.LLM_SEGMENTED_THRESHOLD_CHARS,
    )
    chapter = OpenAICompatibleChapterModel(model_name=settings.LLM_MODEL, chat_model=chat)
    registry = StageRegistry(
        [
            DataFetcherAgent(
                planner=QueryPlanner(max_pages=settings.SKILLHUB_MAX_PAGES),
                executor=RetrievalExecutor(
                    gateway,
                    concurrency=1,
                    page_size=settings.SKILLHUB_PAGE_SIZE,
                ),
                provider_mode="live",
                semantic_router=semantic_router,
                semantic_confidence_threshold=settings.AGENT1_SEMANTIC_ROUTER_CONFIDENCE,
                intent_decomposer=decomposer,
                intent_confidence_accept=settings.AGENT1_INTENT_CONFIDENCE_ACCEPT,
                intent_confidence_review=settings.AGENT1_INTENT_CONFIDENCE_REVIEW,
            ),
            SecuredStageAgent(DataInterpreterAgent(model=RuntimeAwareAnalysisModel(analysis))),
            # Image generation is intentionally disabled for this data/LLM evaluation.
            ChartGeneratorAgent(
                prompt_compiler=None,
                image_generator=None,
                generate_industry_chain_images=False,
            ),
            SecuredStageAgent(
                ChapterWriterAgent(model=RuntimeAwareChapterWritingModel(chapter))
            ),
            ReportFusionAgent(),
        ]
    )
    registry.validate_complete()
    return registry, skill_client, async_client


def _input_for(case: dict[str, Any]) -> dict[str, Any]:
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
        "data_fetch_options": {},
    }


async def _drive(graph, state: dict[str, Any], config: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Resume only non-error human review gates; genuine failures stay visible."""
    result = await graph.ainvoke(state, config)
    for _ in range(MAX_RESUME_ROUNDS):
        interrupts = result.get("__interrupt__")
        if not interrupts:
            return result
        info = interrupts[0].value
        stage_result = info.get("result", {}) or {}
        error = stage_result.get("error")
        stage = str(stage_result.get("stage", ""))
        stage_data = stage_result.get("data", {}) or {}
        collabs = stage_data.get("collaboration_requests", []) or []
        has_blocking_collab = any(
            (item.get("blocking") or item.get("severity") == "blocking")
            for item in collabs
            if isinstance(item, dict)
        )
        target = target_stage_for(case)
        if target and stage == target and not error:
            # A partial-chain case (intent / tool-plan / specialized) reached
            # its target stage's review gate with a clean result.  Stop here
            # instead of resuming, so downstream LLM and SkillHub calls are
            # never spent on stages the case does not evaluate.
            result["current_stage"] = stage
            return result
        is_intercept = case.get("expected_outcome") == "intercept"
        if error or (has_blocking_collab and is_intercept):
            # A genuine interception.  Hard stops carry an error code; soft
            # stops carry a blocking collaboration request.  Both must pause
            # the pipeline so fail-closed grading sees the real stop stage.
            # Positive cases resume through blocking requests so the full
            # chain can be evaluated end to end.
            result["current_stage"] = stage
            return result
        package = stage_data.get("decision_package", {}) or {}
        revision = info.get("revision", 1)
        if package:
            decision = {
                "action": "accept_with_risks",
                "expected_revision": revision,
                "decision_id": package.get("decision_id", ""),
                "risk_snapshot_sha256": package.get("risk_snapshot_sha256", ""),
                "accepted_risk_codes": package.get("acknowledgement_required_codes", []),
                "comment": "真实评测：接受已披露风险，继续验证下游契约。",
            }
        else:
            decision = {
                "action": "approve",
                "expected_revision": revision,
                "comment": "真实评测：自动批准非错误人工审核节点。",
            }
        result = await graph.ainvoke(Command(resume=decision), config)
    result["current_stage"] = result.get("current_stage") or "review_gate"
    return result


def _stage_data(final: dict[str, Any], stage: str) -> dict[str, Any]:
    return ((final.get("stage_results", {}) or {}).get(stage, {}) or {}).get("data", {}) or {}


def _stage_status(final: dict[str, Any], stage: str) -> str:
    # Scorers compare against uppercase enum names (WAITING_REVIEW/COMPLETED).
    raw = ((final.get("stage_results", {}) or {}).get(stage, {}) or {}).get("status", "") or ""
    return str(raw).upper()


def extract_artifacts(final: dict[str, Any]) -> dict[str, Any]:
    fetch = dict(_stage_data(final, "data_fetch"))
    analysis = dict(_stage_data(final, "data_interpret"))
    charts = _stage_data(final, "chart_generate")
    chapters = _stage_data(final, "chapter_write")
    fusion = _stage_data(final, "report_fusion")
    # Scorers (C3/P1/G5) read the stage terminal status, which lives on the
    # StageResult, not inside its data payload.  Inject it so rule checks see
    # the real WAITING_REVIEW/COMPLETED state instead of an empty string.
    fetch.setdefault("status", _stage_status(final, "data_fetch"))
    analysis.setdefault("status", _stage_status(final, "data_interpret"))
    return {
        "fetch_result": fetch,
        "retrieval_plan": fetch.get("retrieval_plan", {}),
        "analysis": analysis,
        "charts": charts.get("chart_specs", []),
        "report": {"chapters": chapters.get("chapters", []), "fusion": fusion},
    }


def _check_rows(case: dict[str, Any], final: dict[str, Any]) -> list[dict[str, Any]]:
    l1_ids = [item for item in case.get("checks", []) if item not in {*(f"I{i}" for i in range(1, 9)), "M1", "M2", "M3"}]
    rows = [
        {"check_id": item.check_id, "passed": item.passed, "reason": item.reason}
        for item in run_l1_checks(extract_artifacts(final), case, checks=l1_ids)
    ]
    intent = _stage_data(final, "data_fetch").get("intent_routing", {}) or {}
    plans = intent.get("plans", []) or intent.get("intent_plans", []) or []
    if isinstance(plans, dict):
        plans = list(plans.values())
    if case["id"].startswith("I-"):
        evaluated = evaluate_intent_case(plans[0] if plans else {}, case)
        condensed = {
            "I1": evaluated["I1"],
            "I2": evaluated["I2"],
            "I3": evaluated["I3_required"] and evaluated["I3_forbidden"],
            "I4": evaluated["I4_entity"] and evaluated["I4_time"],
            "I5": evaluated["I5"],
            "I6": evaluated["I6"],
            "I7": evaluated["I7_mode"],
            "I8": evaluated["I8_stable_signature_available"],
        }
        rows.extend(
            {"check_id": key, "passed": value, "reason": "真实意图计划断言"}
            for key, value in condensed.items()
            if key in case.get("checks", [])
        )
    rows.extend(score_expected_stages(case, final))
    rows.extend(score_handoffs(case, final))
    return rows


async def _score_l2_semantics(
    *,
    case: dict[str, Any],
    final: dict[str, Any],
    http_client: httpx.AsyncClient,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Use the configured live LLM once for the semantic/M1-M3 judgement.

    The project has no separately configured second judge family.  We record
    that limitation explicitly instead of claiming a nonexistent dual-family
    panel; a later configured Judge-B can be added without changing any case
    or business rule.
    """
    if case.get("expected_outcome") != "completed":
        return ({"status": "not_applicable", "score": None}, [])
    summary = {
        "case_id": case["id"],
        "input": case["input"],
        "required_methodologies": case.get("required_methodologies", []),
        "analysis": _stage_data(final, "data_interpret"),
        "chapters": _stage_data(final, "chapter_write").get("chapters", []),
    }
    compact = json.dumps(summary, ensure_ascii=False, default=str)[:24_000]
    judge = ChatOpenAI(
        model=settings.LLM_MODEL,
        api_key=_secret_value(settings.LLM_API_KEY),
        base_url=settings.LLM_BASE_URL,
        temperature=0,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=0,
        model_kwargs={"max_tokens": 600},
        http_async_client=http_client,
    )
    system = (
        "你是金融研究报告评测法官。仅依据给定产物判定，不得补充事实。"
        "输出严格 JSON：{\"score\":0到1,\"M1\":bool,\"M2\":bool,\"M3\":bool,\"reason\":\"一句话\"}。"
        "M1=要求的方法论确实被触发；M2=没有无关方法论；M3=每个触发方法论有维度和场景。"
    )
    try:
        response = await judge.ainvoke([SystemMessage(content=system), HumanMessage(content=compact)])
        text = response.content if isinstance(response.content, str) else str(response.content)
        start, end = text.find("{"), text.rfind("}")
        payload = json.loads(text[start : end + 1]) if start >= 0 and end >= start else {}
        score = float(payload.get("score", 0))
        result = {
            "status": "scored",
            "score": max(0.0, min(score, 1.0)),
            "reason": str(payload.get("reason", ""))[:500],
            "panel": "single_live_model_secondary_not_configured",
        }
        checks = [
            {
                "check_id": item,
                "passed": bool(payload.get(item, False)),
                "reason": result["reason"] or "real_l2_judge",
            }
            for item in (set(case.get("checks", [])) & {"M1", "M2", "M3"})
        ]
        return result, checks
    except Exception as exc:
        return (
            {
                "status": "failed",
                "score": 0.0,
                "reason": f"real_l2_judge_error:{type(exc).__name__}",
                "panel": "single_live_model_secondary_not_configured",
            },
            [
                {"check_id": item, "passed": False, "reason": "real_l2_judge_failed"}
                for item in (set(case.get("checks", [])) & {"M1", "M2", "M3"})
            ],
        )


def _reached_subgoals(final: dict[str, Any]) -> list[str]:
    stages = final.get("stage_results", {}) or {}
    mapping = {
        "data_fetch": ["a1_plan", "a1_fetch"],
        "data_interpret": ["a2_calc"],
        "chart_generate": ["a3_chart"],
        "chapter_write": ["a4_chapter"],
        "report_fusion": ["a5_export"],
    }
    return [goal for stage, goals in mapping.items() if stage in stages for goal in goals]


def _bug_from_grade(case: dict[str, Any], grade: dict[str, Any]) -> BugRecord:
    reason = str(grade.get("reason", "unknown failure"))
    if any(token in reason for token in ("provider", "rate", "access", "ToolExecution")):
        root = RootCause.C_TOOL
    elif "stage error" in reason or "missing" in reason:
        root = RootCause.E_BUSINESS
    else:
        root = classify_by_signal(ErrorSignals(error_type=reason)) or RootCause.A_PROMPT
    return BugRecord(
        agent_id="five_agent_chain",
        fault_level="blocking" if case.get("must_pass") else "defect",
        repro_input=case["input"],
        observed=reason,
        snapshot_fragment=grade.get("trace_file", "traces.jsonl"),
        root_cause=root,
        fix_suggestion="根据 trace 中首个失败 stage 修复，不改变 V7 业务规则。",
        ship_ready=False,
    )


async def run_case(
    case: dict[str, Any],
    *,
    run: LiveRun,
    controller: StopController,
) -> dict[str, Any]:
    skill_transport = LiveContentAddressedTransport(
        cache_dir=CACHE_DIR, provider="skillhub", controller=controller
    )
    llm_transport = LiveContentAddressedTransport(
        cache_dir=CACHE_DIR, provider="llm", controller=controller
    )
    registry, skill_client, llm_client = build_live_registry(
        skill_transport=skill_transport, llm_transport=llm_transport
    )
    run_id = f"live-{case['id'].lower().replace('-', '_')}-{int(time.time())}"
    graph = build_pipeline_graph(registry, checkpointer=InMemorySaver())
    state = create_pipeline_state(
        project_id="real-evaluation",
        run_id=run_id,
        input_data=_input_for(case),
        review_stages=[StageName.DATA_FETCH, StageName.DATA_INTERPRET],
    )
    config = {"configurable": {"thread_id": run_id}}
    started = time.monotonic()
    final: dict[str, Any]
    caught: str | None = None
    try:
        final = await _drive(graph, state, config, case)
    except EvaluationStop as exc:
        controller.stop(exc.code, exc.detail)
        final = {"status": "BLOCKED", "stage_results": {}, "current_stage": None}
        caught = str(exc)
    except Exception as exc:  # a real exception must be traced and graded, never hidden
        final = {"status": "BLOCKED", "stage_results": {}, "current_stage": None}
        caught = f"{type(exc).__name__}:{exc}"
    finally:
        await skill_transport.aclose()

    terminal = evaluate_terminal_state(case, final)
    checks = _check_rows(case, final) if caught is None else []
    l2, l2_checks = (
        await _score_l2_semantics(case=case, final=final, http_client=llm_client)
        if caught is None and terminal.passed
        else ({"status": "not_run", "score": None}, [])
    )
    checks.extend(l2_checks)
    if caught:
        checks.append({"check_id": "EXECUTION", "passed": False, "reason": caught})
    gate = build_gate_record(case, check_results=checks, reached_subgoals=_reached_subgoals(final))
    passed = terminal.passed and gate["gate"] == "PASS" and all(item["passed"] for item in checks)
    verdict = terminal.verdict if passed else ("blocked" if controller.stopped else "fail")
    trace = {
        "trace_version": "real-transport-v1",
        "provider_mode": "live",
        "case": case,
        "run_id": run_id,
        "elapsed_s": round(time.monotonic() - started, 3),
        "final": final,
        "skill_calls": skill_client.calls,
        "transport": [*map(asdict, skill_transport.events), *map(asdict, llm_transport.events)],
        "terminal": asdict(terminal),
        "checks": checks,
        "l2": l2,
        "gate": gate,
        "stop": {"code": controller.code, "detail": controller.detail},
    }
    await llm_client.aclose()
    await llm_transport.aclose()
    run.append_jsonl(run.traces_file, trace)
    grade = {
        "case_id": case["id"],
        "verdict": verdict,
        "passed": passed,
        "reason": caught or terminal.reason,
        "checks": checks,
        "l2": l2,
        "gate": gate,
        "provider_mode": "live",
        "trace_file": str(run.traces_file),
        "elapsed_s": trace["elapsed_s"],
        "external_requests": sum(1 for event in trace["transport"] if not event["cache_hit"]),
        "cache_hits": sum(1 for event in trace["transport"] if event["cache_hit"]),
    }
    run.append_jsonl(run.grades_file, grade)
    return grade


async def run_cases(case_ids: list[str] | None = None, *, limit: int | None = None) -> int:
    run = LiveRun.create()
    try:
        assert_real_configuration()
    except LiveConfigurationError as exc:
        run.write_manifest(
            {
                "mode": "live",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "stop": {"code": "configuration_invalid", "detail": str(exc)},
                "cases_completed": [],
            }
        )
        run.bugs_file.write_text(f"# 缺陷统计\n\n- 阻断故障数：1\n- 配置：{exc}\n", encoding="utf-8")
        print(f"archive={run.root}")
        return 2
    cases = load_case_suite()
    errors = validate_case_suite(cases, registered_checks=registered_check_ids())
    if errors:
        raise LiveConfigurationError("case_schema_invalid: " + "; ".join(errors))
    selected = [case for case in cases if not case_ids or case["id"] in set(case_ids)]
    selected.sort(key=lambda item: (not bool(item.get("must_pass")), item["id"]))
    if limit:
        selected = selected[:limit]
    original_artifact_root = settings.ARTIFACT_ROOT
    settings.ARTIFACT_ROOT = run.root / "artifacts"
    controller = StopController()
    bug_summary = BugSummary()
    manifest = {
        "mode": "live",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": settings.LLM_MODEL,
        "llm_base_url_configured": bool(settings.LLM_BASE_URL),
        "skillhub_base_url": settings.IWENCAI_BASE_URL,
        "cache_dir": str(CACHE_DIR),
        "image_generation": "disabled_by_evaluation_scope",
        "cases_planned": [case["id"] for case in selected],
    }
    run.write_manifest(manifest)
    grades: list[dict[str, Any]] = []
    try:
        for index, case in enumerate(selected, 1):
            if controller.stopped:
                break
            grade = await run_case(case, run=run, controller=controller)
            grades.append(grade)
            if not grade["passed"]:
                bug_summary.bugs.append(_bug_from_grade(case, grade))
            print(
                f"[{index}/{len(selected)}] {case['id']} {grade['verdict']} "
                f"requests={grade['external_requests']} cache_hits={grade['cache_hits']}"
            )
    finally:
        settings.ARTIFACT_ROOT = original_artifact_root
        bug_summary_text = bug_summary.render()
        run.bugs_file.write_text(bug_summary_text, encoding="utf-8")
        manifest.update(
            {
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "cases_completed": [item["case_id"] for item in grades],
                "passed": sum(1 for item in grades if item["passed"]),
                "failed_or_blocked": sum(1 for item in grades if not item["passed"]),
                "external_requests": sum(item["external_requests"] for item in grades),
                "cache_hits": sum(item["cache_hits"] for item in grades),
                "stop": {"code": controller.code, "detail": controller.detail},
            }
        )
        run.write_manifest(manifest)
        print(f"archive={run.root}")
    return 2 if controller.stopped else (0 if all(item["passed"] for item in grades) else 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="pure live five-agent evaluator")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_cases(args.case_ids, limit=args.limit)))


if __name__ == "__main__":
    main()
