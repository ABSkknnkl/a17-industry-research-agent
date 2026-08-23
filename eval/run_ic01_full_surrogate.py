"""Drive I-C01 through the FULL five-agent chain with surrogate (AI stand-in) models.

I-C01 is an intent_plan partial-chain case, so ``surrogate_runner`` stops after
data_fetch.  This driver builds the same surrogate registry but overrides the
case semantics to ``completed`` so the pipeline runs Agent 1→5 end to end and
produces the full report (7 chapters / 21 sections + MD/HTML/PDF/manifest).

Honesty: mode is labelled ``surrogate`` everywhere; SkillHub stays live via the
content-addressed cache (cache hits preferred, live fallback when missing).
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import settings
from app.schemas.workflow import StageName
from app.workflow.graph import build_pipeline_graph
from app.workflow.state import create_pipeline_state

from eval.case_schema import load_case_suite
from eval.harness import evaluate_terminal_state
from eval.real_runner import CACHE_DIR, _drive, _input_for
from eval.surrogate_runner import build_surrogate_registry
from eval.transport import LiveContentAddressedTransport, StopController


FULL_SUBGOALS = ["a1_plan", "a1_fetch", "a2_calc", "a3_chart", "a4_chapter", "a5_export"]


def _full_chain_case(case: dict) -> dict:
    """Override partial-chain semantics so the pipeline runs end to end."""
    full = dict(case)
    full["expected_outcome"] = "completed"
    full["subgoals"] = list(FULL_SUBGOALS)
    full["expected_stages"] = {
        "agent2": {"evidence_closed": True, "min_claims": 1},
        "agent4": {"chapters": 7, "sections": 21},
        "agent5": {"required_artifacts": ["markdown", "html", "pdf", "manifest"]},
    }
    full["expected_handoffs"] = [
        "a1_to_a2",
        "a2_to_a3",
        "a2_to_a4",
        "a3_to_a4",
        "a4_to_a5",
    ]
    return full


async def main() -> int:
    cases = load_case_suite()
    case = next(c for c in cases if c["id"] == "I-C01")
    full_case = _full_chain_case(case)

    controller = StopController()
    skill_transport = LiveContentAddressedTransport(
        cache_dir=CACHE_DIR, provider="skillhub", controller=controller
    )
    registry, skill_client = build_surrogate_registry(skill_transport=skill_transport)

    run_id = f"surrogate-i-c01-full-{int(time.time())}"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_root = ROOT / "eval" / "transcript" / f"surrogate_ic01_full_{stamp}"
    out_root.mkdir(parents=True, exist_ok=True)
    original_artifact_root = settings.ARTIFACT_ROOT
    settings.ARTIFACT_ROOT = out_root / "artifacts"

    graph = build_pipeline_graph(registry, checkpointer=InMemorySaver())
    state = create_pipeline_state(
        project_id="surrogate-evaluation",
        run_id=run_id,
        input_data=_input_for(case),
        review_stages=[StageName.DATA_FETCH, StageName.DATA_INTERPRET],
    )
    config = {"configurable": {"thread_id": run_id}}

    started = time.monotonic()
    caught = None
    try:
        final = await _drive(graph, state, config, full_case)
    except Exception as exc:  # surface real failures, never hide
        final = {"status": "BLOCKED", "stage_results": {}, "current_stage": None}
        caught = f"{type(exc).__name__}:{exc}"
    finally:
        await skill_transport.aclose()
        settings.ARTIFACT_ROOT = original_artifact_root

    terminal = evaluate_terminal_state(full_case, final)
    transport_events = [asdict(e) for e in skill_transport.events]
    result = {
        "mode": "surrogate",
        "llm_mode": "surrogate",
        "skillhub_mode": "live",
        "case_id": "I-C01",
        "run_id": run_id,
        "elapsed_s": round(time.monotonic() - started, 3),
        "caught": caught,
        "terminal": asdict(terminal),
        "final_status": final.get("status"),
        "current_stage": final.get("current_stage"),
        "cache_hits": sum(1 for e in transport_events if e["cache_hit"]),
        "external_requests": sum(1 for e in transport_events if not e["cache_hit"]),
        "skill_calls": skill_client.calls,
    }
    (out_root / "run_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (out_root / "final_state.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    print(f"run_id={run_id}")
    print(f"terminal: passed={terminal.passed} verdict={terminal.verdict} reason={terminal.reason}")
    print(f"final_status={final.get('status')} current_stage={final.get('current_stage')}")
    print(f"cache_hits={result['cache_hits']} external_requests={result['external_requests']}")
    for name, item in (final.get("stage_results", {}) or {}).items():
        if isinstance(item, dict):
            print(f"  stage {name}: status={item.get('status')} error={item.get('error')}")
    fusion = (final.get("stage_results", {}) or {}).get("report_fusion", {}) or {}
    for art in fusion.get("artifacts", []) or []:
        if isinstance(art, dict):
            print(f"  artifact: {art.get('kind')} -> {art.get('path')}")
    print(f"out_root={out_root}")
    return 0 if terminal.passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
