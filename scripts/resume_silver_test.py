#!/usr/bin/env python3
"""
断点接续执行 test-silver-02 剩余阶段（阶段3图表生成 -> 阶段4章节撰写 -> 阶段5报告融合）并验证
"""

import asyncio
import sys
import time
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))
sys.path.insert(0, str(project_root / "agents_core" / "data-fetcher"))
sys.path.insert(0, str(project_root / "agents_core" / "data-analysis"))
sys.path.insert(0, str(project_root / "agents_core" / "chart-generator"))
sys.path.insert(0, str(project_root / "agents_core" / "chapter-writer"))
sys.path.insert(0, str(project_root / "agents_core" / "report-fusion"))

import backend.app.core.setup_env
from backend.app.engine.state_machine import engine
from backend.app.core.storage import storage
from scripts.verify_pipeline_health import verify_run


async def main() -> None:
    run_id = "test-silver-02"
    print(f"==================================================")
    print(f"🔄 接续执行白银实测任务 [{run_id}]")
    print(f"   已具备前序产物: dataset.json, interpretation_report.json")
    print(f"   执行后续链路: chart_generate -> chapter_write -> report_fusion")
    print(f"==================================================")

    state = storage.load_state(run_id)
    if not state:
        print(f"❌ 未找到任务状态: {run_id}")
        sys.exit(1)

    # 标记阶段2为 approved
    state.stage_results["data_interpret"].status = "approved"
    state.current_stage = "chart_generate"
    state.status = "running"
    storage.save_state(state)

    start_time = time.time()
    await engine._execute_stage(run_id, "chart_generate", review_stages=[], feedback=None)

    elapsed = time.time() - start_time
    final_state = storage.load_state(run_id)
    print(f"\n==================================================")
    print(f"🏁 流水线接续执行结束，耗时: {elapsed:.1f} 秒")
    print(f"   最终全局状态: {final_state.status if final_state else 'unknown'}")
    print(f"==================================================")

    success = verify_run(project_root, run_id)
    if success:
        print(f"\n🎯 [PASS] 白银主题端到端全链路实测取得完全成功！")
        sys.exit(0)
    else:
        print(f"\n❌ [FAIL] 白银主题全链路实测未通过健康检查！")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
