"""4条精简压力测试——智能体1真实取数 + 智能体2(不调LLM,Assistant充当大模型)拦截验证。

用户指令：智能体2不调用真实LLM，由本脚本内置的「验证大模型」代替——它审查智能体1
获取的数据 + 智能体2确定性计算结果，识别数据缺陷并生成 collaboration_requests，
从而触发 WAITING_REVIEW 拦截。

4条指令各自的预期拦截原因：
  CASE1 获取宁德时代2025单年财报，杜邦拆解+总资产周转率  → 缺期初资产
  CASE2 固态电池厂商市占，CR5                        → 有效样本不足
  CASE3 宁德时代2023年报+2024Q3营收同比               → 年度/季度周期混用
  CASE4 宁德新能源科技股份2024-2025营收，销售净利率      → 实体匹配失败+基础科目依赖

统一预期：全部进入 WAITING_REVIEW，明确提示异常原因，不编造数据。
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
# 充当大模型的验证模型（确定性审查，不调用任何外部LLM）
# ============================================================
class VerificationModel:
    """Assistant 充当的大模型：审查数据缺陷，触发 WAITING_REVIEW。"""

    model_name = "assistant-verification-model"

    async def generate_analysis(self, *, system_prompt: str, runtime_prompt: str) -> AnalysisDraft:
        del system_prompt
        payload = json.loads(runtime_prompt)
        request = payload["analysis_request"]
        evidence = request.get("evidence_items", [])
        focus = " ".join(request.get("focus_questions", []))
        research_as_of = request.get("research_as_of")

        # 基础 draft（引用有效证据，避免额外风控拦截干扰）
        first = evidence[0] if evidence else {}
        eid = first.get("evidence_id", "")
        claim = AnalysisClaim(
            claim_id="C-001", claim_type="fact",
            text="已获取证据，待数据缺陷复核。",
            evidence_ids=[eid] if eid else [],
            confidence="medium", uncertainty="数据缺陷待复核，未形成结论。",
        )
        draft = AnalysisDraft(
            headline="数据审查发现缺陷，请求补充条件后重跑。",
            overall_confidence="medium",
            financial_quality="differences_pending_verification",
            claims=[claim],
            dimensions=[
                DimensionAnalysis(name=n, summary="维度待复核。", claim_ids=[claim.claim_id] if eid else [])
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
            risks=["数据缺陷未解决，不构成研究结论。"],
        )

        # ---- 按指令执行确定性审查 ----
        if "杜邦" in focus or "总资产周转" in focus:
            draft.collaboration_requests.append(self._check_case1(evidence))
        elif "CR5" in focus or "市占" in focus or "份额" in focus:
            draft.collaboration_requests.append(self._check_case2(evidence))
        elif "2023年报" in focus and "2024Q3" in focus:
            draft.collaboration_requests.append(self._check_case3(evidence))
        elif "宁德新能源科技" in focus:
            draft.collaboration_requests.append(self._check_case4(evidence))
        return draft

    @staticmethod
    def _periods_for(evidence, metric_tokens, scope_token="宁德时代", period_filter=None):
        pes = set()
        for it in evidence:
            name = it.get("metric_name") or ""
            scope = it.get("scope") or ""
            pe = it.get("period_end")
            if any(t in name for t in metric_tokens) and scope_token in scope and pe:
                m = pe[5:7] if pe else ""
                if period_filter is None or m == period_filter:
                    pes.add(pe)
        return pes

    def _check_case1(self, evidence) -> CollaborationRequest:
        # 缺期初资产：总资产是否只有1个报告期（期初+期末各需1期）
        asset_periods = self._periods_for(evidence, ["总资产"], "宁德时代")
        reason = (
            f"宁德时代总资产仅有 {len(asset_periods)} 个报告期数据 {sorted(asset_periods)}，"
            "缺少期初资产，无法计算总资产周转率与三步杜邦ROE。"
            if asset_periods
            else "未获取到宁德时代总资产数据，无法完成杜邦拆解与总资产周转率计算。"
        )
        return CollaborationRequest(
            request_id="CASE1-INSUFFICIENT-PERIOD",
            question="请补充宁德时代期初总资产及上一年度股东权益数据。",
            reason=reason,
            affected_dimensions=["growth", "risk"],
        )

    def _check_case2(self, evidence) -> CollaborationRequest:
        # CR5样本不足：市占率/份额指标数量 < 5
        share_items = [it for it in evidence if any(
            t in (it.get("metric_name") or "") for t in ("市占率", "市场份额", "市场占有率")
        ) and isinstance(it.get("value"), (int, float))]
        return CollaborationRequest(
            request_id="CASE2-INSufficient-SAMPLE",
            question="请补充固态电池厂商市占率明细（至少5家）。",
            reason=f"有效市占率样本仅 {len(share_items)} 个，不足CR5所需5家，拒绝计算集中度。",
            affected_dimensions=["competition"],
        )

    def _check_case3(self, evidence) -> CollaborationRequest:
        # 年度/季度混用：宁德时代营收是否同时存在 2023年报(12-31) 与 2024Q3(09-30)
        annual = self._periods_for(evidence, ["营业收入"], "宁德时代", period_filter="12")
        quarterly = self._periods_for(evidence, ["营业收入"], "宁德时代", period_filter="09")
        if annual and quarterly:
            reason = (
                f"宁德时代营收存在年度口径({sorted(annual)})与季度口径({sorted(quarterly)})混用，"
                "跨周期直接计算营收同比会产生口径失真，已拦截。"
            )
        else:
            reason = (
                f"宁德时代营收报告期分布：年度={sorted(annual)}，2024Q3季度={sorted(quarterly)}；"
                "无法同时满足2023年报与2024Q3的营收同比计算所需口径。"
            )
        return CollaborationRequest(
            request_id="CASE3-PERIOD-MIXED",
            question="请统一营收数据的年度或季度报告期口径后重跑。",
            reason=reason,
            affected_dimensions=["growth"],
        )

    def _check_case4(self, evidence) -> CollaborationRequest:
        # 实体匹配失败：是否命中全称「宁德新能源科技」
        target = "宁德新能源科技"
        matched = [it for it in evidence if target in (it.get("scope") or "")]
        scopes = sorted({it.get("scope", "") for it in evidence})
        return CollaborationRequest(
            request_id="CASE4-ENTITY-MISMATCH",
            question="请确认标的证券代码或全称（宁德新能源科技股份有限公司）。",
            reason=(
                f"证据中未匹配到实体「{target}」，实际覆盖实体：{scopes[:6]}；"
                "无法据此计算销售净利率，拒绝跨实体估算。"
                if not matched
                else f"已匹配到 {len(matched)} 条「{target}」证据，但缺少营业收入/净利润科目，无法计算净利率。"
            ),
            affected_dimensions=["growth", "risk"],
        )


# ============================================================
# 4条指令的智能体1入参
# ============================================================
CASES = [
    {
        "id": "CASE1",
        "topic": "动力电池",
        "focus": ["获取宁德时代2025单年财报，完成三步杜邦拆解，计算总资产周转率并生成图表"],
        "metrics": ["营业收入", "营业成本", "净利润", "总资产", "股东权益"],
        "scope": ["宁德时代"],
        "brief_focus": ["宁德时代"],
    },
    {
        "id": "CASE2",
        "topic": "固态电池",
        "focus": ["查询固态电池厂商市占数据，计算CR5集中度并绘制份额图表"],
        "metrics": ["市占率", "市场份额"],
        "scope": ["固态电池"],
        "brief_focus": [],
    },
    {
        "id": "CASE3",
        "topic": "动力电池",
        "focus": ["使用宁德时代2023年报、2024Q3数据计算营收同比，输出趋势图"],
        "metrics": ["营业收入"],
        "scope": ["宁德时代"],
        "brief_focus": ["宁德时代"],
    },
    {
        "id": "CASE4",
        "topic": "锂电池",
        "focus": ["查询宁德新能源科技股份有限公司2024-2025营收，计算销售净利率绘图"],
        "metrics": ["营业收入", "净利润"],
        "scope": ["宁德新能源科技"],
        "brief_focus": ["宁德新能源科技"],
    },
]


async def main():
    out = Path(__file__).parent / "test_output" / "agents_review_block"
    out.mkdir(parents=True, exist_ok=True)
    agent1 = create_data_fetcher_agent(settings)
    summary = []

    for case in CASES:
        print("\n" + "=" * 70)
        print(f"指令 {case['id']}: {case['focus'][0]}")
        print("=" * 70)
        input_data = {
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
                "geography": "中国", "included_topics": [], "excluded_topics": [],
                "focus_companies": case["brief_focus"], "report_depth": "standard",
            },
            "data_fetch_options": {"metrics": case["metrics"], "industry_scope": case["scope"]},
        }

        # 智能体1
        ctx1 = StageContext(owner_id="test", project_id="agents-review",
                            run_id=f"review-{case['id']}", revision=1, input_data=input_data)
        r1 = await agent1.run(ctx1)
        d1 = r1.data
        ev_count = len(d1.get("evidence_items", []))
        print(f"[智能体1] 状态={r1.status.value} 证据={ev_count} "
              f"质量门={d1.get('acquisition_quality', {}).get('passed')}")

        # 智能体2（用验证模型，不调外部LLM）
        agent2 = DataInterpreterAgent(model=VerificationModel())
        ctx2 = StageContext(owner_id="test", project_id="agents-review",
                            run_id=f"review-{case['id']}", revision=1,
                            input_data=input_data,
                            previous_results={StageName.DATA_FETCH: r1})
        r2 = await agent2.run(ctx2)
        d2 = r2.data
        print(f"[智能体2] 状态={r2.status.value} 错误={r2.error or '无'}")
        reqs = d2.get("collaboration_requests", [])
        qual = d2.get("quality", {})
        print(f"[拦截] quality.passed={qual.get('passed')} collaboration_requests={len(reqs)}")
        for r in reqs:
            print(f"   * [{r.get('request_id')}] {r.get('question')}")
            print(f"     reason: {r.get('reason')}")

        # 记录
        summary.append({
            "case": case["id"], "focus": case["focus"][0],
            "agent1_status": r1.status.value, "evidence_count": ev_count,
            "agent2_status": r2.status.value,
            "want_review": r2.status == StageStatus.WAITING_REVIEW,
            "collaboration_requests": reqs,
        })
        (out / f"{case['id']}.json").write_text(
            json.dumps({"agent1": d1, "agent2": d2}, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n\n" + "=" * 70)
    print("最终结论")
    print("=" * 70)
    for s in summary:
        verdict = "✅" if s["want_review"] else "❌ 未拦截"
        print(f"  {s['case']}: 智能体2 状态={s['agent2_status']} {verdict}")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n产物目录: {out}")


if __name__ == "__main__":
    asyncio.run(main())