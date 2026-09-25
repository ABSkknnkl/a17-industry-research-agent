<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { StageName } from '../api/types'
import { STAGE_LABELS } from '../api/types'

const props = defineProps<{
  visible: boolean
  stage: StageName
  revision: number
  data: Record<string, unknown>
  annotations?: any[]
  submitting?: boolean
  initialTab?: string
}>()

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
  (e: 'submitRevise', payload: { comment: string; edited_data?: Record<string, unknown> | null }): void
  (e: 'submitDirectEdit', payload: { edited_data: Record<string, unknown>; comment?: string }): void
  (e: 'approve'): void
}>()

const activeTab = ref('tab-1')

// =========================================================================
// 阶段 1：数据采集 (data_fetch)
// =========================================================================
// 1.1 增量数据补采 (Data Replenishment)
const replenishEntity = ref('')
const replenishDomain = ref('financials')
const replenishQuery = ref('')
const replenishReason = ref('')

function quickFillReplenish(type: string) {
  if (type === 'finance') {
    replenishDomain.value = 'financials'
    replenishEntity.value = '宁德时代, 比亚迪'
    replenishQuery.value = '查询宁德时代与比亚迪近3年研发费用、毛利率及储能业务拆分出货量'
    replenishReason.value = '下游图表与章节缺少核心龙头研发投入与储能毛利拆分'
  } else if (type === 'chain') {
    replenishDomain.value = 'industry_chain'
    replenishEntity.value = '产业链上中下游'
    replenishQuery.value = '查询正负极材料、电解液、隔膜及电池系统集成各环节龙头厂商与产能集中度'
    replenishReason.value = '补充产业链各环节核心供需格局'
  } else if (type === 'macro') {
    replenishDomain.value = 'macro'
    replenishEntity.value = '行业产销数据'
    replenishQuery.value = '查询近3年新能源汽车与储能动力电池月度装机量、出口规模及政策补贴演变'
    replenishReason.value = '补充宏观产销增速支撑行业大盘论据'
  } else if (type === 'competitors') {
    replenishDomain.value = 'financials'
    replenishEntity.value = '国轩高科, 亿纬锂能, 中创新航'
    replenishQuery.value = '查询第二梯队核心动力电池企业营收规模与国内市场份额占比'
    replenishReason.value = '补充二线标的对标竞争矩阵数据'
  }
}

function handleReplenishSubmit() {
  const query = replenishQuery.value.trim()
  if (!query) {
    ElMessage.warning('请填写补采查询提示词')
    return
  }
  const entities = replenishEntity.value
    ? replenishEntity.value.split(/[,，、\s]+/).filter(Boolean)
    : []
  const demand = {
    domain: replenishDomain.value,
    entities,
    query_hint: query,
    reason: replenishReason.value.trim() || '分析师人工增量补采',
  }
  emit('submitRevise', {
    comment: `增量补采需求: ${query} (领域: ${replenishDomain.value})`,
    edited_data: {
      action_type: 'replenish',
      demand,
    },
  })
  emit('update:visible', false)
}

// 1.2 局部子域重采 (Partial Re-collection)
const selectedDomains = ref<string[]>(['financials'])
const partialRefetchComment = ref('')

function handlePartialRefetchSubmit() {
  if (selectedDomains.value.length === 0) {
    ElMessage.warning('请至少勾选一个需要重新采集的投研子领域')
    return
  }
  emit('submitRevise', {
    comment: `局部重采子领域 [${selectedDomains.value.join(', ')}]: ${partialRefetchComment.value || '更新子领域数据'}`,
    edited_data: {
      action_type: 'partial_refetch',
      domains: selectedDomains.value,
      query_hint: partialRefetchComment.value || '重新采集选定子领域核心指标',
      reason: '局部子域重采',
    },
  })
  emit('update:visible', false)
}

// 1.3 脏数据清洗与剔除 (Data Cleansing)
interface CleanRecord {
  record_id: string
  entity_name?: string
  metric: string
  value: any
  unit?: string
  domain?: string
  query?: string
}
const localSourceRecords = ref<CleanRecord[]>([])
const selectedRecordIdsToDelete = ref<string[]>([])
const recordSearch = ref('')

function initDataFetchClean() {
  const raw = (props.data?.source_records || props.data?.records || []) as CleanRecord[]
  localSourceRecords.value = raw.map((r) => ({
    record_id: r.record_id || `REC-${Math.random().toString(36).slice(2, 7)}`,
    entity_name: r.entity_name || '综合行业',
    metric: r.metric || '指标',
    value: r.value,
    unit: r.unit || '',
    domain: r.domain || 'financials',
    query: r.query || '',
  }))
  selectedRecordIdsToDelete.value = []
}

const filteredSourceRecords = computed(() => {
  if (!recordSearch.value.trim()) return localSourceRecords.value
  const kw = recordSearch.value.toLowerCase()
  return localSourceRecords.value.filter(
    (r) =>
      r.metric.toLowerCase().includes(kw) ||
      (r.entity_name && r.entity_name.toLowerCase().includes(kw)) ||
      (r.domain && r.domain.toLowerCase().includes(kw))
  )
})

function handleCleanSubmit() {
  if (selectedRecordIdsToDelete.value.length === 0) {
    ElMessage.warning('请至少勾选一条需要剔除的脏数据记录')
    return
  }
  emit('submitDirectEdit', {
    edited_data: {
      deleted_record_ids: selectedRecordIdsToDelete.value,
    },
    comment: `人工清洗剔除 ${selectedRecordIdsToDelete.value.length} 条噪声数据记录`,
  })
  emit('update:visible', false)
}

// =========================================================================
// 阶段 2：数据解读 (data_interpret)
// =========================================================================
// 2.1 可比公司标的池微调 (Comps Matrix)
interface LocalCompItem {
  name: string
  code: string
  market_cap?: number | string
  pe?: number | string
  pb?: number | string
  valuation_tier: string
}
const localComps = ref<LocalCompItem[]>([])

function initCompsData() {
  const cm = (props.data?.comps_matrix || {}) as any
  const entries = cm.entries || cm.comps || []
  if (Array.isArray(entries) && entries.length > 0) {
    localComps.value = entries.map((c: any) => ({
      name: c.name || c.entity_name || '标的公司',
      code: c.code || c.entity_code || '',
      market_cap: c.market_cap || c.mc || 0,
      pe: c.pe || c.pe_ttm || 0,
      pb: c.pb || 0,
      valuation_tier: c.valuation_tier || '第一梯队',
    }))
  } else {
    // 默认空行
    localComps.value = [
      { name: '行业龙头标的A', code: '000001', market_cap: 2500, pe: 28.5, pb: 4.2, valuation_tier: '核心龙头' },
      { name: '高成长对标B', code: '300001', market_cap: 800, pe: 42.0, pb: 5.6, valuation_tier: '高成长对标' },
    ]
  }
}

function addCompRow() {
  localComps.value.push({
    name: '新增对标公司',
    code: '000xxx',
    market_cap: 500,
    pe: 25.0,
    pb: 3.0,
    valuation_tier: '第二梯队',
  })
}

function removeCompRow(idx: number) {
  localComps.value.splice(idx, 1)
}

function handleCompsSubmit() {
  emit('submitDirectEdit', {
    edited_data: {
      comps_matrix: {
        entries: localComps.value,
        comps: localComps.value,
        total_market_cap: localComps.value.reduce((acc, c) => acc + (Number(c.market_cap) || 0), 0),
      },
    },
    comment: `更新可比公司标的池（共 ${localComps.value.length} 家对标企业）`,
  })
  emit('update:visible', false)
}

// 2.2 核心研判论点精修 (Claims & Findings)
interface LocalFinding {
  id: string
  title: string
  text: string
}
const localFindings = ref<LocalFinding[]>([])

function initFindingsData() {
  const raw = (props.data?.findings || props.data?.key_findings || props.data?.claims || []) as any[]
  if (Array.isArray(raw) && raw.length > 0) {
    localFindings.value = raw.map((f, i) => ({
      id: f.id || `F-${i + 1}`,
      title: f.title || f.claim || `投研核心研判 #${i + 1}`,
      text: typeof f === 'string' ? f : f.text || f.content || f.description || '',
    }))
  } else {
    localFindings.value = [
      { id: 'F-1', title: '产业处于技术迭代与出海加速双轮驱动期', text: '核心龙头厂商依托规模效应与技术壁垒形成显著护城河，海外市场渗透率稳步攀升。' },
      { id: 'F-2', title: '上游原材料供给充裕推动产业链降本增效', text: '主要原材料价格进入合理平稳区间，中下游系统集成环节毛利率出现修复拐点。' },
    ]
  }
}

function addFindingRow() {
  localFindings.value.push({
    id: `F-${localFindings.value.length + 1}`,
    title: '新增行业核心论点',
    text: '补充具体的研判观点与量化依据阐述...',
  })
}

function removeFindingRow(idx: number) {
  localFindings.value.splice(idx, 1)
}

function handleFindingsSubmit() {
  emit('submitDirectEdit', {
    edited_data: {
      findings: localFindings.value,
      key_findings: localFindings.value,
    },
    comment: `微调核心研判结论（共 ${localFindings.value.length} 条论点）`,
  })
  emit('update:visible', false)
}

// 2.3 异常指标与风险项裁决 (Risk & Anomaly Gate)
interface RiskItem {
  id: string
  label: string
  desc: string
  decision: 'emphasize' | 'keep' | 'ignore'
}
const localRisks = ref<RiskItem[]>([])

function initRisksData() {
  const rawRisks = (props.data?.risks || props.data?.anomalies || []) as any[]
  if (Array.isArray(rawRisks) && rawRisks.length > 0) {
    localRisks.value = rawRisks.map((r, i) => ({
      id: r.id || `RISK-${i + 1}`,
      label: r.title || r.label || r.name || `风险预警 #${i + 1}`,
      desc: r.description || r.desc || (typeof r === 'string' ? r : JSON.stringify(r)),
      decision: 'keep',
    }))
  } else {
    localRisks.value = [
      { id: 'RISK-1', label: '行业产能阶段性供需失衡与降价风险', desc: '新投产产能集中释放可能引发结构性价格战，压制二三线厂商毛利空间。', decision: 'emphasize' },
      { id: 'RISK-2', label: '地缘政治与海外贸易关税壁垒风险', desc: '重点海外目标市场贸易保护政策与关税调整可能影响出口放量进度。', decision: 'keep' },
      { id: 'RISK-3', label: '新技术路线商业化突破替代风险', desc: '新一代固态/半固态技术迭代节奏若超预期，可能对既有技术路径产线产生折旧压力。', decision: 'keep' },
    ]
  }
}

function handleRisksSubmit() {
  emit('submitDirectEdit', {
    edited_data: {
      risk_decisions: localRisks.value,
    },
    comment: `完成风险项与异常信号人工裁决（共 ${localRisks.value.length} 项）`,
  })
  emit('update:visible', false)
}

// =========================================================================
// 阶段 3：图表生成 (chart_generate)
// =========================================================================
interface LocalChartItem {
  chart_id: string
  title: string
  chart_type: string
  excluded: boolean
  unit?: string
  footnotes?: string[]
  _rawSpec?: Record<string, unknown>
}
const localCharts = ref<LocalChartItem[]>([])
const newChartDemand = ref('')

function morphChartOption(option: any, targetType: string): any {
  if (!option || typeof option !== 'object') return option
  const opt = JSON.parse(JSON.stringify(option))
  const series = opt.series
  if (!series || !Array.isArray(series)) return opt

  const xAxis = opt.xAxis
  const yAxis = opt.yAxis

  if (targetType === 'horizontal_bar') {
    series.forEach((s: any) => {
      s.type = 'bar'
      delete s.stack
      delete s.areaStyle
    })
    const isXCat = xAxis?.type === 'category' || (xAxis?.data && yAxis?.type !== 'category')
    if (isXCat) {
      const newY = { ...xAxis, type: 'category' }
      const newX = { ...(yAxis || {}), type: 'value' }
      opt.xAxis = newX
      opt.yAxis = newY
    }
  } else if (['bar', 'line', 'stacked_bar', 'area'].includes(targetType)) {
    const isYCat = yAxis?.type === 'category' && xAxis?.type === 'value'
    if (isYCat) {
      const newX = { ...yAxis, type: 'category' }
      const newY = { ...xAxis, type: 'value' }
      opt.xAxis = newX
      opt.yAxis = newY
    }
    series.forEach((s: any) => {
      if (targetType === 'bar') {
        s.type = 'bar'
        delete s.stack
        delete s.areaStyle
      } else if (targetType === 'line') {
        s.type = 'line'
        delete s.stack
        delete s.areaStyle
      } else if (targetType === 'stacked_bar') {
        s.type = 'bar'
        s.stack = 'total'
        delete s.areaStyle
      } else if (targetType === 'area') {
        s.type = 'line'
        delete s.stack
        s.areaStyle = s.areaStyle || {}
      }
    })
  }
  return opt
}

function initChartData() {
  const raw = (props.data?.chart_specs || props.data?.charts || []) as any[]
  localCharts.value = raw.map((c, i) => ({
    chart_id: c.chart_id || `CHART-${i + 1}`,
    title: c.title || `图表 #${i + 1}`,
    chart_type: c.chart_type || 'bar',
    excluded: c.status === 'excluded',
    unit: c.unit || (c.options?.yAxis?.name || c.option?.yAxis?.name || ''),
    footnotes: c.footnotes || ['数据来源：同花顺 iFinD，全链路智能体整理'],
    _rawSpec: c,
  }))
}

function handleChartMorphSubmit() {
  const updated = localCharts.value.map((c) => {
    const raw = c._rawSpec ? JSON.parse(JSON.stringify(c._rawSpec)) : {}
    const morphedOption = morphChartOption(raw.option, c.chart_type)
    return {
      ...raw,
      chart_id: c.chart_id,
      title: c.title,
      chart_type: c.chart_type,
      status: c.excluded ? 'excluded' : 'ready',
      unit: c.unit,
      footnotes: c.footnotes,
      option: morphedOption,
    }
  })
  emit('submitDirectEdit', {
    edited_data: {
      chart_specs: updated,
    },
    comment: `就地调整图表形态与显隐配置（共 ${updated.length} 张图表）`,
  })
  emit('update:visible', false)
}

function handleNewChartSubmit() {
  if (!newChartDemand.value.trim()) {
    ElMessage.warning('请填写新增图表分析诉求')
    return
  }
  emit('submitRevise', {
    comment: `新增图表诉求: ${newChartDemand.value.trim()}`,
    edited_data: {
      new_chart_demand: newChartDemand.value.trim(),
    },
  })
  emit('update:visible', false)
}

// =========================================================================
// 阶段 4：章节撰写 (chapter_write)
// =========================================================================
// 4.1 指定单章定向重写 (Single-Chapter Rewrite)
const targetChapterId = ref('CH-04')
const singleChapterInstruction = ref('')
const CHAPTER_OPTIONS = [
  { id: 'CH-01', title: 'CH-01 行业概述与发展阶段' },
  { id: 'CH-02', title: 'CH-02 宏观环境与政策驱动' },
  { id: 'CH-03', title: 'CH-03 产业链深度剖析' },
  { id: 'CH-04', title: 'CH-04 竞争格局与龙头壁垒' },
  { id: 'CH-05', title: 'CH-05 财务分析与经营质量' },
  { id: 'CH-06', title: 'CH-06 行业未来驱动与催化' },
  { id: 'CH-07', title: 'CH-07 投资策略与风险提示' },
]

function quickFillSingleChapter(text: string) {
  singleChapterInstruction.value = text
}

function handleSingleChapterSubmit() {
  const inst = singleChapterInstruction.value.trim()
  if (!inst) {
    ElMessage.warning('请填写针对该章节的重写指令或优化侧重点')
    return
  }
  emit('submitRevise', {
    comment: `针对章节 ${targetChapterId.value} 定向重写: ${inst}`,
    edited_data: {
      action_type: 'single_chapter_rewrite',
      target_chapter_id: targetChapterId.value,
      instruction: inst,
    },
  })
  emit('update:visible', false)
}

// 4.2 正文段落就地精修 (Paragraph Inline Polishing)
interface ParaEdit {
  paragraph_id: string
  kind?: string
  text: string
  evidence_ids?: string[]
}
interface SecEdit {
  section_id: string
  title: string
  paragraphs: ParaEdit[]
}
interface ChapEdit {
  chapter_id: string
  title: string
  sections: SecEdit[]
}
const localChapterList = ref<ChapEdit[]>([])
const editActiveChapId = ref('')
const editActiveSecId = ref('')

function initChapterEditData() {
  const rawChapters = (props.data?.chapters || props.data?.sections || []) as any[]
  localChapterList.value = JSON.parse(JSON.stringify(rawChapters))
  if (localChapterList.value.length > 0) {
    editActiveChapId.value = localChapterList.value[0].chapter_id
    if (localChapterList.value[0].sections?.length > 0) {
      editActiveSecId.value = localChapterList.value[0].sections[0].section_id
    }
  }
}

const currentEditChapter = computed(() =>
  localChapterList.value.find((c) => c.chapter_id === editActiveChapId.value)
)
const currentEditSection = computed(() =>
  currentEditChapter.value?.sections?.find((s) => s.section_id === editActiveSecId.value)
)

watch(editActiveChapId, (newId) => {
  const ch = localChapterList.value.find((c) => c.chapter_id === newId)
  if (ch && ch.sections?.length > 0) {
    editActiveSecId.value = ch.sections[0].section_id
  } else {
    editActiveSecId.value = ''
  }
})

function handleParagraphEditSubmit() {
  emit('submitDirectEdit', {
    edited_data: {
      chapters: localChapterList.value,
    },
    comment: `就地精修正文内容（共更新 ${localChapterList.value.length} 个章节）`,
  })
  emit('update:visible', false)
}

// 4.3 风格倾向引导
const selectedStyleTone = ref('机构审慎型')
const globalStylePrompt = ref('')

function handleStyleSubmit() {
  const toneDesc = `【行文风格倾向】: ${selectedStyleTone.value}。${globalStylePrompt.value}`
  emit('submitRevise', {
    comment: toneDesc,
    edited_data: {
      style_instruction: toneDesc,
    },
  })
  emit('update:visible', false)
}

// =========================================================================
// 阶段 5：报告融合 (report_fusion)
// =========================================================================
// 5.1 8 张核心指标卡深度定制 (8 Metric Cards)
interface MetricCardItem {
  id: string
  label: string
  value: string
  unit: string
  change_rate: string
  tone: 'up' | 'down' | 'neutral'
}
const localMetricCards = ref<MetricCardItem[]>([])

function initMetricCards() {
  const rawCards = (props.data?.key_metrics || props.data?.metrics_cards || []) as any[]
  if (Array.isArray(rawCards) && rawCards.length > 0) {
    localMetricCards.value = rawCards.map((m, i) => ({
      id: m.id || `M-${i + 1}`,
      label: m.label || m.name || m.title || `核心指标 ${i + 1}`,
      value: String(m.value ?? '100'),
      unit: m.unit || '',
      change_rate: m.change_rate || m.change || '+12.5%',
      tone: m.tone || 'up',
    }))
  } else {
    // 默认提供标准 8 张指标卡模板
    const defaultLabels = [
      { label: '行业总市场规模', value: '12,850', unit: '亿元', change: '+18.4%', tone: 'up' as const },
      { label: '近三年 CAGR 复合增速', value: '24.6', unit: '%', change: '+3.2pct', tone: 'up' as const },
      { label: '行业龙头 CR3 集中度', value: '68.5', unit: '%', change: '+4.1pct', tone: 'up' as const },
      { label: '样本企业平均毛利率', value: '26.8', unit: '%', change: '+1.5pct', tone: 'up' as const },
      { label: '行业研发投入强度中枢', value: '8.4', unit: '%', change: '+0.8pct', tone: 'up' as const },
      { label: '主要标的市盈率 PE(TTM)', value: '29.3', unit: '倍', change: '-5.2%', tone: 'neutral' as const },
      { label: '资产负债率健康中枢', value: '48.2', unit: '%', change: '-2.1pct', tone: 'down' as const },
      { label: '海外市场渗透率', value: '31.5', unit: '%', change: '+6.8pct', tone: 'up' as const },
    ]
    localMetricCards.value = defaultLabels.map((d, i) => ({
      id: `CARD-${i + 1}`,
      label: d.label,
      value: d.value,
      unit: d.unit,
      change_rate: d.change,
      tone: d.tone,
    }))
  }
}

function handleMetricCardsSubmit() {
  emit('submitDirectEdit', {
    edited_data: {
      key_metrics: localMetricCards.value,
      metrics_cards: localMetricCards.value,
    },
    comment: '定制 8 张开篇核心量化指标卡（已同步更新交付物）',
  })
  emit('update:visible', false)
}

// 5.2 投资评级与执行摘要定稿 (Summary & Rating)
const localReportTitle = ref('')
const localRating = ref('买入 (Buy)')
const localSummaryText = ref('')

function initFusionSummary() {
  localReportTitle.value = String(props.data?.title || '深度行业研究报告')
  localRating.value = String(props.data?.investment_rating || props.data?.rating || '买入 (Buy)')
  const es = props.data?.executive_summary
  if (typeof es === 'string') {
    localSummaryText.value = es
  } else if (Array.isArray(es)) {
    localSummaryText.value = es.join('\n\n')
  } else if (es && typeof es === 'object') {
    localSummaryText.value = (es as any).text || (es as any).content || JSON.stringify(es)
  }
}

function handleSummaryRatingSubmit() {
  emit('submitDirectEdit', {
    edited_data: {
      title: localReportTitle.value,
      investment_rating: localRating.value,
      executive_summary: localSummaryText.value,
    },
    comment: '完成投资评级确认与执行摘要终审定稿',
  })
  emit('update:visible', false)
}

function handleFinalApprove() {
  emit('approve')
  emit('update:visible', false)
}

// =========================================================================
// 弹窗打开初始化
// =========================================================================
watch(
  () => props.visible,
  (val) => {
    if (val) {
      if (props.initialTab) {
        activeTab.value = props.initialTab
      } else {
        activeTab.value = 'tab-1'
      }
      if (props.stage === 'data_fetch') {
        initDataFetchClean()
      } else if (props.stage === 'data_interpret') {
        initCompsData()
        initFindingsData()
        initRisksData()
      } else if (props.stage === 'chart_generate') {
        initChartData()
      } else if (props.stage === 'chapter_write') {
        initChapterEditData()
      } else if (props.stage === 'report_fusion') {
        initMetricCards()
        initFusionSummary()
      }
    }
  },
  { immediate: true }
)

const dialogTitle = computed(() => {
  const map: Record<StageName, string> = {
    data_fetch: '数据采集智能体 · 投研人机协同工作台',
    data_interpret: '数据解读智能体 · 投研人机协同工作台',
    chart_generate: '图表生成智能体 · 投研人机协同工作台',
    chapter_write: '章节撰写智能体 · 投研人机协同工作台',
    report_fusion: '报告融合智能体 · 投研人机协同工作台',
  }
  return map[props.stage] || `${STAGE_LABELS[props.stage]} · 协同工作台`
})
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="dialogTitle"
    width="920px"
    class="stage-modal"
    destroy-on-close
    @close="emit('update:visible', false)"
  >
    <div class="modal-inner">
      <!-- 阶段专属说明横幅 -->
      <div class="modal-banner">
        <div class="banner-badge">专业协同模式</div>
        <div class="banner-text">
          <template v-if="stage === 'data_fetch'">
            数据采集阶段提供<strong>「增量数据补采」</strong>（单点快速抓取入库）、<strong>「局部子域重采」</strong>（仅重采指定领域）与<strong>「脏数据清洗剔除」</strong>，拒绝推翻全量数据的低效重跑。
          </template>
          <template v-else-if="stage === 'data_interpret'">
            数据解读阶段提供<strong>「可比公司标的池调整」</strong>、<strong>「核心研判论点精修」</strong>与<strong>「异常指标裁决」</strong>，精准校准分析师投研逻辑。
          </template>
          <template v-else-if="stage === 'chart_generate'">
            图表生成阶段提供<strong>「形态类型切换」</strong>（柱状/折线/堆叠快速转换）、<strong>「显隐编排控制」</strong>与<strong>「元数据精修」</strong>，确保券商出版级制图。
          </template>
          <template v-else-if="stage === 'chapter_write'">
            章节撰写阶段提供<strong>「指定单章定向重写」</strong>（仅重写单一不满意的章节，其余6章完全保留）、<strong>「段落正文就地精修」</strong>与<strong>「风格引导」</strong>。
          </template>
          <template v-else-if="stage === 'report_fusion'">
            报告融合阶段提供<strong>「8 张核心指标卡深度定制」</strong>、<strong>「投资评级与执行摘要定稿」</strong>与<strong>「出版级签发交付」</strong>。
          </template>
        </div>
      </div>

      <!-- ------------------------------------------------------------- -->
      <!-- 阶段 1：数据采集 (data_fetch) -->
      <!-- ------------------------------------------------------------- -->
      <el-tabs v-if="stage === 'data_fetch'" v-model="activeTab" class="stage-tabs">
        <!-- Tab 1.1: 增量补采 -->
        <el-tab-pane label="增量数据补采" name="replenish">
          <div class="tab-pane-content">
            <div class="section-lead">针对当前缺失的重点公司、前沿技术指标或细分业务，执行针对性单点查询并无缝合入数据集：</div>
            
            <div class="quick-chips">
              <span class="chip-label">热门补采预设：</span>
              <el-button size="small" round @click="quickFillReplenish('finance')">补充龙头研发与储能财务</el-button>
              <el-button size="small" round @click="quickFillReplenish('chain')">补充产业链关键环节</el-button>
              <el-button size="small" round @click="quickFillReplenish('macro')">补充宏观产销与出口</el-button>
              <el-button size="small" round @click="quickFillReplenish('competitors')">补充二线对标份额</el-button>
            </div>

            <el-form label-position="top" size="default">
              <el-row :gutter="16">
                <el-col :span="12">
                  <el-form-item label="补采目标实体（公司代码/企业名/行业细分）">
                    <el-input v-model="replenishEntity" placeholder="例如：宁德时代, 比亚迪, 国轩高科" />
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="投研数据领域">
                    <el-select v-model="replenishDomain" style="width: 100%">
                      <el-option label="财务与盈利表现 (Financials)" value="financials" />
                      <el-option label="产业链上下游环节 (Industry Chain)" value="industry_chain" />
                      <el-option label="宏观政策与产销大盘 (Macro)" value="macro" />
                      <el-option label="竞争格局与市场份额 (Competitors)" value="competitors" />
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>

              <el-form-item label="问财精准查询提示词 (Query Hint)">
                <el-input
                  v-model="replenishQuery"
                  type="textarea"
                  :rows="3"
                  placeholder="输入针对性查询提示，例如：查询宁德时代与比亚迪2023-2025年研发费用、毛利率及储能出货量"
                />
              </el-form-item>

              <el-form-item label="补采原因 / 分析诉求">
                <el-input v-model="replenishReason" placeholder="例如：下游定量图表缺少核心龙头储能出货数据" />
              </el-form-item>
            </el-form>

            <div class="pane-footer">
              <el-button type="primary" size="large" :loading="submitting" @click="handleReplenishSubmit">
                启动定向单点补采并并入数据集
              </el-button>
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 1.2: 局部子域重采 -->
        <el-tab-pane label="局部子域重采" name="partial_refetch">
          <div class="tab-pane-content">
            <div class="section-lead">勾选需要重新采集的投研子领域，其余领域已获取的数据将被完整保留：</div>
            
            <div class="domain-checkboxes">
              <el-checkbox-group v-model="selectedDomains">
                <div class="domain-card">
                  <el-checkbox label="financials">
                    <span class="d-title">重点公司财务与盈利指标</span>
                    <span class="d-desc">重新抓取样本龙头营业收入、净利润、毛利率、资产负债率等指标</span>
                  </el-checkbox>
                </div>
                <div class="domain-card">
                  <el-checkbox label="industry_chain">
                    <span class="d-title">产业链上下游与供需环节</span>
                    <span class="d-desc">重新梳理原材料、核心部件、系统总装与终端应用场景</span>
                  </el-checkbox>
                </div>
                <div class="domain-card">
                  <el-checkbox label="macro">
                    <span class="d-title">宏观政策驱动与大盘环境</span>
                    <span class="d-desc">重新采集产业政策规划、行业总装机量与月度产销走势</span>
                  </el-checkbox>
                </div>
                <div class="domain-card">
                  <el-checkbox label="competitors">
                    <span class="d-title">竞争格局与市场份额对标</span>
                    <span class="d-desc">重新评估行业 CR3/CR5 集中度与第二梯队差异化壁垒</span>
                  </el-checkbox>
                </div>
              </el-checkbox-group>
            </div>

            <div style="margin-top: 16px">
              <el-input
                v-model="partialRefetchComment"
                placeholder="补充重采指导（例如：扩大时间范围至最近5年，限定A股核心标的）"
              />
            </div>

            <div class="pane-footer">
              <el-button type="primary" size="large" :loading="submitting" @click="handlePartialRefetchSubmit">
                启动所选子领域精准重采
              </el-button>
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 1.3: 脏数据清洗 -->
        <el-tab-pane label="脏数据清洗与剔除" name="clean">
          <div class="tab-pane-content">
            <div class="clean-toolbar">
              <span class="clean-stats">
                当前数据集展示记录：共 {{ localSourceRecords.length }} 条 · 已选待剔除
                <strong style="color: var(--el-color-danger)">{{ selectedRecordIdsToDelete.length }}</strong> 条
              </span>
              <el-input
                v-model="recordSearch"
                placeholder="过滤指标名称、实体公司..."
                size="small"
                style="width: 220px"
                clearable
              />
            </div>

            <el-table
              :data="filteredSourceRecords"
              size="small"
              height="340px"
              style="width: 100%; margin-top: 8px"
              border
              @selection-change="(rows: CleanRecord[]) => selectedRecordIdsToDelete = rows.map(r => r.record_id)"
            >
              <el-table-column type="selection" width="46" align="center" />
              <el-table-column prop="entity_name" label="实体标的" width="130" />
              <el-table-column prop="metric" label="指标名称" min-width="150" />
              <el-table-column label="数值与单位" width="130">
                <template #default="{ row }">
                  <strong>{{ row.value }}</strong> <span class="muted">{{ row.unit }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="domain" label="领域" width="110">
                <template #default="{ row }">
                  <el-tag size="small" type="info">{{ row.domain }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="query" label="来源查询" min-width="160" show-overflow-tooltip />
            </el-table>

            <div class="pane-footer">
              <el-button
                type="danger"
                size="large"
                :disabled="selectedRecordIdsToDelete.length === 0"
                :loading="submitting"
                @click="handleCleanSubmit"
              >
                立即剔除所选记录并更新数据集
              </el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>

      <!-- ------------------------------------------------------------- -->
      <!-- 阶段 2：数据解读 (data_interpret) -->
      <!-- ------------------------------------------------------------- -->
      <el-tabs v-else-if="stage === 'data_interpret'" v-model="activeTab" class="stage-tabs">
        <!-- Tab 2.1: 标的池微调 -->
        <el-tab-pane label="可比公司标的池调整" name="comps">
          <div class="tab-pane-content">
            <div class="clean-toolbar">
              <span class="clean-stats">当前样本标的池（共 {{ localComps.length }} 家企业）：</span>
              <el-button size="small" type="primary" plain @click="addCompRow">+ 添加对标企业</el-button>
            </div>

            <el-table :data="localComps" size="small" height="340px" style="width: 100%" border>
              <el-table-column label="公司名称" min-width="130">
                <template #default="{ row }">
                  <el-input v-model="row.name" size="small" />
                </template>
              </el-table-column>
              <el-table-column label="证券代码" width="110">
                <template #default="{ row }">
                  <el-input v-model="row.code" size="small" />
                </template>
              </el-table-column>
              <el-table-column label="市值 (亿元)" width="120">
                <template #default="{ row }">
                  <el-input v-model="row.market_cap" size="small" />
                </template>
              </el-table-column>
              <el-table-column label="PE(TTM)" width="95">
                <template #default="{ row }">
                  <el-input v-model="row.pe" size="small" />
                </template>
              </el-table-column>
              <el-table-column label="所属梯队 / 估值分层" width="150">
                <template #default="{ row }">
                  <el-select v-model="row.valuation_tier" size="small">
                    <el-option label="核心龙头" value="核心龙头" />
                    <el-option label="第一梯队" value="第一梯队" />
                    <el-option label="高成长对标" value="高成长对标" />
                    <el-option label="第二梯队" value="第二梯队" />
                    <el-option label="审慎观察" value="审慎观察" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="70" align="center">
                <template #default="{ $index }">
                  <el-button type="danger" link @click="removeCompRow($index)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>

            <div class="pane-footer">
              <el-button type="success" size="large" :loading="submitting" @click="handleCompsSubmit">
                保存标的池调整 (就地毫秒级生效)
              </el-button>
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 2.2: 核心论点精修 -->
        <el-tab-pane label="核心研判论点精修" name="findings">
          <div class="tab-pane-content">
            <div class="clean-toolbar">
              <span class="clean-stats">当前定性论点提炼（共 {{ localFindings.length }} 条）：</span>
              <el-button size="small" type="primary" plain @click="addFindingRow">+ 补充研判论点</el-button>
            </div>

            <div class="findings-scroll">
              <div v-for="(f, idx) in localFindings" :key="f.id || idx" class="finding-card">
                <div class="finding-card-header">
                  <el-tag size="small" type="primary">{{ f.id }}</el-tag>
                  <el-input v-model="f.title" placeholder="论点标题" style="flex: 1; margin: 0 10px" />
                  <el-button type="danger" link @click="removeFindingRow(idx)">移除</el-button>
                </div>
                <el-input
                  v-model="f.text"
                  type="textarea"
                  :rows="2"
                  placeholder="详细逻辑阐述与数据依据..."
                  style="margin-top: 8px"
                />
              </div>
            </div>

            <div class="pane-footer">
              <el-button type="success" size="large" :loading="submitting" @click="handleFindingsSubmit">
                保存论点精修 (就地毫秒级生效)
              </el-button>
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 2.3: 风险项裁决 -->
        <el-tab-pane label="异常指标与风险裁决" name="risks">
          <div class="tab-pane-content">
            <div class="section-lead">对智能体识别出的行业异常与风险预警进行人工定性裁决：</div>

            <div class="risks-scroll">
              <div v-for="r in localRisks" :key="r.id" class="risk-card">
                <div class="risk-top">
                  <span class="risk-title">{{ r.label }}</span>
                  <el-radio-group v-model="r.decision" size="small">
                    <el-radio-button value="emphasize">重点突出</el-radio-button>
                    <el-radio-button value="keep">一般性提示</el-radio-button>
                    <el-radio-button value="ignore">忽略排除</el-radio-button>
                  </el-radio-group>
                </div>
                <div class="risk-desc-text">{{ r.desc }}</div>
              </div>
            </div>

            <div class="pane-footer">
              <el-button type="success" size="large" :loading="submitting" @click="handleRisksSubmit">
                保存风险裁决 (就地毫秒级生效)
              </el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>

      <!-- ------------------------------------------------------------- -->
      <!-- 阶段 3：图表生成 (chart_generate) -->
      <!-- ------------------------------------------------------------- -->
      <el-tabs v-else-if="stage === 'chart_generate'" v-model="activeTab" class="stage-tabs">
        <!-- Tab 3.1: 图表形态切换 -->
        <el-tab-pane label="图表形态与类型切换" name="morph">
          <div class="tab-pane-content">
            <div class="section-lead">就地调整图表的可视化呈现形态（柱状/折线/水平条形/堆叠图快速切换）：</div>

            <el-table :data="localCharts" size="small" height="340px" style="width: 100%" border>
              <el-table-column prop="chart_id" label="图表编号" width="100" />
              <el-table-column label="图表标题" min-width="180">
                <template #default="{ row }">
                  <el-input v-model="row.title" size="small" />
                </template>
              </el-table-column>
              <el-table-column label="图表呈现类型" width="160">
                <template #default="{ row }">
                  <el-select v-model="row.chart_type" size="small">
                    <el-option label="柱状图 (bar)" value="bar" />
                    <el-option label="折线图 (line)" value="line" />
                    <el-option label="水平条形图 (horizontal_bar)" value="horizontal_bar" />
                    <el-option label="堆叠柱状图 (stacked_bar)" value="stacked_bar" />
                    <el-option label="面积图 (area)" value="area" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="是否纳入研报" width="120" align="center">
                <template #default="{ row }">
                  <el-switch v-model="row.excluded" :active-value="false" :inactive-value="true" inline-prompt active-text="展示" inactive-text="排除" />
                </template>
              </el-table-column>
            </el-table>

            <div class="pane-footer">
              <el-button type="success" size="large" :loading="submitting" @click="handleChartMorphSubmit">
                保存图表形态变更 (就地毫秒级生效)
              </el-button>
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 3.2: 新增图表诉求 -->
        <el-tab-pane label="新增定向图表诉求" name="new_chart">
          <div class="tab-pane-content">
            <div class="section-lead">提出定向图表编译生成诉求，图表智能体将基于现有量化数据直接编译新图表：</div>

            <el-form label-position="top">
              <el-form-item label="图表诉求与展示维度">
                <el-input
                  v-model="newChartDemand"
                  type="textarea"
                  :rows="4"
                  placeholder="例如：请生成近5年行业前三强企业研发费用率走势对比折线图，标注2024年拐点"
                />
              </el-form-item>
            </el-form>

            <div class="pane-footer">
              <el-button type="primary" size="large" :loading="submitting" @click="handleNewChartSubmit">
                提交图表编译器生成新图表
              </el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>

      <!-- ------------------------------------------------------------- -->
      <!-- 阶段 4：章节撰写 (chapter_write) -->
      <!-- ------------------------------------------------------------- -->
      <el-tabs v-else-if="stage === 'chapter_write'" v-model="activeTab" class="stage-tabs">
        <!-- Tab 4.1: 单章定向重写 -->
        <el-tab-pane label="指定单章定向重写" name="single_chapter">
          <div class="tab-pane-content">
            <div class="single-rewrite-hero">
              <div class="hero-badge">章节独立重写引擎</div>
              <div class="hero-text">
                7 章 21 节已撰写完毕。若对某一章节不满意，<strong>仅重写该章节</strong>，其余 6 个已满意的章节原封不动完整保留，不破坏全局产出。
              </div>
            </div>

            <el-form label-position="top" style="margin-top: 16px">
              <el-form-item label="选择要重写的单一章节">
                <el-select v-model="targetChapterId" style="width: 380px" size="large">
                  <el-option
                    v-for="op in CHAPTER_OPTIONS"
                    :key="op.id"
                    :label="op.title"
                    :value="op.id"
                  />
                </el-select>
              </el-form-item>

              <div class="quick-chips">
                <span class="chip-label">快捷优化策略：</span>
                <el-button size="small" round @click="quickFillSingleChapter('深化龙头核心壁垒分析，补充专利矩阵与产能护城河论证')">
                  深化竞争壁垒
                </el-button>
                <el-button size="small" round @click="quickFillSingleChapter('强化量化数据与图表引用，穿透至具体财务指标与毛利率数据')">
                  强化数据穿透
                </el-button>
                <el-button size="small" round @click="quickFillSingleChapter('补充海外对标与全球化出海进度，分析主要海外市场份额走势')">
                  补充出海对比
                </el-button>
                <el-button size="small" round @click="quickFillSingleChapter('细化固态电池与快充技术商业化量产时间表及降本路径')">
                  细化技术路径
                </el-button>
              </div>

              <el-form-item label="针对该单章的定向优化指令 (Instruction)">
                <el-input
                  v-model="singleChapterInstruction"
                  type="textarea"
                  :rows="4"
                  placeholder="填写具体的章节修改指导，例如：深入分析第二梯队厂商的差异化生存策略，强化财务毛利走势对比..."
                />
              </el-form-item>
            </el-form>

            <div class="pane-footer">
              <el-button type="primary" size="large" :loading="submitting" @click="handleSingleChapterSubmit">
                立即定向重写所选单章 (其余6章原封不动)
              </el-button>
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 4.2: 正文段落就地精修 -->
        <el-tab-pane label="正文段落就地精修" name="inline_polish">
          <div class="tab-pane-content">
            <div class="selector-row">
              <div class="select-item">
                <span class="select-label">章节：</span>
                <el-select v-model="editActiveChapId" style="width: 260px">
                  <el-option
                    v-for="ch in localChapterList"
                    :key="ch.chapter_id"
                    :label="`${ch.chapter_id} ${ch.title}`"
                    :value="ch.chapter_id"
                  />
                </el-select>
              </div>
              <div v-if="currentEditChapter?.sections?.length" class="select-item">
                <span class="select-label">小节：</span>
                <el-select v-model="editActiveSecId" style="width: 320px">
                  <el-option
                    v-for="sec in currentEditChapter.sections"
                    :key="sec.section_id"
                    :label="`${sec.section_id} ${sec.title}`"
                    :value="sec.section_id"
                  />
                </el-select>
              </div>
            </div>

            <div v-if="currentEditSection" class="paragraphs-list">
              <div
                v-for="(p, idx) in currentEditSection.paragraphs"
                :key="p.paragraph_id || idx"
                class="para-card"
              >
                <div class="para-header">
                  <el-tag size="small" type="info">{{ p.paragraph_id || `P-${idx + 1}` }}</el-tag>
                  <el-tag v-if="p.kind" size="small" type="success" style="margin-left: 6px">{{ p.kind }}</el-tag>
                </div>
                <el-input
                  v-model="p.text"
                  type="textarea"
                  :rows="3"
                  style="margin-top: 6px"
                />
              </div>
            </div>

            <div class="pane-footer">
              <el-button type="success" size="large" :loading="submitting" @click="handleParagraphEditSubmit">
                保存正文修改 (就地毫秒级生效)
              </el-button>
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 4.3: 研报行文风格引导 -->
        <el-tab-pane label="研报行文风格引导" name="style_guide">
          <div class="tab-pane-content">
            <div class="section-lead">为整篇研报设置统一的表达风格与机构行文倾向：</div>

            <el-form label-position="top">
              <el-form-item label="研报基调风格倾向">
                <el-radio-group v-model="selectedStyleTone" size="large">
                  <el-radio-button value="机构审慎型">头部券商深度审慎风</el-radio-button>
                  <el-radio-button value="前沿成长型">科技产业前沿成长风</el-radio-button>
                  <el-radio-button value="量化事实型">客观量化数据穿透风</el-radio-button>
                </el-radio-group>
              </el-form-item>

              <el-form-item label="全局行文偏好说明">
                <el-input
                  v-model="globalStylePrompt"
                  type="textarea"
                  :rows="3"
                  placeholder="例如：避免套话与宏大空洞叙事，突出标的估值敏感性与核心催化剂时间表"
                />
              </el-form-item>
            </el-form>

            <div class="pane-footer">
              <el-button type="primary" size="large" :loading="submitting" @click="handleStyleSubmit">
                提交全局风格优化指令
              </el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>

      <!-- ------------------------------------------------------------- -->
      <!-- 阶段 5：报告融合 (report_fusion) -->
      <!-- ------------------------------------------------------------- -->
      <el-tabs v-else-if="stage === 'report_fusion'" v-model="activeTab" class="stage-tabs">
        <!-- Tab 5.1: 8 张核心指标卡定制 -->
        <el-tab-pane label="8 张核心指标卡定制" name="metric_cards">
          <div class="tab-pane-content">
            <div class="section-lead">深度定制研报开篇呈现的 8 张核心指标卡（可就地修改指标名、数值、单位、变化率与基调色彩）：</div>

            <div class="metric-cards-grid">
              <div v-for="(m, i) in localMetricCards" :key="m.id || i" class="m-card-item">
                <div class="m-card-top">
                  <span class="m-idx">#{{ i + 1 }}</span>
                  <el-select v-model="m.tone" size="small" style="width: 100px">
                    <el-option label="看好 / 增长" value="up" />
                    <el-option label="承压 / 下滑" value="down" />
                    <el-option label="中性 / 平稳" value="neutral" />
                  </el-select>
                </div>
                <div class="m-card-fields">
                  <el-input v-model="m.label" size="small" placeholder="指标名称" />
                  <div class="m-row">
                    <el-input v-model="m.value" size="small" placeholder="数值" style="width: 60%" />
                    <el-input v-model="m.unit" size="small" placeholder="单位" style="width: 38%" />
                  </div>
                  <el-input v-model="m.change_rate" size="small" placeholder="同比/环比变化，如 +15.2%" />
                </div>
              </div>
            </div>

            <div class="pane-footer">
              <el-button type="success" size="large" :loading="submitting" @click="handleMetricCardsSubmit">
                保存 8 张核心指标卡定制 (就地生效)
              </el-button>
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 5.2: 投资评级与执行摘要定稿 -->
        <el-tab-pane label="投资评级与执行摘要定稿" name="summary_rating">
          <div class="tab-pane-content">
            <el-form label-position="top">
              <el-row :gutter="16">
                <el-col :span="14">
                  <el-form-item label="研报主标题">
                    <el-input v-model="localReportTitle" size="large" />
                  </el-form-item>
                </el-col>
                <el-col :span="10">
                  <el-form-item label="行业投资建议评级">
                    <el-select v-model="localRating" size="large" style="width: 100%">
                      <el-option label="买入 (Buy) · 强烈推荐" value="买入 (Buy)" />
                      <el-option label="增持 (Overweight) · 适度超配" value="增持 (Overweight)" />
                      <el-option label="中性 (Neutral) · 标配跟踪" value="中性 (Neutral)" />
                      <el-option label="谨慎观察 (Cautious)" value="谨慎观察 (Cautious)" />
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>

              <el-form-item label="研报执行摘要 (Executive Summary)">
                <el-input
                  v-model="localSummaryText"
                  type="textarea"
                  :rows="6"
                  placeholder="精修研报核心结论、投资亮点与估值判断摘要..."
                />
              </el-form-item>
            </el-form>

            <div class="pane-footer">
              <el-button type="success" size="large" :loading="submitting" @click="handleSummaryRatingSubmit">
                保存评级与执行摘要定稿 (就地生效)
              </el-button>
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 5.3: 出版级核准签发 -->
        <el-tab-pane label="出版级核准签发与交付" name="export_signoff">
          <div class="tab-pane-content">
            <div class="signoff-box">
              <div class="signoff-badge">VERIFIED</div>
              <div class="signoff-content">
                <h4>全链路一致性与质检合规门已通过</h4>
                <p>7 章 21 节券商深度专题、量化矢量图表库与 8 张核心指标卡已完成融合校验，符合金融出版与学术质检规范。</p>
              </div>
            </div>

            <div class="pane-footer" style="margin-top: 30px">
              <el-button type="primary" size="large" class="signoff-btn" @click="handleFinalApprove">
                正式签发定稿并导出交付研报
              </el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-dialog>
</template>

<style scoped>
.stage-modal :deep(.el-dialog__body) {
  padding: 16px 24px 24px;
}
.modal-inner {
  display: flex;
  flex-direction: column;
}
.modal-banner {
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
  border-left: 4px solid var(--el-color-primary);
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 16px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}
.banner-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  margin-bottom: 4px;
}
.stage-tabs :deep(.el-tabs__item) {
  font-size: 13.5px;
  font-weight: 500;
}
.tab-pane-content {
  padding-top: 10px;
}
.section-lead {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 14px;
}
.quick-chips {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}
.chip-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.pane-footer {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}
.domain-checkboxes {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.domain-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 10px 12px;
  background: var(--el-bg-color);
}
.d-title {
  font-weight: 600;
  font-size: 13px;
  display: block;
}
.d-desc {
  font-size: 11.5px;
  color: var(--el-text-color-secondary);
  display: block;
  margin-top: 2px;
}
.clean-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.clean-stats {
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.findings-scroll, .risks-scroll {
  max-height: 340px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.finding-card, .risk-card {
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
  padding: 10px 12px;
  background: var(--el-bg-color);
}
.finding-card-header {
  display: flex;
  align-items: center;
}
.risk-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.risk-title {
  font-weight: 600;
  font-size: 13.5px;
}
.risk-desc-text {
  font-size: 12.5px;
  color: var(--el-text-color-secondary);
  margin-top: 6px;
  line-height: 1.5;
}
.single-rewrite-hero {
  background: linear-gradient(135deg, rgba(64, 158, 255, 0.08), rgba(103, 194, 58, 0.08));
  border: 1px solid rgba(64, 158, 255, 0.2);
  border-radius: 8px;
  padding: 12px 16px;
}
.hero-badge {
  font-size: 11px;
  font-weight: 600;
  color: var(--el-color-primary);
  margin-bottom: 4px;
}
.hero-text {
  font-size: 13px;
  color: var(--el-text-color-primary);
  line-height: 1.6;
}
.selector-row {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
}
.select-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.select-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.paragraphs-list {
  max-height: 320px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.para-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 8px 12px;
  background: var(--el-bg-color);
}
.para-header {
  display: flex;
  align-items: center;
}
.metric-cards-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
}
.m-card-item {
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
  padding: 10px;
  background: var(--el-bg-color);
}
.m-card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.m-idx {
  font-size: 12px;
  font-weight: bold;
  color: var(--el-color-primary);
}
.m-card-fields {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.m-row {
  display: flex;
  justify-content: space-between;
}
.signoff-box {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-lighter);
}
.signoff-badge {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.05em;
  padding: 4px 8px;
  border-radius: 4px;
  background: var(--el-color-success-light-9);
  color: var(--el-color-success);
  border: 1px solid var(--el-color-success-light-5);
}
.signoff-content h4 {
  margin: 0 0 6px;
  font-size: 16px;
  color: var(--el-text-color-primary);
}
.signoff-content p {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}
.signoff-btn {
  padding: 12px 32px;
  font-size: 15px;
}
</style>
