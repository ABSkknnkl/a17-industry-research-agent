"""端到端实测智能体3的产业链 AI 生图（真实调用生图模型）。

用 run-20260926022235-107 的真实 industry_chain_segments 作为输入，
走与生产完全相同的入口 generate_industry_chain_image()。
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

ROOT = Path("/Users/Zhuanz1/Downloads/行业研究智能体-全链路系统 4")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents_core" / "chart-generator"))

import backend.app.core.config  # noqa: F401  触发 .env 加载
from chart_generator.image_gen import (  # noqa: E402
    ImageGenSettings,
    generate_industry_chain_image,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

RUN = ROOT / "data/runs/run-20260926022235-107"
OUT = ROOT / "output/generated/industry_chain"


async def main() -> None:
    cfg = ImageGenSettings.from_env()
    print(f"生图模型: {cfg.model} @ {cfg.base_url}", flush=True)
    print(f"API_KEY: {'已配置' if cfg.api_key else '❌ 未配置'}", flush=True)

    report = json.loads((RUN / "artifacts/interpretation_report.json").read_text(encoding="utf-8"))
    segments = report["industry_chain_segments"]
    subject = report["subject"]
    print(f"输入: subject={subject} segments={len(segments)}", flush=True)

    result = await generate_industry_chain_image(
        subject=subject,
        title=f"{subject}产业链结构",
        option={},
        artifact_dir=OUT,
        chart_id="CHAIN-DEMO",
        segments=segments,
    )

    if result is None:
        print("❌ 生图返回 None —— 失败（生产链路会回退为 SVG 产业链图）", flush=True)
        raise SystemExit(2)

    print("✅ 生图成功", flush=True)
    print(f"   图片: {result.image_path}", flush=True)
    print(f"   MIME: {result.image_mime_type} | 生图模型: {result.generation_image_model}", flush=True)
    print(f"   提示词模型: {result.generation_prompt_model} | 模板: {result.chain_template}", flush=True)
    print(f"   图谱: {len(result.chain_graph.get('nodes') or [])} 节点 / "
          f"{len(result.chain_graph.get('edges') or [])} 边", flush=True)


asyncio.run(main())
