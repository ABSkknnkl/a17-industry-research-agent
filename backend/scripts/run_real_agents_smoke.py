#!/usr/bin/env python3
"""Run the vendored five agents sequentially against live providers.

This command never enables mock providers and never prints credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.real_core import RealFiveAgentAdapter, create_real_stages  # noqa: E402
from app.agents.real_core.artifacts import RealAgentArtifactStore  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.schemas.workflow import StageName, StageResult, StageStatus  # noqa: E402
from app.workflow.stages import StageContext  # noqa: E402


def _assert_live_configuration() -> None:
    issues: list[str] = []
    if not settings.REAL_AGENTS_ENABLED:
        issues.append("REAL_AGENTS_ENABLED_must_be_true")
    if settings.LLM_USE_MOCK:
        issues.append("LLM_USE_MOCK_must_be_false")
    if settings.SKILLHUB_USE_MOCK:
        issues.append("SKILLHUB_USE_MOCK_must_be_false")
    if not settings.LLM_API_KEY:
        issues.append("LLM_API_KEY_missing")
    if not settings.LLM_BASE_URL:
        issues.append("LLM_BASE_URL_missing")
    if not (settings.IWENCAI_API_KEY or settings.SKILLHUB_API_KEY):
        issues.append("IWENCAI_API_KEY_or_SKILLHUB_API_KEY_missing")
    if issues:
        raise SystemExit("live_configuration_invalid:" + ",".join(issues))


async def _run(args: argparse.Namespace) -> dict[str, object]:
    _assert_live_configuration()
    run_id = args.run_id or f"smoke-{uuid.uuid4().hex[:12]}"
    store = RealAgentArtifactStore(settings.ARTIFACT_ROOT)
    stages = create_real_stages(RealFiveAgentAdapter(), store)
    previous: dict[StageName, StageResult] = {}
    input_data = {
        "industry_topic": args.industry,
        "focus_questions": args.focus,
        "market_scope": args.market,
        "security_types": args.security_type,
        "research_as_of": args.research_as_of,
        "reporting_currency": "CNY",
        "analysis_depth": args.depth,
    }

    for stage in stages:
        print(f"[{stage.stage.value}] running", flush=True)
        result = await stage.run(
            StageContext(
                project_id="real-agent-smoke",
                run_id=run_id,
                revision=1,
                input_data=input_data,
                previous_results=previous,
            )
        )
        if result.status == StageStatus.FAILED or result.error:
            raise RuntimeError(f"{stage.stage.value}_failed:{result.error or 'unknown'}")
        previous[stage.stage] = result
        print(
            f"[{stage.stage.value}] {result.status.value}; artifacts={len(result.artifacts)}",
            flush=True,
        )

    fusion = previous[StageName.REPORT_FUSION]
    artifact_ids = {item.artifact_id for item in fusion.artifacts}
    required = {"report_markdown", "report_html", "report_pdf"}
    missing = sorted(required - artifact_ids)
    if missing:
        raise RuntimeError("report_artifacts_missing:" + ",".join(missing))
    for artifact in fusion.artifacts:
        path = (store.root / artifact.uri).resolve()
        if not path.is_relative_to(store.root) or not path.exists():
            raise RuntimeError(f"artifact_invalid:{artifact.artifact_id}")

    return {
        "run_id": run_id,
        "status": "completed",
        "stages": [stage.value for stage in previous],
        "artifact_directory": str(store.run_dir(run_id) / "artifacts"),
        "report_artifacts": sorted(artifact_ids & required),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run all five vendored agents with live providers")
    parser.add_argument("--industry", required=True, help="Industry or research topic")
    parser.add_argument("--as-of", dest="research_as_of", required=True, help="YYYY-MM-DD")
    parser.add_argument("--focus", action="append", default=[], help="Repeatable focus question")
    parser.add_argument("--market", action="append", default=["中国内地"])
    parser.add_argument("--security-type", action="append", default=["普通股"])
    parser.add_argument("--depth", choices=("overview", "standard", "deep"), default="standard")
    parser.add_argument("--run-id", help="Optional safe run identifier")
    return parser


def main() -> None:
    summary = asyncio.run(_run(_parser().parse_args()))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
