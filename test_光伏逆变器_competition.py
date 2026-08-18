"""光伏逆变器竞争格局测试——智能体1(真实iFinD)→智能体2(Assistant当大模型)→智能体3(图表)。

测试用例: 光伏逆变器行业竞争格局，分析龙头优势与差异化
禁止改动任何生产代码。
"""

import asyncio
import json
import os
import sys
import traceback
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
    DimensionAnalysis,
    ScenarioAnalysis,
    ValidationCard,
)
from app.schemas.workflow import StageName, StageStatus
from app.workflow.stages import StageContext
from app.agents.data_fetcher.factory import create_data_fetcher_agent
from app.agents.data_interpreter.service import DataInterpreterAgent

OUT = Path(__file__).parent / "test_output" / "光伏逆变器_competition"
OUT.mkdir(parents=True, exist_ok=True)


# ============================================================
# 充当大模型的验证模型：竞争格局分析专用
# ============================================================
class CompetitionVerificationModel:
    """Assistant 充当的大模型：确定性审查竞争格局数据，不调用任何外部 LLM。"""

    model_name = "assistant-competition-model"

    async def generate_analysis(self, *, system_prompt: str, runtime_prompt: str) -> AnalysisDraft:
        del system_prompt
        payload = json.loads(runtime_prompt)
        request = payload["analysis_request"]
        evidence = request.get("evidence_items", [])
        metrics = payload.get("calculated_metrics", [])
        calc_issues = payload.get("calculation_issues", [])
        topic = request.get("industry_topic", "光伏逆变器行业竞争格局")

        eid = evidence[0].get("evidence_id", "") if evidence else ""

        claim = AnalysisClaim(
            claim_id="C-001",
            claim_type="fact",
            text="已获取光伏逆变器行业竞争格局证据，据实生成分析候选。",
            evidence_ids=[eid] if eid else [],
            confidence="medium",
            uncertainty="口径限制在可追溯证据范围内，未估算缺失数据。",
        )

        # 竞争格局相关维度
        competition_dimensions = [
            "competition",
            "industry_chain",
            "growth",
            "macro_policy",
            "risk",
        ]

        draft = AnalysisDraft(
            headline=f"基于核验证据完成「{topic}」竞争格局分析。",
            overall_confidence="medium",
            financial_quality="differences_pending_verification",
            claims=[claim],
            dimensions=[
                DimensionAnalysis(
                    name=n,
                    summary=f"光伏逆变器行业{n}维度已核验。",
                    claim_ids=[claim.claim_id] if eid else [],
                )
                for n in competition_dimensions
            ],
            validation_cards=[
                ValidationCard(
                    name=n,
                    status="pending_verification",
                    summary="待复核。",
                    evidence_ids=[eid] if eid else [],
                )
                for n in ("scope_comparability", "financial_quality", "valuation_expectation")
            ],
            scenarios=[
                ScenarioAnalysis(
                    name=n,
                    assumptions=["行业格局保持稳定"],
                    triggers=["市占率变化", "政策调整"],
                    transmission_path="竞争格局变化→龙头企业盈利变动→估值重估",
                    evidence_ids=[eid] if eid else [],
                    disconfirming_conditions=["新进入者颠覆"],
                    monitoring_indicators=["市占率", "毛利率", "出货量"],
                )
                for n in ("base", "upside", "downside")
            ],
            risks=["分析基于当前可追溯证据，未估算缺失数据。"
                   "竞争格局受政策、技术迭代、海外贸易壁垒多重因素影响。"],
        )

        # 针对计算结果生成图表候选
        seen = set()
        chart_map = {
            "market_share": ("bar", "composition"),
            "revenue": ("bar", "comparison"),
            "gross_margin": ("line", "trend"),
            "shipment": ("bar", "comparison"),
            "overseas_revenue": ("bar", "comparison"),
            "rd_expense": ("bar", "comparison"),
        }
        for m in metrics:
            ct, purpose = chart_map.get(
                m.get("calculation_type"), ("bar", "comparison")
            )
            ids = m.get("evidence_ids") or []
            if not ids or tuple(sorted(ids)) in seen:
                continue
            seen.add(tuple(sorted(ids)))
            draft.chart_candidates.append(
                ChartCandidate(
                    title=f"光伏逆变器 {m.get('metric_name')}（{ct}）",
                    chart_type=ct,
                    evidence_ids=ids,
                    analysis_purpose=purpose,
                    insight_goal=f"呈现{m.get('metric_name')}的竞争格局对比",
                    priority=80,
                    chapter_hint="CH-02",
                    user_requested=True,
                )
            )

        # 兜底：没有计算指标时，从证据中直接生成图表候选
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
                        title=f"光伏逆变器 {metric_name}（{ct}）",
                        chart_type=ct,
                        evidence_ids=ids,
                        analysis_purpose=purpose,
                        insight_goal=f"呈现{metric_name}的竞争格局数据",
                        priority=80,
                        chapter_hint="CH-02",
                        user_requested=True,
                    )
                )

        return draft


def build_input():
    return {
        "industry_topic": "光伏逆变器行业竞争格局",
        "market_scope": ["中国"],
        "security_types": ["A股"],
        "reporting_currency": "CNY",
        "research_as_of": "2026-08-17",
        "focus_questions": [
            "光伏逆变器行业竞争格局如何？",
            "龙头企业优势与差异化体现在哪些方面？",
            "国内外厂商市占率对比",
            "海外贸易政策对出口业务的影响",
        ],
        "evidence_items": [],
        "analysis_depth": "standard",
        "risk_preference": "balanced",
        "research_brief": {
            "geography": "中国",
            "included_topics": ["光伏逆变器", "竞争格局", "龙头企业", "海外市场"],
            "excluded_topics": [],
            "focus_companies": ["阳光电源", "华为", "锦浪科技", "固德威", "SMA", "SolarEdge"],
            "report_depth": "standard",
        },
        "data_fetch_options": {
            "metrics": [
                "营业收入",
                "毛利率",
                "净利率",
                "出货量",
                "海外收入占比",
                "研发费用率",
                "市占率",
            ],
            "industry_scope": ["光伏逆变器", "光伏"],
        },
        "chart_generate_options": {
            "requested_chart_count": 8,
            "user_priority": True,
        },
    }


async def main():
    print("=" * 60)
    print("光伏逆变器行业竞争格局 — 智能体1→2→3 测试")
    print("=" * 60)

    agent1 = create_data_fetcher_agent(settings)
    case_id = "PV_INVERTER_COMPETITION"
    input_data = build_input()

    bugs = []
    transcript = {
        "case_id": case_id,
        "input_data": input_data,
        "agent1": {},
        "agent2": {},
        "agent3": {},
    }

    # ==================== 智能体1 ====================
    print("\n[智能体1] 数据采集...")
    ctx1 = StageContext(
        owner_id="test",
        project_id="pv-inverter",
        run_id=case_id,
        revision=1,
        input_data=input_data,
    )
    try:
        r1 = await agent1.run(ctx1)
    except Exception as e:
        bugs.append({"agent": "Agent 1", "error": str(e), "type": type(e).__name__, "traceback": traceback.format_exc()})
        print(f"[智能体1] 异常: {e}")
        transcript["agent1"]["status"] = "ERROR"
        transcript["agent1"]["error"] = str(e)
        return  # 不继续

    d1 = r1.data
    ev_count = len(d1.get("evidence_items", []))
    events = d1.get("events", [])
    blocking = d1.get("blocking_issues", [])
    error_msg = r1.error if hasattr(r1, 'error') else d1.get("blocking_issues", [])
    transcript["agent1"] = {
        "status": r1.status.value,
        "error": r1.error if hasattr(r1, 'error') else None,
        "blocking_issues": blocking,
        "evidence_count": ev_count,
        "events_summary": [
            {"event_type": e.get("event_type"), "message": e.get("message", "")[:200]}
            for e in (events or [])
        ],
    }
    print(f"[智能体1] 状态={r1.status.value} 证据={ev_count}条 阻断={blocking} error={r1.error if hasattr(r1, 'error') else 'N/A'}")

    # 质量评估详情
    quality = d1.get("acquisition_quality", {})
    req_coverage = d1.get("requirement_coverage", [])
    print(f"  质量评估: passed={quality.get('passed')} core_data={quality.get('core_data_available')}")
    print(f"  需求覆盖: {len(req_coverage)}条")
    for rc in req_coverage[:5]:
        print(f"    - [{rc.get('status')}] {rc.get('question', '')[:80]}")
    if quality:
        print(f"  质量详情: {json.dumps({k: v for k, v in quality.items() if k != 'raw'}, ensure_ascii=False, default=str)[:500]}")

    if ev_count == 0:
        print("[智能体1] 未获取到数据，终止测试。")
        return

    if r1.status != StageStatus.COMPLETED:
        print(f"[智能体1] 状态非COMPLETED({r1.status.value})，但证据={ev_count}条，继续推进。")

    # 摘要证据项
    ev_summary = []
    for ev in d1.get("evidence_items", [])[:20]:
        ev_summary.append({
            "evidence_id": ev.get("evidence_id", ""),
            "metric_name": ev.get("metric_name", ""),
            "entity_name": ev.get("entity_name", ""),
            "period_end": ev.get("period_end", ""),
            "value": str(ev.get("value", ""))[:100],
            "unit": ev.get("unit", "未提供"),
        })
    transcript["agent1"]["evidence_sample"] = ev_summary

    # ==================== 智能体2 ====================
    print("\n[智能体2] 数据分析（Assistant充当大模型）...")
    agent2 = DataInterpreterAgent(model=CompetitionVerificationModel())
    ctx2 = StageContext(
        owner_id="test",
        project_id="pv-inverter",
        run_id=case_id,
        revision=1,
        input_data=input_data,
        previous_results={StageName.DATA_FETCH: r1},
    )
    try:
        r2 = await agent2.run(ctx2)
    except Exception as e:
        bugs.append({"agent": "Agent 2", "error": str(e), "type": type(e).__name__, "traceback": traceback.format_exc()})
        print(f"[智能体2] 异常: {e}")
        transcript["agent2"]["status"] = "ERROR"
        transcript["agent2"]["error"] = str(e)
        return

    d2 = r2.data
    cands = d2.get("chart_candidates", [])
    reqs = d2.get("collaboration_requests", [])
    calc_issues = d2.get("calculation_issues", [])
    claims = d2.get("claims", [])
    dimensions = d2.get("dimensions", [])

    transcript["agent2"] = {
        "status": r2.status.value,
        "chart_candidates": len(cands),
        "collaboration_requests": len(reqs),
        "calculation_issues": len(calc_issues),
        "claims": len(claims),
        "dimensions": [d.get("name") for d in (dimensions or [])],
        "candidate_details": [
            {"title": c.get("title"), "chart_type": c.get("chart_type"), "evidence_count": len(c.get("evidence_ids", []))}
            for c in cands[:10]
        ],
        "collaboration_details": [
            {"request_id": r.get("request_id"), "reason": r.get("reason", "")[:200]}
            for r in (reqs or [])[:5]
        ],
        "calc_issue_details": [
            {"calc_type": i.get("calculation_type"), "issue": i.get("issue", "")[:200]}
            for i in (calc_issues or [])[:5]
        ],
    }
    print(f"[智能体2] 状态={r2.status.value} 候选={len(cands)} 拦截={len(reqs)} 计算问题={len(calc_issues)}")

    # 即使Agent2未完成，也保存transcript和HTML
    if r2.status not in {StageStatus.COMPLETED, StageStatus.APPROVED}:
        print("[智能体3] 跳过：Agent 2尚未完成分析。")
        print("[报告] 保存部分结果...")
        _build_html(case_id, input_data, transcript, [], [], [], bugs)
        (OUT / "transcript.json").write_text(
            json.dumps(transcript, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"  状态={r2.status.value} 拦截={len(reqs)}")
        for r in reqs[:3]:
            print(f"  - [{r.get('request_id')}] {r.get('reason', '')[:300]}")
        return bugs, transcript

    # ==================== 智能体3 ====================
    print("\n[智能体3] 图表生成...")
    from app.agents.chart_generator.service import ChartGeneratorAgent

    agent3 = ChartGeneratorAgent()
    ctx3 = StageContext(
        owner_id="test",
        project_id="pv-inverter",
        run_id=case_id,
        revision=1,
        input_data=input_data,
        previous_results={
            StageName.DATA_FETCH: r1,
            StageName.DATA_INTERPRET: r2,
        },
    )
    try:
        r3 = await agent3.run(ctx3)
    except Exception as e:
        bugs.append({"agent": "Agent 3", "error": str(e), "type": type(e).__name__, "traceback": traceback.format_exc()})
        print(f"[智能体3] 异常: {e}")
        transcript["agent3"]["status"] = "ERROR"
        transcript["agent3"]["error"] = str(e)
        return

    d3 = r3.data
    specs = d3.get("chart_specs", [])
    suppressed = d3.get("suppressed", [])
    quality = d3.get("quality_issues", [])

    transcript["agent3"] = {
        "status": r3.status.value,
        "charts_generated": len(specs),
        "suppressed": len(suppressed),
        "quality_issues": len(quality),
        "spec_details": [
            {
                "title": s.get("title", ""),
                "chart_type": s.get("chart_type", ""),
                "data_points": len(s.get("data_points", [])),
            }
            for s in specs
        ],
        "suppressed_details": [
            {"title": s.get("title", ""), "reason": s.get("suppression_reason", "")[:200]}
            for s in suppressed[:5]
        ],
        "quality_details": [
            {"issue": q.get("issue", "")[:200]}
            for q in (quality or [])[:5]
        ],
    }
    print(f"[智能体3] 状态={r3.status.value} 图表={len(specs)} 抑制={len(suppressed)} 质控={len(quality)}")

    # ==================== 生成HTML报告 ====================
    print("\n[报告] 生成HTML...")
    _build_html(case_id, input_data, transcript, specs, suppressed, quality, bugs)
    print(f"[报告] 已保存到 {OUT / 'report.html'}")

    # ==================== 保存原始JSON ====================
    (OUT / "transcript.json").write_text(
        json.dumps(transcript, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"[原始数据] 已保存到 {OUT / 'transcript.json'}")

    # ==================== 打印摘要 ====================
    print("\n" + "=" * 60)
    print("测试摘要")
    print("=" * 60)
    print(f"  智能体1: 状态={r1.status.value} 证据={ev_count}条")
    print(f"  智能体2: 状态={r2.status.value} 候选={len(cands)} 拦截={len(reqs)}")
    print(f"  智能体3: 状态={r3.status.value} 图表={len(specs)} 抑制={len(suppressed)}")
    print(f"  Bug: {len(bugs)}个")
    if bugs:
        for b in bugs:
            print(f"    - [{b['agent']}] {b['type']}: {b['error'][:120]}")

    return bugs, transcript


def _build_html(case_id, input_data, transcript, specs, suppressed, quality, bugs):
    """生成简单HTML报告。"""
    a1 = transcript.get("agent1", {})
    a2 = transcript.get("agent2", {})
    a3 = transcript.get("agent3", {})

    spec_rows = ""
    for s in specs:
        chart_id = s.get("chart_id", "")
        html = s.get("html", "")
        title = s.get("title", "图表")
        if html:
            spec_rows += f"""<div class="chart-card">
                <h4>{title}</h4>
                <div class="chart-container">{html}</div>
                <p class="chart-id">ID: {chart_id}</p>
            </div>"""
        else:
            spec_rows += f"""<div class="chart-card">
                <h4>{title}</h4>
                <pre class="chart-json">{json.dumps(s, ensure_ascii=False, indent=2, default=str)[:2000]}</pre>
            </div>"""

    bug_rows = ""
    for b in bugs:
        bug_rows += f"""<tr>
            <td>{b.get('agent')}</td>
            <td>{b.get('type')}</td>
            <td>{b.get('error', '')[:300]}</td>
        </tr>"""

    suppressed_rows = ""
    for s in suppressed:
        suppressed_rows += f"""<li>{s.get('title', '')}: {s.get('suppression_reason', '')[:200]}</li>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>光伏逆变器行业竞争格局 — 测试报告</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:1100px;margin:0 auto;padding:20px;background:#f5f5f5}}
h1{{color:#1a1a2e;border-bottom:2px solid #e94560;padding-bottom:10px}}
h2{{color:#16213e;margin-top:30px}}
.card{{background:#fff;border-radius:8px;padding:20px;margin:15px 0;box-shadow:0 2px 8px rgba(0,0,0,0.1)}}
.chart-card{{background:#fff;border-radius:8px;padding:20px;margin:15px 0;box-shadow:0 2px 8px rgba(0,0,0,0.1)}}
.chart-container{{width:100%;height:400px}}
.chart-id{{color:#999;font-size:12px}}
.chart-json{{background:#f8f8f8;padding:10px;font-size:12px;overflow:auto;max-height:400px}}
table{{width:100%;border-collapse:collapse;margin:10px 0}}
th,td{{border:1px solid #ddd;padding:8px;text-align:left;font-size:14px}}
th{{background:#e94560;color:#fff}}
.bug{{background:#fff3cd;border-left:4px solid #ffc107;padding:10px;margin:8px 0}}
.ok{{color:#28a745}}
.warn{{color:#ffc107}}
.err{{color:#dc3545}}
.tag{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:12px;margin:2px}}
.tag-ok{{background:#d4edda;color:#155724}}
.tag-warn{{background:#fff3cd;color:#856404}}
.tag-err{{background:#f8d7da;color:#721c24}}
</style>
</head>
<body>
<h1>光伏逆变器行业竞争格局 — 测试报告</h1>
<p>测试时间: 2026-08-17 | 用例ID: {case_id}</p>

<div class="card">
<h2>测试输入</h2>
<p><strong>行业话题:</strong> {input_data.get('industry_topic', '')}</p>
<p><strong>焦点问题:</strong> {'; '.join(input_data.get('focus_questions', []))}</p>
<p><strong>关注公司:</strong> {', '.join(input_data.get('research_brief', {}).get('focus_companies', []))}</p>
<p><strong>采集指标:</strong> {', '.join(input_data.get('data_fetch_options', {}).get('metrics', []))}</p>
</div>

<div class="card">
<h2>智能体1 — 数据采集</h2>
<table>
<tr><th>项目</th><th>值</th></tr>
<tr><td>状态</td><td><span class="tag tag-{'ok' if a1.get('status')=='COMPLETED' else 'warn'}">{a1.get('status', 'N/A')}</span></td></tr>
<tr><td>证据数量</td><td>{a1.get('evidence_count', 0)}</td></tr>
<tr><td>事件数量</td><td>{len(a1.get('events_summary', []))}</td></tr>
</table>
<h3>证据样本</h3>
<table>
<tr><th>指标</th><th>实体</th><th>期间</th><th>值</th><th>单位</th></tr>
{"".join(f"<tr><td>{ev.get('metric_name','')}</td><td>{ev.get('entity_name','')}</td><td>{ev.get('period_end','')}</td><td>{ev.get('value','')}</td><td>{ev.get('unit','')}</td></tr>" for ev in a1.get('evidence_sample', [])[:15])}
</table>
</div>

<div class="card">
<h2>智能体2 — 数据分析（Assistant充当大模型）</h2>
<table>
<tr><th>项目</th><th>值</th></tr>
<tr><td>状态</td><td><span class="tag tag-{'ok' if a2.get('status')=='COMPLETED' else 'err'}">{a2.get('status', 'N/A')}</span></td></tr>
<tr><td>图表候选</td><td>{a2.get('chart_candidates', 0)}</td></tr>
<tr><td>协作请求</td><td>{a2.get('collaboration_requests', 0)}</td></tr>
<tr><td>计算问题</td><td>{a2.get('calculation_issues', 0)}</td></tr>
<tr><td>分析维度</td><td>{', '.join(a2.get('dimensions', []))}</td></tr>
</table>
<h3>候选详情</h3>
<table>
<tr><th>标题</th><th>类型</th><th>证据数</th></tr>
{"".join(f"<tr><td>{c.get('title','')}</td><td>{c.get('chart_type','')}</td><td>{c.get('evidence_count','')}</td></tr>" for c in a2.get('candidate_details', []))}
</table>
</div>

<div class="card">
<h2>智能体3 — 图表生成</h2>
<table>
<tr><th>项目</th><th>值</th></tr>
<tr><td>状态</td><td><span class="tag tag-{'ok' if a3.get('status')=='COMPLETED' else 'warn'}">{a3.get('status', 'N/A')}</span></td></tr>
<tr><td>生成图表</td><td>{a3.get('charts_generated', 0)}</td></tr>
<tr><td>抑制图表</td><td>{a3.get('suppressed', 0)}</td></tr>
<tr><td>质控问题</td><td>{a3.get('quality_issues', 0)}</td></tr>
</table>
</div>

<h2>生成图表</h2>
{spec_rows}

<div class="card">
<h2>抑制图表</h2>
<ul>{suppressed_rows if suppressed_rows else '<li>无</li>'}</ul>
</div>

<div class="card">
<h2>Bug</h2>
{'<p class="ok">无Bug</p>' if not bugs else f'<table><tr><th>Agent</th><th>类型</th><th>错误</th></tr>{bug_rows}</table>'}
</div>

<script>
// 重新渲染ECharts容器
document.querySelectorAll('.chart-container').forEach(function(el) {{
    var html = el.innerHTML;
    if (html.indexOf('echarts') > -1) {{
        // 重新执行内嵌脚本
        var scripts = el.querySelectorAll('script');
        scripts.forEach(function(s) {{
            try {{ eval(s.textContent); }} catch(e) {{}}
        }});
    }}
}});
</script>
</body>
</html>"""

    (OUT / "report.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    result = asyncio.run(main())
    if result:
        bugs, transcript = result
        if bugs:
            print("\n[BUG] 检测到问题，开始根因分析...")
            _bug_analysis = []
            for b in bugs:
                _bug_analysis.append({
                    "agent": b["agent"],
                    "error_type": b["type"],
                    "error_message": b["error"],
                    "traceback": b.get("traceback", ""),
                })
            (OUT / "bugs.json").write_text(
                json.dumps(_bug_analysis, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            print(f"[BUG] 已保存到 {OUT / 'bugs.json'}")