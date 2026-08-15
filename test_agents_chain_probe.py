"""链路连通性探测——仅测智能体1真实iFinD数据获取（用例1杜邦财务）。

校验点：
1. 智能体1能否连接真实 iFinD/Iwencai
2. 能否获取宁德时代、比亚迪 2023-2025 财务数据（营收/净利/资产/存货/应收等）
3. 是否有数据缺口/质量门拦截
禁止改动任何生产代码。
"""

import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

os.environ["no_proxy"] = "*"

BACKEND_DIR = Path(__file__).parent / "backend"
os.chdir(str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.schemas.workflow import StageName, StageStatus
from app.workflow.stages import StageContext
from app.agents.data_fetcher.factory import create_data_fetcher_agent


def build_input(qid: str):
    """构造智能体1输入合同。用例1：杜邦财务+边界降级+自动绘图。"""
    if qid == "CASE1":
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
    raise ValueError(f"unknown case {qid}")


async def main():
    print("=" * 60)
    print("智能体1 连通性探测 —— 用例1 杜邦财务")
    print("=" * 60)
    print(f"provider_mode 由 client 决定: 见 skillhub factory")
    print(f"SKILLHUB_USE_MOCK={settings.SKILLHUB_USE_MOCK}, "
          f"IWENCAI_API_KEY={'有' if settings.IWENCAI_API_KEY else '无'}")
    print(f"ENVIRONMENT={settings.ENVIRONMENT}")

    input_data = build_input("CASE1")
    context = StageContext(
        owner_id="test",
        project_id="agents-chain-probe",
        run_id="probe-case1",
        revision=1,
        input_data=input_data,
    )

    from app.integrations.skillhub.client import IwencaiSkillClient
    client = IwencaiSkillClient(
        api_key=settings.IWENCAI_API_KEY.get_secret_value() if settings.IWENCAI_API_KEY else None,
        base_url=settings.IWENCAI_BASE_URL,
        timeout_seconds=settings.TOOL_TIMEOUT_SECONDS,
        max_retries=settings.SKILLHUB_MAX_RETRIES,
    )
    print(f"client.provider_mode = {client.provider_mode}")

    agent = create_data_fetcher_agent(settings)
    result = await agent.run(context)

    print(f"\n状态: {result.status.value if hasattr(result.status, 'value') else result.status}")
    print(f"错误: {result.error or '无'}")
    data = result.data
    evidence = data.get("evidence_items", [])
    datasets = data.get("chart_datasets", [])
    skill_calls = data.get("skill_calls", [])
    gaps = data.get("data_gaps", [])
    quality = data.get("acquisition_quality", {})

    print(f"\n证据数量: {len(evidence)}")
    print(f"图表数据集: {len(datasets)}")
    print(f"skill调用: {len(skill_calls)}")
    print(f"数据缺口: {len(gaps)}")
    print(f"质量门 passed: {quality.get('passed')}")
    print(f"blocking_issues: {data.get('blocking_issues')}")

    print("\n--- skill 调用状态 ---")
    for sc in skill_calls:
        print(f"  {sc.get('skill_name')}: {sc.get('status')} rows={sc.get('row_count')} "
              f"err={sc.get('error_code')}")

    print("\n--- 证据样例(前12条) ---")
    for it in evidence[:12]:
        print(f"  {it.get('evidence_id')} | {it.get('metric_name')} = {it.get('value')} "
              f"{it.get('unit')} | {it.get('period_end')} | scope={it.get('scope')} "
              f"grade={it.get('grade')} source={it.get('source_name')}")

    print("\n--- 数据缺口 ---")
    for g in gaps[:10]:
        print(f"  {g.get('skill_name')}: {g.get('reason_code')} - {g.get('description')}")

    out = Path(__file__).parent / "test_output" / "agents_chain_probe"
    out.mkdir(parents=True, exist_ok=True)
    (out / "agent1_case1.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n探测输出: {out / 'agent1_case1.json'}")


if __name__ == "__main__":
    asyncio.run(main())