"""Command-line entry point for one research-agent run."""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
import json

from data_fetcher.agent import DataFetcherAgent
from data_fetcher.models import ResearchRequest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="同花顺问财 SkillHub 数据获取智能体")
    parser.add_argument("--industry", required=True, help="研究行业或主题")
    parser.add_argument("--focus", action="append", default=[], help="关注点，可重复")
    parser.add_argument("--require", action="append", default=[], dest="requirements", help="数据要求，可重复")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today(), help="研究基准日 YYYY-MM-DD")
    parser.add_argument("--max-iterations", type=int, default=6)
    parser.add_argument("--max-skill-calls", type=int, default=24)
    parser.add_argument("--max-execution-seconds", type=float, default=600.0)
    parser.add_argument("--no-save", action="store_true", help="不保存运行产物")
    return parser


async def _run(args: argparse.Namespace) -> int:
    request = ResearchRequest(
        industry=args.industry,
        focus_points=args.focus,
        data_requirements=args.requirements,
        as_of=args.as_of,
        max_iterations=args.max_iterations,
        max_skill_calls=args.max_skill_calls,
        max_execution_seconds=args.max_execution_seconds,
    )
    result = await DataFetcherAgent().run(request, save_artifacts=not args.no_save)
    print(json.dumps({
        "run_id": result.run_id,
        "status": result.status,
        "stop_reason": result.stop_reason,
        "coverage": result.coverage.score,
        "errors": [error.model_dump(mode="json") for error in result.errors],
        "artifact_dir": result.artifact_dir,
    }, ensure_ascii=False, indent=2))
    return 0 if result.status in ("completed", "partial") else 1


def main() -> None:
    raise SystemExit(asyncio.run(_run(build_parser().parse_args())))


if __name__ == "__main__":
    main()
