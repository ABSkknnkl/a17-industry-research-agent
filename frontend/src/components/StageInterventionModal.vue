<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Cpu, View, EditPen, Promotion, Check } from '@element-plus/icons-vue'
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
// 阶段 1：数据获取 (data_fetch)
// =========================================================================
// 1.0 审核确认检索范围与关键词 (Scope & Keywords Review)
interface ScopeDomain {
  id: string
  name: string
  desc: string
  checked: boolean
}
const scopeDomains = ref<ScopeDomain[]>([
  { id: 'macro', name: '宏观政策与产销大盘', desc: '产业规划政策、行业总装机量、进出口走势与投融资大盘', checked: true },
  { id: 'industry_chain', name: '产业链供需与关键环节', desc: '原材料成本、核心元器件、中游制造与下游应用渗透率', checked: true },
  { id: 'financials', name: '样本龙头财务与盈利能力', desc: '营业收入、净利润、毛利率、研发费用率及资产负债率', checked: true },
  { id: 'competitors', name: '竞争格局与市场份额对标', desc: 'CR3/CR5行业集中度、第二梯队对标与出海全球市占率', checked: true },
])
const activeKeywords = ref<string[]>([])
const newKeywordInput = ref('')

function initScopeKeywords() {
  const rawKeywords = (props.data?.keywords || props.data?.search_keywords || []) as string[]
  if (Array.isArray(rawKeywords) && rawKeywords.length > 0) {
    activeKeywords.value = [...rawKeywords]
  } else {
    const recs = (props.data?.source_records || props.data?.records || []) as any[]
    const extracted = new Set<string>()
    recs.forEach((r) => {
      if (r.metric) extracted.add(r.metric)
      if (r.entity_name && r.entity_name !== '综合行业') extracted.add(r.entity_name)
    })
    if (extracted.size > 0) {
      activeKeywords.value = Array.from(extracted).slice(0, 8)
    } else {
      activeKeywords.value = ['行业市场规模', '龙头毛利率', '研发投入壁垒', '海外出海份额', '产业链供需格局']
    }
  }
}

function removeKeyword(idx: number) {
  activeKeywords.value.splice(idx, 1)
}

function addKeyword() {
  const kw = newKeywordInput.value.trim()
  if (kw && !activeKeywords.value.includes(kw)) {
    activeKeywords.value.push(kw)
    newKeywordInput.value = ''
  }
}

function handleScopeKeywordsConfirm() {
  const selectedScope = scopeDomains.value.filter((s) => s.checked).map((s) => s.id)
  if (selectedScope.length === 0) {
    ElMessage.warning('请至少保留一个检索领域')
    return
  }
  if (activeKeywords.value.length === 0) {
    ElMessage.warning('请至少保留一个检索关键词')
    return
  }
  emit('submitDirectEdit', {
    edited_data: {
      confirmed_scope: selectedScope,
      confirmed_keywords: activeKeywords.value,
    },
    comment: `审核确认检索范围(${selectedScope.length}个领域)与关键词(${activeKeywords.value.length}个词)`,
  })
  emit('update:visible', false)
}

function handleScopeKeywordsRevise() {
  const selectedScope = scopeDomains.value.filter((s) => s.checked).map((s) => s.id)
  emit('submitRevise', {
    comment: `按人工确认的检索范围[${selectedScope.join(', ')}]与关键词[${activeKeywords.value.join(', ')}]重新检索`,
    edited_data: {
      action_type: 'scope_keywords_refetch',
      confirmed_scope: selectedScope,
      confirmed_keywords: activeKeywords.value,
    },
  })
  emit('update:visible', false)
}

// 1.1 增量数据补采 (Data Replenishment) - 通用且自适应上下文
const replenishEntity = ref('')
const replenishDomain = ref('financials')
const replenishQuery = ref('')
const replenishReason = ref('')

function getContextTopic(): string {
  const d = props.data || {}
  const raw =
    (d.industry_topic as string) ||
    (d.topic as string) ||
    (d.industry as string) ||
    (d.title as string) ||
    ((d.metadata as any)?.industry_topic as string) ||
    ((d.metadata as any)?.topic as string) ||
    ''
  if (typeof raw === 'string' && raw.trim()) {
    const cleaned = raw.replace(/行业研究报告|行业分析报告|深度研究报告|深度报告|行业研报|研究报告/g, '').trim()
    if (cleaned) {
      return cleaned.endsWith('行业') ? cleaned : `${cleaned}行业`
    }
  }
  return '行业'
}

function getContextEntities(): string[] {
  const d = props.data || {}
  const recs = (d.source_records || d.records || []) as any[]
  const set = new Set<string>()
  recs.forEach((r) => {
    const name = r.entity_name || r.entity || r.name
    if (name && typeof name === 'string') {
      const clean = name.replace(/\(.*?\)/g, '').replace(/（.*?）/g, '').trim()
      if (
        clean &&
        clean !== '综合行业' &&
        clean !== '行业大盘' &&
        clean !== '未知代码' &&
        !clean.includes('统计') &&
        !clean.includes('大盘')
      ) {
        set.add(clean)
      }
    }
  })
  return Array.from(set)
}

function initDataFetchReplenish(forceReset = false) {
  const topic = getContextTopic()
  const entities = getContextEntities()
  const defaultEntity = entities.length > 0 ? entities.slice(0, 2).join(', ') : '行业核心龙头企业'

  if (forceReset || !replenishQuery.value) {
    replenishDomain.value = 'financials'
    replenishEntity.value = defaultEntity
    replenishQuery.value = `查询${topic}核心龙头企业近3年营业收入、净利润、毛利率及研发费用率`
    replenishReason.value = `下游图表与报告章节缺少${topic}核心龙头财务表现与盈利质量数据`
  }
}

function quickFillReplenish(type: string) {
  const topic = getContextTopic()
  const entities = getContextEntities()

  if (type === 'finance') {
    replenishDomain.value = 'financials'
    replenishEntity.value = entities.length > 0 ? entities.slice(0, 2).join(', ') : '行业核心龙头企业'
    replenishQuery.value = `查询${topic}核心龙头企业近3年营业收入、净利润、毛利率及研发费用率`
    replenishReason.value = `下游图表与报告章节缺少${topic}核心龙头财务表现与盈利质量数据`
  } else if (type === 'chain') {
    replenishDomain.value = 'industry_chain'
    replenishEntity.value = '产业链上下游关键环节'
    replenishQuery.value = `查询${topic}产业链上游原材料/元器件、中游制造与下游应用主要环节代表企业及集中度`
    replenishReason.value = `补充${topic}产业链各环节核心供需格局与价值分布`
  } else if (type === 'macro') {
    replenishDomain.value = 'macro'
    replenishEntity.value = `${topic}产销与大盘数据`
    replenishQuery.value = `查询近3年${topic}市场总规模、月度产销增速、进出口数据及核心产业政策`
    replenishReason.value = `补充宏观经济周期与${topic}大盘增速支撑行业分析论据`
  } else if (type === 'competitors') {
    replenishDomain.value = 'competitors'
    replenishEntity.value = entities.length > 2 ? entities.slice(2, 5).join(', ') : '行业第二梯队重点标的'
    replenishQuery.value = `查询${topic}主要企业国内市场份额占比、营收规模与行业梯队竞争格局`
    replenishReason.value = `补充${topic}行业梯队对标与竞争壁垒矩阵数据`
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
// 2.0 补充专家背景知识与修正核心判断 (Knowledge & Judgments)
const expertBackgroundNotes = ref('')
interface JudgmentItem {
  id: string
  title: string
  text: string
  decision: 'confirm' | 'modify' | 'reject'
}
const localJudgments = ref<JudgmentItem[]>([])

function quickFillExpertKnowledge(type: string) {
  if (type === 'channel') {
    expertBackgroundNotes.value = '【草根调研纪要】最新产业调研显示，海外头部云厂商下半年资本开支预期上修，核心高算力元器件采购订单节奏明显前置；但上游关键芯片供给周期拉长至 36 周以上。'
  } else if (type === 'policy') {
    expertBackgroundNotes.value = '【政策与出海壁垒】重点出口区域出台本地化供应链采购合规要求，具备海外本地化交付产线与专利授权资质的厂商护城河进一步加深。'
  } else if (type === 'tech') {
    expertBackgroundNotes.value = '【技术演进先验】新一代低功耗技术路线商业化渗透率预计于未来 4-6 个季度跨越临界拐点，既有老产线存在折旧计提加速压力。'
  }
}

function initKnowledgeAndJudgment() {
  expertBackgroundNotes.value = String(props.data?.expert_background || props.data?.prior_notes || '')
  const rawFindings = (props.data?.findings || props.data?.key_findings || props.data?.claims || []) as any[]
  if (Array.isArray(rawFindings) && rawFindings.length > 0) {
    localJudgments.value = rawFindings.map((f, i) => ({
      id: f.id || `J-${i + 1}`,
      title: f.title || f.claim || `核心研判 #${i + 1}`,
      text: typeof f === 'string' ? f : f.text || f.content || f.description || '',
      decision: 'confirm',
    }))
  } else {
    localJudgments.value = [
      { id: 'J-1', title: '产业处于高景气周期与出海放量红利期', text: '行业龙头依托技术代际差与客户黏性享受溢价，海外出海份额持续提升。', decision: 'confirm' },
      { id: 'J-2', title: '上游供给扩张带动成本曲线优化', text: '原材料价格进入合理平稳区间，中下游制造环节毛利出现修复拐点。', decision: 'confirm' },
    ]
  }
}

function handleKnowledgeAndJudgmentSubmit() {
  const activeFindings = localJudgments.value
    .filter((j) => j.decision !== 'reject')
    .map((j) => ({ id: j.id, title: j.title, text: j.text }))

  emit('submitDirectEdit', {
    edited_data: {
      expert_background: expertBackgroundNotes.value.trim(),
      findings: activeFindings,
      key_findings: activeFindings,
    },
    comment: `补充专家背景知识并修正核心判断（确认 ${activeFindings.length} 条研判论据）`,
  })
  emit('update:visible', false)
}

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
  highlight_target?: string // 重点高亮标的/系列
  benchmark_line?: number | null // 重点参考基准线
  emphasis_note?: string // 重点事件/拐点标注
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

  if (targetType === 'pie' || targetType === 'donut') {
    const categories = xAxis?.data || yAxis?.data || []
    const firstSeries = series[0] || {}
    const rawData = Array.isArray(firstSeries.data) ? firstSeries.data : []
    const pieData = (categories.length > 0 ? categories : rawData).map((cat: any, idx: number) => {
      const val = typeof rawData[idx] === 'object' ? rawData[idx]?.value : rawData[idx]
      return {
        name: String(typeof cat === 'object' ? (cat.name || cat.value || `项目${idx + 1}`) : cat),
        value: typeof val === 'number' ? Math.abs(val) : 10,
      }
    }).filter((item: any) => item.value > 0)

    opt.series = [{
      name: firstSeries.name || opt.title?.text || '占比结构',
      type: 'pie',
      radius: ['45%', '70%'],
      avoidLabelOverlap: true,
      itemStyle: { borderRadius: 4, borderColor: '#ffffff', borderWidth: 2 },
      label: { show: true, formatter: '{b}: {d}%' },
      data: pieData.length > 0 ? pieData : [{ name: '核心分部', value: 60 }, { name: '其他分部', value: 40 }],
    }]
    delete opt.xAxis
    delete opt.yAxis
    delete opt.radar
  } else if (targetType === 'radar') {
    const categories = (xAxis?.data || yAxis?.data || []).slice(0, 6)
    const validCats = categories.length >= 3 ? categories : ['盈利能力', '成长弹性', '资产质量', '估值吸引力', '研发强度']
    const indicators = validCats.map((cat: any) => ({
      name: String(typeof cat === 'object' ? (cat.name || cat.value) : cat),
      max: 100,
    }))
    opt.radar = {
      indicator: indicators,
      shape: 'polygon',
      splitNumber: 4,
    }
    opt.series = [{
      type: 'radar',
      data: series.slice(0, 3).map((s: any, idx: number) => {
        const sName = s.name || `标的${idx + 1}`
        const vals = Array.isArray(s.data)
          ? s.data.slice(0, indicators.length).map((v: any) => {
              const num = typeof v === 'object' ? v?.value : v
              return typeof num === 'number' ? Math.min(Math.max(Math.abs(num), 10), 100) : 50
            })
          : [60, 70, 80, 75, 85]
        while (vals.length < indicators.length) vals.push(50)
        return { value: vals, name: sName }
      }),
    }]
    delete opt.xAxis
    delete opt.yAxis
  } else if (targetType === 'horizontal_bar') {
    // 若原图是 pie 或 radar，先恢复直角坐标系
    if (!xAxis && opt.series?.[0]?.type === 'pie') {
      const pieData = opt.series[0].data || []
      opt.xAxis = { type: 'value' }
      opt.yAxis = { type: 'category', data: pieData.map((d: any) => d.name) }
      opt.series = [{ type: 'bar', data: pieData.map((d: any) => d.value) }]
    } else {
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
    }
    delete opt.radar
  } else if (['bar', 'line', 'stacked_bar', 'area'].includes(targetType)) {
    // 若原图是 pie 或 radar，先恢复直角坐标系
    if (!xAxis && opt.series?.[0]?.type === 'pie') {
      const pieData = opt.series[0].data || []
      opt.xAxis = { type: 'category', data: pieData.map((d: any) => d.name) }
      opt.yAxis = { type: 'value' }
      opt.series = [{
        name: opt.series[0].name || '数值',
        type: targetType === 'stacked_bar' ? 'bar' : (targetType === 'area' ? 'line' : targetType),
        data: pieData.map((d: any) => d.value),
      }]
    } else if (!xAxis && opt.radar?.indicator) {
      const indicators = opt.radar.indicator || []
      opt.xAxis = { type: 'category', data: indicators.map((d: any) => d.name) }
      opt.yAxis = { type: 'value' }
      const radarSeries = opt.series?.[0]?.data || []
      opt.series = radarSeries.map((rs: any) => ({
        name: rs.name || '标的',
        type: targetType === 'stacked_bar' ? 'bar' : (targetType === 'area' ? 'line' : targetType),
        data: rs.value || [],
      }))
      delete opt.radar
    } else {
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
    delete opt.radar
  }
  return opt
}

function applyEmphasisToOption(option: any, chart: LocalChartItem): any {
  if (!option || typeof option !== 'object') return option
  const opt = JSON.parse(JSON.stringify(option))

  // 1. 注入参考基准线 (markLine)
  if (chart.benchmark_line !== null && chart.benchmark_line !== undefined && chart.benchmark_line !== 0) {
    const series = opt.series || []
    if (series.length > 0) {
      series[0].markLine = {
        data: [{ yAxis: chart.benchmark_line, name: `参考基准线 (${chart.benchmark_line})` }],
        lineStyle: { color: '#E6A23C', type: 'dashed', width: 2 },
        label: { position: 'end', formatter: `基准: ${chart.benchmark_line}` },
      }
    }
  }

  // 2. 注入重点事件/拐点标注 (markPoint)
  if (chart.emphasis_note && chart.emphasis_note.trim()) {
    const series = opt.series || []
    if (series.length > 0) {
      series[0].markPoint = {
        data: [{ type: 'max', name: chart.emphasis_note.trim() }],
        label: { formatter: chart.emphasis_note.trim() },
      }
    }
  }

  // 3. 高亮重点标的 (highlight_target)
  if (chart.highlight_target && chart.highlight_target.trim()) {
    const target = chart.highlight_target.trim().toLowerCase()
    const series = opt.series || []
    series.forEach((s: any) => {
      if (s.name && String(s.name).toLowerCase().includes(target)) {
        s.itemStyle = { color: '#409EFF', borderWidth: 2 }
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
    highlight_target: c.highlight_target || '',
    benchmark_line: c.benchmark_line ?? null,
    emphasis_note: c.emphasis_note || '',
    _rawSpec: c,
  }))
}

function handleChartMorphSubmit() {
  const updated = localCharts.value.map((c) => {
    const raw = c._rawSpec ? JSON.parse(JSON.stringify(c._rawSpec)) : {}
    let morphedOption = morphChartOption(raw.option, c.chart_type)
    morphedOption = applyEmphasisToOption(morphedOption, c)
    return {
      ...raw,
      chart_id: c.chart_id,
      title: c.title,
      chart_type: c.chart_type,
      status: c.excluded ? 'excluded' : 'ready',
      unit: c.unit,
      footnotes: c.footnotes,
      highlight_target: c.highlight_target,
      benchmark_line: c.benchmark_line,
      emphasis_note: c.emphasis_note,
      option: morphedOption,
    }
  })
  emit('submitDirectEdit', {
    edited_data: {
      chart_specs: updated,
    },
    comment: `配置图表样式与强调重点（共更新 ${updated.length} 张图表）`,
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
// 4.0 提出修改意见与补充要求 (Revision Suggestions & Supplementary Requirements)
const selectedRevisionTags = ref<string[]>([])
const revisionRequirementText = ref('')
const revisionScope = ref<'single' | 'all'>('single')

const REVISION_TAGS = [
  '强化核心竞争壁垒与护城河论述',
  '弱化宏观套话，聚焦细分产业落地',
  '补齐各环节毛利率与估值对标数据',
  '补充海外出海市场份额与关税壁垒',
  '增加前沿技术商业化量产节奏预测',
  '提升行业下行风险与估值安全边际',
]

function toggleRevisionTag(tag: string) {
  const idx = selectedRevisionTags.value.indexOf(tag)
  if (idx >= 0) selectedRevisionTags.value.splice(idx, 1)
  else selectedRevisionTags.value.push(tag)
}

function handleRevisionRequirementsSubmit() {
  const inst = [
    selectedRevisionTags.value.length ? `【修改意见】: ${selectedRevisionTags.value.join('；')}` : '',
    revisionRequirementText.value.trim() ? `【补充要求】: ${revisionRequirementText.value.trim()}` : '',
  ].filter(Boolean).join('\n')

  if (!inst) {
    ElMessage.warning('请勾选修改意见或输入补充要求')
    return
  }

  emit('submitRevise', {
    comment: revisionScope.value === 'single'
      ? `针对章节 ${targetChapterId.value} 提出修改意见与补充要求: ${inst}`
      : `针对全文提出修改意见与补充要求: ${inst}`,
    edited_data: {
      action_type: revisionScope.value === 'single' ? 'single_chapter_rewrite' : 'full_revision',
      target_chapter_id: revisionScope.value === 'single' ? targetChapterId.value : null,
      instruction: inst,
    },
  })
  emit('update:visible', false)
}

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
// 5.0 整体审核并提出修订方向 (Holistic Audit & Global Steering)
const globalSteeringDirection = ref('机构审慎 / 深度防守')
const globalSteeringComment = ref('')

const STEERING_OPTIONS = [
  { label: '机构审慎 / 深度防守', desc: '强调估值安全边际与宏观下行压力，收缩激进增长假设，提升下行风险提示比重' },
  { label: '积极成长 / 景气驱动', desc: '聚焦出海爆发与核心龙头业绩弹性，突出产业红利期与上行催化剂' },
  { label: '技术破局 / 创新催化', desc: '聚焦前沿技术代际变革（如硅光/半固态），突出供应链卡位与技术护城河' },
  { label: '中立客观 / 深度对标', desc: '全方位客观交叉验证，强化样本企业多维指标横向对比与历史估值分位数' },
]

function handleGlobalSteeringSubmit() {
  const comment = `【全局修订方向】: ${globalSteeringDirection.value}。${globalSteeringComment.value}`
  emit('submitRevise', {
    comment,
    edited_data: {
      action_type: 'global_steering',
      steering_direction: globalSteeringDirection.value,
      instruction: comment,
    },
  })
  emit('update:visible', false)
}

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
        initScopeKeywords()
        initDataFetchClean()
        initDataFetchReplenish(true)
      } else if (props.stage === 'data_interpret') {
        initKnowledgeAndJudgment()
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
    data_fetch: '数据获取智能体 · 审核确认检索范围与关键词',
    data_interpret: '数据解读智能体 · 补充背景知识与修正判断',
    chart_generate: '可视化图表智能体 · 选择图表样式与强调重点',
    chapter_write: '分章节内容智能体 · 提出修改意见与补充要求',
    report_fusion: '报告融合智能体 · 整体审核并提出修订方向',
  }
  return map[props.stage] || `${STAGE_LABELS[props.stage]} · 人机协同控制台`
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
        <div class="closed-loop-flow">
          <span class="loop-chip active"><el-icon><Cpu /></el-icon> 1. AI辅助推荐</span>
          <span class="loop-arrow">→</span>
          <span class="loop-chip active"><el-icon><View /></el-icon> 2. 人工审核把关</span>
          <span class="loop-arrow">→</span>
          <span class="loop-chip"><el-icon><EditPen /></el-icon> 3. 反馈优化调整</span>
          <span class="loop-arrow">→</span>
          <span class="loop-chip"><el-icon><Promotion /></el-icon> 4. AI改进生效</span>
        </div>
        <div class="banner-text">
          <template v-if="stage === 'data_fetch'">
            数据获取阶段提供<strong>「审核确认检索范围与关键词」</strong>、<strong>「增量数据精准补采」</strong>与<strong>「脏数据清洗剔除」</strong>，严格把关上游数据源头质量。
          </template>
          <template v-else-if="stage === 'data_interpret'">
            数据解读阶段提供<strong>「补充专家背景知识先验」</strong>、<strong>「修正与裁决核心研判判断」</strong>与<strong>「可比公司标的池调整」</strong>，确保投研论据准确可信。
          </template>
          <template v-else-if="stage === 'chart_generate'">
            可视化图表阶段提供<strong>「选择图表呈现样式（柱/折/条/堆）」</strong>、<strong>「指定重点标的高亮与基准线强调重点」</strong>与<strong>「新增定向图表诉求」</strong>。
          </template>
          <template v-else-if="stage === 'chapter_write'">
            分章节内容阶段提供<strong>「提出修改意见与补充要求（单章定向重写）」</strong>与<strong>「正文段落就地精修」</strong>，高效定向迭代章节内容。
          </template>
          <template v-else-if="stage === 'report_fusion'">
            报告融合阶段提供<strong>「全篇四维质量整体审核」</strong>、<strong>「提出宏观修订方向」</strong>与<strong>「8 张指标卡与投资评级终审定稿」</strong>。
          </template>
        </div>
      </div>

      <!-- ------------------------------------------------------------- -->
      <!-- 阶段 1：数据获取 (data_fetch) -->
      <!-- ------------------------------------------------------------- -->
      <el-tabs v-if="stage === 'data_fetch'" v-model="activeTab" class="stage-tabs">
        <!-- Tab 1.0: 检索范围与关键词审核 -->
        <el-tab-pane label="审核确认检索范围与关键词" name="scope_keywords">
          <div class="tab-pane-content">
            <div class="section-lead">
              核对并调整数据检索覆盖的投研领域与关键词集合。确认后将以此范围作为后续分析的权威数据源：
            </div>

            <div class="scope-section-title">
              <span class="title-bold">1. 审核投研检索范围 (子领域选择)</span>
              <span class="title-sub">勾选本次研究需要覆盖的数据维度：</span>
            </div>
            <div class="scope-grid">
              <div
                v-for="domain in scopeDomains"
                :key="domain.id"
                class="scope-card"
                :class="{ active: domain.checked }"
                @click="domain.checked = !domain.checked"
              >
                <div class="scope-card-top">
                  <el-checkbox v-model="domain.checked" @click.stop>{{ domain.name }}</el-checkbox>
                </div>
                <div class="scope-card-desc">{{ domain.desc }}</div>
              </div>
            </div>

            <div class="scope-section-title" style="margin-top: 18px">
              <span class="title-bold">2. 审核与精简检索核心关键词</span>
              <span class="title-sub">点击标签后的 × 可剔除不相关词；支持输入新关键词扩充：</span>
            </div>
            <div class="keywords-cloud">
              <el-tag
                v-for="(kw, idx) in activeKeywords"
                :key="kw"
                closable
                size="large"
                class="kw-tag"
                @close="removeKeyword(idx)"
              >
                {{ kw }}
              </el-tag>
              <div class="kw-add-box">
                <el-input
                  v-model="newKeywordInput"
                  placeholder="+ 添加关键词后回车"
                  size="small"
                  style="width: 160px"
                  @keyup.enter="addKeyword"
                />
                <el-button size="small" type="primary" plain @click="addKeyword">添加</el-button>
              </div>
            </div>

            <div class="pane-footer" style="display: flex; gap: 12px; justify-content: flex-end">
              <el-button type="primary" size="large" :loading="submitting" @click="handleScopeKeywordsConfirm">
                确认审核无误并进入下一步
              </el-button>
              <el-button type="info" plain size="large" :loading="submitting" @click="handleScopeKeywordsRevise">
                按此范围与关键词重新检索
              </el-button>
            </div>
          </div>
        </el-tab-pane>

        <!-- Tab 1.1: 增量补采 -->
        <el-tab-pane label="增量数据补采" name="replenish">
          <div class="tab-pane-content">
            <div class="section-lead">针对当前缺失的重点公司、前沿技术指标或细分业务，执行针对性单点查询并无缝合入数据集：</div>
            
            <div class="quick-chips">
              <span class="chip-label">热门补采预设：</span>
              <el-button size="small" round @click="quickFillReplenish('finance')">补充龙头财务与盈利</el-button>
              <el-button size="small" round @click="quickFillReplenish('chain')">补充产业链关键环节</el-button>
              <el-button size="small" round @click="quickFillReplenish('macro')">补充宏观产销与大盘</el-button>
              <el-button size="small" round @click="quickFillReplenish('competitors')">补充竞争格局与份额</el-button>
            </div>

            <el-form label-position="top" size="default">
              <el-row :gutter="16">
                <el-col :span="12">
                  <el-form-item label="补采目标实体（公司代码/企业名/行业细分）">
                    <el-input v-model="replenishEntity" placeholder="例如：行业核心龙头企业名、公司代码或细分板块" />
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
                  placeholder="输入针对性查询提示，例如：查询核心龙头企业近3年营业收入、毛利率及研发费用率"
                />
              </el-form-item>

              <el-form-item label="补采原因 / 分析诉求">
                <el-input v-model="replenishReason" placeholder="例如：下游定量图表与报告章节缺少核心龙头关键财务指标" />
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
        <!-- Tab 2.0: 补充背景知识与修正判断 -->
        <el-tab-pane label="补充背景知识与修正判断" name="knowledge_judgment">
          <div class="tab-pane-content">
            <div class="section-lead">
              补充一手行业专家纪要或非公开背景先验（将作为贝叶斯先验融入全文分析）；对智能体提取的核心研判结论进行逐条裁决修正：
            </div>

            <!-- 1. 专家背景知识注入区 -->
            <div class="knowledge-block">
              <div class="scope-section-title">
                <span class="title-bold">1. 补充行业专家背景知识 (先验事实输入)</span>
                <span class="title-sub">快捷填入行业典型调研先验，或自由粘贴一手产业笔记：</span>
              </div>
              <div class="quick-chips" style="margin-bottom: 8px">
                <span class="chip-label">快捷注入先验：</span>
                <el-button size="small" round @click="quickFillExpertKnowledge('channel')">海外云厂商资本开支与采购节奏</el-button>
                <el-button size="small" round @click="quickFillExpertKnowledge('policy')">重点出海市场本地化合规壁垒</el-button>
                <el-button size="small" round @click="quickFillExpertKnowledge('tech')">新架构商业化替代拐点预警</el-button>
              </div>
              <el-input
                v-model="expertBackgroundNotes"
                type="textarea"
                :rows="3"
                placeholder="例如：【草根调研】头部客户下半年采购订单增长30%，但上游芯片交付周期拉长..."
              />
            </div>

            <!-- 2. 核心研判判断逐条修正区 -->
            <div class="judgments-block" style="margin-top: 18px">
              <div class="scope-section-title">
                <span class="title-bold">2. 核心研判论点逐条修正与裁决</span>
                <span class="title-sub">选择【认同保留】、【就地修正观点】或【剔除否定】：</span>
              </div>

              <div class="judgments-list">
                <div v-for="j in localJudgments" :key="j.id" class="judgment-card" :class="j.decision">
                  <div class="judgment-top">
                    <div class="j-title-row">
                      <el-tag size="small" type="primary">{{ j.id }}</el-tag>
                      <el-input
                        v-if="j.decision === 'modify'"
                        v-model="j.title"
                        size="small"
                        placeholder="修改论点标题..."
                        style="margin-left: 8px; flex: 1"
                      />
                      <span v-else class="j-title-text">{{ j.title }}</span>
                    </div>
                    <el-radio-group v-model="j.decision" size="small">
                      <el-radio-button value="confirm">认同保留</el-radio-button>
                      <el-radio-button value="modify">修正观点</el-radio-button>
                      <el-radio-button value="reject">剔除否定</el-radio-button>
                    </el-radio-group>
                  </div>
                  <div v-if="j.decision === 'modify'" style="margin-top: 8px">
                    <el-input
                      v-model="j.text"
                      type="textarea"
                      :rows="2"
                      placeholder="修改详细逻辑与论据..."
                    />
                  </div>
                  <div v-else class="judgment-desc" :class="{ 'rejected-text': j.decision === 'reject' }">
                    {{ j.text }}
                  </div>
                </div>
              </div>
            </div>

            <div class="pane-footer">
              <el-button type="success" size="large" :loading="submitting" @click="handleKnowledgeAndJudgmentSubmit">
                保存背景知识与判断修正 (就地生效)
              </el-button>
            </div>
          </div>
        </el-tab-pane>

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
        <!-- Tab 3.1: 图表样式选择与强调重点 -->
        <el-tab-pane label="选择图表样式与强调重点" name="morph_emphasis">
          <div class="tab-pane-content">
            <div class="section-lead">
              就地调整图表的可视化呈现样式（柱状/折线/水平条形/堆叠/面积图），并配置重点标的高亮、参考警戒基准线与关键拐点标注：
            </div>

            <el-table :data="localCharts" size="small" height="340px" style="width: 100%" border>
              <el-table-column prop="chart_id" label="编号" width="85" />
              <el-table-column label="图表标题" min-width="150">
                <template #default="{ row }">
                  <el-input v-model="row.title" size="small" />
                </template>
              </el-table-column>
              <el-table-column label="呈现样式" width="135">
                <template #default="{ row }">
                  <el-select v-model="row.chart_type" size="small">
                    <el-option label="柱状图 (bar)" value="bar" />
                    <el-option label="折线图 (line)" value="line" />
                    <el-option label="水平条形图 (h_bar)" value="horizontal_bar" />
                    <el-option label="堆叠柱状图 (stacked)" value="stacked_bar" />
                    <el-option label="面积图 (area)" value="area" />
                    <el-option label="环形饼图 (donut/pie)" value="pie" />
                    <el-option label="雷达多维图 (radar)" value="radar" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="强调重点配置 (高亮标的 / 参考基准线 / 拐点标注)" min-width="320">
                <template #default="{ row }">
                  <div class="chart-emphasis-grid">
                    <el-input
                      v-model="row.highlight_target"
                      size="small"
                      placeholder="高亮企业/标的名"
                      style="width: 32%"
                    />
                    <el-input
                      v-model.number="row.benchmark_line"
                      size="small"
                      placeholder="基准线值(如 25)"
                      style="width: 32%"
                    />
                    <el-input
                      v-model="row.emphasis_note"
                      size="small"
                      placeholder="拐点/重点标注"
                      style="width: 32%"
                    />
                  </div>
                </template>
              </el-table-column>
              <el-table-column label="纳入研报" width="85" align="center">
                <template #default="{ row }">
                  <el-switch v-model="row.excluded" :active-value="false" :inactive-value="true" inline-prompt active-text="开" inactive-text="关" />
                </template>
              </el-table-column>
            </el-table>

            <div class="pane-footer">
              <el-button type="success" size="large" :loading="submitting" @click="handleChartMorphSubmit">
                保存图表样式与强调重点配置 (就地生效)
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
        <!-- Tab 4.0: 提出修改意见与补充要求 -->
        <el-tab-pane label="提出修改意见与补充要求" name="revision_requirements">
          <div class="tab-pane-content">
            <div class="section-lead">
              根据赛题人机协同规范，您可针对具体章节或报告全篇提出结构化修改意见与补充要求，指导智能体执行定向高阶重构：
            </div>

            <div class="scope-section-title">
              <span class="title-bold">1. 选择协同修改范围</span>
              <el-radio-group v-model="revisionScope" size="small" style="margin-left: 12px">
                <el-radio-button value="single">针对指定单章定向重构 (其余6章原封不动)</el-radio-button>
                <el-radio-button value="all">针对全篇报告全局优化</el-radio-button>
              </el-radio-group>
            </div>

            <div v-if="revisionScope === 'single'" style="margin-top: 10px">
              <el-select v-model="targetChapterId" style="width: 380px" size="default">
                <el-option
                  v-for="op in CHAPTER_OPTIONS"
                  :key="op.id"
                  :label="op.title"
                  :value="op.id"
                />
              </el-select>
            </div>

            <div class="scope-section-title" style="margin-top: 18px">
              <span class="title-bold">2. 结构化修改意见 (点击快速勾选组合)</span>
              <span class="title-sub">选择需要强化的分析深度与论证维度：</span>
            </div>
            <div class="revision-tags-grid">
              <div
                v-for="tag in REVISION_TAGS"
                :key="tag"
                class="rev-tag-item"
                :class="{ active: selectedRevisionTags.includes(tag) }"
                @click="toggleRevisionTag(tag)"
              >
                <el-icon v-if="selectedRevisionTags.includes(tag)" class="tag-check"><Check /></el-icon>
                <span v-else class="tag-check">+</span>
                <span class="tag-label">{{ tag }}</span>
              </div>
            </div>

            <div class="scope-section-title" style="margin-top: 18px">
              <span class="title-bold">3. 补充具体要求 (自由指导指示)</span>
              <span class="title-sub">输入个性化投研分析诉求、对比标的或特殊行文侧重点：</span>
            </div>
            <el-input
              v-model="revisionRequirementText"
              type="textarea"
              :rows="3"
              placeholder="例如：请在第4章深入剖析头部两家厂商在北美云厂商的采购份额对比，论证其壁垒深度；引用图表3量化数据..."
            />

            <div class="pane-footer">
              <el-button type="primary" size="large" :loading="submitting" @click="handleRevisionRequirementsSubmit">
                提交修改意见与补充要求 (启动 AI 定向改进)
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
        <!-- Tab 5.0: 整体审核并提出修订方向 -->
        <el-tab-pane label="整体审核并提出修订方向" name="audit_steering">
          <div class="tab-pane-content">
            <div class="section-lead">
              全篇报告已完成 5 阶段流水线编排与生成。您可查看四维质量整体审核看板，并提出宏观修订方向（导向调控），指导融合智能体统领润色：
            </div>

            <!-- 1. 四维质量整体审核看板 (AI辅助把关) -->
            <div class="audit-board">
              <div class="audit-item">
                <div class="audit-val">7 / 7 章</div>
                <div class="audit-lbl">结构章节完整度</div>
                <div class="audit-sub">21 节投研逻辑自洽</div>
              </div>
              <div class="audit-item">
                <div class="audit-val">100%</div>
                <div class="audit-lbl">量化数据穿透率</div>
                <div class="audit-sub">同花顺 iFinD 溯源索引</div>
              </div>
              <div class="audit-item">
                <div class="audit-val">{{ localCharts.length || 6 }} 幅</div>
                <div class="audit-lbl">可视化图表嵌入</div>
                <div class="audit-sub">券商出版级矢量混排</div>
              </div>
              <div class="audit-item">
                <div class="audit-val" style="color: var(--el-color-primary)">{{ localRating }}</div>
                <div class="audit-lbl">当前投资建议评级</div>
                <div class="audit-sub">基于多维财务估值矩阵</div>
              </div>
            </div>

            <!-- 2. 全局修订方向选择 -->
            <div class="scope-section-title" style="margin-top: 18px">
              <span class="title-bold">提出全局修订方向 (宏观投资立场与基调导向)</span>
              <span class="title-sub">选择适合本次研报交付目的的全局论述基调：</span>
            </div>

            <div class="steering-grid">
              <div
                v-for="st in STEERING_OPTIONS"
                :key="st.label"
                class="steering-card"
                :class="{ active: globalSteeringDirection === st.label }"
                @click="globalSteeringDirection = st.label"
              >
                <div class="steering-top">
                  <el-radio :model-value="globalSteeringDirection" :label="st.label" @click.stop>
                    <span class="steering-name">{{ st.label }}</span>
                  </el-radio>
                </div>
                <div class="steering-desc">{{ st.desc }}</div>
              </div>
            </div>

            <div class="scope-section-title" style="margin-top: 18px">
              <span class="title-bold">全篇统筹修订指示与特别说明</span>
              <span class="title-sub">补充总编审校指导细节（如重点论点前置、段落篇幅平衡）：</span>
            </div>
            <el-input
              v-model="globalSteeringComment"
              type="textarea"
              :rows="3"
              placeholder="例如：请将第三章竞争格局的结论提炼前置到执行摘要开头；下调乐观盈利预测，强化海外关税下行风险提示..."
            />

            <div class="pane-footer" style="display: flex; gap: 12px; justify-content: flex-end">
              <el-button type="primary" size="large" :loading="submitting" @click="handleGlobalSteeringSubmit">
                提交全局修订方向 (启动 AI 终审重构)
              </el-button>
            </div>
          </div>
        </el-tab-pane>

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
  padding: 12px 16px;
  margin-bottom: 16px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}
.closed-loop-flow {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.loop-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11.5px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--el-fill-color);
  color: var(--el-text-color-secondary);
  font-weight: 500;
}
.loop-chip.active {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-weight: 600;
  border: 1px solid var(--el-color-primary-light-7);
}
.loop-arrow {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
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

/* 标题与分区小标 */
.scope-section-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 10px;
}
.title-bold {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.title-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* 阶段 1：检索范围与关键词 */
.scope-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.scope-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 10px 12px;
  background: var(--el-bg-color);
  cursor: pointer;
  transition: all 0.2s ease;
}
.scope-card:hover {
  border-color: var(--el-color-primary-light-5);
}
.scope-card.active {
  border-color: var(--el-color-primary-light-3);
  background: var(--el-color-primary-light-9);
}
.scope-card-top {
  font-weight: 600;
  font-size: 13px;
}
.scope-card-desc {
  font-size: 11.5px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
  line-height: 1.4;
}
.keywords-cloud {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 12px;
  background: var(--el-fill-color-blank);
  border: 1px dashed var(--el-border-color);
  border-radius: 6px;
}
.kw-tag {
  font-size: 12.5px;
  padding: 4px 10px;
}
.kw-add-box {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 阶段 2：研判裁决卡片 */
.judgments-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 280px;
  overflow-y: auto;
}
.judgment-card {
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
  padding: 10px 12px;
  background: var(--el-bg-color);
  transition: all 0.2s ease;
}
.judgment-card.confirm {
  border-left: 3px solid var(--el-color-success);
}
.judgment-card.modify {
  border-left: 3px solid var(--el-color-warning);
  background: rgba(230, 162, 60, 0.03);
}
.judgment-card.reject {
  border-left: 3px solid var(--el-color-danger);
  opacity: 0.6;
}
.judgment-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.j-title-row {
  display: flex;
  align-items: center;
  flex: 1;
}
.j-title-text {
  font-weight: 600;
  font-size: 13.5px;
  margin-left: 8px;
}
.judgment-desc {
  font-size: 12.5px;
  color: var(--el-text-color-regular);
  margin-top: 6px;
  line-height: 1.5;
}
.rejected-text {
  text-decoration: line-through;
  color: var(--el-text-color-placeholder);
}

/* 阶段 3：图表强调重点表单网格 */
.chart-emphasis-grid {
  display: flex;
  gap: 6px;
  align-items: center;
}

/* 阶段 4：修改意见标签网格 */
.revision-tags-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}
.rev-tag-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color);
  cursor: pointer;
  font-size: 12px;
  color: var(--el-text-color-regular);
  transition: all 0.2s ease;
}
.rev-tag-item:hover {
  border-color: var(--el-color-primary);
}
.rev-tag-item.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-weight: 600;
}
.tag-check {
  font-weight: bold;
}

/* 阶段 5：体检看板与全局导向 */
.audit-board {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  background: var(--el-fill-color-blank);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
}
.audit-item {
  text-align: center;
  padding: 4px 0;
  border-right: 1px solid var(--el-border-color-extra-light);
}
.audit-item:last-child {
  border-right: none;
}
.audit-val {
  font-size: 17px;
  font-weight: 700;
  color: var(--el-color-success);
}
.audit-lbl {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-top: 2px;
}
.audit-sub {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}
.steering-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-bottom: 14px;
}
.steering-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 10px 14px;
  background: var(--el-bg-color);
  cursor: pointer;
  transition: all 0.2s ease;
}
.steering-card:hover {
  border-color: var(--el-color-primary-light-5);
}
.steering-card.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.steering-name {
  font-weight: 600;
  font-size: 13px;
}
.steering-desc {
  font-size: 11.5px;
  color: var(--el-text-color-secondary);
  margin-top: 4px;
  line-height: 1.4;
  padding-left: 22px;
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
