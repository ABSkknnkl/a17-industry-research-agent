import asyncio
from datetime import datetime
import logging
import sys

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

import backend.app.core.setup_env
from backend.app.core.event_hub import event_hub
from backend.app.core.storage import storage
from backend.app.engine.state_machine import engine


async def main():
    run_id = "run-20260922093902-000"
    print("=" * 80)
    print(f"🚀 从当前中断点继续执行: {run_id} (当前阶段: chart_generate)")
    print(f"⏰ 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    seen = set()

    async def poll_events():
        while True:
            events = event_hub.get_events(run_id)
            for evt in events:
                if evt.id not in seen:
                    seen.add(evt.id)
                    tool_str = f" [{evt.tool}]" if evt.tool else ""
                    print(f"[{evt.timestamp[11:19]}] [{evt.stage_label}] ({evt.event_type}){tool_str} {evt.message}")
            await asyncio.sleep(1.0)

    event_task = asyncio.create_task(poll_events())

    try:
        await engine._execute_stage(run_id, "chart_generate", review_stages=[], feedback=None)
    except Exception as e:
        print(f"\n❌ 执行异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        event_task.cancel()

    final_state = storage.load_state(run_id)
    if final_state:
        print("\n" + "=" * 80)
        print(f"🏁 执行完毕: status={final_state.status}, current_stage={final_state.current_stage}")
        print("=" * 80)
        run_dir = storage.get_run_dir(run_id)
        artifacts_dir = run_dir / "artifacts"
        if artifacts_dir.exists():
            print("\n产物清单:")
            for item in sorted(artifacts_dir.iterdir()):
                if item.is_file():
                    print(f"  - {item.name} ({item.stat().st_size:,} bytes)")
                elif item.is_dir():
                    fc = len(list(item.iterdir()))
                    print(f"  - {item.name}/ ({fc} files)")


if __name__ == "__main__":
    asyncio.run(main())
