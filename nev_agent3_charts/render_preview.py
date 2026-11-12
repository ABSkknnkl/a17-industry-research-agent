"""把智能体3的选型清单 + 主智能体编写的全部图表实现，渲染为可离线预览页面。

用法：``python3 render_preview.py`` → 生成同目录 ``index.html``。
页面只依赖本地 ``echarts.min.js``，不发起任何网络请求。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import charts

ROOT = Path(__file__).resolve().parent
PLAN_PATH = ROOT / "chart_plan.json"
OUTPUT_PATH = ROOT / "index.html"
OPTIONS_PATH = ROOT / "chart_options.json"

CALIBER_NOTES = [
    "2026 年前三季度 ≠ 2025 全年，禁止并列或相加。",
    "渗透率只有 2025 年，无法构建 2021—2025 年度序列。",
    "rd_ratio（研发费用率）缺失，不得用研发费用金额代替研发强度。",
    "产业链 200 条记录为行情/概念字段，不构成上中下游环节归属证据。",
    "销量为累计值、渗透率为国内零售口径、出口为年度值，三者不得混用或相加。",
    "金额类 unit 多为 null/unknown，按量级判断为元并换算亿元，原始值以 dataset.json 为准。",
]


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _card(option: dict[str, Any], index: int) -> str:
    meta = option["chart_meta"]
    refs = "、".join(meta["insight_refs"]) or "—"
    binding = meta.get("data_binding", {})
    metrics = "、".join(binding.get("metrics", [])) or "—"
    domain = binding.get("domain", "—")
    footnotes = "".join(f"<li>{_esc(n)}</li>" for n in meta["footnotes"])
    evids = "".join(
        f"<code>{_esc(e)}</code>" for e in meta["evidence_ids"]
    )
    return f"""
    <article class="card">
      <div class="card-head">
        <span class="idx">{index:02d}</span>
        <div>
          <h2>{_esc(meta['title'])}</h2>
          <div class="tags">
            <span class="tag type">{_esc(meta['chart_type'])}</span>
            <span class="tag chapter">{_esc(meta['recommended_chapter_id'])}</span>
            <span class="tag unit">单位 {_esc(meta['unit'])}</span>
          </div>
        </div>
      </div>
      <p class="goal">{_esc(meta['insight_goal'])}</p>
      <div class="chart" id="chart-{index}"></div>
      <div class="meta-grid">
        <div><span class="k">对应结论</span><span class="v">{_esc(refs)}</span></div>
        <div><span class="k">数据域 / 字段</span><span class="v">{_esc(domain)} · {_esc(metrics)}</span></div>
      </div>
      <details class="notes">
        <summary>口径与数据限制（{len(meta['footnotes'])} 条）</summary>
        <ul>{footnotes}</ul>
      </details>
      <details class="notes evid">
        <summary>证据 ID（{len(meta['evidence_ids'])} 条，全部来自 A1 dataset.json）</summary>
        <div class="evid-list">{evids}</div>
      </details>
    </article>
    """


def _suppressed(items: list[dict[str, Any]]) -> str:
    if not items:
        return "<p class='muted'>无抑制项。</p>"
    rows = "".join(
        f"<tr><td>{_esc(x.get('title',''))}</td>"
        f"<td><code>{_esc(x.get('requested_type',''))}</code></td>"
        f"<td>{_esc(x.get('reason_code',''))}</td>"
        f"<td>{_esc(x.get('reason',''))}</td></tr>"
        for x in items
    )
    return f"""
    <table class="supp">
      <thead><tr><th>被抑制图表</th><th>请求类型</th><th>原因码</th><th>专业理由</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
    """


def build_html(plan: dict[str, Any], options: list[dict[str, Any]]) -> str:
    cards = "".join(_card(o, i + 1) for i, o in enumerate(options))
    types = [o["chart_meta"]["chart_type"] for o in options]
    type_tags = "".join(f"<span class='tag type'>{_esc(t)}</span>" for t in types)
    caliber = "".join(f"<li>{_esc(n)}</li>" for n in CALIBER_NOTES)
    payload = json.dumps(options, ensure_ascii=False, allow_nan=False)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>新能源汽车专题 · 智能体3图表交付</title>
<script src="echarts.min.js"></script>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#f5f7fa; color:#334155;
         font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif; }}
  .wrap {{ max-width:1240px; margin:0 auto; padding:32px 24px 64px; }}
  header h1 {{ font-size:24px; margin:0 0 8px; color:#1B365D; }}
  header p {{ margin:0; color:#64748B; font-size:13px; line-height:1.8; }}
  .panel {{ background:#fff; border:1px solid #e2e8f0; border-radius:10px;
            padding:20px 24px; margin:20px 0; }}
  .panel h3 {{ margin:0 0 12px; font-size:15px; color:#1B365D; }}
  .stats {{ display:flex; gap:28px; flex-wrap:wrap; margin-bottom:14px; }}
  .stat b {{ display:block; font-size:26px; color:#1B365D; line-height:1.2; }}
  .stat span {{ font-size:12px; color:#64748B; }}
  .tag {{ display:inline-block; padding:2px 9px; border-radius:4px; font-size:11px;
          margin:0 6px 5px 0; background:#eef2f7; color:#334155; }}
  .tag.type {{ background:#1B365D; color:#fff; }}
  .tag.chapter {{ background:#0f766e; color:#fff; }}
  .tag.unit {{ background:#fff7ed; color:#9a5b13; border:1px solid #fed7aa; }}
  ul.caliber {{ margin:0; padding-left:20px; font-size:13px; line-height:2; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(520px,1fr)); gap:20px; }}
  .card {{ background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:18px 20px 16px; }}
  .card-head {{ display:flex; gap:12px; align-items:flex-start; }}
  .idx {{ font-size:13px; font-weight:700; color:#fff; background:#1B365D;
          border-radius:6px; padding:5px 8px; flex:none; }}
  .card h2 {{ font-size:15px; margin:2px 0 8px; line-height:1.5; color:#1B365D; }}
  .goal {{ font-size:12.5px; color:#64748B; line-height:1.7; margin:10px 0 6px; }}
  .chart {{ width:100%; height:360px; }}
  .meta-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:8px;
                font-size:12px; margin:8px 0 6px; }}
  .meta-grid .k {{ color:#94a3b8; display:block; }}
  .meta-grid .v {{ color:#334155; }}
  details.notes {{ border-top:1px dashed #e2e8f0; padding-top:8px; margin-top:8px;
                   font-size:12px; color:#475569; }}
  details.notes summary {{ cursor:pointer; color:#0f766e; }}
  details.notes ul {{ margin:8px 0 0; padding-left:18px; line-height:1.8; }}
  .evid-list {{ display:flex; flex-wrap:wrap; gap:5px; margin-top:8px; }}
  .evid-list code {{ font-size:10.5px; background:#f1f5f9; padding:2px 5px; border-radius:3px; }}
  table.supp {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
  table.supp th, table.supp td {{ border-bottom:1px solid #e2e8f0; padding:8px 10px;
                                  text-align:left; vertical-align:top; line-height:1.6; }}
  table.supp th {{ color:#64748B; font-weight:600; background:#f8fafc; }}
  table.supp code {{ background:#f1f5f9; padding:1px 5px; border-radius:3px; }}
  .muted {{ color:#94a3b8; font-size:13px; }}
  footer {{ margin-top:28px; font-size:12px; color:#94a3b8; line-height:1.9; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>新能源汽车专题 · 智能体3图表交付</h1>
    <p>图表类型由智能体3（ChartGeneratorAgent）内部大模型选型推荐；全部 ECharts option 实现代码由主智能体按清单逐一编写。<br>
       数据源：A1 dataset.json（research_as_of 2026-11-09）与 A2 interpretation_report.json；未做任何外推。</p>
  </header>

  <section class="panel">
    <h3>交付概览</h3>
    <div class="stats">
      <div class="stat"><b>{len(options)}</b><span>图表张数</span></div>
      <div class="stat"><b>{len(set(types))}</b><span>图表种类</span></div>
      <div class="stat"><b>{len(plan.get('suppressed_charts', []))}</b><span>主动抑制</span></div>
      <div class="stat"><b>{sum(len(o['chart_meta']['evidence_ids']) for o in options)}</b><span>引用证据 ID 次</span></div>
    </div>
    <div>{type_tags}</div>
  </section>

  <section class="panel">
    <h3>口径红线（引用前必读）</h3>
    <ul class="caliber">{caliber}</ul>
  </section>

  <div class="grid">{cards}</div>

  <section class="panel">
    <h3>主动抑制的候选图表（证据不足 / 越界）</h3>
    {_suppressed(plan.get('suppressed_charts', []))}
  </section>

  <footer>
    选型依据：智能体3 CHART_AGENT_SYSTEM_PROMPT + chart-selection / chart-readability / financial-charting 技能规范。<br>
    配色与结构对齐 chart-generator/compiler.py（CICC Deep Blue #1B365D / Brick Red #D52B1E / Amber #D97706 / Teal #0f766e）。<br>
    本页为静态预览，引用数值请以 A1 dataset.json 的 value 与 unit_provenance 为准。
  </footer>
</div>
<script>
const CHART_OPTIONS = {payload};
CHART_OPTIONS.forEach(function (opt, i) {{
  const el = document.getElementById('chart-' + (i + 1));
  if (!el) return;
  const chart = echarts.init(el, null, {{ renderer: 'canvas' }});
  chart.setOption(opt);
  window.addEventListener('resize', function () {{ chart.resize(); }});
}});
</script>
</body>
</html>
"""


def main() -> None:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    options = charts.build_all(plan)
    # 同时导出纯 option 数组，便于后端直接把图表配置交给前端 ECharts
    OPTIONS_PATH.write_text(
        json.dumps(options, ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    OUTPUT_PATH.write_text(build_html(plan, options), encoding="utf-8")
    print(f"[render_preview] {len(options)} charts -> {OUTPUT_PATH}")
    print(f"[render_preview] {len(options)} options -> {OPTIONS_PATH}")


if __name__ == "__main__":
    main()
