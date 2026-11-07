from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from chart_generator import ChartGenerationRequest, ChartGeneratorAgent
from chart_generator.models import ChartPreferences, InterpretationReport


def resolve_input(path: Path) -> tuple[Path, Path | None]:
    base_dir = path if path.is_dir() else path.parent
    report_file = path / "interpretation_report.json" if path.is_dir() else path
    dataset_file = base_dir / "input_dataset.json"
    if not dataset_file.is_file():
        dataset_file = base_dir / "dataset.json"
    return report_file, (dataset_file if dataset_file.is_file() else None)


def build_parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(description="解读报告可视化图表生成智能体")
    parser.add_argument("analysis", type=Path, help="interpretation_report.json 或 data-analysis 运行目录")
    parser.add_argument("--max-charts", type=int, default=None, help="最大图表数（默认 None 为不设数量上限）")
    parser.add_argument("--type", action="append", default=[], dest="types")
    parser.add_argument("--no-save", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    report_path,dataset_path=resolve_input(args.analysis)
    report=InterpretationReport.model_validate(json.loads(report_path.read_text(encoding="utf-8")))
    dataset=json.loads(dataset_path.read_text(encoding="utf-8")) if dataset_path else None
    result=await ChartGeneratorAgent().run(ChartGenerationRequest(report=report,input_dataset=dataset,preferences=ChartPreferences(max_charts=args.max_charts,requested_types=args.types)),save_artifacts=not args.no_save)
    print(result.model_dump_json(indent=2,exclude={"charts":{"__all__":{"option"}}}))
    return 0 if result.status in {"completed","partial"} else 1


def main() -> None:
    raise SystemExit(asyncio.run(_run(build_parser().parse_args())))


if __name__ == "__main__":
    main()

