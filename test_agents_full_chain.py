"""端到端链路测试——智能体1→2→3 真实数据源+真实LLM（用例1杜邦财务）。

校验点：
A. 智能体1获取真实数据质量门通过
B. 智能体2确定性计算（杜邦/存货周转/应收周转/毛利率/营收同比）正确性
C. 智能体2 LLM 输出 chart_candidates 能否被智能体3消费生成图表
D. 链路贯通：智能体3 基于智能体2 候选 + 智能体1 数据集生成图表
禁止改动任何生产代码。
"""

import asyncio
import json
import os
import sys
from pathlib import Path

os.environ["no_proxy"] = "*"

BACKEND_DIR = Path(__file__).parent / "backend"
os.chdir(str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.integrations.llm.openai_compatible import OpenAICompatibleAnalysisModel
from app.schemas.workflow import StageName, StageStatus
from app.workflow.stages import StageContext
from app.agents.data_fetcher.factory import create_data_fetcher_agent
from app.agents.data_interpreter.service import DataInterpreterAgent


def build_case1_input():
    return {
        "industry_topic": "动力电池",
        "market_scope": ["中国"],
        "security_types": ["A股"],
        "reporting_currency": "CNY",
        "research_as_of": "2026-08-12",
        "focus_questions": [
            "整理宁德时代、比亚迪2023-2025财务报表，完成杜邦ROE拆解，计算存货周转天数、应收账款周转天数、毛利率、营收同比"
        ],
        "evidence_items": [],
        "analysis_depth": "standard",
        "risk_preference": "balanced",
        "research_brief": {
            "geography": "中国",
            "time_range": "2023-01-01至2025-12-31",
            "included_topics": [],
            "excluded_topics": [],
            "focus_companies": ["宁德时代", "比亚迪"],
            "report_depth": "standard",
        },
        "data_fetch_options": {
            "metrics": ["营业收入", "营业成本", "净利润", "总资产", "股东权益", "存货", "应收账款"],
            "industry_scope": ["宁德时代", "比亚迪"],
        },
    }


async def main():
    out = Path(__file__).parent / "test_output" / "agents_full_chain"
    out.mkdir(parents=True, exist_ok=True)

    # ============ 智能体1 ============
    print("=" * 60)
    print("智能体1：真实 iFinD 数据获取")
    print("=" * 60)
    agent1 = create_data_fetcher_agent(settings)
    ctx1 = StageContext(
        owner_id="test", project_id="agents-full-chain", run_id="chain-case1",
        revision=1, input_data=build_case1_input(),
    )
    r1 = await agent1.run(ctx1)
    print(f"状态={r1.status.value} 错误={r1.error or '无'}")
    d1 = r1.data
    print(f"证据={len(d1.get('evidence_items', []))} 数据集={len(d1.get('chart_datasets', []))} "
          f"质量门={d1.get('acquisition_quality', {}).get('passed')}")
    (out / "agent1.json").write_text(json.dumps(d1, ensure_ascii=False, indent=2), encoding="utf-8")

    # ============ 智能体2 ============
    print("\n" + "=" * 60)
    print("智能体2：真实 DeepSeek LLM 分析 + 确定性计算")
    print("=" * 60)
    model = OpenAICompatibleAnalysisModel(
        model_name=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY.get_secret_value() if settings.LLM_API_KEY else None,
        base_url=settings.LLM_BASE_URL,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        max_output_tokens=settings.LLM_MAX_OUTPUT_TOKENS,
        segmented_threshold_chars=settings.LLM_SEGMENTED_THRESHOLD_CHARS,
    )
    agent2 = DataInterpreterAgent(model=model)
    ctx2 = StageContext(
        owner_id="test", project_id="agents-full-chain", run_id="chain-case1",
        revision=1, input_data=build_case1_input(),
        previous_results={StageName.DATA_FETCH: r1},
    )
    r2 = await agent2.run(ctx2)
    print(f"状态={r2.status.value} 错误={r2.error or '无'}")
    d2 = r2.data
    metrics = d2.get("calculated_metrics", [])
    candidates = d2.get("chart_candidates", [])
    issues = d2.get("calculation_issues", [])
    print(f"计算指标={len(metrics)} 图表候选={len(candidates)} 计算问题={len(issues)}")
    print("--- 图表候选 ---")
    for c in candidates:
        print(f"  {c.get('chart_type')}: {c.get('title')} ids={len(c.get('evidence_ids', []))}")
    (out / "agent2.json").write_text(json.dumps(d2, ensure_ascii=False, indent=2), encoding="utf-8")

    # ============ 智能体3 ============
    print("\n" + "=" * 60)
    print("智能体3：图表生成")
    print("=" * 60)
    from app.agents.chart_generator.service import ChartGeneratorAgent
    agent3 = ChartGeneratorAgent()
    ctx3 = StageContext(
        owner_id="test", project_id="agents-full-chain", run_id="chain-case1",
        revision=1, input_data=build_case1_input(),
        previous_results={StageName.DATA_FETCH: r1, StageName.DATA_INTERPRET: r2},
    )
    r3 = await agent3.run(ctx3)
    print(f"状态={r3.status.value} 错误={r3.error or '无'}")
    d3 = r3.data
    specs = d3.get("chart_specs", [])
    suppressed = d3.get("suppressed_candidates", [])
    quality = d3.get("quality", {})
    print(f"生成图表={len(specs)} 抑制={len(suppressed)} 质量门={quality.get('passed')}")
    for s in specs:
        print(f"  {s.get('chart_type')}: {s.get('title')}")
    if suppressed:
        print("--- 抑制/降级 ---")
        for s in suppressed:
            print(f"  {s.get('title')}: [{s.get('reason_code')}] {s.get('reason')}")
    (out / "agent3.json").write_text(json.dumps(d3, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n产物目录: {out}")


if __name__ == "__main__":
    asyncio.run(main())