#!/usr/bin/env python3
"""把「审核门实际放行」的真实链路 A3 图表统一渲染为离线展示页。

只读取既有真实运行产物，不改任何业务代码/审核门/既有产物。
数据源：output/runs/charts-20261112111814-dd70766b/chart_result.json
（补齐版上游数据 + 真实 A3 实跑，quality.passed=true, ready_count=6）

产物：index_gate_approved.html（单文件离线自包含）
"""

from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT.parent / "a17-industry-research-agent"
RESULT = APP / "output/runs/charts-20261112111814-dd70766b/chart_result.json"
ECHARTS = ROOT / "echarts.min.js"
OUT = ROOT / "index_gate_approved.html"

# 选图决策：题号 → 图型 + 放行依据（与四问逐条对应）
DECISION = {
    "CHART-01-25932089": {
        "q": "Q1", "why": "Q1 明确要求产业链结构；A5 _chart_contract_issues 对 industry_chain 直接豁免，链图走独立证据引擎",
        "gate": "A3 链图证据引擎 + A5 豁免",
    },
    "CHART-02-8530EBAC": {
        "q": "Q1 / Q2", "why": "两问都要 2021—2025 销量变化；5 年同口径年度累计值，可派生同比，点级契约 9 点全通过",
        "gate": "option_contract_issue 9/9 点通过",
    },
    "CHART-03-CB011226": {
        "q": "Q1 / Q3", "why": "两问要三家整车毛利率；比率单位 % 显式，无 unit_unknown；异常观测已单列不混入比较",
        "gate": "measurement_contract + 8 点点级契约",
    },
    "CHART-04-6339166A": {
        "q": "Q2", "why": "Q2 点名出口量 2021—2025 变化；年度值 5 点 + 派生同比，双轴单位分别标注",
        "gate": "option_contract_issue 9/9 点通过",
    },
    "CHART-05-1B49A9E3": {
        "q": "Q4", "why": "Q4 要电池 vs 整车的研发强度；本轮真实取数补齐 rd_ratio 后才可发布，按同组同年费用合计/营收合计",
        "gate": "derived_measurement_contract 3 点通过",
    },
    "CHART-06-2A1D68B1": {
        "q": "Q1 / Q2", "why": "两问要渗透率变化；本轮补齐 2021-02 起月度观测，观测期由单年扩到 2021—2025；仍标月度零售口径。注意：真实链路按时序契约规范化为 8 个非等间隔月末观测（2021-02、2021-09、2023-12、2024-07、2025-08…），不是连续月度序列，不得解读为逐月趋势或环比",
        "gate": "period_type 一致 + 8 点点级契约；observation_range 2021-02-28—2025-12-31",
    },
}


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def card(idx: int, c: dict) -> tuple[str, str | None]:
    cid = c["chart_id"]
    d = DECISION.get(cid, {})
    option = c.get("option") or {}
    inline_svg = c.get("inline_svg") or ""
    is_svg = c.get("render_mode") == "svg" and bool(inline_svg)
    foot = c.get("footnotes") or []
    eids = c.get("evidence_ids") or []
    points = (c.get("data_contract") or {}).get("points") or []

    if is_svg:
        # 真实链路产出的内联 SVG，去掉固定宽高让它自适应
        svg = inline_svg.replace('width="1440" height="810"', 'width="100%" height="100%"', 1)
        body = f'<div class="chart svg-wrap">{svg}</div>'
        opt_payload = None
    else:
        body = f'<div class="chart" id="chart-{idx}"></div>'
        opt_payload = json.dumps(option, ensure_ascii=False, allow_nan=False)

    foot_html = "".join(f"<li>{esc(f)}</li>" for f in foot) or "<li>（该图无附加脚注）</li>"
    evid_html = "".join(f"<code>{esc(e)}</code>" for e in eids[:30]) or "—"
    q = esc(d.get("q", "—"))
    why = esc(d.get("why", ""))
    gate = esc(d.get("gate", ""))

    card_html = f"""
    <article class="card">
      <div class="card-head">
        <span class="idx">{idx:02d}</span>
        <div>
          <h2>{esc(c['title'])}</h2>
          <div class="tags">
            <span class="tag q">对应 {q}</span>
            <span class="tag type">{esc(c['chart_type'])}</span>
            <span class="tag status">审核门已放行</span>
            <span class="tag unit">证据 {len(eids)} 条 / 契约点 {len(points)}</span>
          </div>
        </div>
      </div>
      <p class="goal"><b>为什么选它：</b>{why}</p>
      <p class="goal"><b>放行依据：</b>{gate}</p>
      {body}
      <details class="notes">
        <summary>口径与数据限制（{len(foot)} 条）</summary>
        <ul>{foot_html}</ul>
      </details>
      <details class="notes">
        <summary>证据 ID（{len(eids)} 条，来自真实链路 A1/A2）</summary>
        <div class="evid-list">{evid_html}</div>
      </details>
    </article>
    """
    return card_html, opt_payload


def main() -> None:
    cr = json.loads(RESULT.read_text(encoding="utf-8"))
    charts = [c for c in cr["charts"] if c.get("status") == "ready"]
    q = cr.get("quality") or {}
    assert q.get("passed") is True, "来源运行未通过门禁，不得展示"
    assert len(charts) == q.get("ready_count"), "图数与放行记录不一致"

    cards, payloads = [], []
    for i, c in enumerate(charts, 1):
        h, p = card(i, c)
        cards.append(h)
        # payload 数组下标与 DOM id 一致；链图占位 null
        payloads.append(p)

    # 只把 ECharts 图交给脚本渲染，链图用内联 SVG
    render_list = []
    for i, p in enumerate(payloads, 1):
        if p is not None:
            render_list.append({"dom": f"chart-{i}", "option": json.loads(p)})

    echarts_js = ECHARTS.read_text(encoding="utf-8").replace("</script>", "<\\/script>")
    payload = json.dumps(render_list, ensure_ascii=False, allow_nan=False)

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>新能源汽车四问 · 审核门放行图表</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#f5f7fa; color:#334155;
         font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; }}
  .wrap {{ max-width:1280px; margin:0 auto; padding:32px 24px 64px; }}
  header h1 {{ font-size:24px; margin:0 0 8px; color:#1B365D; }}
  header p {{ margin:0; color:#64748B; font-size:13px; line-height:1.85; }}
  .panel {{ background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:20px 24px; margin:20px 0; }}
  .panel h3 {{ margin:0 0 12px; font-size:15px; color:#1B365D; }}
  .stats {{ display:flex; gap:28px; flex-wrap:wrap; margin-bottom:12px; }}
  .stat b {{ display:block; font-size:26px; color:#1B365D; line-height:1.2; }}
  .stat span {{ font-size:12px; color:#64748B; }}
  table.dec {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
  table.dec th, table.dec td {{ border-bottom:1px solid #e2e8f0; padding:8px 10px; text-align:left; vertical-align:top; line-height:1.7; }}
  table.dec th {{ background:#f8fafc; color:#64748B; font-weight:600; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(540px,1fr)); gap:20px; }}
  .card {{ background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:18px 20px 16px; }}
  .card-head {{ display:flex; gap:12px; align-items:flex-start; }}
  .idx {{ font-size:13px; font-weight:700; color:#fff; background:#1B365D; border-radius:6px; padding:5px 8px; flex:none; }}
  .card h2 {{ font-size:15px; margin:2px 0 8px; line-height:1.5; color:#1B365D; }}
  .tag {{ display:inline-block; padding:2px 9px; border-radius:4px; font-size:11px; margin:0 6px 5px 0; background:#eef2f7; }}
  .tag.q {{ background:#0f766e; color:#fff; }}
  .tag.type {{ background:#1B365D; color:#fff; }}
  .tag.status {{ background:#e8f5ee; color:#1a7f4b; border:1px solid #b7e2c8; }}
  .tag.unit {{ background:#fff7ed; color:#9a5b13; border:1px solid #fed7aa; }}
  .goal {{ font-size:12.5px; color:#64748B; line-height:1.75; margin:8px 0 4px; }}
  .chart {{ width:100%; height:370px; }}
  .svg-wrap {{ height:auto; min-height:370px; overflow:hidden; }}
  .svg-wrap svg {{ width:100%; height:auto; display:block; }}
  details.notes {{ border-top:1px dashed #e2e8f0; padding-top:8px; margin-top:8px; font-size:12px; color:#475569; }}
  details.notes summary {{ cursor:pointer; color:#0f766e; }}
  details.notes ul {{ margin:8px 0 0; padding-left:18px; line-height:1.8; }}
  .evid-list {{ display:flex; flex-wrap:wrap; gap:5px; margin-top:8px; }}
  .evid-list code {{ font-size:10.5px; background:#f1f5f9; padding:2px 5px; border-radius:3px; }}
  .warn {{ border-left:4px solid #D97706; }}
  footer {{ margin-top:28px; font-size:12px; color:#94a3b8; line-height:1.9; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>新能源汽车四问 · 审核门放行图表</h1>
    <p>图表全部取自<b>真实五阶段链路 A3 实跑产物</b>（run <code>charts-20261112111814-dd70766b</code>，
       使用本轮补齐版上游 A1/A2），<code>quality.passed=true</code>、<code>ready_count=6</code>、<code>issues=[]</code>。<br>
       选图依据：《五行业选题与网页研究问题.docx》第 5 节四问 + 审核门三层拦截条件。不放宽任何门禁。
    </p>
  </header>

  <section class="panel">
    <h3>交付概览</h3>
    <div class="stats">
      <div class="stat"><b>{len(charts)}</b><span>放行图表</span></div>
      <div class="stat"><b>4</b><span>覆盖问题</span></div>
      <div class="stat"><b>3</b><span>放行图型</span></div>
      <div class="stat"><b>{sum(len(c.get('evidence_ids') or []) for c in charts)}</b><span>引用证据次</span></div>
    </div>
    <table class="dec">
      <thead><tr><th>问题</th><th>所选图表</th><th>图型</th><th>门禁结论</th></tr></thead>
      <tbody>
        <tr><td>Q1 销量/渗透率 + 三家财务 + 产业链</td><td>产业链拓扑、销量及同比、整车毛利率、渗透率月度</td><td>industry_chain / combo / line</td><td>放行</td></tr>
        <tr><td>Q2 销量/渗透率/出口量 + 口径差异</td><td>销量及同比、出口量及同比、渗透率月度</td><td>combo / line</td><td>放行（口径差异留缺口）</td></tr>
        <tr><td>Q3 三家营收/毛利率/现金流分化</td><td>整车组毛利率趋势</td><td>line</td><td>部分放行（营收/现金流留缺口）</td></tr>
        <tr><td>Q4 电池 vs 整车研发强度/利润率/现金流</td><td>电池组研发费用率趋势</td><td>line</td><td>部分放行（利润率/现金流留缺口）</td></tr>
      </tbody>
    </table>
  </section>

  <section class="panel warn">
    <h3>主动不选的图表（选了也过不了门禁，按你的要求不硬凑）</h3>
    <table class="dec">
      <thead><tr><th>问题诉求</th><th>不放行原因</th><th>处置</th></tr></thead>
      <tbody>
        <tr><td>三家整车 2023—2025 营收、经营现金流图</td><td>A1 金额 <code>unit=null</code> + <code>unit_unknown</code>，A3 <code>measurement_contract</code> 抑制、A5 <code>required_financial_cell</code> 报错</td><td>留缺口，不伪造单位</td></tr>
        <tr><td>Q4 利润率/现金流分组对比、Q3 整车分部独立比较</td><td>分部财报口径缺失；分组现金流受金额单位缺口阻断</td><td>留缺口</td></tr>
        <tr><td>Q2 汽车总量 / 乘用车口径差异对照</td><td>无结构化指标，属方法论元数据</td><td>留缺口</td></tr>
        <tr><td>2021—2025 年度全口径渗透率趋势</td><td>数据源只有月度零售口径，月度不得冒充年度</td><td>改用月度观测序列</td></tr>
        <tr><td>连续逐月渗透率折线</td><td>真实链路按时序契约规范化为 8 个非等间隔月末观测，点级契约只认这些点</td><td>不硬补中间月份，图下注明不得解读为逐月趋势</td></tr>
      </tbody>
    </table>
  </section>

  <div class="grid">{''.join(cards)}</div>

  <footer>
    数据来源：A1 dataset.json（research_as_of 2026-11-09）与 A2 interpretation_report.json；本轮真实重新取数补齐 58 条记录，A1/A2 成对同步，source_conflicts=0。<br>
    本页为单文件离线展示：ECharts 与链图 SVG 均已内联，不发起任何网络请求。
  </footer>
</div>
<script>
{echarts_js}
</script>
<script>
const RENDER_LIST = {payload};
RENDER_LIST.forEach(function (item) {{
  const el = document.getElementById(item.dom);
  if (!el) return;
  const chart = echarts.init(el, null, {{ renderer: 'canvas' }});
  chart.setOption(item.option);
  window.addEventListener('resize', function () {{ chart.resize(); }});
}});
</script>
</body>
</html>
"""
    OUT.write_text(doc, encoding="utf-8")
    print(f"[gallery] {len(charts)} 张放行图 -> {OUT.name} ({OUT.stat().st_size/1024/1024:.2f} MB)")
    print(f"[gallery] ECharts 渲染 {len(render_list)} 张 / 内联 SVG 1 张")
    print(f"[gallery] 卡片数 {doc.count('<article class=\"card\">')}")


if __name__ == "__main__":
    main()
