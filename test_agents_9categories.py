"""9类金融投研场景——智能体1(真实iFinD)→智能体2(Assistant当大模型)→智能体3(图表)。

覆盖：单家公司深度调研、行业景气度、竞争格局CR、价格周期、估值宏观、
政策舆情、多维度复合、简短口语化、风险导向。
Agent 1 返回数据缺失则跳过该条选另一条。
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
# 充当大模型的验证模型：适配9类场景的确定性审查
# ============================================================
CHART_MAP = {
    "cr3": ("bar", "composition"),
    "cr5": ("bar", "composition"),
    "gross_margin": ("line", "trend"),
    "net_margin": ("line", "trend"),
    "revenue_yoy": ("bar", "comparison"),
    "net_profit_yoy": ("bar", "comparison"),
    "dupont_roe": ("bar", "comparison"),
    "asset_turnover": ("line", "trend"),
    "inventory_turnover": ("line", "trend"),
    "inventory_days": ("bar", "comparison"),
    "receivables_turnover": ("line", "trend"),
    "receivables_days": ("bar", "comparison"),
    "capacity_utilization": ("line", "trend"),
    "production_sales_ratio": ("line", "trend"),
}


class VerificationModel:
    """Assistant 充当的大模型：确定性审查，不调用任何外部 LLM。"""

    model_name = "assistant-verification-model"

    async def generate_analysis(
        self, *, system_prompt: str, runtime_prompt: str
    ) -> AnalysisDraft:
        del system_prompt
        payload = json.loads(runtime_prompt)
        request = payload["analysis_request"]
        evidence = request.get("evidence_items", [])
        metrics = payload.get("calculated_metrics", [])
        calc_issues = payload.get("calculation_issues", [])
        focus = " ".join(request.get("focus_questions", []))
        topic = request.get("industry_topic", "")

        first = evidence[0] if evidence else {}
        eid = first.get("evidence_id", "")

        claim = AnalysisClaim(
            claim_id="C-001",
            claim_type="fact",
            text="已获取并核验证据，据实生成分析候选。",
            evidence_ids=[eid] if eid else [],
            confidence="medium",
            uncertainty="口径限制在可追溯证据范围内，未估算缺失数据。",
        )
        draft = AnalysisDraft(
            headline=f"基于核验证据完成「{topic}」多维度分析。",
            overall_confidence="medium",
            financial_quality="differences_pending_verification",
            claims=[claim],
            dimensions=[
                DimensionAnalysis(
                    name=n,
                    summary=f"{n}维度已核验。",
                    claim_ids=[claim.claim_id] if eid else [],
                )
                for n in (
                    "competition",
                    "growth",
                    "macro_policy",
                    "industry_chain",
                    "risk",
                )
            ],
            validation_cards=[
                ValidationCard(
                    name=n,
                    status="pending_verification",
                    summary="待复核。",
                    evidence_ids=[eid] if eid else [],
                )
                for n in (
                    "scope_comparability",
                    "financial_quality",
                    "valuation_expectation",
                )
            ],
            scenarios=[
                ScenarioAnalysis(
                    name=n,
                    assumptions=["口径保持不变"],
                    triggers=["指标变化"],
                    transmission_path="变化→判断更新→重估",
                    evidence_ids=[eid] if eid else [],
                    disconfirming_conditions=["数据冲突"],
                    monitoring_indicators=["营收"],
                )
                for n in ("base", "upside", "downside")
            ],
            risks=["分析基于当前可追溯证据，未估算缺失数据。"],
        )

        # 针对每类计算结果生成图表候选
        seen = set()
        for m in metrics:
            ct, purpose = CHART_MAP.get(
                m.get("calculation_type"), ("bar", "comparison")
            )
            ids = m.get("evidence_ids") or []
            if not ids or tuple(sorted(ids)) in seen:
                continue
            seen.add(tuple(sorted(ids)))
            draft.chart_candidates.append(
                ChartCandidate(
                    title=f"{m.get('metric_name')}（{ct}）",
                    chart_type=ct,
                    evidence_ids=ids,
                    analysis_purpose=purpose,
                    insight_goal=f"呈现{m.get('metric_name')}的计算结果",
                    priority=80,
                    chapter_hint=(
                        "CH-02"
                        if ct in {"line", "bar", "pie", "area", "combo"}
                        else "CH-04"
                    ),
                    user_requested=True,
                )
            )

        # 为证据项生成兜底图表候选（没有计算指标时）
        if not metrics and evidence:
            evidence_by_metric: dict[str, list[dict]] = {}
            for ev in evidence:
                mn = ev.get("metric_name", "")
                if mn:
                    evidence_by_metric.setdefault(mn, []).append(ev)
            for metric_name, evs in list(evidence_by_metric.items())[:8]:
                ids = [ev.get("evidence_id") for ev in evs if ev.get("evidence_id")]
                if not ids or tuple(sorted(ids)) in seen:
                    continue
                seen.add(tuple(sorted(ids)))
                has_time = any(ev.get("period_end") for ev in evs)
                ct = "line" if has_time and len(evs) >= 3 else "bar"
                purpose = "trend" if ct == "line" else "comparison"
                draft.chart_candidates.append(
                    ChartCandidate(
                        title=f"{metric_name}{'趋势' if ct == 'line' else '对比'}",
                        chart_type=ct,
                        evidence_ids=ids,
                        analysis_purpose=purpose,
                        insight_goal=f"呈现{metric_name}的可视化",
                        priority=70,
                        chapter_hint="CH-02",
                        user_requested=True,
                    )
                )

        # 审查数据缺陷 → 拦截请求
        reqs = self._review(focus, topic, evidence, metrics, calc_issues)
        draft.collaboration_requests.extend(reqs)
        return draft

    @staticmethod
    def _review(focus, topic, evidence, metrics, calc_issues):
        reqs: list[CollaborationRequest] = []
        metric_names = {(m.get("metric_name") or "") for m in metrics}
        calc_types = {m.get("calculation_type") for m in metrics}
        evidence_metric_names = {ev.get("metric_name", "") for ev in evidence}

        # CR/市占率
        if "CR" in focus or "市占" in focus or "CR5" in focus:
            if "cr3" not in calc_types and "cr5" not in calc_types:
                reqs.append(
                    CollaborationRequest(
                        request_id="CONCENTRATION-NO-SAMPLE",
                        question="请补充各厂商市占率明细（至少5家）。",
                        reason="计算模块未产出CR3/CR5，市占率样本不足，拒绝捏造集中度。",
                        affected_dimensions=["competition"],
                    )
                )
        # 杜邦/周转
        if "杜邦" in focus or "周转" in focus:
            missing = [
                name
                for name in ("杜邦复算ROE", "存货周转天数", "应收账款周转天数")
                if name not in metric_names
            ]
            if missing:
                reqs.append(
                    CollaborationRequest(
                        request_id="DUPONT-INSUFFICIENT",
                        question="请补充期初/期末总资产、股东权益、存货、应收账款等科目。",
                        reason=f"未产出：{'、'.join(missing)}；缺少期初数据或科目口径不全，已降级。",
                        affected_dimensions=["growth", "risk"],
                    )
                )
        # 产能利用率/产销率
        if "产能" in focus or "产销" in focus:
            missing = [
                name for name in ("产能利用率", "产销率") if name not in metric_names
            ]
            if missing:
                reqs.append(
                    CollaborationRequest(
                        request_id="CAPACITY-INSUFFICIENT",
                        question="请补充产量、有效产能、销量数据。",
                        reason=f"未产出：{'、'.join(missing)}；缺少产量/产能/销量科目，拒绝估算。",
                        affected_dimensions=["industry_chain"],
                    )
                )
        # 周期混用检测
        if calc_issues and "混" in "".join(i.get("reason", "") for i in calc_issues):
            reqs.append(
                CollaborationRequest(
                    request_id="PERIOD-MIXED",
                    question="请统一年度/季度报告期口径。",
                    reason="检测到季度与年度数据混用，已拦截异常计算并记录日志。",
                    affected_dimensions=["growth"],
                )
            )
        # 估值/PE/PB 特殊检测
        if "PE" in focus or "PB" in focus or "估值" in focus:
            pe_pb_found = any(
                "PE" in m or "PB" in m or "市盈" in m or "市净" in m
                for m in evidence_metric_names
            )
            if not pe_pb_found and "PE" not in "".join(metric_names):
                reqs.append(
                    CollaborationRequest(
                        request_id="VALUATION-DATA-INSUFFICIENT",
                        question="请补充板块PE/PB估值数据及历史分位。",
                        reason="未获取到PE/PB相关估值指标，无法生成估值分析。",
                        affected_dimensions=["macro_policy"],
                    )
                )
        # 政策/舆情类（定性为主，无数据不是问题）
        if (
            "政策" in focus
            or "关税" in focus
            or "出口管制" in focus
            or "舆情" in focus
            or "新闻" in focus
            or "资讯" in focus
            or "观点" in focus
        ):
            if not evidence and not metrics:
                reqs.append(
                    CollaborationRequest(
                        request_id="POLICY-NEWS-INSUFFICIENT",
                        question="请补充相关政策文件、新闻公告或行业点评。",
                        reason="政策/舆情类问题需要定性证据，当前无可追溯来源。",
                        affected_dimensions=["macro_policy", "risk"],
                    )
                )
        # 风险导向类（E级证据多）
        if "风险" in focus or "担忧" in focus:
            e_grade = [ev for ev in evidence if ev.get("grade") == "E"]
            if len(e_grade) > 5:
                reqs.append(
                    CollaborationRequest(
                        request_id="RISK-E-GRADE-WARNING",
                        question=f"当前{len(e_grade)}条E级证据需人工核验。",
                        reason="E级(传闻/市场消息)较多，可能影响风险判断可靠性。",
                        affected_dimensions=["risk"],
                    )
                )
        return reqs


# ============================================================
# 9类测试话术（每个类别选1句，含备选）
# ============================================================
CATEGORIES = [
    {
        "name": "单家公司深度调研",
        "cases": [
            {
                "id": "C1",
                "topic": "动力电池",
                "focus": [
                    "整理宁德时代近四年营收、归母净利润、毛利率、各项费用率，同时梳理主营业务结构"
                ],
                "metrics": [
                    "营业收入",
                    "归母净利润",
                    "毛利率",
                    "销售费用",
                    "管理费用",
                    "研发费用",
                    "主营业务收入",
                ],
                "scope": ["宁德时代"],
                "brief_focus": ["宁德时代"],
            },
            {
                "id": "C1-BAK",
                "topic": "新能源汽车",
                "focus": [
                    "分析比亚迪新能源汽车业务产销情况、海外市场拓展进度以及成本变化趋势"
                ],
                "metrics": ["汽车销量", "海外收入", "营业成本", "新能源汽车销量"],
                "scope": ["比亚迪"],
                "brief_focus": ["比亚迪"],
            },
        ],
    },
    {
        "name": "行业景气度",
        "cases": [
            {
                "id": "C2",
                "topic": "动力电池",
                "focus": [
                    "动力电池行业近5年市场规模、增速、竞争格局，预判未来两年行业景气变化"
                ],
                "metrics": ["市场规模", "装机量", "行业增速", "市场份额"],
                "scope": ["动力电池"],
                "brief_focus": [],
            },
            {
                "id": "C2-BAK",
                "topic": "光伏",
                "focus": [
                    "光伏产业链硅料、硅片、电池、组件各环节盈利变化，梳理行业产能扩张情况"
                ],
                "metrics": ["毛利率", "产能", "产量", "价格"],
                "scope": ["光伏"],
                "brief_focus": [],
            },
        ],
    },
    {
        "name": "竞争格局/CR",
        "cases": [
            {
                "id": "C3",
                "topic": "锂电池",
                "focus": ["锂电池行业CR3、CR5市场占有率变化，对比国内外龙头企业差距"],
                "metrics": ["市占率", "市场份额", "装机量"],
                "scope": ["锂电池"],
                "brief_focus": [],
            },
            {
                "id": "C3-BAK",
                "topic": "光伏逆变器",
                "focus": [
                    "光伏逆变器国内外厂商市占率，海外贸易政策对出口业务带来的影响"
                ],
                "metrics": ["市占率", "市场份额", "出口量"],
                "scope": ["光伏逆变器"],
                "brief_focus": [],
            },
        ],
    },
    {
        "name": "价格/周期/原材料",
        "cases": [
            {
                "id": "C4",
                "topic": "有色金属",
                "focus": ["锂、钴、镍近一年价格走势，分析供需基本面和价格后续驱动因素"],
                "metrics": ["碳酸锂价格", "钴价格", "镍价格", "锂价格"],
                "scope": ["锂", "钴", "镍"],
                "brief_focus": [],
            },
            {
                "id": "C4-BAK",
                "topic": "煤炭",
                "focus": ["动力煤近三年价格中枢，供需格局以及相关调控政策影响"],
                "metrics": ["动力煤价格", "动力煤产量", "动力煤消费量"],
                "scope": ["动力煤"],
                "brief_focus": [],
            },
        ],
    },
    {
        "name": "估值/市场/宏观",
        "cases": [
            {
                "id": "C5",
                "topic": "新能源汽车",
                "focus": ["当前新能源车板块整体PE、PB估值以及近三年历史估值分位"],
                "metrics": ["PE", "PB", "市盈率", "市净率", "估值分位"],
                "scope": ["新能源车"],
                "brief_focus": [],
            },
            {
                "id": "C5-BAK",
                "topic": "沪深300",
                "focus": ["沪深300、创业板当前估值水平，对比历史区间判断估值位置"],
                "metrics": ["PE", "PB", "市盈率", "市净率"],
                "scope": ["沪深300", "创业板"],
                "brief_focus": [],
            },
        ],
    },
    {
        "name": "政策/舆情/产业事件",
        "cases": [
            {
                "id": "C6",
                "topic": "动力电池回收",
                "focus": [
                    "近期动力电池回收相关产业政策梳理，评估政策落地带来的行业影响"
                ],
                "metrics": [],
                "scope": ["动力电池回收"],
                "brief_focus": [],
            },
            {
                "id": "C6-BAK",
                "topic": "新能源汽车",
                "focus": ["收集关于海外新能源车关税调整的相关新闻与行业点评"],
                "metrics": [],
                "scope": ["新能源车出口"],
                "brief_focus": [],
            },
        ],
    },
    {
        "name": "多维度复合",
        "cases": [
            {
                "id": "C7",
                "topic": "储能",
                "focus": [
                    "结合行业规模、竞争格局、原材料价格、政策四个维度，综合分析储能行业投资逻辑"
                ],
                "metrics": ["市场规模", "市场份额", "原材料价格", "装机量"],
                "scope": ["储能"],
                "brief_focus": [],
            },
            {
                "id": "C7-BAK",
                "topic": "动力电池",
                "focus": [
                    "对比宁德时代与比亚迪电池业务成本结构、客户结构、技术路线差异"
                ],
                "metrics": ["营业成本", "营业收入", "毛利率", "客户结构"],
                "scope": ["宁德时代", "比亚迪"],
                "brief_focus": ["宁德时代", "比亚迪"],
            },
        ],
    },
    {
        "name": "简短口语化",
        "cases": [
            {
                "id": "C8",
                "topic": "动力电池",
                "focus": ["动力电池行业现在景气度怎么样"],
                "metrics": ["装机量", "行业增速", "产能利用率"],
                "scope": ["动力电池"],
                "brief_focus": [],
            },
            {
                "id": "C8-BAK",
                "topic": "碳酸锂",
                "focus": ["最近锂价持续下跌的核心原因是什么"],
                "metrics": ["碳酸锂价格", "锂供给", "锂需求"],
                "scope": ["锂"],
                "brief_focus": [],
            },
        ],
    },
    {
        "name": "风险导向",
        "cases": [
            {
                "id": "C9",
                "topic": "动力电池",
                "focus": [
                    "梳理动力电池行业潜在风险，包括产能过剩、价格战、原材料波动风险"
                ],
                "metrics": ["产能", "产能利用率", "价格", "原材料价格"],
                "scope": ["动力电池"],
                "brief_focus": [],
            },
            {
                "id": "C9-BAK",
                "topic": "光伏",
                "focus": ["汇总市场对于光伏企业盈利下行的各类担忧观点"],
                "metrics": ["毛利率", "净利润", "产能"],
                "scope": ["光伏"],
                "brief_focus": [],
            },
        ],
    },
]


def build_input(case: dict) -> dict:
    return {
        "industry_topic": case["topic"],
        "market_scope": ["中国"],
        "security_types": ["A股"],
        "reporting_currency": "CNY",
        "research_as_of": "2026-08-12",
        "focus_questions": case["focus"],
        "evidence_items": [],
        "analysis_depth": "standard",
        "risk_preference": "balanced",
        "research_brief": {
            "geography": "中国",
            "included_topics": [],
            "excluded_topics": [],
            "focus_companies": case["brief_focus"],
            "report_depth": "standard",
        },
        "data_fetch_options": {
            "metrics": case["metrics"],
            "industry_scope": case["scope"],
        },
        "chart_generate_options": {
            "requested_chart_count": 8,
            "user_priority": True,
        },
    }


def build_html(
    case, category_name, specs, suppressed, quality, reqs, agent1_info, agent2_info
):
    cards = []
    for spec in specs:
        option_json = json.dumps(spec["option"], ensure_ascii=False)
        var_name = "c_" + spec["chart_id"].replace("-", "_")
        div_id = spec["chart_id"].replace("-", "_")
        cards.append(f"""
        <div class="card">
          <h3>{spec['title']}</h3>
          <div class="tag">{spec['chart_type']} / {spec.get('variant', '')}</div>
          <div class="ids">{spec['chart_id']}</div>
          <div id="{div_id}" class="chart"></div>
          <script>var {var_name}=echarts.init(document.getElementById('{div_id}'));{var_name}.setOption({option_json});</script>
        </div>""")
    supp = (
        "".join(
            f'<div class="supp"><b>{s["title"]}</b> [{s["reason_code"]}] {s["reason"]}</div>'
            for s in suppressed
        )
        or "<div class='supp ok'>无抑制图表</div>"
    )
    reqs_html = (
        "".join(
            f'<div class="req"><b>{r.get("request_id")}</b> {r.get("question")}<div class="req-reason">{r.get("reason")}</div></div>'
            for r in reqs
        )
        or "<div class='req ok'>无拦截请求</div>"
    )
    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="UTF-8">
<title>{case['id']} 智能体1-2-3链路</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
body{{font-family:-apple-system,"PingFang SC",sans-serif;margin:24px;background:#f0f2f5;color:#1f2937}}
h1{{color:#1e3a5f}} h2{{color:#2563eb;margin-top:28px}}
.summary{{background:#fff;padding:16px;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:16px}}
.summary p{{margin:4px 0}}
.req,.supp{{background:#fff7ed;color:#9a3412;padding:8px 12px;border-radius:8px;margin:6px 0;font-size:13px}}
.req.ok,.supp.ok{{background:#ecfdf5;color:#065f46}}
.req-reason{{color:#b45309;font-size:12px;margin-top:4px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(520px,1fr));gap:20px;margin-top:16px}}
.card{{background:#fff;border-radius:10px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
.card h3{{margin:0 0 6px;font-size:15px}}
.tag{{display:inline-block;background:#e0e7ff;color:#3730a3;padding:2px 10px;border-radius:12px;font-size:12px}}
.ids{{color:#9ca3af;font-size:11px;margin-top:4px}}
.chart{{width:100%;height:360px}}
</style></head><body>
<h1>{case['id']}：{category_name} — 智能体1→2→3 链路测试</h1>
<div class="summary">
  <p><b>话术:</b> {case['focus'][0][:80]}...</p>
  <p><b>话题:</b> {case['topic']} | <b>指标:</b> {', '.join(case['metrics'][:6]) or '(定性)'}</p>
  <p><b>智能体1:</b> {agent1_info} | <b>智能体2:</b> {agent2_info}</p>
  <p><b>质量门:</b> {quality.get('passed')} | <b>生成图表:</b> {len(specs)} | <b>抑制:</b> {len(suppressed)}</p>
</div>
<h2>拦截请求（collaboration_requests）</h2>{reqs_html}
<h2>抑制/降级</h2>{supp}
<h2>生成的图表（{len(specs)}张）</h2><div class="grid">{''.join(cards)}</div>
</body></html>"""


async def main():
    out = Path(__file__).parent / "test_output" / "agents_9categories"
    out.mkdir(parents=True, exist_ok=True)
    agent1 = create_data_fetcher_agent(settings)
    summary = []
    all_bugs = []

    for category in CATEGORIES:
        cat_name = category["name"]
        case = None
        result = None

        for candidate in category["cases"]:
            cid = candidate["id"]
            print(f"\n{'=' * 70}")
            print(f"类别: {cat_name} | 话术 {cid}: {candidate['focus'][0][:50]}...")
            print("=" * 70)

            input_data = build_input(candidate)

            # 智能体1
            ctx1 = StageContext(
                owner_id="test",
                project_id="agents-9cat",
                run_id=f"9c-{cid}",
                revision=1,
                input_data=input_data,
            )
            try:
                r1 = await agent1.run(ctx1)
            except Exception as e:
                print(f"[智能体1] 异常: {e}")
                all_bugs.append(
                    {
                        "category": cat_name,
                        "case_id": cid,
                        "agent": "Agent 1",
                        "error": str(e),
                        "type": type(e).__name__,
                    }
                )
                continue

            d1 = r1.data
            ev_count = len(d1.get("evidence_items", []))
            print(
                f"[智能体1] 状态={r1.status.value} 证据={ev_count} 数据集={len(d1.get('chart_datasets', []))}"
            )

            if r1.status == StageStatus.COMPLETED and ev_count > 0:
                case = candidate
                result = r1
                break
            elif r1.status == StageStatus.WAITING_REVIEW:
                data_quality = d1.get("acquisition_quality", {})
                core_available = data_quality.get("core_data_available", False)
                print(
                    "  [跳过] Agent 1尚未完成审核，生产链路不得继续；"
                    f"核心数据可用={core_available}，尝试备选..."
                )
                all_bugs.append(
                    {
                        "category": cat_name,
                        "case_id": cid,
                        "agent": "Agent 1",
                        "error": r1.error or "data_quality_gate_failed",
                        "type": "Agent1DataUnavailable",
                        "detail": f"证据={ev_count}，核心数据可用={core_available}",
                    }
                )
            else:
                print(f"  [跳过] 状态={r1.status.value}，尝试备选...")
                all_bugs.append(
                    {
                        "category": cat_name,
                        "case_id": cid,
                        "agent": "Agent 1",
                        "error": r1.error or r1.status.value,
                        "type": "Agent1Failed",
                    }
                )

        if case is None or result is None:
            print(f"  [全部跳过] 类别「{cat_name}」所有备选均无法获取数据。")
            all_bugs.append(
                {
                    "category": cat_name,
                    "case_id": "ALL",
                    "agent": "Agent 1",
                    "error": "all_candidates_failed",
                    "type": "AllCandidatesFailed",
                    "detail": "该类别所有备选话术均无法获取数据",
                }
            )
            summary.append(
                {
                    "category": cat_name,
                    "case_id": "SKIPPED",
                    "agent1": "FAILED",
                    "agent2": "N/A",
                    "agent3": "N/A",
                    "charts": 0,
                    "suppressed": 0,
                    "candidates": 0,
                    "collaboration_requests": [],
                }
            )
            continue

        cid = case["id"]
        d1 = result.data
        ev_count = len(d1.get("evidence_items", []))

        # 智能体2（验证模型）
        agent2 = DataInterpreterAgent(model=VerificationModel())
        ctx2 = StageContext(
            owner_id="test",
            project_id="agents-9cat",
            run_id=f"9c-{cid}",
            revision=1,
            input_data=input_data,
            previous_results={StageName.DATA_FETCH: result},
        )
        try:
            r2 = await agent2.run(ctx2)
        except Exception as e:
            print(f"[智能体2] 异常: {e}")
            all_bugs.append(
                {
                    "category": cat_name,
                    "case_id": cid,
                    "agent": "Agent 2",
                    "error": str(e),
                    "type": type(e).__name__,
                }
            )
            summary.append(
                {
                    "category": cat_name,
                    "case_id": cid,
                    "agent1": r1.status.value,
                    "agent2": f"ERROR: {type(e).__name__}",
                    "agent3": "N/A",
                    "charts": 0,
                    "suppressed": 0,
                    "candidates": 0,
                    "collaboration_requests": [],
                }
            )
            continue

        d2 = r2.data
        cands = d2.get("chart_candidates", [])
        reqs = d2.get("collaboration_requests", [])
        print(f"[智能体2] 状态={r2.status.value} 候选={len(cands)} 拦截={len(reqs)}")

        if r2.status not in {StageStatus.COMPLETED, StageStatus.APPROVED}:
            print("[智能体3] 跳过：Agent 2尚未完成分析或审核。")
            summary.append(
                {
                    "category": cat_name,
                    "case_id": cid,
                    "agent1": result.status.value,
                    "agent2": r2.status.value,
                    "agent3": "N/A",
                    "charts": 0,
                    "suppressed": 0,
                    "candidates": len(cands),
                    "collaboration_requests": [
                        {"request_id": r.get("request_id"), "reason": r.get("reason")}
                        for r in reqs
                    ],
                }
            )
            continue

        # 智能体3
        agent3 = await _make_agent3()
        ctx3 = StageContext(
            owner_id="test",
            project_id="agents-9cat",
            run_id=f"9c-{cid}",
            revision=1,
            input_data=input_data,
            previous_results={
                StageName.DATA_FETCH: result,
                StageName.DATA_INTERPRET: r2,
            },
        )
        try:
            r3 = await agent3.run(ctx3)
        except Exception as e:
            print(f"[智能体3] 异常: {e}")
            all_bugs.append(
                {
                    "category": cat_name,
                    "case_id": cid,
                    "agent": "Agent 3",
                    "error": str(e),
                    "type": type(e).__name__,
                }
            )
            summary.append(
                {
                    "category": cat_name,
                    "case_id": cid,
                    "agent1": r1.status.value,
                    "agent2": r2.status.value,
                    "agent3": f"ERROR: {type(e).__name__}",
                    "charts": 0,
                    "suppressed": 0,
                    "candidates": len(cands),
                    "collaboration_requests": [],
                }
            )
            continue

        d3 = r3.data
        specs = d3.get("chart_specs", [])
        suppressed = d3.get("suppressed_candidates", [])
        quality = d3.get("quality", {})
        print(
            f"[智能体3] 状态={r3.status.value} 图表={len(specs)} 抑制={len(suppressed)}"
        )
        for s in specs:
            print(f"   {s.get('chart_type')}: {s.get('title')}")

        # HTML
        html = build_html(
            case,
            cat_name,
            specs,
            suppressed,
            quality,
            reqs,
            f"{r1.status.value}(证据{ev_count})",
            f"{r2.status.value}(候选{len(cands)})",
        )
        (out / f"{cid}.html").write_text(html, encoding="utf-8")
        (out / f"{cid}.json").write_text(
            json.dumps(
                {"agent1": d1, "agent2": d2, "agent3": d3}, ensure_ascii=False, indent=2
            ),
            encoding="utf-8",
        )

        summary.append(
            {
                "category": cat_name,
                "case_id": cid,
                "agent1": r1.status.value,
                "agent2": r2.status.value,
                "agent3": r3.status.value,
                "charts": len(specs),
                "suppressed": len(suppressed),
                "candidates": len(cands),
                "collaboration_requests": [
                    {"request_id": r.get("request_id"), "reason": r.get("reason")}
                    for r in reqs
                ],
            }
        )

    print("\n\n" + "=" * 70)
    print("===== 9类测试汇总 =====")
    print("=" * 70)
    for s in summary:
        print(
            f"  {s['category']}: {s['case_id']} | A1={s['agent1']} A2={s['agent2']} A3={s['agent3']} 图表={s['charts']}"
        )
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 生成汇总报告
    summary_md = _build_summary_report(summary, all_bugs)
    (out / "TEST_REPORT.md").write_text(summary_md, encoding="utf-8")

    if all_bugs:
        bug_md = _build_bug_analysis(all_bugs)
        (out / "BUG_ANALYSIS.md").write_text(bug_md, encoding="utf-8")
        print(f"\nBUG分析已保存: {out / 'BUG_ANALYSIS.md'}")

    print(f"\n产物目录: {out}")


def _build_summary_report(summary, bugs):
    lines = [
        "# 9类金融投研场景 — 智能体1→2→3 链路测试报告",
        "",
        f"测试时间: 2026-08-17",
        f"测试用例: {len(summary)} 类",
        f"成功: {sum(1 for s in summary if s['charts'] > 0)} 类",
        f"失败/跳过: {sum(1 for s in summary if s['charts'] == 0)} 类",
        "",
        "## 汇总表",
        "",
        "| 类别 | 话术ID | Agent1 | Agent2 | Agent3 | 图表数 | 抑制 | 候选 |",
        "|------|--------|--------|--------|--------|--------|------|------|",
    ]
    for s in summary:
        lines.append(
            f"| {s['category']} | {s['case_id']} | {s['agent1']} | {s['agent2']} | {s['agent3']} | {s['charts']} | {s['suppressed']} | {s['candidates']} |"
        )

    lines.extend(
        [
            "",
            "## 各类别详情",
            "",
        ]
    )
    for s in summary:
        lines.append(f"### {s['category']} ({s['case_id']})")
        lines.append(f"- Agent1: {s['agent1']}")
        lines.append(f"- Agent2: {s['agent2']} (候选图表: {s['candidates']})")
        lines.append(
            f"- Agent3: {s['agent3']} (生成图表: {s['charts']}, 抑制: {s['suppressed']})"
        )
        if s["collaboration_requests"]:
            lines.append("- 拦截请求:")
            for r in s["collaboration_requests"]:
                lines.append(f"  - [{r['request_id']}] {r['reason']}")
        lines.append("")

    if bugs:
        lines.extend(
            [
                "## 发现的Bug",
                "",
                f"共 {len(bugs)} 个问题，详见 `BUG_ANALYSIS.md`。",
            ]
        )

    return "\n".join(lines)


def _build_bug_analysis(bugs):
    lines = [
        "# Bug根因分析文档",
        "",
        f"测试时间: 2026-08-17",
        f"Bug总数: {len(bugs)}",
        "",
        "## Bug列表",
        "",
        "| # | 类别 | 话术ID | Agent | 错误类型 | 错误信息 |",
        "|---|------|--------|-------|----------|----------|",
    ]
    for i, b in enumerate(bugs, 1):
        lines.append(
            f"| {i} | {b['category']} | {b['case_id']} | {b['agent']} | {b['type']} | {b.get('error', '')[:80]} |"
        )

    lines.extend(
        [
            "",
            "## 根因分析",
            "",
        ]
    )

    # 按类型分组分析
    by_type: dict[str, list] = {}
    for b in bugs:
        by_type.setdefault(b["type"], []).append(b)

    for bug_type, items in by_type.items():
        lines.append(f"### {bug_type} ({len(items)}个)")
        lines.append("")
        for item in items:
            lines.append(
                f"- **类别**: {item['category']} | **话术**: {item['case_id']} | **Agent**: {item['agent']}"
            )
            lines.append(f"  - 错误: {item.get('error', 'N/A')}")
            if item.get("detail"):
                lines.append(f"  - 详情: {item['detail']}")
        lines.append("")

    # 添加根因推断
    lines.extend(
        [
            "## 根因推断",
            "",
        ]
    )

    if any(b["type"] == "Agent1DataUnavailable" for b in bugs):
        lines.extend(
            [
                "### Agent1数据不可用 (Agent1DataUnavailable)",
                "",
                "**根因**: Agent1通过iFinD SkillHub获取数据时，某些行业/指标组合无法返回可用数据。",
                "可能原因:",
                "1. iFinD数据库中不包含该指标（如某些专项指标仅在企业年报中披露）",
                "2. SkillHub的query planner无法将用户需求映射到正确的skill和query",
                "3. 数据返回后normalizer无法匹配到目标指标名称",
                "4. 行业scope与data_fetch_options.metrics不匹配，导致query planner无法生成有效的检索任务",
                "",
            ]
        )

    if any(b["type"] == "Agent1Failed" for b in bugs):
        lines.extend(
            [
                "### Agent1执行失败 (Agent1Failed)",
                "",
                "**根因**: Agent1在运行过程中抛出异常或返回非COMPLETED状态。",
                "可能原因:",
                "1. SkillHub API调用超时或网络错误",
                "2. 数据质量门检查失败（core_data_available=false）",
                "3. 输入参数校验失败",
                "",
            ]
        )

    if any(b["type"] == "AllCandidatesFailed" for b in bugs):
        lines.extend(
            [
                "### 全部备选失败 (AllCandidatesFailed)",
                "",
                "**根因**: 某类别所有备选话术均无法从Agent1获取数据。",
                "这可能表明该类别的问题类型（如政策/舆情类）不适合当前的数据获取管道，",
                "因为当前管道主要针对定量金融数据（财报、行情、行业指标），",
                "对于纯定性文本（政策文件、新闻报道、行业点评）的检索能力不足。",
                "",
            ]
        )

    if any(
        b["type"]
        not in {"Agent1DataUnavailable", "Agent1Failed", "AllCandidatesFailed"}
        for b in bugs
    ):
        lines.extend(
            [
                "### 其他Agent错误",
                "",
                "**根因**: Agent2或Agent3在执行过程中出现异常。",
                "需要检查具体的错误信息来确定根因。",
                "",
            ]
        )

    return "\n".join(lines)


async def _make_agent3():
    from app.agents.chart_generator.service import ChartGeneratorAgent

    return ChartGeneratorAgent()


if __name__ == "__main__":
    asyncio.run(main())
