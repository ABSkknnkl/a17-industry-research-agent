/**
 * 后端枚举值 → 终端用户能看懂的中文标签
 *
 * 取值来源：`contracts/display-labels.json`（唯一事实源，请与本文件保持一致）。
 *
 * 职责划分：
 *   - 数据技能：后端会在 SourceRecord 上下发 `skill_label`，前端优先用它，
 *     `skillLabel()` 仅作为老数据 / 缺字段时的兜底。
 *   - 分析维度与覆盖状态：后端**无法**下发（DimensionCoverage 是 LLM 结构化
 *     输出契约，加字段会破坏 model_json_schema；阶段数据又是 extra="forbid"，
 *     也不能塞额外 key）。这两个只能由前端映射，详见 contracts/README.md。
 *
 * 未收录的值回退显示原文，不会丢信息。
 *
 * 取值来源：
 *   - SkillName          backend/app/schemas/acquisition.py（StrEnum）
 *   - research_dimension backend/app/schemas/acquisition.py（Literal）
 *   - EvidenceCategory   frontend/src/api/types.ts
 */

// ------------------------------------------------------------------
// 数据技能（SkillName），如 hithink_industry_query
// ------------------------------------------------------------------
const SKILL_LABELS: Record<string, string> = {
  hithink_industry_query: '行业数据',
  hithink_finance_query: '财务数据',
  hithink_macro_query: '宏观数据',
  industry_chain_analysis: '产业链分析',
  report_search: '研报检索',
  news_search: '新闻检索',
  announcement_search: '公告检索',
  hithink_event_query: '事件数据',
  hithink_business_query: '主营构成',
  hithink_sector_selector: '板块选股',
  hithink_insresearch_query: '机构调研',
  hithink_index_query: '指数数据',
  hithink_futures_query: '期货数据',
  hithink_stock_selector: '个股选股',
  hithink_astock_selector: 'A股选股',
  hithink_basicinfo_query: '公司基本信息',
  hithink_market_query: '行情数据',
  hithink_management_query: '股东与股本',
  web_search: '联网搜索',

  // 证据来源类型（EvidenceCategory）
  company: '公司公告',
  industry: '行业资料',
  tech: '技术资料',
  opinion: '公开观点',
}

export const skillLabel = (skill: string): string => {
  if (!skill) return ''
  const trimmed = skill.trim()
  const normalized = trimmed.replace(/-/g, '_')
  return SKILL_LABELS[normalized] ?? SKILL_LABELS[trimmed] ?? trimmed
}

// ------------------------------------------------------------------
// 分析维度（research_dimension）
// ------------------------------------------------------------------
const DIMENSION_LABELS: Record<string, string> = {
  industry: '行业概况',
  growth: '成长性',
  competition: '竞争格局',
  finance: '财务数据',
  macro_policy: '宏观政策',
  industry_chain: '产业链',
  risk: '风险',
  research: '研报观点',
  company: '公司基本面',
}

export const dimensionLabel = (dim?: string): string => (dim ? (DIMENSION_LABELS[dim] ?? dim) : '')

// ------------------------------------------------------------------
// 证据来源类型（EvidenceCategory）
// ------------------------------------------------------------------
const EVIDENCE_CATEGORY_LABELS: Record<string, string> = {
  company: '公司公告',
  industry: '行业资料',
  tech: '技术资料',
  opinion: '公开观点',
}

export const evidenceCategoryLabel = (category?: string): string =>
  category ? (EVIDENCE_CATEGORY_LABELS[category] ?? category) : ''

// ------------------------------------------------------------------
// 通用字段名（阶段摘要里直接展示后端 key 时兜底用）
// ------------------------------------------------------------------
const FIELD_LABELS: Record<string, string> = {
  status: '状态',
  stage: '所处阶段',
  run_id: '任务编号',
  report_id: '报告编号',
  title: '标题',
  summary: '摘要',
  message: '说明',
  error: '错误信息',
  reason: '原因',
  count: '数量',
  total: '总数',
  version: '版本',
  created_at: '创建时间',
  updated_at: '更新时间',
  elapsed_ms: '耗时（毫秒）',
}

export const fieldLabel = (key: string): string => FIELD_LABELS[key] ?? key

// ------------------------------------------------------------------
// 财务指标名（key_metrics[].name / insights 关联指标）
//
// 后端下发的是内部英文字段名（revenue / parent_net_profit / product_revenue:整车），
// 直接展示会把内部字段暴露给分析师，且人工编辑后会把英文名写进报告指标卡。
// 这里只做「英文 → 中文」的展示映射，不改写后端数据本身。
// ------------------------------------------------------------------
const METRIC_LABELS: Record<string, string> = {
  revenue: '营业收入',
  parent_net_profit: '归母净利润',
  net_profit: '净利润',
  gross_margin: '毛利率',
  net_margin: '净利率',
  roe: '净资产收益率',
  debt_ratio: '资产负债率',
  operating_cash_flow: '经营活动现金流',
  rd_expense: '研发费用',
  market_cap: '总市值',
  pe_ttm: '市盈率(TTM)',
  pb: '市净率',
}

/** `product_revenue:动力电池系统` → `分产品营收·动力电池系统`；未收录值回退原文 */
export function metricLabel(name?: string): string {
  if (!name) return ''
  const trimmed = name.trim()
  if (trimmed.startsWith('product_revenue:')) {
    return `分产品营收·${trimmed.slice('product_revenue:'.length)}`
  }
  return METRIC_LABELS[trimmed] ?? trimmed
}

/** 金额归一：元 → 亿元（≥1 亿时），返回可直接展示的数值字符串与单位 */
export function normalizeMetricAmount(
  value: unknown,
  unit?: string | null
): { value: string; unit: string } {
  const rawUnit = (unit ?? '').trim()
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return { value: '', unit: rawUnit }
  }
  if (rawUnit === '元' && Math.abs(value) >= 100_000_000) {
    return { value: (value / 100_000_000).toFixed(2), unit: '亿元' }
  }
  if (rawUnit === '元') {
    return { value: value.toFixed(2), unit: '元' }
  }
  return { value: String(value), unit: rawUnit }
}

/**
 * 同比/环比变化：后端 `change_pct` 是**小数比例**（0.0345 表示 +3.45%），
 * `percentage_point_change` 是百分点。缺失一律显示空串，绝不落到 0。
 */
export function formatMetricChange(changePct?: unknown, percentagePointChange?: unknown): string {
  if (typeof changePct === 'number' && Number.isFinite(changePct)) {
    const pct = changePct * 100
    return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`
  }
  if (typeof percentagePointChange === 'number' && Number.isFinite(percentagePointChange)) {
    return `${percentagePointChange >= 0 ? '+' : ''}${percentagePointChange.toFixed(2)}pp`
  }
  return ''
}

// ------------------------------------------------------------------
// 对象状态（EvidenceStatus / ClaimStatus / ChartStatus / ParagraphStatus）
// 与 ClaimReviewList、EvidenceReviewTable 里既有的翻译保持一致
// ------------------------------------------------------------------
const EVIDENCE_STATUS_LABELS: Record<string, string> = {
  active: '有效',
  excluded: '已排除',
  provisional: '待复核',
}

export const evidenceStatusLabel = (status?: string): string =>
  status ? (EVIDENCE_STATUS_LABELS[status] ?? status) : ''

const CLAIM_STATUS_LABELS: Record<string, string> = {
  active: '有效',
  provisional: '待复核',
  rejected: '待重生成',
  evidence_insufficient: '证据不足',
}

export const claimStatusLabel = (status?: string): string =>
  status ? (CLAIM_STATUS_LABELS[status] ?? status) : ''

const CHART_STATUS_LABELS: Record<string, string> = {
  active: '已纳入报告',
  provisional: '待复核',
  deleted: '已删除',
  running: '生成中',
}

export const chartStatusLabel = (status?: string): string =>
  status ? (CHART_STATUS_LABELS[status] ?? status) : ''

const PARAGRAPH_STATUS_LABELS: Record<string, string> = {
  active: '已定稿',
  provisional: '待复核',
}

export const paragraphStatusLabel = (status?: string): string =>
  status ? (PARAGRAPH_STATUS_LABELS[status] ?? status) : ''

// ------------------------------------------------------------------
// 图表类型（ChartTypeName）
// ------------------------------------------------------------------
const CHART_TYPE_LABELS: Record<string, string> = {
  line: '折线图',
  bar: '柱状图',
  pie: '饼图',
  radar: '雷达图',
  industry_chain: '产业链图',
  combo: '组合图',
  area: '面积图',
  scatter: '散点图',
  bubble: '气泡图',
  heatmap: '热力图',
  boxplot: '箱线图',
  treemap: '矩形树图',
}

export const chartTypeLabel = (type?: string): string =>
  type ? (CHART_TYPE_LABELS[type] ?? type) : ''

// ------------------------------------------------------------------
// 发布模式（release_mode）
// ------------------------------------------------------------------
const RELEASE_MODE_LABELS: Record<string, string> = {
  formal: '正式模式',
  draft_with_warnings: '草稿模式',
}

export const releaseModeLabel = (mode?: string): string =>
  mode ? (RELEASE_MODE_LABELS[mode] ?? mode) : ''

// ------------------------------------------------------------------
// 报告产物类型（artifact kind）
// 原为 ArtifactList.vue 的私有函数，下载页也需要同一套文案，故上收。
// ------------------------------------------------------------------
const ARTIFACT_KIND_LABELS: Record<string, string> = {
  report_markdown: '报告 Markdown',
  report_html: '报告 HTML',
  report_pdf: '报告 PDF',
  artifact_manifest: '产物清单',
  chart: '图表',
  data: '数据',
}

export const artifactKindLabel = (kind?: string): string =>
  kind ? (ARTIFACT_KIND_LABELS[kind] ?? kind) : ''

// ------------------------------------------------------------------
// 章节序号
// ------------------------------------------------------------------
/**
 * 从章节 ID 反推序号：'CH-03' → '3'，非法则 '?'。
 *
 * 为什么从 ID 推而不是从标题：后端给的是**纯标题**（无「N、」前缀），
 * 编号属于结构信息而非命名内容。弹窗、确认文案需要「第 N 章」时用这个，
 * 不去改写标题。
 */
export function chapterNumber(chapterId?: string): string {
  const matched = /^CH-(\d{2})$/.exec(chapterId ?? '')
  return matched ? String(Number(matched[1])) : '?'
}
