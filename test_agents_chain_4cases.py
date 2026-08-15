"""4条高难度话术回归验收——智能体1(真实iFinD)→智能体2(Assistant当大模型)→智能体3(图表)。

用户要求：智能体2不调用真实LLM，由本脚本内置「验证大模型」代替，审查智能体1数据、
生成 chart_candidates，让智能体3生成图表嵌入HTML；若智能体1取数被拦截也算成功。
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
from app.schemas.analysis import (
    AnalysisClaim,
    AnalysisDraft,
    ChartCandidate,
    CollaborationRequest,
    DimensionAnalysis,
    ScenarioAnalysis,
    ValidationCard,
)
from app.schemas.workflow import StageName, StageStatus
from app.workflow.stages import StageContext
from app.agents.data_fetcher.factory import create_data_fetcher_agent
from app.agents.data_interpreter.service import DataInterpreterAgent


# ============================================================
# 充当大模型的验证模型：审查数据 → 生成候选 / 拦截
# ============================================================
# calculation_type → (chart_type, analysis_purpose)
CHART_MAP = {
    "dupont_roe": ("bar", "comparison"),
    "inventory_days": ("bar", "comparison"),
    "receivables_days": ("bar", "comparison"),
    "gross_margin": ("line", "trend"),
    "net_margin": ("line", "trend"),
    "revenue_yoy": ("bar", "comparison"),
    "net_profit_yoy": ("bar", "comparison"),
    "asset_turnover": ("line", "trend"),
    "capacity_utilization": ("line", "trend"),
    "production_sales_ratio": ("line", "trend"),
    "cr3": ("bar", "composition"),
    "cr5": ("bar", "composition"),
}


class VerificationModel:
    """Assistant 充当的大模型：确定性审查，不调用任何外部 LLM。"""

    model_name = "assistant-verification-model"

    async def generate_analysis(self, *, system_prompt: str, runtime_prompt: str) -> AnalysisDraft:
        del system_prompt
        payload = json.loads(runtime_prompt)
        request = payload["analysis_request"]
        evidence = request.get("evidence_items", [])
        metrics = payload.get("calculated_metrics", [])
        calc_issues = payload.get("calculation_issues", [])
        focus = " ".join(request.get("focus_questions", []))

        first = evidence[0] if evidence else {}
        eid = first.get("evidence_id", "")
        claim = AnalysisClaim(
            claim_id="C-001", claim_type="fact",
            text="已获取并核验证据，据实生成分析候选。",
            evidence_ids=[eid] if eid else [],
            confidence="medium", uncertainty="口径限制在看板中披露，未估算缺失数据。",
        )
        draft = AnalysisDraft(
            headline="基于核验证据完成多指标计算与图表候选。",
            overall_confidence="medium",
            financial_quality="differences_pending_verification",
            claims=[claim],
            dimensions=[
                DimensionAnalysis(name=n, summary="维度已核验。", claim_ids=[claim.claim_id] if eid else [])
                for n in ("competition", "growth", "macro_policy", "industry_chain", "risk")
            ],
            validation_cards=[
                ValidationCard(name=n, status="pending_verification", summary="待复核。",
                               evidence_ids=[eid] if eid else [])
                for n in ("scope_comparability", "financial_quality", "valuation_expectation")
            ],
            scenarios=[
                ScenarioAnalysis(name=n, assumptions=["口径保持不变"], triggers=["指标变化"],
                                 transmission_path="变化→判断更新→重估",
                                 evidence_ids=[eid] if eid else [],
                                 disconfirming_conditions=["数据冲突"], monitoring_indicators=["营收"])
                for n in ("base", "upside", "downside")
            ],
            risks=["分析基于当前可追溯证据，未估算缺失数据。"],
        )

        # 针对每类计算结果生成图表候选（引用计算所用证据ID，供Agent3匹配DS-CALC数据集）
        seen = set()
        for m in metrics:
            ct, purpose = CHART_MAP.get(m.get("calculation_type"), ("bar", "comparison"))
            ids = m.get("evidence_ids") or []
            if not ids or tuple(sorted(ids)) in seen:
                continue
            seen.add(tuple(sorted(ids)))
            draft.chart_candidates.append(ChartCandidate(
                title=f"{m.get('metric_name')}（{ct}）",
                chart_type=ct,
                evidence_ids=ids,
                analysis_purpose=purpose,
                insight_goal=f"呈现{m.get('metric_name')}的计算结果",
                priority=80,
                chapter_hint="CH-02" if ct in {"line", "bar", "pie", "area", "combo"} else "CH-04",
                user_requested=True,
            ))

        # 审查数据缺陷 → 拦截请求
        reqs = self._review(focus, evidence, metrics, calc_issues)
        draft.collaboration_requests.extend(reqs)
        return draft

    @staticmethod
    def _review(focus, evidence, metrics, calc_issues):
        reqs: list[CollaborationRequest] = []
        metric_names = {(m.get("metric_name") or "") for m in metrics}
        calc_types = {m.get("calculation_type") for m in metrics}

        # 用例2/3：市占率CRn
        if "CR" in focus or "市占" in focus or "CR5" in focus:
            if "cr3" not in calc_types and "cr5" not in calc_types:
                reqs.append(CollaborationRequest(
                    request_id="CONCENTRATION-NO-SAMPLE",
                    question="请补充各厂商市占率明细（至少5家）。",
                    reason="计算模块未产出CR3/CR5，市占率样本不足，拒绝捏造集中度。",
                    affected_dimensions=["competition"],
                ))
        # 用例1：杜邦/周转
        if "杜邦" in focus or "周转" in focus:
            missing = [
                name for name in ("杜邦复算ROE", "存货周转天数", "应收账款周转天数")
                if name not in metric_names
            ]
            if missing:
                reqs.append(CollaborationRequest(
                    request_id="DUPONT-INSUFFICIENT",
                    question="请补充期初/期末总资产、股东权益、存货、应收账款等科目。",
                    reason=f"未产出：{'、'.join(missing)}；缺少期初数据或科目口径不全，已降级。",
                    affected_dimensions=["growth", "risk"],
                ))
        # 用例4：产能利用率/产销率
        if "产能" in focus or "产销" in focus:
            missing = [
                name for name in ("产能利用率", "产销率") if name not in metric_names
            ]
            if missing:
                reqs.append(CollaborationRequest(
                    request_id="CAPACITY-INSUFFICIENT",
                    question="请补充产量、有效产能、销量数据。",
                    reason=f"未产出：{'、'.join(missing)}；缺少产量/产能/销量科目，拒绝估算。",
                    affected_dimensions=["industry_chain"],
                ))
        # 周期混用检测（用例4）
        if calc_issues and "混" in "".join(i.get("reason", "") for i in calc_issues):
            reqs.append(CollaborationRequest(
                request_id="PERIOD-MIXED",
                question="请统一年度/季度报告期口径。",
                reason="检测到季度与年度数据混用，已拦截异常计算并记录日志。",
                affected_dimensions=["growth"],
            ))
        return reqs


# ============================================================
# 4条话术入参
# ============================================================
CASES = [
    {
        "id": "CASE1", "topic": "动力电池",
        "focus": ["整理宁德时代、比亚迪2023-2025财务报表，完成三步杜邦ROE拆解，计算存货周转天数、应收账款周转天数、毛利率、营收同比，基于现有指标生成财务对标图表"],
        "metrics": ["营业收入", "营业成本", "净利润", "总资产", "股东权益", "存货", "应收账款"],
        "scope": ["宁德时代", "比亚迪"], "brief_focus": ["宁德时代", "比亚迪"],
        "options": {},
    },
    {
        "id": "CASE2", "topic": "动力电池",
        "focus": ["获取国内动力电池厂商历年市占明细，自动计算CR3、CR5集中度，合并尾部小企业份额，使用该份额数据集生成可视化图表"],
        "metrics": ["市占率", "市场份额"], "scope": ["动力电池"], "brief_focus": [],
        "options": {},
    },
    {
        "id": "CASE3", "topic": "储能逆变器",
        "focus": ["采集储能逆变器企业市场份额明细，计算行业集中度CR5，同一份份额数据同时输出饼图与柱状对比图"],
        "metrics": ["市占率", "市场份额"], "scope": ["储能逆变器"], "brief_focus": [],
        "options": {"allow_multiple_charts_per_dataset": True},
    },
    {
        "id": "CASE4", "topic": "光伏产业链",
        "focus": ["汇总光伏产业链各环节2022-2025产量、产能数据，计算产能利用率与产销率，梳理上下游结构绘制产业链图谱，利用环节盈利数据生成对比图表"],
        "metrics": ["产量", "产能", "销量", "有效产能", "产能利用率", "产销率"],
        "scope": ["光伏"], "brief_focus": [],
        "options": {},
    },
]


def build_html(case, specs, suppressed, quality, reqs, agent1_info, agent2_info):
    cards = []
    for spec in specs:
        option_json = json.dumps(spec["option"], ensure_ascii=False)
        var_name = "c_" + spec["chart_id"].replace("-", "_")
        div_id = spec["chart_id"].replace("-", "_")
        cards.append(f"""
        <div class="card">
          <h3>{spec['title']}</h3>
          <div class="tag">{spec['chart_type']} / {spec['variant']}</div>
          <div class="ids">{spec['chart_id']}</div>
          <div id="{div_id}" class="chart"></div>
          <script>var {var_name}=echarts.init(document.getElementById('{div_id}'));{var_name}.setOption({option_json});</script>
        </div>""")
    supp = "".join(
        f'<div class="supp"><b>{s["title"]}</b> [{s["reason_code"]}] {s["reason"]}</div>'
        for s in suppressed) or "<div class='supp'>无抑制图表</div>"
    reqs_html = "".join(
        f'<div class="req"><b>{r.get("request_id")}</b> {r.get("question")}<div class="req-reason">{r.get("reason")}</div></div>'
        for r in reqs) or "<div class='req ok'>无拦截请求</div>"
    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<title>{case['id']} 智能体1-2-3链路</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
body{{font-family:-apple-system,"PingFang SC",sans-serif;margin:24px;background:#f0f2f5;color:#1f2937}}
h1{{color:#1e3a5f}} h2{{color:#2563eb;margin-top:28px}}
.summary{{background:#fff;padding:16px;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:16px}}
.summary p{{margin:4px 0}}
.req,.supp{{background:#fff7ed;color:#9a3412;padding:8px 12px;border-radius:8px;margin:6px 0;font-size:13px}}
.req.ok{{background:#ecfdf5;color:#065f46}}
.req-reason{{color:#b45309;font-size:12px;margin-top:4px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(520px,1fr));gap:20px;margin-top:16px}}
.card{{background:#fff;border-radius:10px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.card h3{{margin:0 0 6px;font-size:15px}}
.tag{{display:inline-block;background:#e0e7ff;color:#3730a3;padding:2px 10px;border-radius:12px;font-size:12px}}
.ids{{color:#9ca3af;font-size:11px;margin-top:4px}}
.chart{{width:100%;height:360px}}
</style></head><body>
<h1>{case['id']}：智能体1→2→3 链路测试</h1>
<div class="summary">
  <p><b>智能体1:</b> {agent1_info} | <b>智能体2:</b> {agent2_info}</p>
  <p><b>质量门:</b> {quality.get('passed')} | <b>生成图表:</b> {len(specs)} | <b>抑制:</b> {len(suppressed)}</p>
</div>
<h2>拦截请求（collaboration_requests）</h2>{reqs_html}
<h2>抑制/降级</h2>{supp}
<h2>生成的图表（{len(specs)}张）</h2><div class="grid">{''.join(cards)}</div>
</body></html>"""


async def main():
    out = Path(__file__).parent / "test_output" / "agents_chain_4cases"
    out.mkdir(parents=True, exist_ok=True)
    agent1 = create_data_fetcher_agent(settings)
    summary = []

    for case in CASES:
        print("\n" + "=" * 70)
        print(f"话术 {case['id']}: {case['focus'][0][:40]}...")
        print("=" * 70)
        input_data = {
            "industry_topic": case["topic"],
            "market_scope": ["中国"], "security_types": ["A股"],
            "reporting_currency": "CNY", "research_as_of": "2026-08-12",
            "focus_questions": case["focus"], "evidence_items": [],
            "analysis_depth": "standard", "risk_preference": "balanced",
            "research_brief": {"geography": "中国", "included_topics": [], "excluded_topics": [],
                               "focus_companies": case["brief_focus"], "report_depth": "standard"},
            "data_fetch_options": {"metrics": case["metrics"], "industry_scope": case["scope"]},
            "chart_generate_options": {
                "requested_chart_count": 8, "user_priority": True,
                **case["options"],
            },
        }

        # 智能体1
        ctx1 = StageContext(owner_id="test", project_id="agents-4cases",
                            run_id=f"4c-{case['id']}", revision=1, input_data=input_data)
        r1 = await agent1.run(ctx1)
        d1 = r1.data
        ev_count = len(d1.get("evidence_items", []))
        print(f"[智能体1] 状态={r1.status.value} 证据={ev_count} 数据集={len(d1.get('chart_datasets', []))}")

        # 智能体2（验证模型）
        agent2 = DataInterpreterAgent(model=VerificationModel())
        ctx2 = StageContext(owner_id="test", project_id="agents-4cases",
                            run_id=f"4c-{case['id']}", revision=1, input_data=input_data,
                            previous_results={StageName.DATA_FETCH: r1})
        r2 = await agent2.run(ctx2)
        d2 = r2.data
        cands = d2.get("chart_candidates", [])
        reqs = d2.get("collaboration_requests", [])
        print(f"[智能体2] 状态={r2.status.value} 候选={len(cands)} 拦截={len(reqs)}")

        # 智能体3
        agent3 = await _make_agent3()
        ctx3 = StageContext(owner_id="test", project_id="agents-4cases",
                            run_id=f"4c-{case['id']}", revision=1, input_data=input_data,
                            previous_results={StageName.DATA_FETCH: r1, StageName.DATA_INTERPRET: r2})
        r3 = await agent3.run(ctx3)
        d3 = r3.data
        specs = d3.get("chart_specs", [])
        suppressed = d3.get("suppressed_candidates", [])
        quality = d3.get("quality", {})
        print(f"[智能体3] 状态={r3.status.value} 图表={len(specs)} 抑制={len(suppressed)}")
        for s in specs:
            print(f"   {s.get('chart_type')}: {s.get('title')}")

        # HTML
        html = build_html(
            case, specs, suppressed, quality, reqs,
            f"{r1.status.value}(证据{ev_count})", f"{r2.status.value}(候选{len(cands)})",
        )
        (out / f"{case['id']}.html").write_text(html, encoding="utf-8")
        (out / f"{case['id']}.json").write_text(
            json.dumps({"agent1": d1, "agent2": d2, "agent3": d3}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        summary.append({
            "case": case["id"], "agent1": r1.status.value, "agent2": r2.status.value,
            "agent3": r3.status.value, "charts": len(specs), "suppressed": len(suppressed),
            "candidates": len(cands), "collaboration_requests": [
                {"request_id": r.get("request_id"), "reason": r.get("reason")} for r in reqs
            ],
        })

    print("\n\n===== 汇总 =====")
    for s in summary:
        print(f"  {s['case']}: A1={s['agent1']} A2={s['agent2']} A3={s['agent3']} 图表={s['charts']}")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n产物目录: {out}")


async def _make_agent3():
    from app.agents.chart_generator.service import ChartGeneratorAgent
    return ChartGeneratorAgent()


if __name__ == "__main__":
    asyncio.run(main())