import asyncio
from datetime import date, datetime
import json
import logging
from pathlib import Path
import sys

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_unitree")

import backend.app.core.setup_env
from backend.app.core.config import settings
from backend.app.core.event_hub import event_hub
from backend.app.core.storage import storage
from backend.app.engine.state_machine import engine
from backend.app.schemas.workflow import (
    ResearchInput,
    RunCreateRequest,
)


async def main():
    print("=" * 80)
    print("🚀 启动「宇树科技」全链路行业研究流水线端到端测试")
    print(f"⏰ 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    req = RunCreateRequest(
        project_id="proj-unitree-eval",
        input_data=ResearchInput(
            industry_topic="宇树科技",
            market_scope=["中国 A 股"],
            security_types=["股票"],
            reporting_currency="CNY",
            research_as_of=date.today().strftime("%Y-%m-%d"),
            focus_questions=[
                "宇树科技人形与四足机器人核心产品矩阵与技术壁垒",
                "宇树科技产业链供应链及A股核心配套供应商",
                "机器人行业商业化前景与竞争格局",
            ],
            analysis_depth="standard",
            risk_preference="balanced",
        ),
        review_stages=[],  # 全自动流水线推进
    )

    state = await engine.create_run(req)
    run_id = state.run_id
    print(f"\n[任务创建成功] run_id={run_id}, initial_stage={state.current_stage}")

    # 订阅并流式打印 EventHub 事件
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

    # 等待后台流水线任务完成
    running_task = engine._running_tasks.get(run_id)
    if running_task:
        try:
            await running_task
        except Exception as e:
            print(f"\n❌ 流水线执行发生异常: {e}")
        finally:
            event_task.cancel()
    else:
        print("\n⚠️ 未找到运行中的任务！")
        event_task.cancel()

    print("\n" + "=" * 80)
    print("🏁 流水线执行结束，开始对全链路产物与执行日志进行全面检查")
    print("=" * 80)

    final_state = storage.load_state(run_id)
    if not final_state:
        print("❌ 未能加载到最终 state.json！")
        return

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

    print(f"\n运行完成！结果目录: {run_dir}")


if __name__ == "__main__":
    asyncio.run(main())
