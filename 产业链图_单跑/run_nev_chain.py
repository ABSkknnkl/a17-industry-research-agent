#!/usr/bin/env python3
"""新能源汽车产业链图 · 单跑入口（**原版 lane_grid 模板**）。

2026-11-12 二次修订：按用户要求，产业链图渲染模块已从 GitHub
``ABSkknnkl/a17-industry-research-agent`` 逐字节复原为仓库原版
（``render_chain_svg`` 只走 ``_render_lane_grid``，三列目录式），
本脚本不再使用自行编写的「关系图」版式。

合并方式 = 原模板 + 优化过的智能体3数据：

    chain_data/vehicle.json            ← 审定事实底座（20 环节 / 21 边）
        → ChainGraphSpec.model_validate()   source="merged"（仓库合法值）
        → render_chain_svg()           ← 仓库原版唯一 lane_grid 模板
        → assert_graph_fidelity()      ← 仓库原版事实锁死（边标签同源豁免）
        → SVG + PNG 预览

``chain_render_check.assert_render_fidelity`` 仅作**独立诊断**打印
（原模板按设计不画 items / 边标签），不作出图门禁，避免与源码契约冲突。

不调 LLM、不触发豆包检索、不跑其它图表。
用法：/Users/Zhuanz1/miniconda3/bin/python3 run_nev_chain.py
"""

from __future__ import annotations

import asyncio
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path("/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent")
HERE = Path(__file__).resolve().parent

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents_core" / "chart-generator"))

from chain_data import load_chain_profile  # noqa: E402
from chart_generator.chain_graph import ChainGraphSpec  # noqa: E402
from chart_generator.chain_lint import assert_graph_fidelity  # noqa: E402
from chart_generator.chain_render import render_chain_svg  # noqa: E402
from chart_generator.chain_render_check import assert_render_fidelity  # noqa: E402


async def svg_to_png(svg: str, png: Path) -> None:
    """用本地 chromium 把 SVG 截成 PNG，便于直接预览（不依赖网络）。"""
    from playwright.async_api import async_playwright

    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    w, h = (int(float(m.group(1))), int(float(m.group(2)))) if m else (1440, 900)
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch()
        except Exception:
            chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            browser = await p.chromium.launch(executable_path=chrome)
        page = await browser.new_page(
            viewport={"width": w, "height": h}, device_scale_factor=2
        )
        await page.set_content(
            "<html><body style='margin:0;background:#fff'>" + svg + "</body></html>"
        )
        await page.screenshot(path=str(png), full_page=True)
        await browser.close()


def main() -> None:
    payload = load_chain_profile("新能源汽车")
    if payload is None:
        raise SystemExit("未找到新能源汽车审定事实底座，拒绝回退关键词猜测出图")
    ann = payload.get("annotations") or {}
    spec = ChainGraphSpec.model_validate(payload["spec"])

    print(
        f"[接通] {payload.get('version')} · source={spec.source}: {len(spec.nodes)} 环节 / "
        f"{len(spec.edges)} 关系边 / {len(spec.stages)} 段 / "
        f"{sum(len(n.companies) for n in spec.nodes)} 企业次 / "
        f"{sum(len(n.items) for n in spec.nodes)} 细分品类",
        flush=True,
    )
    if spec.source not in {"merged", "deterministic", "llm", "v2_bundle"}:
        raise SystemExit("source 不是仓库原版合法值，渲染分流可能不一致")

    svg = render_chain_svg(spec)  # 仓库原版：唯一 lane_grid
    ET.fromstring(svg)

    # 生产门禁：与仓库源码同源的事实锁死
    missing = assert_graph_fidelity(spec, svg)
    if missing:
        raise SystemExit(f"事实锁死缺失（渲染管线缺陷）：{missing[:5]}")
    print("[校验] 原版事实锁死：通过", flush=True)

    # 独立诊断（不阻断）：原模板按设计不画 items / 边标签
    diag = assert_render_fidelity(spec, svg, ann)
    if diag:
        print(
            "[诊断] 原模板契约豁免项（lane_grid 卡片零连线 / 企业行优先），"
            f"非缺陷：{ {k: len(v) for k, v in diag.items()} }",
            flush=True,
        )

    svg_path = HERE / "新能源汽车产业链图.svg"
    svg_path.write_text(svg, encoding="utf-8")
    print(f"[产出] SVG {svg_path}  ({len(svg)} bytes)", flush=True)

    png_path = HERE / "新能源汽车产业链图.png"
    try:
        asyncio.run(svg_to_png(svg, png_path))
        print(f"[产出] PNG {png_path}", flush=True)
    except Exception as exc:
        print(f"[跳过] PNG 预览未生成：{type(exc).__name__}: {exc}", flush=True)

    print("[完成] 原版 lane_grid 模板 + 审定数据底座；未调 LLM、未消耗豆包额度。",
          flush=True)


if __name__ == "__main__":
    main()
