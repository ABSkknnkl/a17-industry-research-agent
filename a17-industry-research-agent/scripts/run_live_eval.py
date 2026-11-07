#!/usr/bin/env python3
"""
全链路实战评测脚本 (Live End-to-End Evaluation)
行业主题: 人形机器人
测试全链路 5 大智能体真实在线协同、数据融合、出版级图表生成、章节写作与多格式报告交付。
"""

import asyncio
from datetime import date, datetime
import json
import logging
from pathlib import Path
import sys
import time

# 路径加载
project_root = Path(__file__).resolve().parent.parent
for p in [
    project_root,
    project_root / "backend",
    project_root / "agents_core" / "data-fetcher",
    project_root / "agents_core" / "data-analysis",
    project_root / "agents_core" / "chart-generator",
    project_root / "agents_core" / "chapter-writer",
    project_root / "agents_core" / "report-fusion",
]:
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import backend.app.core.setup_env
from backend.app.core.config import settings
from backend.app.core.event_hub import event_hub
from backend.app.core.storage import storage
from backend.app.engine.state_machine import engine
from backend.app.schemas.workflow import (
    ResearchInput,
    RunCreateRequest,
)
from scripts.verify_pipeline_health import verify_run

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("live_eval")


async def main():
    print("=" * 80)
    print("🌟 启动全链路实战评测: 人形机器人 (Humanoid Robotics)")
    print(f"⏰ 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🤖 LLM 模型: {settings.LLM_MODEL} ({settings.LLM_BASE_URL})")
    print(f"📊 问财凭证: {settings.IWENCAI_API_KEY[:15]}...")
    print("=" * 80)

    req = RunCreateRequest(
        project_id="proj-humanoid-robotics-eval",
        input_data=ResearchInput(
            industry_topic="人形机器人",
            market_scope=["中国 A 股"],
            security_types=["股票"],
            reporting_currency="CNY",
            research_as_of="2026-09-24",
            focus_questions=[
                "人形机器人核心执行器与关键零部件（减速器、伺服电机、传感器、行星滚柱丝杠）供应链竞争格局与技术壁垒",
                "A股核心标的（如绿的谐波、三花智控、鸣志电器、拓普集团）的财务表现、毛利率中枢与估值溢价",
                "人形机器人量产进度、BOM成本下降曲线与商业化场景落地瓶颈",
            ],
            analysis_depth="standard",
            risk_preference="balanced",
        ),
        review_stages=[],  # 全流程自动化流转
    )

    state = await engine.create_run(req)
    run_id = state.run_id
    print(f"\n[任务创建成功] run_id={run_id}, initial_stage={state.current_stage}")

    seen_event_ids = set()

    async def poll_events():
        while True:
            events = event_hub.get_events(run_id)
            for evt in events:
                if evt.id not in seen_event_ids:
                    seen_event_ids.add(evt.id)
                    tool_str = f" [{evt.tool}]" if evt.tool else ""
                    print(f"[{evt.timestamp[11:19]}] [{evt.stage_label}] ({evt.event_type}){tool_str} {evt.message}")
            await asyncio.sleep(1.0)

    event_task = asyncio.create_task(poll_events())
    start_time = time.time()

    running_task = engine._running_tasks.get(run_id)
    if running_task:
        try:
            await running_task
        except Exception as e:
            print(f"\n❌ 流水线执行发生异常: {e}")
            import traceback
            traceback.print_exc()
        finally:
            event_task.cancel()
    else:
        print("\n⚠️ 未找到运行中的任务！")
        event_task.cancel()

    elapsed = time.time() - start_time
    print("\n" + "=" * 80)
    print(f"🏁 流水线执行完成，总耗时: {elapsed:.1f} 秒 ({elapsed / 60:.2f} 分钟)")
    print("=" * 80)

    final_state = storage.load_state(run_id)
    if not final_state:
        print("❌ 未能加载到最终 state.json！")
        sys.exit(1)

    print(f"最终流水线状态: status={final_state.status}, current_stage={final_state.current_stage}")
    run_dir = storage.get_run_dir(run_id)
    artifacts_dir = run_dir / "artifacts"

    print("\n产物清单 (artifacts/):")
    if artifacts_dir.exists():
        for item in sorted(artifacts_dir.iterdir()):
            if item.is_file():
                print(f"  - {item.name} ({item.stat().st_size:,} bytes)")
            elif item.is_dir():
                file_count = len(list(item.iterdir()))
                print(f"  - {item.name}/ ({file_count} files)")

    # 执行健康检查
    success = verify_run(project_root, run_id)
    if not success:
        print(f"\n❌ 健康检查未完全通过，请检查上述错误日志！")
        sys.exit(1)

    print(f"\n🎉 [PASS] 人形机器人实战评测圆满成功！产物目录: {artifacts_dir}")


if __name__ == "__main__":
    asyncio.run(main())
