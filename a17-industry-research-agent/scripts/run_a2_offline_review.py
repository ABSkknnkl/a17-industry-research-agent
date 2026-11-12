"""Run A2 on a real A1 dataset without any network or LLM call.

The deterministic channel produces the same ``InterpretationReport`` schema
as a full run; the semantic channel is deliberately disabled so the review
consumes no model quota and stays reproducible offline.

Usage::

    env -u PYTHONPATH python3 scripts/run_a2_offline_review.py \
        --dataset output/a1_five_industry_probe/新能源汽车/runs/<run_id>/dataset.json \
        --output output/a2_industry_review/runs/a2-final-offline/interpretation_report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
# The main backend injects .env into os.environ via config._load_env_files().
# A standalone script must do the same; override=False keeps shell precedence.
load_dotenv(ROOT / ".env", override=False)
for path in (ROOT, ROOT / "agents_core", ROOT / "agents_core" / "data-analysis",
             ROOT / "agents_core" / "chart-generator", ROOT / "backend"):
    sys.path.insert(0, str(path))

from data_interpreter.agent import DataInterpreterAgent  # noqa: E402
from data_interpreter.models import AnalysisRequest, StructuredResearchDataset  # noqa: E402


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments.

    Returns:
        Parsed namespace with dataset, output, subject and as_of.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="A1 dataset.json path")
    parser.add_argument("--output", type=Path, required=True, help="A2 report output path")
    parser.add_argument("--subject", default="新能源汽车", help="Research subject")
    parser.add_argument("--as-of", default="2026-11-09", help="ISO as-of date")
    parser.add_argument("--semantic", action="store_true",
                        help="enable the LLM semantic channel (consumes model quota)")
    return parser.parse_args()


async def main_async(args: argparse.Namespace) -> int:
    """Execute one offline A2 run and persist the report.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Process exit code (0 on success).
    """
    dataset = StructuredResearchDataset.model_validate_json(
        args.dataset.read_text(encoding="utf-8")
    )
    request = AnalysisRequest(
        subject=args.subject,
        as_of=date.fromisoformat(args.as_of),
        enable_semantic_analysis=args.semantic,
    )
    agent = DataInterpreterAgent()
    print(f"semantic_channel={'on' if args.semantic else 'off'} "
          f"llm_available={agent.llm.is_available}", flush=True)
    report = await agent.run(dataset, request, save_artifacts=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"A2 offline report: {args.output}")
    print(f"status={report.status} semantic_status={report.semantic_status}")
    print(f"insights={len(report.insights)} knowledge_facts={len(report.knowledge_facts)} "
          f"evidence_index={len(report.evidence_index)}")
    print(f"chain_analysis={'present' if report.chain_analysis else 'absent'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(parse_args())))
