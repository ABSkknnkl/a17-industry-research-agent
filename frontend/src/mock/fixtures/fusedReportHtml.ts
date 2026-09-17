import { REPORT_HTML_CSS } from './reportHtmlCss'

/**
 * 融合完成后的报告 HTML 生成器（演示用）。
 *
 * 为什么需要它：mock 原先的 report_html 产物只是把 markdown 塞进 <pre>，
 * 报告预览页打开后看不到真实报告的样子。此生成器按
 * backend/app/reporting/templates/report.html.j2 的结构产出同构 HTML
 * （封面 → 草稿横幅 → 目录 → 执行摘要 → 逐章正文 → 图表 → 来源索引 → 免责声明），
 * 样式复用 reportHtmlCss.ts（从真实产物捕获），因此预览观感与真实交付件一致。
 *
 * 本模块是**纯函数**：不 import 任何 fixture，数据由调用方传入，
 * 避免与 realBatteryData.ts 形成循环引用。
 *
 * 演示声明：段落与来源之间的引用关系是按序号确定性映射的（fixture 的段落不带
 * evidence_ids），仅用于让报告结构完整可读，不代表真实溯源结论。
 */

export interface FusedReportChapter {
  chapter_id: string
  title: string
  sections: Array<{
    section_id: string
    title: string
    paragraphs: Array<{ text: string }>
  }>
}

export interface FusedReportChart {
  chart_id: string
  title: string
  chart_type: string
  svg?: string
  insight_goal?: string
}

export interface FusedReportEvidence {
  evidence_id: string
  title: string
  publisher: string
  as_of_date: string
  summary: string
}

export interface FusedReportClaim {
  statement: string
  dimension: string
  evidence_ids: string[]
  counter_condition: string
}

export interface FusedReportSource {
  title: string
  topic: string
  asOf: string
  /** ISO 时间串；按 UTC 直接切片格式化，保证跨环境输出稳定 */
  generatedAt: string
  depthLabel: string
  statusLabel: string
  banner: string
  questions: string[]
  chapters: FusedReportChapter[]
  charts: FusedReportChart[]
  evidences: FusedReportEvidence[]
  claims: FusedReportClaim[]
}

const CHART_TYPE_LABELS: Record<string, string> = {
  line: '折线图',
  bar: '柱状图',
  pie: '饼图',
  area: '面积图',
  combo: '组合图',
  scatter: '散点图',
  radar: '雷达图',
  industry_chain: '产业链图',
}

const CN_NUM = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']

export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** '2026-01-15T10:30:00.000Z' → '2026-01-15 10:30（协调世界时）' */
function formatUtc(iso: string): string {
  const date = iso.slice(0, 10)
  const time = iso.slice(11, 16)
  return `${date} ${time}（协调世界时）`
}

function cnNumber(index: number): string {
  return CN_NUM[index] ?? String(index + 1)
}

/** 段落引用映射：按序号确定性分配来源，保证引用可点、编号连续 */
function citationsFor(paragraphIndex: number, total: number): number[] {
  if (total === 0) return []
  const first = (paragraphIndex % total) + 1
  const second = ((paragraphIndex + 1) % total) + 1
  return first === second ? [first] : [first, second]
}

function renderCitationLinks(paragraphIndex: number, total: number): string {
  const links = citationsFor(paragraphIndex, total)
    .map((n) => `<a class="citation" href="#source-${n}">来源${n}</a>`)
    .join('')
  return links ? `<p class="reference">资料依据：${links}</p>` : ''
}

function renderChart(chart: FusedReportChart, number: number): string {
  if (!chart.svg) return ''
  const typeLabel = CHART_TYPE_LABELS[chart.chart_type] ?? chart.chart_type
  const goal = chart.insight_goal
    ? `<br>分析目的：${escapeHtml(chart.insight_goal)}`
    : ''
  return [
    `<figure class="chart chart-${escapeHtml(chart.chart_type)}" id="${escapeHtml(chart.chart_id)}">`,
    chart.svg,
    '<figcaption>',
    `<span class="chart-number">图${number}</span> · ${escapeHtml(chart.title)} · ${typeLabel}`,
    goal,
    '</figcaption>',
    '</figure>',
  ].join('')
}

function renderCover(src: FusedReportSource, sectionCount: number): string {
  const metas: Array<[string, string]> = [
    ['研究时点', src.asOf],
    ['生成时间', formatUtc(src.generatedAt)],
    ['报告深度', src.depthLabel],
    ['交付状态', src.statusLabel],
    ['章节规模', `${src.chapters.length} 章 ${sectionCount} 节`],
  ]
  const metaHtml = metas
    .map(([label, value]) => `<div class="meta"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join('')
  const questions = src.questions
    .map((q, i) => `<li>${i + 1}. ${escapeHtml(q)}</li>`)
    .join('')
  return [
    '<section class="cover">',
    '<div class="draft-watermark">内部审核草稿</div>',
    `<div class="eyebrow">${escapeHtml(src.topic)} · 行业研究系统</div>`,
    `<h1>${escapeHtml(src.title)}</h1>`,
    `<p class="subtitle">${escapeHtml(src.banner)}</p>`,
    `<div class="meta-grid">${metaHtml}</div>`,
    `<div class="visual-note"><strong>研究问题：</strong><ul class="question-list">${questions}</ul></div>`,
    '</section>',
  ].join('\n')
}

function renderSummary(src: FusedReportSource, evidenceCount: number): string {
  const conclusions = src.claims.slice(0, 5).map((claim, idx) => {
    const chipCitations = claim.evidence_ids
      .slice(0, 2)
      .map((_, i) => ((idx + i) % Math.max(evidenceCount, 1)) + 1)
      .map((n) => `<a class="chip citation" href="#source-${n}">来源${n}</a>`)
      .join('')
    return [
      '<div class="conclusion">',
      `<strong>核心结论 ${idx + 1}（${escapeHtml(claim.dimension)}）</strong>`,
      escapeHtml(claim.statement),
      `<div class="chips">${chipCitations}</div>`,
      `<p class="reference">反证条件：${escapeHtml(claim.counter_condition)}</p>`,
      '</div>',
    ].join('\n')
  })
  return [
    '<h2>执行摘要</h2>',
    '<section class="summary">',
    `<p class="headline">本报告覆盖 ${src.chapters.length} 个章节，结论均挂载来源编号，可在下方来源索引逐条核对。</p>`,
    ...conclusions,
    '</section>',
  ].join('\n')
}

function renderChapters(src: FusedReportSource, chartOffset: number): string {
  return src.chapters
    .map((chapter, chIdx) => {
      const chapterNo = cnNumber(chIdx)
      const sections = chapter.sections
        .map((section, secIdx) => {
          const paragraphs = section.paragraphs
            .map((p, pIdx) => {
              const globalIdx = chIdx * 10 + secIdx * 3 + pIdx
              return `<p>${escapeHtml(p.text)}</p>\n${renderCitationLinks(globalIdx, src.evidences.length)}`
            })
            .join('\n')
          return [
            // 真实报告的层级号习惯：h2 用中文数字（第一章），h3 用阿拉伯数字（第1章第1节）
            `<h3>第${chIdx + 1}章第${secIdx + 1}节 · ${escapeHtml(section.title)}</h3>`,
            paragraphs,
          ].join('\n')
        })
        .join('\n')
      const chart = src.charts[chIdx]
      return [
        `<section class="chapter" id="chapter-${chIdx + 1}">`,
        `<h2>第${chapterNo}章 · ${escapeHtml(chapter.title)}</h2>`,
        `<p class="chapter-summary">${escapeHtml(
          chapter.sections.map((s) => s.title).join('；')
        )}</p>`,
        sections,
        chart ? renderChart(chart, chartOffset + chIdx) : '',
        '</section>',
      ].join('\n')
    })
    .join('\n')
}

function renderSources(src: FusedReportSource): string {
  const rows = src.evidences
    .map(
      (e, idx) =>
        `<tr id="source-${idx + 1}"><td>${idx + 1}</td><td>${escapeHtml(e.title)}</td><td>${escapeHtml(
          e.publisher
        )}</td><td>${escapeHtml(e.as_of_date)}</td><td>${escapeHtml(e.summary)}</td><td>${escapeHtml(
          e.evidence_id
        )}</td></tr>`
    )
    .join('\n')
  return [
    '<section class="source-index chapter" id="source-index">',
    '<h2>来源与证据索引</h2>',
    '<table class="quality-table source-table">',
    '<caption>表附-1 · 来源与证据索引</caption>',
    '<thead><tr><th>序号</th><th>材料</th><th>发布主体</th><th>日期</th><th>要点</th><th>证据编号</th></tr></thead>',
    `<tbody>${rows}</tbody>`,
    '</table>',
    '</section>',
  ].join('\n')
}

export function buildFusedReportHtml(src: FusedReportSource): string {
  const sectionCount = src.chapters.reduce((n, c) => n + c.sections.length, 0)
  // 图表编号从「执行摘要已有结论数」之后开始，避免与正文图表号冲突
  const chartOffset = 1

  const toc = src.chapters
    .map(
      (c, idx) =>
        `<li><a href="#chapter-${idx + 1}">第${cnNumber(idx)}章 · ${escapeHtml(
          c.title
        )}</a></li>`
    )
    .join('')

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(src.title)}</title>
<style>${REPORT_HTML_CSS}</style>
</head>
<body class="visual-data-manual density-balanced">
<main>
${renderCover(src, sectionCount)}
<div class="draft-banner"><strong>内部审核草稿</strong> — ${escapeHtml(src.banner)}</div>
<h2>目录</h2>
<ol class="toc">${toc}</ol>
${renderSummary(src, src.evidences.length)}
${renderChapters(src, chartOffset)}
${renderSources(src)}
<div class="footer-note">
<p>本报告由数据解读智能体的结构化结论、图表智能体的已校验图表与章节撰写智能体的正文确定性组装；报告融合智能体不新增事实、不改写数据结论。</p>
<p><strong>免责声明：</strong>本报告仅用于行业研究与信息交流，不构成证券投资建议、收益保证或交易邀约。</p>
</div>
</main>
</body>
</html>`
}
