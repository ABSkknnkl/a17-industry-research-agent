"""4条高难度话术——智能体1真实数据获取 + 智能体2确定性计算验证。

不对每条跑智能体2 LLM（已知 LengthFinishReasonError 系统性失败），
重点验证：智能体1能否获取正确数据、智能体2确定性计算（杜邦/CRn/产能利用率/产销率）是否正确。
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
from app.schemas.evidence import EvidenceItem
from app.schemas.workflow import StageName
from app.workflow.stages import StageContext
from app.agents.data_fetcher.factory import create_data_fetcher_agent
from app.agents.data_interpreter.calculations import calculate_p0_metrics


def build_input(case: str) -> dict:
    base = {
        "market_scope": ["中国"],
        "security_types": ["A股"],
        "reporting_currency": "CNY",
        "research_as_of": "2026-08-12",
        "evidence_items": [],
        "analysis_depth": "standard",
        "risk_preference": "balanced",
        "research_brief": {
            "geography": "中国", "included_topics": [], "excluded_topics": [],
            "report_depth": "standard",
        },
    }
    if case == "CASE1":
        base.update({
            "industry_topic": "动力电池",
            "focus_questions": ["整理宁德时代、比亚迪2023-2025财务报表，完成杜邦ROE拆解，计算存货周转天数、应收账款周转天数、毛利率、营收同比"],
            "research_brief": {**base["research_brief"], "time_range": "2023-01-01至2025-12-31",
                               "focus_companies": ["宁德时代", "比亚迪"]},
            "data_fetch_options": {"metrics": ["营业收入", "营业成本", "净利润", "总资产", "股东权益", "存货", "应收账款"],
                                   "industry_scope": ["宁德时代", "比亚迪"]},
        })
    elif case == "CASE2":
        base.update({
            "industry_topic": "动力电池",
            "focus_questions": ["获取国内动力电池厂商历年市占明细，自动计算CR3、CR5集中度，合并尾部小企业份额"],
            "data_fetch_options": {"metrics": ["市占率", "市场份额"], "industry_scope": ["动力电池"]},
        })
    elif case == "CASE3":
        base.update({
            "industry_topic": "储能逆变器",
            "focus_questions": ["采集储能逆变器企业市场份额明细，计算行业集中度CR5，同一份份额数据同时输出饼图与柱状对比图"],
            "data_fetch_options": {"metrics": ["市占率", "市场份额"], "industry_scope": ["储能逆变器"]},
        })
    elif case == "CASE4":
        base.update({
            "industry_topic": "光伏产业链",
            "focus_questions": ["汇总光伏产业链各环节2022-2025产量、产能数据，计算产能利用率与产销率，梳理上下游结构绘制产业链图谱"],
            "data_fetch_options": {"metrics": ["产量", "产能", "销量", "有效产能", "产能利用率", "产销率"],
                                   "industry_scope": ["光伏"]},
        })
    else:
        raise ValueError(case)
    return base


CHECKPOINTS = {
    "CASE1": ["杜邦ROE", "存货周转天数", "应收账款周转天数", "毛利率", "营收同比", "期初缺失自动降级", "图表互斥"],
    "CASE2": ["聚合算子CR3", "聚合算子CR5", "图表互斥(饼图/堆叠柱状二选一)", "不捏造缺失份额"],
    "CASE3": ["CR5集中度", "allow_multiple_charts_per_dataset", "互斥限制解除", "不伪造数值"],
    "CASE4": ["产能利用率", "产销率", "产业链图数量上限", "季度/年度混用拦截"],
}


async def main():
    out = Path(__file__).parent / "test_output" / "agents_allcases"
    out.mkdir(parents=True, exist_ok=True)
    agent1 = create_data_fetcher_agent(settings)

    for case in ["CASE1", "CASE2", "CASE3", "CASE4"]:
        print("\n" + "=" * 70)
        print(f"话术 {case}")
        print("=" * 70)
        input_data = build_input(case)
        ctx = StageContext(owner_id="test", project_id="agents-allcases",
                           run_id=f"all-{case}", revision=1, input_data=input_data)
        r1 = await agent1.run(ctx)
        d1 = r1.data
        ev = [EvidenceItem.model_validate(x) for x in d1.get("evidence_items", [])]
        print(f"[智能体1] 状态={r1.status.value} 错误={r1.error or '无'} "
              f"证据={len(ev)} 数据集={len(d1.get('chart_datasets', []))} "
              f"质量门={d1.get('acquisition_quality', {}).get('passed')}")

        # 检查关键指标覆盖率
        names = {(x.get('metric_name') or '') for x in d1.get("evidence_items", [])}
        targets = {
            "CASE2": ["市占率", "市场份额", "市场占有率"],
            "CASE3": ["市占率", "市场份额"],
            "CASE4": ["产量", "产能", "销量", "产能利用率"],
        }.get(case, [])
        if targets:
            hit = [t for t in targets if any(t in n for n in names)]
            miss = [t for t in targets if t not in hit]
            print(f"[覆盖率] 命中={hit} 缺失={miss or '无'}")

        # 智能体2确定性计算
        metrics, issues = calculate_p0_metrics(ev)
        print(f"[智能体2确定性计算] 指标={len(metrics)} 问题={len(issues)}")
        for m in metrics:
            print(f"   {m.calculation_type:<22} {m.metric_name:<12} {m.value:.4f} {m.unit} @ {m.period_end} scope={m.entity_scope}")
        for i in issues[:8]:
            print(f"   [问题] {i.calculation_type}: {i.reason}")

        # 生成简化报告
        report = {
            "case": case, "agent1_status": r1.status.value, "agent1_error": r1.error,
            "evidence_count": len(ev), "dataset_count": len(d1.get("chart_datasets", [])),
            "quality_passed": d1.get("acquisition_quality", {}).get("passed"),
            "metric_coverage": list(names),
            "calculated_metrics": [m.model_dump(mode="json") for m in metrics],
            "calculation_issues": [i.model_dump(mode="json") for i in issues],
            "checkpoints": CHECKPOINTS[case],
        }
        (out / f"{case}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n产物目录: {out}")


if __name__ == "__main__":
    asyncio.run(main())