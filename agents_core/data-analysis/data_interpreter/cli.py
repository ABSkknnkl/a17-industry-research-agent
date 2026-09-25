"""Command-line entry point for one interpretation run."""

from __future__ import annotations

import argparse
import asyncio
from datetime import date
import json
from pathlib import Path

from data_interpreter.agent import DataInterpreterAgent
from data_interpreter.models import AnalysisRequest, StructuredResearchDataset


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="结构化研究数据解读智能体")
    parser.add_argument("dataset", type=Path, help="data-fetcher 生成的 dataset.json")
    parser.add_argument("--subject", default="研究主题", help="研究主题或行业")
    parser.add_argument("--focus", action="append", default=[], help="关注点，可重复")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--deterministic-only", action="store_true", help="跳过模型语义深化")
    parser.add_argument("--no-save", action="store_true", help="不保存分析产物")
    return parser


async def _run(args: argparse.Namespace) -> int:
    payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    dataset = StructuredResearchDataset.model_validate(payload)
    report = await DataInterpreterAgent().run(
        dataset,
        AnalysisRequest(
            subject=args.subject,
            focus_points=args.focus,
            as_of=args.as_of,
            enable_semantic_analysis=not args.deterministic_only,
        ),
        save_artifacts=not args.no_save,
    )
    print(json.dumps({
        "report_id": report.report_id,
        "status": report.status,
        "semantic_status": report.semantic_status,
        "applied_skills": [skill.name for skill in report.applied_skills],
        "key_metrics": len(report.key_metrics),
        "trends": len(report.trends),
        "anomalies": len(report.anomalies),
        "cross_validations": len(report.cross_validations),
        "artifact_dir": report.artifact_dir,
        "warnings": report.warnings,
    }, ensure_ascii=False, indent=2))
    return 0 if report.status in ("completed", "partial") else 1


def main() -> None:
    raise SystemExit(asyncio.run(_run(build_parser().parse_args())))


if __name__ == "__main__":
    main()
