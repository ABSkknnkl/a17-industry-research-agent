#!/usr/bin/env python3
"""真实 LLM 跑 A4（ChapterWriter），上游用模拟数据。

产物：output/live/chapter_result.json + a4_live_meta.json
"""
from __future__ import annotations

import asyncio
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
        key = key.strip()
        if key.startswith("LLM_"):
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))


async def main() -> int:
    load_env()
    from chapter_writer.agent import ChapterWriterAgent
    from chapter_writer.config import Settings
    from chapter_writer.llm import OpenAICompatibleLLM
    from chapter_writer.models import ChapterWritingOptions, ChapterWritingRequest
    from sim_upstream import build

    report, charts, dataset = build()
    from dataclasses import replace
    settings = replace(Settings.from_env(),
                       output_dir=DST / "output" / "live_a4")
    llm = OpenAICompatibleLLM(settings)
    print(f"model={settings.llm_model} base={settings.llm_base_url} available={llm.is_available}")

    request = ChapterWritingRequest(
        report=report, charts=charts, input_dataset=dataset,
        options=ChapterWritingOptions(style="professional",
                                      target_length="standard",
                                      max_repairs=2),
    )
    agent = ChapterWriterAgent(settings=settings, llm=llm)
    started = time.time()
    result = await agent.run(request, save_artifacts=True)
    elapsed = round(time.time() - started, 1)

    out = DST / "output" / "live"
    out.mkdir(parents=True, exist_ok=True)
    (out / "chapter_result.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8")
    meta = {
        "schema_version": "1.0", "stage": "A4_live",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": settings.llm_model, "base_url": settings.llm_base_url,
        "real_model_call": True, "elapsed_seconds": elapsed,
        "status": result.status, "quality": result.quality.model_dump(),
        "chapters": len(result.chapters),
        "sections": sum(len(c.sections) for c in result.chapters),
        "paragraphs": sum(len(s.paragraphs) for c in result.chapters
                          for s in c.sections),
        "fallback_chapters": [c.chapter_id for c in result.chapters if c.used_fallback],
        "warnings": result.warnings[:10],
        "input": "sim_upstream（模拟 A1/A2/A3，明确标注，不代表真实数据）",
        "artifact_dir": result.artifact_dir,
    }
    (out / "a4_live_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"A4 真实模型完成：status={result.status} | {elapsed}s | "
          f"chapters={len(result.chapters)} sections={meta['sections']} "
          f"paragraphs={meta['paragraphs']} | fallback={meta['fallback_chapters']}")
    print(f"quality={result.quality.model_dump()}")
    return 0 if result.chapters else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
