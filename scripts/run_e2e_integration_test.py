#!/usr/bin/env python3
"""
全链路端到端完整测试与防回归健康检查脚本
运行完整下游流水线 (Stage 3 图表生成 -> Stage 4 章节撰写 -> Stage 5 报告融合)，
并调用 verify_pipeline_health.py 进行严谨的交付物验收。
"""

import asyncio
import json
import os
import shutil
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
from backend.app.schemas.workflow import WorkflowState, StageResult, STAGE_ORDER
from scripts.verify_pipeline_health import verify_run


async def run_e2e_test() -> bool:
    run_id = f"test-e2e-run-{int(time.time())}"
    source_run = "run-20260922110809-641"
    source_dir = project_root / "data" / "runs" / source_run

    print("=" * 80)
    print(f"🚀 启动全链路系统端到端完整测试 (E2E Integration Test)")
    print(f"   运行任务 ID: {run_id}")
    print(f"   测试数据源: {source_run} (真实高保真实测数据)")
    print("=" * 80)

    # 1. 准备新任务目录并载入真实数据集与解读报告
    run_dir = storage.get_run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # 复制输入数据与前两阶段产物
    shutil.copy2(source_dir / "input_data.json", run_dir / "input_data.json")
    shutil.copy2(source_dir / "artifacts" / "dataset.json", artifacts_dir / "dataset.json")
    shutil.copy2(source_dir / "artifacts" / "interpretation_report.json", artifacts_dir / "interpretation_report.json")

    # 初始化状态机
    now_str = time.strftime("%Y-%m-%dT%H:%M:%S")
    stage_results = {s: StageResult(stage=s, status="pending", revision=1) for s in STAGE_ORDER}
    stage_results["data_fetch"].status = "approved"
    stage_results["data_interpret"].status = "approved"

    state = WorkflowState(
        project_id="proj-e2e-test",
        run_id=run_id,
        current_stage="chart_generate",
        status="running",
        revision=1,
        stage_results=stage_results,
        created_at=now_str,
        updated_at=now_str,
    )
    storage.save_state(state)

    print("\n▶️ 开始推进阶段 3: 图表生成智能体 (Chart Generator Agent)...")
    start_time = time.time()
    await engine._execute_stage(run_id, "chart_generate", review_stages=["chart_generate", "chapter_write"], feedback=None)
    st = storage.load_state(run_id)
    if st and st.stage_results.get("chart_generate"):
        st.stage_results["chart_generate"].status = "approved"
        st.current_stage = "chapter_write"
        storage.save_state(st)
    elapsed_chart = time.time() - start_time
    print(f"✅ 图表生成完成，耗时: {elapsed_chart:.2f}s")

    print("\n▶️ 开始推进阶段 4: 章节撰写智能体 (Chapter Writer Agent)...")
    start_chapter = time.time()
    await engine._execute_stage(run_id, "chapter_write", review_stages=["chapter_write"], feedback=None)
    st = storage.load_state(run_id)
    if st and st.stage_results.get("chapter_write"):
        st.stage_results["chapter_write"].status = "approved"
        st.current_stage = "report_fusion"
        storage.save_state(st)
    elapsed_chapter = time.time() - start_chapter
    print(f"✅ 章节撰写完成，耗时: {elapsed_chapter:.2f}s")

    print("\n▶️ 开始推进阶段 5: 报告融合智能体 (Report Fusion Agent)...")
    start_fusion = time.time()
    await engine._execute_stage(run_id, "report_fusion", review_stages=[], feedback=None)
    elapsed_fusion = time.time() - start_fusion
    print(f"✅ 报告融合完成，耗时: {elapsed_fusion:.2f}s")

    total_time = time.time() - start_time
    final_state = storage.load_state(run_id)
    print("\n" + "=" * 80)
    print(f"🏁 全流水线端到端执行完毕，总耗时: {total_time:.2f}s")
    print(f"   最终全局状态: {final_state.status if final_state else 'unknown'}")
    print("=" * 80)

    # 2. 检查生成的图表与交付物中的特定质量要素
    charts_dir = artifacts_dir / "charts"
    svg_files = list(charts_dir.glob("*.svg"))
    print(f"\n📊 正在对生成的 {len(svg_files)} 个独立 SVG 矢量图表进行深度质量检验...")

    all_charts_valid = True
    for svg_f in svg_files:
        svg_text = svg_f.read_text(encoding="utf-8")
        assert svg_text.startswith("<svg"), f"{svg_f.name} 不是合法 SVG"
        # 检查图序
        has_fig_num = "图 " in svg_text or "图1" in svg_text
        # 检查色系是否包含中金深蓝
        has_cicc_color = "#1B365D" in svg_text
        print(f"   - {svg_f.name}: 体积 {len(svg_text):,} 字节 | 图序规范: {has_fig_num} | 中金机构色板: {has_cicc_color}")

    # 3. 运行全链路健康检验
    print("\n🏥 运行全链路防回归健康检查 (verify_pipeline_health)...")
    health_passed = verify_run(project_root, run_id)

    return health_passed


if __name__ == "__main__":
    success = asyncio.run(run_e2e_test())
    sys.exit(0 if success else 1)
