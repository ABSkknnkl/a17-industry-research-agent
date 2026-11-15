from __future__ import annotations
import argparse,asyncio,json
from pathlib import Path
from report_fusion import ReportFusionAgent,ReportFusionRequest
from report_fusion.models import ChartResult,ChapterResult,FusionOptions,InterpretationReport

def resolve(path:Path,name:str)->Path:return path/name if path.is_dir() else path
def build_parser():
    p=argparse.ArgumentParser(description="行业研究报告融合与导出智能体");p.add_argument("analysis",type=Path);p.add_argument("--chapters",type=Path,required=True);p.add_argument("--charts",type=Path);p.add_argument("--format",action="append",dest="formats",choices=["markdown","html","pdf"]);p.add_argument("--depth",choices=["brief","standard","deep"],default="standard");p.add_argument("--no-editorial-llm",action="store_true");p.add_argument("--no-save",action="store_true");return p
async def _run(a):
    report=InterpretationReport.model_validate_json(resolve(a.analysis,"interpretation_report.json").read_text(encoding="utf-8"));chapters=ChapterResult.model_validate_json(resolve(a.chapters,"chapter_result.json").read_text(encoding="utf-8"));charts=ChartResult.model_validate_json(resolve(a.charts,"chart_result.json").read_text(encoding="utf-8")) if a.charts else None
    result=await ReportFusionAgent().run(ReportFusionRequest(report=report,chapters=chapters,charts=charts,options=FusionOptions(formats=a.formats or ["markdown","html","pdf"],report_depth=a.depth,enable_editorial_llm=not a.no_editorial_llm)),save_artifacts=not a.no_save)
    print(json.dumps({"run_id":result.run_id,"report_id":result.report_id,"status":result.status,"formats":result.formats,"artifact_dir":result.artifact_dir,"warnings":result.warnings},ensure_ascii=False,indent=2));return 0 if result.status in {"completed","partial"} else 1
def main():raise SystemExit(asyncio.run(_run(build_parser().parse_args())))

if __name__ == "__main__":
    main()

