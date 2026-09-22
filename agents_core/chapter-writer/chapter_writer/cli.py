from __future__ import annotations

import argparse, asyncio, json
from pathlib import Path

from chapter_writer import ChapterWriterAgent, ChapterWritingRequest
from chapter_writer.models import ChartResult, ChapterWritingOptions, InterpretationReport, OutlineChapter


def resolve_report(path:Path)->Path: return path/"interpretation_report.json" if path.is_dir() else path
def resolve_charts(path:Path|None)->Path|None:
    if path is None: return None
    return path/"chart_result.json" if path.is_dir() else path


def build_parser()->argparse.ArgumentParser:
    parser=argparse.ArgumentParser(description="7章21节行业研究章节写作智能体")
    parser.add_argument("analysis",type=Path)
    parser.add_argument("--charts",type=Path)
    parser.add_argument("--outline",type=Path)
    parser.add_argument("--style",choices=["professional","plain_language"],default="professional")
    parser.add_argument("--audience",default="证券研究人员")
    parser.add_argument("--instruction")
    parser.add_argument("--no-save",action="store_true")
    return parser


async def _run(args:argparse.Namespace)->int:
    report=InterpretationReport.model_validate(json.loads(resolve_report(args.analysis).read_text(encoding="utf-8")))
    chart_path=resolve_charts(args.charts); charts=ChartResult.model_validate_json(chart_path.read_text(encoding="utf-8")) if chart_path else None
    outline=[OutlineChapter.model_validate(x) for x in json.loads(args.outline.read_text(encoding="utf-8"))] if args.outline else None
    request=ChapterWritingRequest(report=report,charts=charts,outline=outline,options=ChapterWritingOptions(style=args.style,audience=args.audience,instruction=args.instruction))
    result=await ChapterWriterAgent().run(request,save_artifacts=not args.no_save)
    print(json.dumps({"run_id":result.run_id,"status":result.status,"chapters":len(result.chapters),"sections":sum(len(x.sections) for x in result.chapters),"fallbacks":result.quality.fallback_chapter_ids,"artifact_dir":result.artifact_dir},ensure_ascii=False,indent=2))
    return 0 if result.status in {"completed","partial"} else 1


def main()->None: raise SystemExit(asyncio.run(_run(build_parser().parse_args())))


if __name__ == "__main__":
    main()

