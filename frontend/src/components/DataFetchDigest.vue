<script setup lang="ts">
import { computed, ref } from 'vue'
import { intentPlanLabel, skillLabel } from '../api/labels'
import type { IntentRouting, CollaborationRequest } from '../api/types'

export interface UserAnnotation {
  id: string
  stage: string
  targetType: 'record' | 'intent'
  targetId: string
  title: string
  type: 'emphasize' | 'accept' | 'doubt' | 'reject'
  note?: string
}

const props = defineProps<{
  data: Record<string, unknown>
  sourceRecords?: Record<string, unknown>[]
  runId?: string
}>()

const emit = defineEmits<{
  (e: 'annotate', annotations: UserAnnotation[]): void
  (e: 'view-evidence', recordIds: string[]): void
}>()

const searchKeyword = ref('')
const selectedDomain = ref('all')
const currentPage = ref(1)
const pageSize = ref(15)

function selectDomain(domain: string) {
  selectedDomain.value = domain
  currentPage.value = 1
}

// 对象级标注
const userAnnotations = ref<Record<string, UserAnnotation>>({})

function asArray<T>(val: unknown): T[] {
  return Array.isArray(val) ? (val as T[]) : []
}

const sourceList = computed<Record<string, unknown>[]>(() => {
  return props.sourceRecords ?? asArray<Record<string, unknown>>(props.data.source_records)
})

const intentRouting = computed<IntentRouting | null>(() => {
  const raw = props.data.intent_routing
  return raw && typeof raw === 'object' ? (raw as IntentRouting) : null
})

const intentPlanEntries = computed(() => Object.entries(intentRouting.value?.plans ?? {}))

const domainStats = computed(() => {
  const stats: Record<string, number> = {}
  for (const r of sourceList.value) {
    const dom = String(r.domain || 'other')
    stats[dom] = (stats[dom] || 0) + 1
  }
  return stats
})

const filteredRecords = computed(() => {
  let list = sourceList.value
  if (selectedDomain.value !== 'all') {
    list = list.filter((r) => String(r.domain || '') === selectedDomain.value)
  }
  if (searchKeyword.value.trim()) {
    const q = searchKeyword.value.trim().toLowerCase()
    list = list.filter((r) => {
      const ent = String(r.entity_name || '').toLowerCase()
      const code = String(r.entity_code || '').toLowerCase()
      const metric = String(r.metric || '').toLowerCase()
      const val = String(r.value || '').toLowerCase()
      const qText = String(r.query || '').toLowerCase()
      return (
        ent.includes(q) ||
        code.includes(q) ||
        metric.includes(q) ||
        val.includes(q) ||
        qText.includes(q)
      )
    })
  }
  return list
})

const paginatedRecords = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  return filteredRecords.value.slice(start, start + pageSize.value)
})

function formatDomain(domain: unknown): string {
  const d = String(domain || '')
  if (d === 'industry') return '行业'
  if (d === 'companies') return '公司'
  if (d === 'macro') return '宏观'
  if (d === 'industry_chain') return '产业链'
  if (d === 'financials') return '财务'
  if (d === 'news') return '新闻'
  return d || '通用'
}

function formatSourceValue(row: Record<string, unknown>): string {
  const val = row.value
  const unit = row.unit ? ` ${row.unit}` : ''
  if (val === null || val === undefined || val === '') {
    if (typeof row.row_count === 'number') return `${row.row_count} 行`
    return '—'
  }
  if (Array.isArray(val)) return val.map(String).join('、')
  if (typeof val === 'number') return `${val.toLocaleString('zh-CN')}${unit}`
  return `${String(val)}${unit}`
}

function toggleRecordAnnotation(row: Record<string, unknown>, type: 'emphasize' | 'reject') {
  const rid = String(row.record_id || `${row.entity_name}_${row.metric}`)
  if (userAnnotations.value[rid]?.type === type) {
    delete userAnnotations.value[rid]
  } else {
    userAnnotations.value[rid] = {
      id: rid,
      stage: 'data_fetch',
      targetType: 'record',
      targetId: rid,
      title: `${row.entity_name || ''} - ${row.metric || ''}: ${formatSourceValue(row)}`,
      type,
    }
  }
  emit('annotate', Object.values(userAnnotations.value))
}

const annotationStats = computed(() => {
  const list = Object.values(userAnnotations.value)
  return {
    total: list.length,
    emphasize: list.filter((a) => a.type === 'emphasize').length,
    reject: list.filter((a) => a.type === 'reject').length,
  }
})
</script>

<template>
  <div class="data-fetch-digest" data-testid="data-fetch-digest">
    <!-- 1. 数据概览与统计卡片 -->
    <div class="fetch-stats-strip">
      <div class="stat-group">
        <span class="stat-main">采集来源明细（{{ sourceList.length }} 条）</span>
        <span class="stat-sub muted">已自动完成实体对齐与跨域消歧</span>
      </div>
      <div class="domain-pills">
        <span
          class="domain-pill"
          :class="{ active: selectedDomain === 'all' }"
          @click="selectDomain('all')"
        >
          全部 ({{ sourceList.length }})
        </span>
        <span
          v-for="(cnt, dom) in domainStats"
          :key="dom"
          class="domain-pill"
          :class="{ active: selectedDomain === dom }"
          @click="selectDomain(String(dom))"
        >
          {{ formatDomain(dom) }} ({{ cnt }})
        </span>
      </div>
    </div>

    <!-- 标注统计浮条 -->
    <div v-if="annotationStats.total > 0" class="annotation-bar">
      <span class="annot-icon">⭐</span>
      <span class="annot-summary">
        已标注数据样本：
        <span v-if="annotationStats.emphasize > 0" class="annot-tag is-emp"
          >重点关注 {{ annotationStats.emphasize }} 条</span
        >
        <span v-if="annotationStats.reject > 0" class="annot-tag is-rej"
          >建议剔除 {{ annotationStats.reject }} 条</span
        >
      </span>
      <span class="annot-hint"
        >（批注将指导阶段二数据解读智能体在做财务建模与回归时做加权或过滤）</span
      >
    </div>

    <!-- 2. 搜索过滤栏 -->
    <div class="table-toolbar">
      <el-input
        v-model="searchKeyword"
        size="small"
        placeholder="搜索公司、代码、指标或采集内容..."
        clearable
        style="max-width: 320px"
        @input="currentPage = 1"
      >
        <template #prefix>🔍</template>
      </el-input>
      <span class="muted result-count">
        匹配到 <b>{{ filteredRecords.length }}</b> / {{ sourceList.length }} 条记录
      </span>
    </div>

    <!-- 3. 数据表格 -->
    <el-table :data="paginatedRecords" size="small" border stripe class="fetch-table">
      <el-table-column label="样本主体 / 领域" width="160" show-overflow-tooltip>
        <template #default="{ row }">
          <div v-if="row.entity_name" class="entity-badge">
            <strong class="entity-name">{{ row.entity_name }}</strong>
            <span v-if="row.entity_code" class="entity-code muted">({{ row.entity_code }})</span>
          </div>
          <el-tag v-else size="small" effect="plain">{{ formatDomain(row.domain) }}</el-tag>
        </template>
      </el-table-column>

      <el-table-column label="采集指标 / 事项" width="170" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="metric-name">{{ row.metric || row.source_name || '—' }}</span>
        </template>
      </el-table-column>

      <el-table-column label="采集数值 / 内容详情" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="value-highlight">{{ formatSourceValue(row) }}</span>
        </template>
      </el-table-column>

      <el-table-column label="来源技能" width="130" show-overflow-tooltip>
        <template #default="{ row }">
          <el-tag size="small" effect="light" class="skill-tag">
            {{ row.skill_label || skillLabel(String(row.skill_name ?? '')) }}
          </el-tag>
        </template>
      </el-table-column>

      <el-table-column label="时点 / 报告期" width="105" align="center">
        <template #default="{ row }">
          <span>{{ row.period || row.as_of_date || '最新' }}</span>
        </template>
      </el-table-column>

      <el-table-column label="协同标注" width="130" align="center">
        <template #default="{ row }">
          <div class="row-actions">
            <el-tooltip content="标记为重点分析标的" placement="top">
              <button
                type="button"
                class="icon-btn star-btn"
                :class="{ active: userAnnotations[String(row.record_id)]?.type === 'emphasize' }"
                @click="toggleRecordAnnotation(row, 'emphasize')"
              >
                ⭐ 关注
              </button>
            </el-tooltip>
            <el-tooltip content="标记为异常或拟剔除数据" placement="top">
              <button
                type="button"
                class="icon-btn del-btn"
                :class="{ active: userAnnotations[String(row.record_id)]?.type === 'reject' }"
                @click="toggleRecordAnnotation(row, 'reject')"
              >
                🚫 剔除
              </button>
            </el-tooltip>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页器 -->
    <div class="pagination-bar">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :total="filteredRecords.length"
        :page-sizes="[15, 30, 50, 100]"
        layout="total, sizes, prev, pager, next"
        size="small"
      />
    </div>

    <!-- 4. 意图分解与技能路由计划 -->
    <el-collapse v-if="intentPlanEntries.length > 0" class="intent-collapse">
      <el-collapse-item name="plans">
        <template #title>
          <span class="collapse-title"
            >🧭 查看数据获取意图路由计划 ({{ intentPlanEntries.length }} 个领域子任务)</span
          >
        </template>
        <div class="plans-grid">
          <div v-for="[key, plan] in intentPlanEntries" :key="key" class="plan-card">
            <div class="plan-head">
              <strong>{{ intentPlanLabel(key) }}</strong>
              <el-tag size="small" effect="plain">
                {{
                  skillLabel(
                    (plan as any).skill_name ||
                      plan.sub_requirements?.[0]?.candidate_skills?.[0] ||
                      '问财投研'
                  )
                }}
              </el-tag>
            </div>
            <p class="plan-query muted">
              {{
                (plan as any).query ||
                (plan.sub_requirements?.[0] as any)?.query ||
                '基于主题与约束自动推演'
              }}
            </p>
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<style scoped>
.data-fetch-digest {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.fetch-stats-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  background: #f8fafc;
  border: 1px solid var(--rp-line, #e2e8f0);
  border-radius: 6px;
  padding: 10px 14px;
}
.stat-main {
  font-size: 13.5px;
  color: var(--rp-navy, #1e3a5c);
}
.stat-main b {
  color: #0284c7;
  font-size: 15px;
}
.stat-sub {
  font-size: 11.5px;
  margin-left: 8px;
}

.domain-pills {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.domain-pill {
  font-size: 11.5px;
  padding: 2px 8px;
  border-radius: 4px;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s ease;
}
.domain-pill:hover {
  border-color: #94a3b8;
  color: #0f172a;
}
.domain-pill.active {
  background: var(--rp-navy, #1e3a5c);
  color: #ffffff;
  border-color: var(--rp-navy, #1e3a5c);
  font-weight: 600;
}

/* 标注提示浮条 */
.annotation-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 12px;
  color: #92400e;
}
.annot-tag {
  font-weight: 600;
  margin: 0 4px;
}
.annot-tag.is-emp {
  color: #b45309;
}
.annot-tag.is-rej {
  color: #dc2626;
}
.annot-hint {
  color: #b45309;
  font-size: 11px;
  margin-left: auto;
}

.table-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.result-count {
  font-size: 12px;
}

.fetch-table {
  width: 100%;
}
.entity-badge {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
}
.entity-name {
  color: var(--rp-navy, #1e3a5c);
}
.entity-code {
  font-size: 10.5px;
}
.metric-name {
  font-weight: 600;
  color: #1e293b;
}
.value-highlight {
  color: #0f172a;
}
.skill-tag {
  font-size: 10.5px;
}

.row-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}
.icon-btn {
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  border-radius: 3px;
  font-size: 10.5px;
  padding: 2px 6px;
  cursor: pointer;
  transition: all 0.15s;
}
.icon-btn:hover {
  background: #e2e8f0;
}
.star-btn.active {
  background: #fef3c7;
  border-color: #f59e0b;
  color: #b45309;
  font-weight: 600;
}
.del-btn.active {
  background: #fee2e2;
  border-color: #ef4444;
  color: #b91c1c;
  font-weight: 600;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 4px;
}

/* 意图计划折叠 */
.intent-collapse {
  margin-top: 8px;
  border: 1px solid var(--rp-line, #e2e8f0);
  border-radius: 6px;
  overflow: hidden;
}
.collapse-title {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--rp-navy, #1e3a5c);
}
.plans-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
  padding: 6px 0;
}
.plan-card {
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  border-radius: 6px;
  padding: 8px 12px;
}
.plan-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
  font-size: 12px;
}
.plan-query {
  margin: 0;
  font-size: 11px;
  line-height: 1.5;
}
</style>
