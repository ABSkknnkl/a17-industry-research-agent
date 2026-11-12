"""Run agent 3 (chart-generator) alone for one industry, with the real
question text as ``focus_points`` and Doubao chain search enabled.

Why a standalone runner: the full pipeline needs A1 + A2 first, but the
question-to-chart behaviour lives entirely in A3.  This script reuses a frozen
A1/A2 pair (golden sample) so a chart-selection change can be verified without
re-spending A1 quota.

Usage::

    env -u PYTHONPATH python3 scripts/run_a3_single_industry.py \
        --run-dir output/a3_refactor_validation/runs/a3-live-20261110235216656541/artifacts \
        --max-charts 8 --chain

Environment:
    ``.env`` is loaded with ``override=False`` so ``SEARCH_PROVIDER=doubao`` and
    ``DOUBAO_SEARCH_API_KEY`` reach ``websearch.web_search_available()``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)

for _path in (ROOT, ROOT / "agents_core", ROOT / "agents_core" / "chart-generator",
              ROOT / "backend"):
    sys.path.insert(0, str(_path))

import backend.app.core.setup_env  # noqa: F401,E402
from chart_generator.agent import ChartGeneratorAgent  # noqa: E402
from chart_generator.models import (  # noqa: E402
    ChartGenerationRequest,
    ChartPreferences,
    InterpretationReport,
)

# Question text below is quoted from
# /Users/Zhuanz1/Downloads/五行业选题与网页研究问题.docx section 5 (新能源汽车).
NEV_QUESTIONS = [
    "2021—2025年中国新能源汽车销量及市场渗透率如何变化？请比较比亚迪、长安汽车和赛力斯在2023—2025年的营业收入、毛利率及经营现金流，并分析整车与动力电池产业链的主要关系，形成包含数据表、趋势图、产业链结构和证据来源的完整行业研究报告。",
    "2021—2025年中国新能源汽车销量、渗透率及出口量如何变化？不同统计口径（汽车总量、乘用车等）会如何影响结论？",
    "比亚迪、长安汽车、赛力斯2023—2025年的营收、毛利率及经营现金流如何分化？能否对整车业务单独比较？",
    "宁德时代、亿纬锂能与整车企业在研发强度、利润率及现金流方面有何差异？为什么应按动力电池与整车环节分组分析？",
]

# 行业预设题号：``ChartIntent.question_id`` 是 ``id.split(".")[1]``，即 q1…q5，
# 不是完整 intent id（如 nev.q1.sales）。传错会让 12 道题全部落到
# ``unsupported_question`` 且选图为空。传入后 A3 走「按题选图」路径并产出 question_coverage。
NEV_QUESTION_IDS = ["q1", "q2", "q3", "q4", "q5"]


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments.

    Returns:
        Parsed namespace.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True,
                        help="Directory holding dataset.json + interpretation_report.json")
    parser.add_argument("--max-charts", type=int, default=8)
    parser.add_argument("--chain", action="store_true",
                        help="Explicitly request the industry-chain chart (also enables Doubao search)")
    parser.add_argument("--theme", default="research_light")
    parser.add_argument("--no-question-ids", action="store_true",
                        help="Disable per-question planning (falls back to free chart selection)")
    return parser.parse_args()


async def main_async(args: argparse.Namespace) -> int:
    """Execute one A3 run and print a compact summary.

    Args:
        args: Parsed CLI arguments.

    Returns:
        Process exit code.
    """
    report_path = args.run_dir / "interpretation_report.json"
    dataset_path = args.run_dir / "dataset.json"
    report = InterpretationReport.model_validate_json(
        report_path.read_text(encoding="utf-8")
    )
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))

    requested = ["industry_chain", "combo", "line", "bar", "comparison_bar"] if args.chain \
        else ["combo", "line", "bar"]
    request = ChartGenerationRequest(
        report=report,
        input_dataset=dataset,
        preferences=ChartPreferences(
            max_charts=args.max_charts,
            prefer_combined=True,
            requested_types=requested,
            theme=args.theme,
        ),
        want_industry_chain=True if args.chain else None,
        focus_points=NEV_QUESTIONS,
        defaulted_focus=False,
        chain_scope="industry",
        question_ids=[] if args.no_question_ids else NEV_QUESTION_IDS,
    )

    agent = ChartGeneratorAgent()
    print(f"LLM available: {agent.llm.is_available}", flush=True)
    from chart_generator.websearch import web_search_available
    print(f"web_search_available: {web_search_available()}", flush=True)

    events: list[dict] = []

    async def emit(event: dict) -> None:
        events.append(event)

    result = await agent.run(request, emit=emit, save_artifacts=True)
    charts = [c.model_dump(mode="json") for c in (result.charts or [])]
    types = Counter(c.get("chart_type") for c in charts)
    print("\n=== A3 result ===")
    print(f"subject={report.subject} charts={len(charts)} types={dict(types)}")
    print(f"artifact_dir={getattr(result, 'artifact_dir', None)}")
    for index, chart in enumerate(charts, 1):
        print(f"{index:2d}. [{chart.get('chart_type')}] {chart.get('title')}")
    coverage = result.question_coverage or []
    print(f"\n=== question_coverage ({len(coverage)}) ===")
    for row in coverage:
        print(f"  {row.get('question_id')}/{row.get('intent_id')} {row.get('label')} "
              f"-> {row.get('status')} {row.get('chart_ids')}")
    suspicious = [e for e in events
                  if e.get("event") in ("chain_web_search", "chain_gap_filled",
                                        "chain_web_search_failed")]
    for event in suspicious[:10]:
        print(f"event: {event.get('event')} {json.dumps(event.get('details'), ensure_ascii=False)[:300]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(parse_args())))
