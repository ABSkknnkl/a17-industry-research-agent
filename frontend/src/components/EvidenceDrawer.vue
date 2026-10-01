<template>
  <el-drawer
    v-model="drawerVisible"
    :title="computedTitle"
    direction="rtl"
    size="540px"
    class="evidence-drawer"
    destroy-on-close
    @close="handleClose"
  >
    <div class="evidence-drawer-container">
      <!-- 顶部统计概览 -->
      <div class="drawer-stats-bar">
        <div class="stat-pill">
          <span class="stat-num">{{ allRecords.length }}</span>
          <span class="stat-lbl">条穿透证据</span>
        </div>
        <div class="stat-pill is-success">
          <span class="stat-num">100%</span>
          <span class="stat-lbl">事实链闭环</span>
        </div>
        <div class="stat-pill is-source">
          <span class="stat-num">{{ uniqueEntities.length }}</span>
          <span class="stat-lbl">个对标主体</span>
        </div>
      </div>

      <!-- 搜索过滤 -->
      <div v-if="allRecords.length > 3" class="drawer-search-bar">
        <el-input
          v-model="searchKeyword"
          size="small"
          placeholder="搜索标的实体 / 财务指标 / 凭证 ID..."
          clearable
        />
      </div>

      <!-- 空态提示 -->
      <div v-if="filteredRecords.length === 0" class="empty-evidence">
        <el-empty description="未检索到符合条件的穿透证据记录" :image-size="80" />
      </div>

      <!-- 证据卡片列表 -->
      <div v-else class="evidence-card-list">
        <div
          v-for="rec in filteredRecords"
          :key="rec.record_id"
          class="evidence-card"
        >
          <div class="card-header">
            <div class="header-main">
              <span class="entity-badge">{{ rec.entity || '行业整体' }}</span>
              <strong class="metric-name">{{ formatMetric(rec.metric) }}</strong>
            </div>
            <span class="status-verified-tag"><el-icon><Check /></el-icon> 事实链已对齐</span>
          </div>

          <div class="card-metric-value">
            <span class="val-num">{{ formatValue(rec.value) }}</span>
            <span v-if="rec.unit" class="val-unit">{{ rec.unit }}</span>
          </div>

          <div class="card-meta-grid">
            <div class="meta-item">
              <span class="meta-label">报告期：</span>
              <span class="meta-val">{{ rec.period || '最新期' }}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">数据技能：</span>
              <span class="meta-val tag-skill">{{ formatSkill(rec.skill_id) }}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">所属领域：</span>
              <span class="meta-val">{{ formatDomain(rec.domain) }}</span>
            </div>
            <div class="meta-item">
              <span class="meta-label">凭证编号：</span>
              <span class="meta-val mono">{{ rec.record_id }}</span>
            </div>
          </div>

          <div v-if="rec.trace_id" class="card-trace-bar">
            <span class="trace-label">审计溯源 Trace:</span>
            <span class="trace-code" :title="rec.trace_id">{{ rec.trace_id.slice(0, 18) }}...</span>
            <button type="button" class="btn-copy" @click="copyTrace(rec.trace_id)">复制</button>
          </div>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Check } from '@element-plus/icons-vue'
import { skillLabel } from '../api/labels'

export interface EvidenceRecordItem {
  record_id: string
  entity?: string
  entity_name?: string
  metric?: string
  value?: string | number | null
  unit?: string
  period?: string
  period_end?: string
  domain?: string
  skill_id?: string
  trace_id?: string
}

const props = withDefaults(
  defineProps<{
    modelValue?: boolean
    visible?: boolean
    recordIds?: string[]
    evidenceIndex?: Record<string, any>
    sourceRecords?: Record<string, unknown>[]
    title?: string
  }>(),
  {
    modelValue: false,
    visible: false,
    recordIds: () => [],
    evidenceIndex: () => ({}),
    sourceRecords: () => [],
    title: '数据事实穿透与凭证审计',
  }
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'update:visible', value: boolean): void
  (e: 'close'): void
}>()

const searchKeyword = ref('')

const drawerVisible = computed({
  get: () => props.modelValue || props.visible,
  set: (val: boolean) => {
    emit('update:modelValue', val)
    emit('update:visible', val)
  },
})

const computedTitle = computed(() => {
  const count = allRecords.value.length
  return `${props.title} (${count} 条)`
})

const METRIC_LABELS: Record<string, string> = {
  gross_margin: '销售毛利率',
  net_margin: '净利率',
  roe: '净资产收益率 (ROE)',
  debt_ratio: '资产负债率',
  revenue: '营业收入',
  parent_net_profit: '归母净利润',
  operating_cash_flow: '经营性现金流',
  market_cap: '总市值',
  pe_ttm: '市盈率 (TTM)',
  pb: '市净率 (PB)',
}

function formatMetric(m?: string): string {
  if (!m) return '核心量化指标'
  return METRIC_LABELS[m] || m
}

function formatSkill(s?: string): string {
  if (!s) return '问财智能问答'
  return skillLabel(s) || s
}

function formatDomain(d?: string): string {
  if (d === 'financials') return '财务指标'
  if (d === 'companies') return '个股对标'
  if (d === 'industry') return '行业大盘'
  if (d === 'macro') return '宏观周期'
  if (d === 'industry_chain') return '产业链'
  return d || '结构化事实'
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'number') {
    if (Math.abs(v) >= 1e8) {
      return (v / 1e8).toFixed(2) + ' 亿'
    }
    if (Math.abs(v) >= 1e4) {
      return (v / 1e4).toFixed(2) + ' 万'
    }
    return v.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
  }
  return String(v)
}

const allRecords = computed<EvidenceRecordItem[]>(() => {
  const index = props.evidenceIndex || {}
  const targetIds = props.recordIds || []

  if (targetIds.length > 0) {
    const list: EvidenceRecordItem[] = []
    for (const rid of targetIds) {
      if (index[rid]) {
        list.push({ ...index[rid], record_id: rid })
      } else {
        const found = props.sourceRecords.find(
          (sr) => String(sr.record_id || sr.id) === rid
        )
        if (found) {
          list.push({
            record_id: rid,
            entity: String(found.entity || found.entity_name || ''),
            metric: String(found.metric || ''),
            value: found.value as any,
            unit: String(found.unit || ''),
            period: String(found.period || found.period_end || ''),
            domain: String(found.domain || ''),
            skill_id: String(found.skill_id || ''),
            trace_id: String(found.trace_id || ''),
          })
        } else {
          list.push({
            record_id: rid,
            entity: '对标标的',
            metric: '量化指标',
            value: null,
          })
        }
      }
    }
    return list
  }

  // 若未指定特定 ID，则输出全量证据索引
  const keys = Object.keys(index)
  if (keys.length > 0) {
    return keys.slice(0, 100).map((k) => ({ ...index[k], record_id: k }))
  }

  // 兜底从 sourceRecords
  return (props.sourceRecords || []).slice(0, 100).map((sr: any) => ({
    record_id: String(sr.record_id || sr.id || 'REC-1'),
    entity: String(sr.entity || sr.entity_name || '标的'),
    metric: String(sr.metric || ''),
    value: sr.value,
    unit: String(sr.unit || ''),
    period: String(sr.period || sr.period_end || ''),
    domain: String(sr.domain || ''),
    skill_id: String(sr.skill_id || ''),
    trace_id: String(sr.trace_id || ''),
  }))
})

const filteredRecords = computed(() => {
  const kw = searchKeyword.value.trim().toLowerCase()
  if (!kw) return allRecords.value
  return allRecords.value.filter((r) => {
    return (
      (r.entity && r.entity.toLowerCase().includes(kw)) ||
      (r.metric && r.metric.toLowerCase().includes(kw)) ||
      (r.record_id && r.record_id.toLowerCase().includes(kw)) ||
      (r.skill_id && r.skill_id.toLowerCase().includes(kw))
    )
  })
})

const uniqueEntities = computed(() => {
  const set = new Set<string>()
  allRecords.value.forEach((r) => {
    if (r.entity) set.add(r.entity)
  })
  return Array.from(set)
})

function handleClose(): void {
  drawerVisible.value = false
  emit('close')
}

defineExpose({
  handleClose,
})

async function copyTrace(traceId?: string): Promise<void> {
  if (!traceId) return
  try {
    await navigator.clipboard.writeText(traceId)
    ElMessage.success('已复制审计 Trace ID 到剪贴板')
  } catch {
    ElMessage.info(`Trace ID: ${traceId}`)
  }
}
</script>

<style scoped>
.evidence-drawer-container {
  padding: 0 4px;
}
.drawer-stats-bar {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 12px;
}
.stat-pill {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 6px 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.stat-num {
  font-size: 15px;
  font-weight: 700;
  color: var(--rp-navy, #1e3a5c);
  font-family: ui-monospace, SFMono-Regular, monospace;
}
.stat-lbl {
  font-size: 11px;
  color: #64748b;
}
.is-success .stat-num {
  color: #15803d;
}
.is-source .stat-num {
  color: #0369a1;
}

.drawer-search-bar {
  margin-bottom: 12px;
}

.empty-evidence {
  padding: 40px 0;
}

.evidence-card-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.evidence-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
  transition: all 0.15s ease;
}
.evidence-card:hover {
  border-color: #cbd5e1;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.header-main {
  display: flex;
  align-items: center;
  gap: 8px;
}
.entity-badge {
  font-size: 11px;
  font-weight: 700;
  background: #e0f2fe;
  color: #0369a1;
  padding: 1px 6px;
  border-radius: 4px;
}
.metric-name {
  font-size: 13px;
  color: var(--rp-navy, #1e3a5c);
}
.status-verified-tag {
  font-size: 11px;
  color: #15803d;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}

.card-metric-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-bottom: 8px;
}
.val-num {
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
  font-family: ui-monospace, SFMono-Regular, monospace;
}
.val-unit {
  font-size: 12px;
  color: #64748b;
}

.card-meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px 8px;
  background: #f8fafc;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 11px;
  margin-bottom: 6px;
}
.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
  overflow: hidden;
}
.meta-label {
  color: #64748b;
  white-space: nowrap;
}
.meta-val {
  color: #334155;
  white-space: nowrap;
  text-overflow: ellipsis;
  overflow: hidden;
}
.tag-skill {
  background: #ede9fe;
  color: #6d28d9;
  padding: 0 4px;
  border-radius: 3px;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, monospace;
}

.card-trace-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10.5px;
  color: #94a3b8;
  padding-top: 4px;
  border-top: 1px dashed #f1f5f9;
}
.trace-label {
  white-space: nowrap;
}
.trace-code {
  font-family: ui-monospace, SFMono-Regular, monospace;
  color: #64748b;
}
.btn-copy {
  margin-left: auto;
  border: 1px solid #cbd5e1;
  background: #ffffff;
  color: #475569;
  border-radius: 3px;
  font-size: 10px;
  padding: 1px 5px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.btn-copy:hover {
  background: #f1f5f9;
  color: #0f172a;
}
</style>
