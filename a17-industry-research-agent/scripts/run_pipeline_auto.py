#!/usr/bin/env python3
"""全链路五智能体一键全自动执行（无人工审核门）。

设计要点：
- review_stages=[] 让状态机自动串行推进 5 个阶段，中间不停顿；
- 报告版式由 chart_mode 决定，默认 auto（券商研报 A4 版式：封面 + 目录 + 章节 + 来源表）；
- 事件流实时打印并落盘，便于长任务过程中追踪进度。

Usage:
    python scripts/run_pipeline_auto.py --topic 低空经济 --depth standard

Args:
    --topic: 研究行业主题（必填）
    --depth: 分析深度 overview/standard/deep，默认 standard（越快越好）
    --project-id: 项目标识，默认由主题派生

Returns:
    进程退出码 0 表示流水线跑到 completed；2 表示中途失败。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, datetime
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_pipeline_auto")


STAGES = ["data_fetch", "data_interpret", "chart_generate", "chapter_write", "report_fusion"]


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="五智能体全链路全自动执行 / 断点续跑")
    parser.add_argument("--topic", help="研究行业主题（新建任务时必填）")
    parser.add_argument(
        "--depth",
        default="standard",
        choices=["overview", "standard", "deep"],
        help="分析深度，越浅越快",
    )
    parser.add_argument("--project-id", default=None, help="项目标识")
    parser.add_argument("--resume-run", default=None, help="已有 run_id，断点续跑而非新建")
    parser.add_argument(
        "--from-stage",
        default=None,
        choices=STAGES,
        help="续跑的起始阶段（缺省自动定位第一个未完成阶段）",
    )
    args = parser.parse_args()
    if not args.resume_run and not args.topic:
        parser.error("新建任务必须提供 --topic；续跑请用 --resume-run")
    return args


async def main() -> int:
    """驱动状态机跑完整条流水线并汇总产物。"""
    args = parse_args()
    topic = args.topic or args.resume_run or ""
    project_id = args.project_id or f"proj-{abs(hash(topic)) % 10**8}"

    import backend.app.core.setup_env  # noqa: F401 - 注册 agents_core 各子目录到 sys.path
    from backend.app.core.config import settings
    from backend.app.core.event_hub import event_hub
    from backend.app.core.storage import storage
    from backend.app.engine.state_machine import engine
    from backend.app.schemas.workflow import ResearchInput, RunCreateRequest

    print("=" * 84)
    if args.resume_run:
        print(f"♻️ 断点续跑任务 {args.resume_run}（起始阶段: {args.from_stage or '自动定位'}）")
    else:
        print(f"🚀 启动「{topic}」全链路行业研究流水线（全自动 / 深度={args.depth}）")
    print(f"⏰ 开始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"LLM: {settings.LLM_MODEL} @ {settings.LLM_BASE_URL}")
    print(f"问财 Key: {'set' if settings.IWENCAI_API_KEY else 'MISSING'}")
    import os
    print(f"产业链生图: {'已启用' if os.getenv('IMAGE_API_KEY', '').strip() else '已跳过（未配置 IMAGE_API_KEY）'}")
    print("=" * 84, flush=True)

    if args.resume_run:
        state = await engine.resume_run(args.resume_run, from_stage=args.from_stage)
    else:
        req = RunCreateRequest(
            project_id=project_id,
            input_data=ResearchInput(
                industry_topic=topic,
                market_scope=["中国 A 股"],
                security_types=["股票"],
                reporting_currency="CNY",
                research_as_of=date.today().strftime("%Y-%m-%d"),
                focus_questions=[
                    f"{topic}产业链上中下游核心环节与代表标的",
                    f"{topic}行业规模、增长驱动与竞争格局",
                    f"{topic}商业化进度、政策环境与主要风险",
                ],
                analysis_depth=args.depth,
                risk_preference="balanced",
            ),
            # 空列表 = 全自动，不设人工审核门
            review_stages=[],
        )
        state = await engine.create_run(req)
    run_id = state.run_id
    print(f"\n[任务启动] run_id={run_id} stage={state.current_stage}\n", flush=True)

    seen: set[str] = set()

    async def poll_events() -> None:
        """逐条增量打印智能体执行动线。"""
        while True:
            for evt in event_hub.get_events(run_id):
                if evt.id in seen:
                    continue
                seen.add(evt.id)
                tool = f" [{evt.tool}]" if evt.tool else ""
                ts = evt.timestamp[11:19] if len(evt.timestamp) >= 19 else ""
                print(f"[{ts}] [{evt.stage_label}] ({evt.event_type}){tool} {evt.message}", flush=True)
            await asyncio.sleep(1.5)

    poll_task = asyncio.create_task(poll_events())
    running = engine._running_tasks.get(run_id)
    try:
        if running:
            await running
        else:
            print("⚠️ 未找到运行中任务", flush=True)
    except Exception as exc:  # noqa: BLE001 - 需要把失败原样呈现给用户
        print(f"\n❌ 流水线异常: {exc}", flush=True)
    finally:
        poll_task.cancel()

    final = storage.load_state(run_id)
    print("\n" + "=" * 84)
    print(f"最终状态: status={final.status if final else '?'} stage={final.current_stage if final else '?'}")
    if final:
        for stage, sr in final.stage_results.items():
            err = f" error={sr.error}" if sr.error else ""
            print(f"  - {stage}: {sr.status}{err}")
    run_dir = storage.get_run_dir(run_id)
    art = run_dir / "artifacts"
    if art.exists():
        for item in sorted(art.iterdir()):
            if item.is_file():
                print(f"  * {item.name} ({item.stat().st_size:,} bytes)")
            elif item.is_dir():
                print(f"  * {item.name}/ ({len(list(item.iterdir()))} files)")
    print(f"run_dir={run_dir}")
    print(f"RUN_ID={run_id}")
    print(f"DONE_AT={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 84, flush=True)
    return 0 if final and final.status == "completed" else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
