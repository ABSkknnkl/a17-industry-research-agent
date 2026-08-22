"""L4a AI-surrogate five-agent evaluation runner (EVALUATION_PLAN §2.7, V8).

Replaces the Agent 1/2/4 LLM injection points with the deterministic
surrogate models from ``eval.surrogate_models`` while keeping SkillHub fully
live.  Zero LLM quota is consumed; the goal is to validate agent production
capability — positive cases must produce the complete report (7 chapters /
21 sections + MD/HTML/PDF/manifest) — before L4b re-enables the real LLM.

Honesty red lines (§2.7, aligned with the user's one-vote veto list):

- every trace/grade/manifest row carries ``mode="surrogate"``,
  ``llm_mode="surrogate"`` and ``skillhub_mode="live"`` so a surrogate run
  can never be mistaken for a real LLM run (代打冒充真实调用 = BLOCK);
- M1-M3 are scored deterministically via methodology→skill evidence
  tracing, never by an LLM in this mode;
- fail-closed semantics (terminal state, gate, bug archive) are identical
  to ``eval.real_runner`` so L4a and L4b results stay comparable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agents.chapter_writer.service import ChapterWriterAgent
from app.agents.chart_generator.service import ChartGeneratorAgent
from app.agents.data_fetcher.executor import RetrievalExecutor
from app.agents.data_fetcher.planner import QueryPlanner
from app.agents.data_fetcher.service import DataFetcherAgent
from app.agents.data_interpreter.service import DataInterpreterAgent
from app.agents.report_fusion.service import ReportFusionAgent
from app.core.config import settings
from app.integrations.skillhub.client import IwencaiSkillClient
from app.integrations.skillhub.registry import create_skillhub_gateway
from app.runtime.model_gateway import (
    RuntimeAwareAnalysisModel,
    RuntimeAwareChapterWritingModel,
)
from app.runtime.models import RuntimePolicy
from app.schemas.acquisition import SkillName
from app.schemas.workflow import StageName
from app.security.agent_guard import SecuredStageAgent
from app.workflow.graph import build_pipeline_graph
from app.workflow.stages import StageRegistry
from app.workflow.state import create_pipeline_state

from eval.case_schema import load_case_suite, validate_case_suite
from eval.harness import build_gate_record, evaluate_terminal_state
from eval.real_runner import (
    CACHE_DIR,
    TRANSCRIPT_ROOT,
    RecordingSkillClient,
    _bug_from_grade,
    _check_rows,
    _drive,
    _input_for,
    _reached_subgoals,
    _secret_value,
    _stage_data,
)
from eval.scorers.rules import registered_check_ids
from eval.surrogate_models import (
    SURROGATE_MODEL_NAME,
    SurrogateAnalysisModel,
    SurrogateChapterModel,
    SurrogateDecomposer,
    SurrogateSemanticRouter,
)
from eval.transport import (
    EvaluationStop,
    LiveContentAddressedTransport,
    StopController,
)
from eval.triage import BugSummary


class SurrogateConfigurationError(RuntimeError):
    pass


class SurrogateRun:
    """Archive layout identical to LiveRun but under surrogate_run_*."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.traces_file = root / "traces.jsonl"
        self.grades_file = root / "grades.jsonl"
        self.manifest_file = root / "run_manifest.json"
        self.bugs_file = root / "BUGS.md"

    @classmethod
    def create(cls) -> "SurrogateRun":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        root = TRANSCRIPT_ROOT / f"surrogate_run_{stamp}"
        root.mkdir(parents=True, exist_ok=False)
        return cls(root)

    def append_jsonl(self, path: Path, item: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

    def write_manifest(self, item: dict[str, Any]) -> None:
        self.manifest_file.write_text(
            json.dumps(item, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )


def assert_surrogate_configuration() -> None:
    """L4a needs a live SkillHub only; LLM settings are deliberately unused."""
    if settings.SKILLHUB_USE_MOCK:
        raise SurrogateConfigurationError(
            "SKILLHUB_USE_MOCK=true: surrogate evaluation requires the live SkillHub"
        )
    if not _secret_value(settings.IWENCAI_API_KEY or settings.SKILLHUB_API_KEY):
        raise SurrogateConfigurationError("live_skillhub_configuration_missing")


def build_surrogate_registry(
    *, skill_transport: LiveContentAddressedTransport
) -> tuple[StageRegistry, RecordingSkillClient]:
    """Production stages with surrogate LLM substitutes and a live SkillHub."""
    assert_surrogate_configuration()
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
                semantic_router=SurrogateSemanticRouter(),
                semantic_confidence_threshold=settings.AGENT1_SEMANTIC_ROUTER_CONFIDENCE,
                intent_decomposer=SurrogateDecomposer(),
                intent_confidence_accept=settings.AGENT1_INTENT_CONFIDENCE_ACCEPT,
                intent_confidence_review=settings.AGENT1_INTENT_CONFIDENCE_REVIEW,
            ),
            SecuredStageAgent(
                DataInterpreterAgent(model=RuntimeAwareAnalysisModel(SurrogateAnalysisModel()))
            ),
            # Image generation stays disabled: L4a measures agent production
            # capability, not the image model (user scoping decision).
            ChartGeneratorAgent(
                prompt_compiler=None,
                image_generator=None,
                generate_industry_chain_images=False,
            ),
            SecuredStageAgent(
                ChapterWriterAgent(
                    model=RuntimeAwareChapterWritingModel(SurrogateChapterModel())
                )
            ),
            ReportFusionAgent(),
        ]
    )
    registry.validate_complete()
    return registry, skill_client


# ---------------------------------------------------------------------------
# Deterministic M1-M3 scoring (replaces the L4b live-LLM judge).
# ---------------------------------------------------------------------------

_METHODOLOGY_SKILL: dict[str, SkillName] = {
    "financial_statement": SkillName.FINANCE,
    "commodity_analysis": SkillName.FUTURES,
    "competitive_landscape": SkillName.STOCK_SELECTOR,
    "restricted_industry_chain": SkillName.INDUSTRY_CHAIN,
    "macro_cycle": SkillName.MACRO,
    "behavioral_finance": SkillName.NEWS,
    "institutional_research": SkillName.INSTITUTIONAL_RESEARCH,
}

# Methodology-bearing conditional P1 skills.  P0 methodology skills
# (FINANCE/MACRO/INDUSTRY_CHAIN/NEWS) belong to the standard-depth full scan
# (established semantics per the T-02/T-03/T-11 ruling), so their evidence
# presence is not a false trigger; only conditional P1 methodology skills can
# be "wrongly triggered".
_CONDITIONAL_METHODOLOGY_SKILLS = (
    SkillName.FUTURES,
    SkillName.STOCK_SELECTOR,
    SkillName.INSTITUTIONAL_RESEARCH,
)


def _evidence_skill(evidence: dict[str, Any]) -> str | None:
    """Recover the retrieving skill from the normalizer's notes prefix."""
    notes = str(evidence.get("notes") or "")
    if notes.startswith("通过") and "获取" in notes:
        return notes[len("通过") : notes.index("获取")]
    return None


def _score_m_checks(
    case: dict[str, Any],
    final: dict[str, Any],
    skill_calls: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """M1-M3 without any LLM: methodology -> skill -> evidence -> claim tracing."""
    wanted = set(case.get("required_methodologies", []))
    m_ids = set(case.get("checks", [])) & {"M1", "M2", "M3"}
    if not m_ids:
        return {"status": "not_applicable", "score": None, "panel": "deterministic_surrogate"}, []

    fetch = _stage_data(final, "data_fetch")
    analysis = _stage_data(final, "data_interpret")
    evidence_skill = {
        str(item.get("evidence_id")): _evidence_skill(item)
        for item in (fetch.get("evidence_items", []) or [])
        if isinstance(item, dict)
    }
    claim_evidence: dict[str, list[str]] = {
        str(claim.get("claim_id")): [str(e) for e in claim.get("evidence_ids", []) or []]
        for claim in (analysis.get("claims", []) or [])
        if isinstance(claim, dict)
    }
    called_ok = {str(row.get("skill")) for row in skill_calls if row.get("ok")}

    def claims_from_skill(skill: SkillName) -> set[str]:
        return {
            claim_id
            for claim_id, evidence_ids in claim_evidence.items()
            if any(evidence_skill.get(evidence_id) == skill.value for evidence_id in evidence_ids)
        }

    checks: list[dict[str, Any]] = []

    if "M1" in m_ids:
        missing = sorted(
            methodology
            for methodology in wanted
            if _METHODOLOGY_SKILL[methodology].value not in called_ok
            or not claims_from_skill(_METHODOLOGY_SKILL[methodology])
        )
        checks.append(
            {
                "check_id": "M1",
                "passed": not missing,
                "reason": (
                    "代打确定性判定：全部要求方法论均有真实技能调用且结论可溯源。"
                    if not missing
                    else f"方法论未触发或无结论支撑：{missing}"
                ),
            }
        )

    if "M2" in m_ids:
        allowed = {_METHODOLOGY_SKILL[methodology] for methodology in wanted}
        # standard 深度全量扫描（task_origin=baseline）调用条件方法论技能
        # 是既定语义（T-02 裁决同款）；M2 只判“意图主动路由”的误触发：
        # 技能存在非 baseline 来源的调用任务才可能构成误触发。
        plan_tasks = (fetch.get("retrieval_plan") or {}).get("tasks") or []
        intent_routed_skills = {
            str(task.get("skill_name"))
            for task in plan_tasks
            if isinstance(task, dict)
            and str(task.get("task_origin")) != "baseline"
        }
        intruders = sorted(
            skill.value
            for skill in _CONDITIONAL_METHODOLOGY_SKILLS
            if skill not in allowed
            and claims_from_skill(skill)
            and skill.value in intent_routed_skills
        )
        checks.append(
            {
                "check_id": "M2",
                "passed": not intruders,
                "reason": (
                    "代打确定性判定：无条件方法论技能被误触发。"
                    if not intruders
                    else f"误触发的方法论技能：{intruders}"
                ),
            }
        )

    if "M3" in m_ids:
        dimensions = analysis.get("dimensions", []) or []
        scenarios = analysis.get("scenarios", []) or []
        claim_dimension: dict[str, str] = {}
        for dimension in dimensions:
            if isinstance(dimension, dict):
                for claim_id in dimension.get("claim_ids", []) or []:
                    claim_dimension[str(claim_id)] = str(dimension.get("name"))
        template_ok = len(dimensions) == 5 and len(scenarios) == 3
        unsupported: list[str] = []
        if template_ok:
            for methodology in sorted(wanted):
                skill_claims = claims_from_skill(_METHODOLOGY_SKILL[methodology])
                if not skill_claims or not any(cid in claim_dimension for cid in skill_claims):
                    unsupported.append(methodology)
        passed = template_ok and not unsupported
        reason = (
            "代打确定性判定：五维度+三情景模板完整，各方法论结论均落入对应维度。"
            if passed
            else (
                f"模板不完整（dimensions={len(dimensions)}, scenarios={len(scenarios)}）"
                if not template_ok
                else f"方法论结论未落入对应维度：{unsupported}"
            )
        )
        checks.append({"check_id": "M3", "passed": passed, "reason": reason})

    score = sum(1 for item in checks if item["passed"]) / len(checks) if checks else None
    return (
        {
            "status": "deterministic",
            "score": score,
            "panel": "deterministic_surrogate",
        },
        checks,
    )


async def run_case(
    case: dict[str, Any],
    *,
    run: SurrogateRun,
    controller: StopController,
) -> dict[str, Any]:
    skill_transport = LiveContentAddressedTransport(
        cache_dir=CACHE_DIR, provider="skillhub", controller=controller
    )
    registry, skill_client = build_surrogate_registry(skill_transport=skill_transport)
    run_id = f"surrogate-{case['id'].lower().replace('-', '_')}-{int(time.time())}"
    graph = build_pipeline_graph(registry, checkpointer=InMemorySaver())
    state = create_pipeline_state(
        project_id="surrogate-evaluation",
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
    m_result, m_checks = (
        _score_m_checks(case, final, skill_client.calls)
        if caught is None and terminal.passed
        else ({"status": "not_run", "score": None, "panel": "deterministic_surrogate"}, [])
    )
    checks.extend(m_checks)
    if caught:
        checks.append({"check_id": "EXECUTION", "passed": False, "reason": caught})
    gate = build_gate_record(case, check_results=checks, reached_subgoals=_reached_subgoals(final))
    passed = terminal.passed and gate["gate"] == "PASS" and all(item["passed"] for item in checks)
    verdict = terminal.verdict if passed else ("blocked" if controller.stopped else "fail")
    transport_events = [*map(asdict, skill_transport.events)]
    trace = {
        "trace_version": "surrogate-v1",
        "mode": "surrogate",
        "llm_mode": "surrogate",
        "skillhub_mode": "live",
        "case": case,
        "run_id": run_id,
        "elapsed_s": round(time.monotonic() - started, 3),
        "final": final,
        "skill_calls": skill_client.calls,
        "transport": transport_events,
        "terminal": asdict(terminal),
        "checks": checks,
        "m_checks": m_result,
        "gate": gate,
        "stop": {"code": controller.code, "detail": controller.detail},
    }
    run.append_jsonl(run.traces_file, trace)
    grade = {
        "case_id": case["id"],
        "verdict": verdict,
        "passed": passed,
        "reason": caught or terminal.reason,
        "checks": checks,
        "m_checks": m_result,
        "gate": gate,
        "mode": "surrogate",
        "llm_mode": "surrogate",
        "skillhub_mode": "live",
        "model": SURROGATE_MODEL_NAME,
        "trace_file": str(run.traces_file),
        "elapsed_s": trace["elapsed_s"],
        "external_requests": sum(1 for event in transport_events if not event["cache_hit"]),
        "cache_hits": sum(1 for event in transport_events if event["cache_hit"]),
        "skill_calls_ok": sum(1 for row in skill_client.calls if row.get("ok")),
    }
    run.append_jsonl(run.grades_file, grade)
    return grade


async def run_cases(case_ids: list[str] | None = None, *, limit: int | None = None) -> int:
    run = SurrogateRun.create()
    try:
        assert_surrogate_configuration()
    except SurrogateConfigurationError as exc:
        run.write_manifest(
            {
                "mode": "surrogate",
                "llm_mode": "surrogate",
                "skillhub_mode": "live",
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
        raise SurrogateConfigurationError("case_schema_invalid: " + "; ".join(errors))
    selected = [case for case in cases if not case_ids or case["id"] in set(case_ids)]
    selected.sort(key=lambda item: (not bool(item.get("must_pass")), item["id"]))
    if limit:
        selected = selected[:limit]
    original_artifact_root = settings.ARTIFACT_ROOT
    settings.ARTIFACT_ROOT = run.root / "artifacts"
    controller = StopController()
    bug_summary = BugSummary()
    manifest = {
        "mode": "surrogate",
        "llm_mode": "surrogate",
        "skillhub_mode": "live",
        "model": SURROGATE_MODEL_NAME,
        "llm_base_url_configured": bool(settings.LLM_BASE_URL),
        "skillhub_base_url": settings.IWENCAI_BASE_URL,
        "cache_dir": str(CACHE_DIR),
        "image_generation": "disabled_by_evaluation_scope",
        "started_at": datetime.now(timezone.utc).isoformat(),
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
                f"requests={grade['external_requests']} cache_hits={grade['cache_hits']}",
                flush=True,
            )
    finally:
        settings.ARTIFACT_ROOT = original_artifact_root
        run.bugs_file.write_text(bug_summary.render(), encoding="utf-8")
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
        print(f"archive={run.root}", flush=True)
    return 2 if controller.stopped else (0 if all(item["passed"] for item in grades) else 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="surrogate (AI stand-in) five-agent evaluator")
    parser.add_argument("--case", action="append", dest="case_ids")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_cases(args.case_ids, limit=args.limit)))


if __name__ == "__main__":
    main()
