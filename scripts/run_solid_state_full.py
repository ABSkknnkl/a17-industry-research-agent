#!/usr/bin/env python3
"""固态电池主题 — 五智能体全自动全链路端到端执行"""
import asyncio
from datetime import date, datetime
import logging
from pathlib import Path
import sys

project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_solid_state")

import backend.app.core.setup_env
from backend.app.core.config import settings
from backend.app.core.event_hub import event_hub
from backend.app.core.storage import storage
from backend.app.engine.state_machine import engine
from backend.app.schemas.workflow import ResearchInput, RunCreateRequest

TOPIC = "固态电池"


async def main():
    print("=" * 80)
    print(f"🚀 启动「{TOPIC}」全链路行业研究流水线（全自动）")
    print(f"⏰ 开始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    print(f"LLM: {settings.LLM_MODEL} @ {settings.LLM_BASE_URL}")
    print(f"问财 Key: {'set' if settings.IWENCAI_API_KEY else 'MISSING'}")
    import os
    print(f"生图 Key: {'set' if os.getenv('IMAGE_API_KEY') else 'MISSING'}")

    req = RunCreateRequest(
        project_id="proj-solid-state-battery",
        input_data=ResearchInput(
            industry_topic=TOPIC,
            market_scope=["中国 A 股"],
            security_types=["股票"],
            reporting_currency="CNY",
            research_as_of=date.today().strftime("%Y-%m-%d"),
            focus_questions=[
                "固态电池技术路线（硫化物/氧化物/聚合物）与产业化进度",
                "固态电池产业链上中下游核心环节与A股代表标的财务竞争力",
                "固态电池商业化前景、竞争格局与主要风险",
            ],
            analysis_depth="deep",
            risk_preference="balanced",
        ),
        review_stages=[],
    )

    state = await engine.create_run(req)
    run_id = state.run_id
    print(f"\n[任务创建] run_id={run_id}, stage={state.current_stage}")

    seen = set()

    async def poll_events():
        while True:
            for evt in event_hub.get_events(run_id):
                if evt.id not in seen:
                    seen.add(evt.id)
                    tool = f" [{evt.tool}]" if evt.tool else ""
                    print(f"[{evt.timestamp[11:19]}] [{evt.stage_label}] ({evt.event_type}){tool} {evt.message}")
            await asyncio.sleep(1.5)

    poll_task = asyncio.create_task(poll_events())
    running = engine._running_tasks.get(run_id)
    if running:
        try:
            await running
        except Exception as e:
            print(f"\n❌ 流水线异常: {e}")
        finally:
            poll_task.cancel()
    else:
        print("⚠️ 未找到运行中任务")
        poll_task.cancel()

    final = storage.load_state(run_id)
    print("\n" + "=" * 80)
    print(f"最终状态: status={final.status if final else '?'}, stage={final.current_stage if final else '?'}")
    run_dir = storage.get_run_dir(run_id)
    art = run_dir / "artifacts"
    if art.exists():
        for item in sorted(art.iterdir()):
            if item.is_file():
                print(f"  - {item.name} ({item.stat().st_size:,} bytes)")
            elif item.is_dir():
                print(f"  - {item.name}/ ({len(list(item.iterdir()))} files)")
    print(f"run_dir={run_dir}")
    print(f"RUN_ID={run_id}")


if __name__ == "__main__":
    asyncio.run(main())
