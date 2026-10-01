#!/usr/bin/env python3
"""
真实环境全链路 5 智能体流水线实测运行脚本
使用用户真实配置的 Volcengine Ark (deepseek-v4-flash) 与同花顺官方问财 SkillHub 凭证。
"""

import asyncio
from datetime import date, datetime
import json
import logging
from pathlib import Path
import sys
import time

# Ensure project root is in sys.path
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("real_run")

import backend.app.core.setup_env
from backend.app.core.config import settings
from backend.app.core.event_hub import event_hub
from backend.app.core.storage import storage
from backend.app.engine.state_machine import engine
from backend.app.schemas.workflow import ResearchInput, RunCreateRequest


import argparse

async def main():
    parser = argparse.ArgumentParser(description="全链路 5 智能体真实流水线端到端运行脚本")
    parser.add_argument("pos_topic", nargs="?", default=None, help="研究行业主题 (如 具身智能 / 宠物经济 / 商业航天 / 创新药 / 跨境电商)")
    parser.add_argument("--topic", "-t", type=str, default=None, help="研究行业主题")
    parser.add_argument("--depth", "-d", choices=["standard", "deep"], default="standard", help="分析深度 (standard / deep)")
    parser.add_argument("--must-include", "-m", nargs="+", default=[], help="明确指定核心上市公司 (如 鸣志电器 绿的谐波)")
    parser.add_argument("--focus-points", "--focus", "-f", nargs="+", default=[], help="自定义投研关注要点")
    parser.add_argument("--market-scope", nargs="+", default=["中国 A 股"], help="市场范围 (默认: 中国 A 股)")
    parser.add_argument("--as-of", type=str, default=None, help="研究基准日 (默认今天 YYYY-MM-DD)")
    parser.add_argument("--project-id", type=str, default="real-eval", help="项目标识")
    args = parser.parse_args()

    topic = args.topic or args.pos_topic or "具身智能"
    as_of = args.as_of or date.today().strftime("%Y-%m-%d")

    # 构建高密度专业投研问题（任意行业通用）
    if args.focus_points:
        focus_questions = list(args.focus_points)
    else:
        focus_questions = [
            f"{topic}产业链核心环节（上游核心原料/关键零部件、中游专业装备制造、下游核心应用场景与运营服务）代表性上市公司与产业分工",
            f"{topic}核心A股标的的营收规模、盈利质量、毛利率、净利率、ROE、资产负债率及估值水平",
            f"{topic}行业发展驱动因素、政策催化、市场规模演进与潜在投资风险",
        ]

    # 若指定了必须包含的核心标的，追加高优先级实体穿透提示
    if args.must_include:
        focus_questions.append(
            f"重点调研核心标的（如 {'、'.join(args.must_include)}）的竞争壁垒、产能扩张、财务三表时序与估值空间"
        )

    # 审计多 Key 配置
    active_keys = [k.strip() for k in settings.IWENCAI_API_KEY.split(",") if k.strip()]

    print("=" * 80)
    print(f"🚀 启动「{topic}」真实全链路行业研究流水线端到端实测")
    print(f"⏰ 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🧠 模型基座: {settings.LLM_MODEL} @ {settings.LLM_BASE_URL}")
    print(f"🔑 问财网关: 检测到 {len(active_keys)} 个活跃 API Key (已启用多 Key 自动轮询与故障转移)")
    if args.must_include:
        print(f"🏢 指定标的: {'、'.join(args.must_include)}")
    print(f"⚙️ 分析深度: {args.depth.upper()}, 基准日期: {as_of}")
    print("=" * 80)

    req = RunCreateRequest(
        project_id=args.project_id,
        input_data=ResearchInput(
            industry_topic=topic,
            market_scope=args.market_scope,
            security_types=["股票"],
            reporting_currency="CNY",
            research_as_of=as_of,
            focus_questions=focus_questions,
            analysis_depth=args.depth,
            risk_preference="balanced",
        ),
        review_stages=[],  # 全自动无人值守推进全 5 阶段
    )

    state = await engine.create_run(req)
    run_id = state.run_id
    print(f"\n[任务创建成功] 任务 ID: {run_id}, 起始阶段: {state.current_stage}")

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
        finally:
            event_task.cancel()
    else:
        print("\n⚠️ 未找到运行中的任务！")
        event_task.cancel()

    elapsed = time.time() - start_time
    print("\n" + "=" * 80)
    print(f"🏁 全链路真实流水线执行结束，总耗时: {elapsed:.1f} 秒")
    print("=" * 80)

    final_state = storage.load_state(run_id)
    if not final_state:
        print("❌ 未能加载到最终 state.json！")
        return

    print(f"最终状态: {final_state.status}, 当前阶段: {final_state.current_stage}")
    for s_name, s_res in final_state.stage_results.items():
        print(f"  - 阶段 {s_name}: status={s_res.status}, artifacts={len(s_res.artifacts)}")

    run_dir = storage.get_run_dir(run_id)
    artifacts_dir = run_dir / "artifacts"
    print("\n产物目录检查 (artifacts/):")
    if artifacts_dir.exists():
        for item in sorted(artifacts_dir.iterdir()):
            if item.is_file():
                print(f"  📄 {item.name:<30} ({item.stat().st_size:,} bytes)")
            elif item.is_dir():
                sub_count = len(list(item.iterdir()))
                print(f"  📁 {item.name}/ ({sub_count} 个文件)")

    # 打印最终生成的研报概要
    report_md = artifacts_dir / "report.md"
    if report_md.exists():
        content = report_md.read_text(encoding="utf-8")
        print("\n" + "-" * 40 + " 研报前 500 字符预览 " + "-" * 40)
        print(content[:500] + "...\n" + "-" * 80)

    print(f"\n✅ 完整研报成果已落盘至: {run_dir}")
    if (artifacts_dir / "report.pdf").exists():
        print(f"  📕 PDF 出版级研报: {artifacts_dir / 'report.pdf'} ({Path(artifacts_dir / 'report.pdf').stat().st_size:,} bytes)")
    if (artifacts_dir / "report.html").exists():
        print(f"  🌐 交互式 HTML 研报: {artifacts_dir / 'report.html'} ({Path(artifacts_dir / 'report.html').stat().st_size:,} bytes)")
    if (artifacts_dir / "report.md").exists():
        print(f"  📝 Markdown 深度正文: {artifacts_dir / 'report.md'} ({Path(artifacts_dir / 'report.md').stat().st_size:,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
