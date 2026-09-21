#!/usr/bin/env python3
"""用项目配置的大模型编译产业链生图提示词（可选直接出图）。

链路与生产一致（`chart_generator/service.py` 同一套函数）：

    graph.json → compile_chain_prompt(项目 LLM) → finalize(确定性补全拓扑) → 门禁校验
               → 写 *.prompt.txt
    --generate 时继续：create_image_generator(settings).generate_image(prompt) → 写 *.png

用法（在 backend 目录下）：

    # 只产提示词：拿去喂你自己的生图模型
    .venv/bin/python scripts/compile_chain_prompt_live.py --slug humanoid-robot

    # 产提示词并用项目配置的生图模型直接出图
    .venv/bin/python scripts/compile_chain_prompt_live.py --slug humanoid-robot --generate

    # 指定自己的图谱文件
    .venv/bin/python scripts/compile_chain_prompt_live.py --graph ../output/unitree-chain/unitree-chain-verified-graph.json

需要的环境变量（backend/.env）：

    LLM_API_KEY / LLM_BASE_URL / LLM_MODEL        编译提示词（项目大模型）
    IMAGE_API_KEY / IMAGE_BASE_URL / IMAGE_MODEL  仅 --generate 需要
    IMAGE_SIZE 默认 2048x2048

说明：编译器与生图器都经 `app.integrations.visuals.factory` 创建，与生产走同一实现；
`LLM_USE_MOCK=true` 只在 ENVIRONMENT=test 下允许，否则 factory 会直接拒绝（fail-closed）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.agents.chart_generator.industry_chain import (  # noqa: E402
    ChainTemplate,
    compile_chain_prompt,
    validate_chain_prompt,
)
from app.core.config import settings  # noqa: E402
from app.integrations.visuals.factory import (  # noqa: E402
    create_image_generator,
    create_prompt_compiler,
)

DEFAULT_DIR = ROOT / "output" / "industry-chain-images"


def load_graph(path: Path) -> tuple[dict, ChainTemplate]:
    graph = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(graph, dict) or "nodes" not in graph or "edges" not in graph:
        raise SystemExit(f"不是 build_verified_chain_graph 的产物（缺 nodes/edges）：{path}")
    template: ChainTemplate = graph.get("template_id") or "horizontal_flow"
    return graph, template


async def run(args: argparse.Namespace) -> None:
    graph_path = Path(args.graph) if args.graph else DEFAULT_DIR / f"{args.slug}.graph.json"
    if not graph_path.is_file():
        raise SystemExit(
            f"图谱文件不存在：{graph_path}\n"
            "先用生成图谱的脚本（如 scripts/compile_chain_image_prompts.py）产出 *.graph.json"
        )
    graph, template = load_graph(graph_path)
    slug = args.slug or graph_path.stem

    compiler = create_prompt_compiler(settings)
    prompt = await compile_chain_prompt(compiler=compiler, graph=graph, template=template)

    problems = validate_chain_prompt(prompt, graph)
    if problems:
        raise SystemExit(f"拓扑门禁未通过（{len(problems)} 项）：{problems[:5]}")

    out_prompt = DEFAULT_DIR / f"{slug}.live.prompt.txt"
    out_prompt.parent.mkdir(parents=True, exist_ok=True)
    out_prompt.write_text(prompt, encoding="utf-8")
    print(f"✓ 提示词 ← {compiler.model_name}（{len(prompt)} 字）")
    print(f"  {out_prompt}")
    print(f"  含【连接关系】：{'【连接关系' in prompt}")

    if args.generate:
        generator = create_image_generator(settings)
        image = await generator.generate_image(prompt=prompt)
        out_png = DEFAULT_DIR / f"{slug}.live.png"
        out_png.write_bytes(image.content)
        print(f"✓ 图片 ← {generator.model_name}（{len(image.content):,} 字节）")
        print(f"  {out_png}")


def main() -> None:
    parser = argparse.ArgumentParser(description="用项目大模型编译产业链生图提示词")
    parser.add_argument("--slug", default="", help="图谱 slug，读 <slug>.graph.json")
    parser.add_argument("--graph", default="", help="直接指定 graph.json 路径")
    parser.add_argument("--generate", action="store_true", help="再用项目生图模型出图")
    args = parser.parse_args()
    if not args.slug and not args.graph:
        parser.error("至少要给 --slug 或 --graph")

    try:
        asyncio.run(run(args))
    except RuntimeError as exc:  # factory 的配置校验失败
        raise SystemExit(
            f"配置不完整：{exc}\n"
            "检查 backend/.env 里的 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL"
            "（--generate 还需要 IMAGE_API_KEY / IMAGE_BASE_URL / IMAGE_MODEL）"
        ) from None


if __name__ == "__main__":
    main()
