#!/usr/bin/env python3
"""真实 LLM 跑 A5（ReportFusion + a5_nev 排版），上游为模拟 A1/A2/A3 + 真实 A4 章节。

本脚本会真实调用模型（editorial 融合阶段），产物含调用事件与冻结输出。
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DST = Path(__file__).resolve().parent
for p in (DST, DST / "agents_core", DST / "agents_core/report-fusion",
          DST / "agents_core/chapter-writer"):
    sys.path.insert(0, str(p))

ENV = Path("/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/.env")


def load_env() -> None:
    if not ENV.exists():
        return
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip().startswith("LLM_"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


async def main() -> int:
    load_env()
    from dataclasses import replace
    from chapter_writer.models import (
        ChartResult as CWChartResult, InterpretationReport as CWReport,
        ChapterWritingResult as CWChapterResult,
    )
    from report_fusion.agent import ReportFusionAgent
    from report_fusion.config import Settings
    from report_fusion.llm import OpenAICompatibleLLM
    from report_fusion.models import (
        ChapterResult as RFChapterResult, ChartResult as RFChartResult,
        FusionOptions, InterpretationReport as RFReport, ReportFusionRequest,
    )

    sim = DST / "output" / "sim"
    live = DST / "output" / "live"
    a2 = CWReport.model_validate_json(
        (sim / "a2_interpretation_report.json").read_text(encoding="utf-8"))
    a3 = CWChartResult.model_validate_json(
        (sim / "a3_chart_result.json").read_text(encoding="utf-8"))
    a4 = CWChapterResult.model_validate_json(
        (live / "chapter_result.json").read_text(encoding="utf-8"))

    rf_report = RFReport.model_validate(a2.model_dump(mode="json"))
    rf_charts = RFChartResult.model_validate(a3.model_dump(mode="json"))
    rf_chapters = RFChapterResult(
        run_id=a4.run_id, source_report_id=a4.source_report_id,
        subject=a4.subject, as_of=a4.as_of, status=a4.status,
        outline_version=a4.outline_version,
        chapters=[dict(c.model_dump(mode="json")) for c in a4.chapters],
        warnings=a4.warnings, quality=a4.quality.model_dump(mode="json"),
    )
    request = ReportFusionRequest(
        report=rf_report, chapters=rf_chapters, charts=rf_charts,
        options=FusionOptions(formats=["markdown", "html", "pdf"],
                              chart_mode="a5_nev",
                              enable_editorial_llm=True),
    )
    settings = replace(Settings.from_env(),
                       output_dir=DST / "output" / "live_a5",
                       pdf_timeout_seconds=240.0)
    llm = OpenAICompatibleLLM(settings)
    print(f"model={settings.llm_model} available={llm.is_available} "
          f"editorial=on chart_mode=a5_nev")
    agent = ReportFusionAgent(settings=settings, llm=llm)
    started = time.time()
    result = await agent.run(request, save_artifacts=True)
    elapsed = round(time.time() - started, 1)

    run_dir = Path(result.artifact_dir) if result.artifact_dir else None
    meta = {
        "schema_version": "1.0", "stage": "A5_live",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": settings.llm_model, "base_url": settings.llm_base_url,
        "real_model_call": True, "editorial_llm": True,
        "elapsed_seconds": elapsed,
        "status": result.status, "formats": result.formats,
        "warnings": result.warnings,
        "consistency": result.consistency.model_dump(mode="json"),
        "artifact_dir": str(run_dir),
        "input": {
            "a2": "sim_upstream（模拟，明确标注）",
            "a3": "sim_upstream（模拟 8 图，明确标注）",
            "a4": "真实 LLM 生成（deepseek-v4-flash，52.5s，7 章 21 节 54 段）",
        },
    }
    if run_dir:
        files = {p.name: p.stat().st_size for p in run_dir.iterdir() if p.is_file()}
        meta["artifacts"] = files
        if (run_dir / "report.pdf").exists():
            import pymupdf
            with pymupdf.open(run_dir / "report.pdf") as doc:
                meta["pdf_pages"] = doc.page_count
                meta["outline_entries"] = len(doc.get_toc())
                meta["page_heads"] = [
                    [x.strip() for x in doc[i].get_text().splitlines() if x.strip()][:2]
                    for i in range(min(4, doc.page_count))]
    (live / "a5_live_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"A5 真实模型完成：status={result.status} formats={result.formats} "
          f"| {elapsed}s | pdf_pages={meta.get('pdf_pages')} "
          f"outline={meta.get('outline_entries')}")
    print(f"run_dir={run_dir}")
    return 0 if run_dir and "pdf" in result.formats else 1


if __name__ == "__main__":
    import asyncio
    raise SystemExit(asyncio.run(main()))
