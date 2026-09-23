#!/usr/bin/env python3
"""
白银主题端到端全链路自动化测试脚本
从阶段 1 到阶段 5 完整执行，并自动进行防回归健康检查。
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# 添加 backend 与 agents 路径
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))
sys.path.insert(0, str(project_root / "agents_core" / "data-fetcher"))
sys.path.insert(0, str(project_root / "agents_core" / "data-analysis"))
sys.path.insert(0, str(project_root / "agents_core" / "chart-generator"))
sys.path.insert(0, str(project_root / "agents_core" / "chapter-writer"))
sys.path.insert(0, str(project_root / "agents_core" / "report-fusion"))

import backend.app.core.setup_env
from backend.app.schemas.workflow import RunCreateRequest, ResearchInput
from backend.app.engine.state_machine import engine
from backend.app.core.storage import storage
from scripts.verify_pipeline_health import verify_run


async def main() -> None:
    run_id = "test-silver-02"
    industry = "白银"
    print(f"==================================================")
    print(f"🌟 启动全新全链路端到端实测")
    print(f"   运行任务 ID: {run_id}")
    print(f"   研究行业主题: {industry}")
    print(f"   流转策略: 全流程自动化无人值守模式 (review_stages=[])")
    print(f"==================================================")

    req = RunCreateRequest(
        project_id="silver-research",
        input_data=ResearchInput(
            industry_topic=industry,
            focus_questions=[
                "白银现货价格与宏观美元指数、通胀周期的反向联动关系",
                "白银产业链核心标的（如洛阳钼业、深中华A）的财务竞争力与盈利质量对比",
            ],
            analysis_depth="deep",
        ),
        review_stages=[],
    )

    # 准备任务运行目录
    run_dir = storage.get_run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    input_file = run_dir / "input_data.json"
    input_file.write_text(req.model_dump_json(indent=2), encoding="utf-8")

    start_time = time.time()
    
    # 状态机初始化五个阶段
    now_str = time.strftime("%Y-%m-%dT%H:%M:%S")
    from backend.app.schemas.workflow import WorkflowState, StageResult, STAGE_ORDER
    stage_results = {s: StageResult(stage=s, status="pending", revision=1) for s in STAGE_ORDER}
    state = WorkflowState(
        project_id=req.project_id,
        run_id=run_id,
        current_stage="data_fetch",
        status="running",
        revision=1,
        stage_results=stage_results,
        created_at=now_str,
        updated_at=now_str,
    )
    storage.save_state(state)

    print(f"\n▶️ 触发全流程执行...")
    await engine._execute_stage(run_id, "data_fetch", review_stages=[], feedback=None)

    elapsed = time.time() - start_time
    final_state = storage.load_state(run_id)
    print(f"\n==================================================")
    print(f"🏁 流水线执行结束，总耗时: {elapsed:.1f} 秒")
    print(f"   最终全局状态: {final_state.status if final_state else 'unknown'}")
    print(f"==================================================")

    # 执行健康检查
    success = verify_run(project_root, run_id)
    if success:
        print(f"\n🎯 [PASS] 白银主题端到端全链路实测取得完全成功！")
        sys.exit(0)
    else:
        print(f"\n❌ [FAIL] 白银主题全链路实测未通过健康检查！")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
