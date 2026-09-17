/*
 * 报告 HTML 样式 —— 从真实后端产物捕获，非手写。
 *
 * 来源：backend/artifacts/run-real-full-chain/reports/r3/report.html 的 <style> 块，
 * 由 backend/app/reporting/templates/report.html.j2 生成。
 *
 * 直接复用真实样式，保证 mock 的报告预览与真实交付件视觉一致；
 * 后端模板改版时需要重新捕获（本文件无逻辑，纯样式常量）。
 */
export const REPORT_HTML_CSS = `
:root { --ink:#0f172a; --muted:#64748b; --line:#dbe4ef; --blue:#1d4ed8; --paper:#fff; --soft:#f4f7fb; --accent-soft:#eff6ff; }
* { box-sizing:border-box; }
html { background:#e9eef5; }
body { margin:0; color:var(--ink); background:var(--paper); font-family:"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",Arial,sans-serif; line-height:1.75; font-size:15px; }
main { max-width:1040px; margin:0 auto; padding:56px 64px 80px; }
.cover { min-height:760px; display:flex; flex-direction:column; justify-content:center; border-top:8px solid var(--blue); position:relative; page-break-after:always; }
.eyebrow { color:var(--blue); font-weight:700; letter-spacing:.14em; text-transform:uppercase; }
h1 { font-size:44px; line-height:1.22; margin:18px 0; letter-spacing:-.02em; }
.subtitle { font-size:19px; color:var(--muted); max-width:720px; }
.meta-grid { margin-top:56px; display:grid; grid-template-columns:repeat(5,1fr); gap:12px; }
.meta { border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
.meta span { display:block; color:var(--muted); font-size:12px; }
.meta strong { display:block; margin-top:4px; overflow-wrap:anywhere; }
h2 { margin:48px 0 20px; padding-bottom:10px; border-bottom:2px solid var(--ink); font-size:28px; page-break-after:avoid; }
h3 { margin:30px 0 12px; font-size:20px; color:#162b4d; page-break-after:avoid; }
p { margin:10px 0; text-align:justify; }
.summary { background:var(--accent-soft); border:1px solid #bfdbfe; border-radius:14px; padding:26px 30px; }
.headline { font-size:21px; font-weight:700; line-height:1.55; }
.conclusion { border-left:4px solid var(--blue); padding:8px 14px; margin:14px 0; background:#fff; }
.chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:7px; }
.chip { color:#334155; background:#e2e8f0; border-radius:999px; padding:2px 9px; font-size:11px; }
.toc { columns:2; column-gap:36px; padding:0; list-style:none; }
.toc li { break-inside:avoid; padding:5px 0; border-bottom:1px dotted var(--line); }
.toc a { color:inherit; text-decoration:none; }
.chapter { page-break-before:always; }
.chapter-summary { color:#334155; font-size:16px; background:var(--soft); padding:12px 16px; border-radius:8px; }
.reference { color:var(--muted); font-size:12px; margin-top:5px; }
.citation { color:var(--blue); text-decoration:none; border-bottom:1px dotted #93c5fd; margin-right:6px; }
.citation:hover { color:#1e40af; border-bottom-style:solid; }
.chart { margin:22px 0 28px; border:1px solid var(--line); border-radius:14px; padding:14px; break-inside:avoid; background:#fff; }
.chart svg { width:100%; height:auto; display:block; }
.chart figcaption { margin:8px 8px 2px; color:var(--muted); font-size:12px; }
.chart-number { color:var(--ink); font-weight:700; }
.chart-pie,.chart-radar { width:64%; margin-left:auto; margin-right:auto; }
.uncertainty { border:1px solid #fcd34d; background:#fffbeb; border-radius:8px; padding:10px 14px; margin:14px 0; break-inside:avoid; page-break-inside:avoid; }
.uncertainty strong { color:#92400e; }
.risk-list li, .boundary-list li { margin:6px 0; }
.footer-note { margin-top:48px; border-top:1px solid var(--line); padding-top:18px; color:var(--muted); font-size:12px; }
.draft-watermark { position:absolute; inset:0; pointer-events:none; z-index:5; display:flex; align-items:center; justify-content:center; opacity:0.08; font-size:72px; font-weight:900; color:#dc2626; transform:rotate(-20deg); letter-spacing:0.3em; }
.draft-banner { background:#fef2f2; border:2px solid #dc2626; border-radius:10px; padding:14px 20px; margin-bottom:24px; color:#991b1b; }
.draft-banner strong { color:#dc2626; }
.risk-appendix { page-break-before:always; }
.quality-appendix { page-break-before:always; }
.quality-table { width:100%; border-collapse:collapse; margin:12px 0 22px; font-size:13px; }
.quality-table th,.quality-table td { border:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top; }
.quality-table th { background:var(--soft); }
.source-index { page-break-before:always; }
.source-index tbody tr { scroll-margin-top:20px; }
.source-table { table-layout:fixed; font-size:11px; font-variant-numeric:tabular-nums; }
.source-table th,.source-table td { overflow-wrap:anywhere; line-height:1.45; padding:7px 8px; }
.source-table th:first-child,.source-table td:first-child { width:5%; text-align:center; }
.source-table th:nth-child(2),.source-table td:nth-child(2) { width:20%; }
.source-table th:nth-child(3),.source-table td:nth-child(3) { width:15%; }
.source-table th:nth-child(4),.source-table td:nth-child(4) { width:12%; white-space:nowrap; }
.source-table th:nth-child(5),.source-table td:nth-child(5) { width:13%; white-space:nowrap; }
.source-table th:nth-child(6),.source-table td:nth-child(6) { width:15%; }
.source-table th:nth-child(7),.source-table td:nth-child(7) { width:20%; }
table caption { caption-side:top; text-align:left; color:var(--ink); font-weight:700; margin:0 0 8px; }
thead { display:table-header-group; }
.visual-note { border:1px solid var(--line); border-radius:10px; padding:12px 16px; margin:18px 0 0; color:var(--muted); font-size:12px; background:var(--soft); }
.visual-note strong { color:var(--ink); }

/* 数据手册型：高密度、数值优先、表格与证据索引更突出。 */
.visual-data-manual { --blue:#17365d; --accent-soft:#f2f6fa; }
.visual-data-manual main { max-width:1120px; }
.visual-data-manual .cover { border-top-width:12px; }
.visual-data-manual h2 { color:#17365d; border-bottom-color:#17365d; }
.visual-data-manual .chapter-summary { border-left:4px solid #17365d; border-radius:0; }
.visual-data-manual .chart { border-radius:4px; }
.visual-data-manual .quality-table { font-size:12px; }

/* 分析笔记型：图、表、正文均衡，是系统默认外壳。 */
.visual-analysis-note { --blue:#1d4ed8; --accent-soft:#eff6ff; }
.visual-analysis-note .conclusion { border-radius:0 8px 8px 0; }

/* 深度研究型：收窄版心、提升行距，强调连续论证。 */
.visual-deep-research { --blue:#7c2d12; --accent-soft:#fff7ed; }
.visual-deep-research body,.visual-deep-research { font-family:"Songti SC","STSong","Noto Serif CJK SC",serif; }
.visual-deep-research main { max-width:920px; padding-left:76px; padding-right:76px; }
.visual-deep-research h1 { font-weight:600; letter-spacing:.01em; }
.visual-deep-research h2 { color:#451a03; border-bottom:1px solid #9a3412; }
.visual-deep-research h3 { color:#7c2d12; }
.visual-deep-research .chapter-summary { background:transparent; border-left:3px solid #9a3412; border-radius:0; padding-left:18px; }
.visual-deep-research .chart { border-width:1px 0; border-radius:0; padding:18px 0; }

.density-compact { font-size:14px; line-height:1.62; }
.density-compact main { padding-top:42px; padding-bottom:60px; }
.density-compact h2 { margin-top:38px; }
.density-compact .chart { margin:16px 0 20px; }
.density-detailed { font-size:15.5px; line-height:1.85; }
.density-detailed main { padding-top:64px; padding-bottom:96px; }
.density-detailed .chapter-summary { padding-top:16px; padding-bottom:16px; }
@page { size:A4; @bottom-center { content:"动力电池行业研究报告  ·  " counter(page); color:#64748b; font-size:9pt; } }
@media print {
  html,body { background:#fff; }
  body { font-size:13.5px; line-height:1.62; }
  /* 与 .visual-*/.density-* 屏幕规则同权重且后置，确保打印版心归零 */
  .visual-data-manual main, .visual-analysis-note main, .visual-deep-research main, main { max-width:none; padding:0; }
  .density-compact main, .density-detailed main { padding-top:0; padding-bottom:0; }
  .cover { min-height:245mm; }
  h1 { font-size:32pt; }
  h2 { margin:32px 0 14px; }
  h3 { margin:20px 0 8px; }
  p { margin:7px 0; }
  .summary { padding:18px 22px; }
  .conclusion { margin:9px 0; padding:6px 12px; }
  .chapter-summary { padding:9px 14px; }
  .chart { margin:16px 0 18px; padding:10px; box-shadow:none; }
  .chart svg { max-height:78mm; }
  .uncertainty { margin:10px 0; padding:7px 12px; }
  .footer-note { margin-top:18px; padding-top:12px; font-size:10.5px; line-height:1.45; }
}
  
`
