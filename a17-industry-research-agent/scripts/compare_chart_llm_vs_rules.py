"""对照实验：智能体3「有 LLM」vs「纯确定性规则」的产出差异。

用法::

    <venv>/bin/python scripts/compare_chart_llm_vs_rules.py            # 跑无 LLM 全流程
    <venv>/bin/python scripts/compare_chart_llm_vs_rules.py --with-llm # 真调 LLM 跑一遍（约 1 分钟）

对照组说明：
- 「无 LLM」= 置空 LLM_API_KEY → agent.run() 走 `_deterministic_fallback` 分支（:362-374），
  并经过与主流程**完全相同**的后处理（linter → 多样性约束 → 排序裁剪）。
- 「有 LLM」= 不干预环境变量，走 `_plan_charts` 的 LLM 选型分支。
两者用同一份 interpretation_report.json，因此差异可归因于 LLM。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path("/Users/Zhuanz1/Downloads/行业研究智能体-全链路系统 4")
RUN = ROOT / "data/runs/run-20260926022235-107"  # 低空经济，已有真实 LLM 产出可对照

parser = argparse.ArgumentParser()
parser.add_argument("--with-llm", action="store_true", help="真调 LLM（有成本，约 1 分钟）")
parser.add_argument("--max-charts", type=int, default=15)
parser.add_argument("--allow-image", action="store_true",
                    help="允许调用产业链生图模型（默认禁止：本对照实验不需要、且会花钱花时间）")
args = parser.parse_args()

if not args.with_llm:
    # 必须在导入 config 之前置空：_load_env_files() 只在变量「不存在」时才写 .env
    os.environ["LLM_API_KEY"] = ""

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents_core/chart-generator"))

import backend.app.core.setup_env  # noqa: F401,E402
import chart_generator.agent as agent_module  # noqa: E402
from chart_generator.agent import ChartGeneratorAgent  # noqa: E402
from chart_generator.models import (  # noqa: E402
    ChartGenerationRequest,
    ChartPreferences,
    InterpretationReport,
)

if not args.allow_image:
    # 关键：把 agent 模块命名空间里的生图入口换成 no-op。
    # agent.run() 在 segments 非空时会调它（agent.py:549），本对照实验不需要，
    # 且生图单次最长 600s、按次计费 —— 必须显式屏蔽，否则实验既慢又花钱。
    async def _image_disabled(**_kwargs):
        return None

    agent_module.generate_industry_chain_image = _image_disabled
    print("[已屏蔽] 产业链生图模型不会被调用（用 --allow-image 可放开）")


def load_report() -> InterpretationReport:
    data = json.loads((RUN / "artifacts/interpretation_report.json").read_text(encoding="utf-8"))
    return InterpretationReport.model_validate(data)


def summarize(label: str, charts: list, suppressed: list, events: list) -> None:
    types = Counter(c.get("chart_type") for c in charts)
    chapters = Counter(c.get("recommended_chapter_id") or "未标注" for c in charts)
    print(f"\n{'=' * 74}")
    print(f"【{label}】")
    print(f"{'=' * 74}")
    print(f"成图 {len(charts)} 张 | 抑制 {len(suppressed)} 张")
    print(f"图表类型 {len(types)} 种: {dict(types)}")
    print(f"章节分布 {len(chapters)} 章: {dict(chapters)}")
    skills = [e for e in events if e["event"] in ("skill_invoked_by_llm", "skill_routed_by_policy")]
    print(f"技能加载方式: {skills[0]['event'] if skills else '-'} "
          f"（{len(skills[0]['details'].get('skills') or []) if skills and 'skills' in skills[0]['details'] else len(skills)} 个）")
    print("\n标题清单:")
    for i, c in enumerate(charts, 1):
        print(f"  {i:2d}. [{c.get('recommended_chapter_id') or '?'}] "
              f"{str(c.get('chart_type')):<15} {c.get('title')}")


async def main() -> None:
    agent = ChartGeneratorAgent()
    print(f"LLM 可用: {agent.llm.is_available}")
    req = ChartGenerationRequest(
        report=load_report(),
        input_dataset=None,
        preferences=ChartPreferences(max_charts=args.max_charts),
    )
    events: list[dict] = []

    async def emit(ev: dict) -> None:
        events.append(ev)

    result = await agent.run(req, emit=emit, save_artifacts=False)
    charts = [c.model_dump(mode="json") for c in (result.charts or [])]
    suppressed = [s.model_dump(mode="json") for s in (getattr(result, "suppressed_charts", None) or [])]

    label = "有 LLM（LLM 选型分支）" if args.with_llm else "无 LLM（确定性规则分支）"
    summarize(label, charts, suppressed, events)


asyncio.run(main())
