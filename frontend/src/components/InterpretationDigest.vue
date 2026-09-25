<script setup lang="ts">
import { computed, ref } from 'vue'
import { dimensionLabel } from '../api/labels'

export interface UserAnnotation {
  id: string
  stage: string
  targetType: 'insight' | 'fact' | 'record' | 'metric'
  targetId: string
  title: string
  type: 'emphasize' | 'accept' | 'doubt' | 'reject'
  note?: string
}

const props = defineProps<{
  data: Record<string, unknown>
  runId?: string
}>()

const emit = defineEmits<{
  (e: 'annotate', annotations: UserAnnotation[]): void
  (e: 'view-evidence', recordIds: string[]): void
}>()

const activeTab = ref<'insights' | 'facts' | 'metrics' | 'coverage'>('insights')
const filterConfidence = ref<string>('all')
const searchKeyword = ref<string>('')

// 对象级标注字典: targetId -> UserAnnotation
const userAnnotations = ref<Record<string, UserAnnotation>>({})

function asArray<T>(val: unknown): T[] {
  return Array.isArray(val) ? (val as T[]) : []
}

const executiveSummary = computed(() => {
  return String(props.data.executive_summary || props.data.summary || '')
})

const insights = computed<Record<string, unknown>[]>(() => {
  return asArray<Record<string, unknown>>(props.data.insights)
})

const filteredInsights = computed(() => {
  let list = insights.value
  if (filterConfidence.value !== 'all') {
    list = list.filter((item) => String(item.confidence || '').toLowerCase() === filterConfidence.value)
  }
  if (searchKeyword.value.trim()) {
    const q = searchKeyword.value.trim().toLowerCase()
    list = list.filter((item) => {
      const title = String(item.title || '').toLowerCase()
      const conc = String(item.conclusion || '').toLowerCase()
      const sig = String(item.significance || '').toLowerCase()
      return title.includes(q) || conc.includes(q) || sig.includes(q)
    })
  }
  return list
})

const knowledgeFacts = computed<Record<string, unknown>[]>(() => {
  return asArray<Record<string, unknown>>(props.data.knowledge_facts)
})

const keyMetrics = computed<Record<string, unknown>[]>(() => {
  return asArray<Record<string, unknown>>(props.data.key_metrics)
})

const trends = computed<Record<string, unknown>[]>(() => {
  return asArray<Record<string, unknown>>(props.data.trends)
})

const anomalies = computed<Record<string, unknown>[]>(() => {
  return asArray<Record<string, unknown>>(props.data.anomalies)
})

const crossValidations = computed<Record<string, unknown>[]>(() => {
  return asArray<Record<string, unknown>>(props.data.cross_validations)
})

const dimensionCoverage = computed<Record<string, unknown>[]>(() => {
  return asArray<Record<string, unknown>>(props.data.dimension_coverage)
})

const risks = computed<Record<string, unknown>[]>(() => {
  return asArray<Record<string, unknown>>(props.data.risks)
})

// 标注动作
function toggleAnnotation(
  targetId: string,
  targetType: 'insight' | 'fact' | 'metric',
  title: string,
  type: 'emphasize' | 'accept' | 'doubt' | 'reject'
) {
  if (userAnnotations.value[targetId]?.type === type) {
    delete userAnnotations.value[targetId]
  } else {
    userAnnotations.value[targetId] = {
      id: targetId,
      stage: 'data_interpret',
      targetType,
      targetId,
      title,
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
    doubt: list.filter((a) => a.type === 'doubt').length,
    reject: list.filter((a) => a.type === 'reject').length,
  }
})

function confidenceTagType(conf: unknown): 'success' | 'warning' | 'info' {
  const c = String(conf || '').toLowerCase()
  if (c === 'high') return 'success'
  if (c === 'medium') return 'warning'
  return 'info'
}

function confidenceLabel(conf: unknown): string {
  const c = String(conf || '').toLowerCase()
  if (c === 'high') return '高置信度'
  if (c === 'medium') return '中等置信'
  return '参考级'
}

function categoryLabel(cat: unknown): string {
  const c = String(cat || '').toLowerCase()
  const map: Record<string, string> = {
    company: '公司',
    financial: '财务',
    industry: '行业',
    macro: '宏观',
    industry_chain: '产业链',
    event: '事件',
  }
  return map[c] || '其他'
}

function formatVal(val: unknown, unit?: unknown): string {
  if (val === null || val === undefined) return '—'
  const u = unit ? ` ${unit}` : ''
  if (typeof val === 'number') {
    return `${val.toLocaleString('zh-CN')}${u}`
  }
  return `${String(val)}${u}`
}
</script>

<template>
  <div class="interpretation-digest" data-testid="interpretation-digest">
    <!-- 1. 研报宏观综述 Executive Summary -->
    <section v-if="executiveSummary" class="summary-hero-card">
      <div class="hero-header">
        <div class="hero-title-group">
          <span class="hero-badge">Executive Summary</span>
          <h4 class="hero-title">全行业深度研报综合评述</h4>
        </div>
        <div class="hero-meta">
          <span class="stat-pill"><b>{{ insights.length }}</b> 项深度洞察</span>
          <span class="stat-pill"><b>{{ knowledgeFacts.length }}</b> 条原子事实</span>
          <span class="stat-pill"><b>{{ keyMetrics.length }}</b> 项核心指标</span>
        </div>
      </div>
      <p class="hero-text">{{ executiveSummary }}</p>
    </section>

    <!-- 标注统计浮条（当有标注时展示） -->
    <div v-if="annotationStats.total > 0" class="annotation-bar">
      <span class="annot-summary">
        当前已标注 <b>{{ annotationStats.total }}</b> 项对象：
        <span v-if="annotationStats.emphasize > 0" class="annot-tag is-emp">重点强调 {{ annotationStats.emphasize }} 项</span>
        <span v-if="annotationStats.doubt > 0" class="annot-tag is-dbt">存疑核实 {{ annotationStats.doubt }} 项</span>
        <span v-if="annotationStats.reject > 0" class="annot-tag is-rej">建议剔除 {{ annotationStats.reject }} 项</span>
      </span>
      <span class="annot-hint">（这些批注已实时同步至人机协同控制区，可直接在下方「核心研判论点精修」中定向优化）</span>
    </div>

    <!-- 2. 多维度内容导航 Tabs -->
    <div class="digest-tabs-header">
      <el-radio-group v-model="activeTab" size="small" class="digest-nav-radios">
        <el-radio-button value="insights">
          研报深度洞察 ({{ insights.length }})
        </el-radio-button>
        <el-radio-button value="facts">
          原子事实底稿 ({{ knowledgeFacts.length }})
        </el-radio-button>
        <el-radio-button value="metrics">
          量化测算与异动 ({{ keyMetrics.length }})
        </el-radio-button>
        <el-radio-button value="coverage">
          维度覆盖与风险 ({{ dimensionCoverage.length }})
        </el-radio-button>
      </el-radio-group>

      <!-- 搜索与筛选 (针对洞察列表) -->
      <div v-if="activeTab === 'insights'" class="tab-filters">
        <el-select v-model="filterConfidence" size="small" style="width: 110px">
          <el-option label="全部置信度" value="all" />
          <el-option label="高置信度" value="high" />
          <el-option label="中置信度" value="medium" />
        </el-select>
        <el-input
          v-model="searchKeyword"
          size="small"
          placeholder="搜索洞察关键词..."
          clearable
          style="width: 180px"
        />
      </div>
    </div>

    <!-- TAB 1: 研报深度洞察 -->
    <div v-if="activeTab === 'insights'" class="tab-content insights-view">
      <div v-if="filteredInsights.length === 0" class="empty-hint">
        <el-empty description="未找到符合筛选条件的洞察" :image-size="60" />
      </div>
      <div v-else class="insights-grid">
        <article
          v-for="(ins, idx) in filteredInsights"
          :key="String(ins.insight_id || idx)"
          class="insight-card"
          :class="{
            'is-emphasized': userAnnotations[String(ins.insight_id)]?.type === 'emphasize',
            'is-doubted': userAnnotations[String(ins.insight_id)]?.type === 'doubt',
            'is-rejected': userAnnotations[String(ins.insight_id)]?.type === 'reject',
          }"
        >
          <header class="card-head">
            <div class="head-left">
              <span class="insight-idx">#{{ String(idx + 1).padStart(2, '0') }}</span>
              <h5 class="insight-title">{{ ins.title || '投研洞察' }}</h5>
              <el-tag :type="confidenceTagType(ins.confidence)" size="small" effect="plain" class="conf-pill">
                {{ confidenceLabel(ins.confidence) }}
              </el-tag>
            </div>

            <!-- 对象级标注快捷按钮 -->
            <div class="annotation-actions">
              <el-tooltip content="标记为后续章节重点强调" placement="top">
                <button
                  type="button"
                  class="action-chip"
                  :class="{ active: userAnnotations[String(ins.insight_id)]?.type === 'emphasize' }"
                  @click="toggleAnnotation(String(ins.insight_id), 'insight', String(ins.title), 'emphasize')"
                >
                  强调
                </button>
              </el-tooltip>
              <el-tooltip content="对结论存疑，要求重新核实" placement="top">
                <button
                  type="button"
                  class="action-chip"
                  :class="{ active: userAnnotations[String(ins.insight_id)]?.type === 'doubt' }"
                  @click="toggleAnnotation(String(ins.insight_id), 'insight', String(ins.title), 'doubt')"
                >
                  存疑
                </button>
              </el-tooltip>
              <el-tooltip content="剔除该洞察，不写入最终报告" placement="top">
                <button
                  type="button"
                  class="action-chip"
                  :class="{ active: userAnnotations[String(ins.insight_id)]?.type === 'reject' }"
                  @click="toggleAnnotation(String(ins.insight_id), 'insight', String(ins.title), 'reject')"
                >
                  剔除
                </button>
              </el-tooltip>
            </div>
          </header>

          <!-- 结论正文 -->
          <p class="insight-conclusion">{{ ins.conclusion }}</p>

          <!-- 产业意义 / 投资价值评估 -->
          <div v-if="ins.significance" class="insight-significance">
            <span class="sig-label">研判意义：</span>
            <span class="sig-text">{{ ins.significance }}</span>
          </div>

          <!-- 底栏：关联证据穿透 -->
          <footer class="card-foot">
            <div class="evidence-cluster">
              <span class="evidence-lead">凭证溯源:</span>
              <template v-if="asArray(ins.evidence_record_ids).length > 0">
                <el-tag
                  v-for="eid in asArray<string>(ins.evidence_record_ids).slice(0, 4)"
                  :key="eid"
                  size="small"
                  class="evidence-tag-interactive"
                  @click="emit('view-evidence', [eid])"
                >
                  {{ eid }}
                </el-tag>
                <span v-if="asArray(ins.evidence_record_ids).length > 4" class="more-tag muted">
                  +{{ asArray(ins.evidence_record_ids).length - 4 }}
                </span>
              </template>
              <span v-else class="muted">—</span>
            </div>
          </footer>
        </article>
      </div>
    </div>

    <!-- TAB 2: 原子事实底稿 -->
    <div v-else-if="activeTab === 'facts'" class="tab-content facts-view">
      <el-table :data="knowledgeFacts" size="small" border stripe style="width: 100%">
        <el-table-column prop="fact_id" label="事实编号" width="110">
          <template #default="{ row }">
            <span class="fact-id-code">{{ row.fact_id || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="subject" label="分析主体" width="130" show-overflow-tooltip>
          <template #default="{ row }">
            <strong>{{ row.subject || '—' }}</strong>
          </template>
        </el-table-column>
        <el-table-column prop="category" label="所属领域" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ categoryLabel(row.category) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="predicate" label="属性 / 关系" width="140" show-overflow-tooltip />
        <el-table-column prop="object_summary" label="客观事实陈述" min-width="220" show-overflow-tooltip />
        <el-table-column prop="confidence" label="置信度" width="95" align="center">
          <template #default="{ row }">
            <el-tag :type="confidenceTagType(row.confidence)" size="small" effect="light">
              {{ confidenceLabel(row.confidence) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="关联证据" width="130" align="center">
          <template #default="{ row }">
            <el-button
              v-if="asArray(row.evidence_record_ids).length > 0"
              link
              type="primary"
              size="small"
              @click="emit('view-evidence', asArray(row.evidence_record_ids))"
            >
              穿透 {{ asArray(row.evidence_record_ids).length }} 条
            </el-button>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- TAB 3: 量化测算与异动 -->
    <div v-else-if="activeTab === 'metrics'" class="tab-content metrics-view">
      <!-- 核心测算指标卡片 -->
      <div v-if="keyMetrics.length > 0" class="sub-section">
        <h5 class="sub-title">核心量化指标（{{ keyMetrics.length }} 项）</h5>
        <div class="metrics-grid">
          <div v-for="m in keyMetrics.slice(0, 12)" :key="String(m.metric_id)" class="metric-pill-card">
            <span class="m-entity muted">{{ m.entity || '行业基准' }}</span>
            <span class="m-name">{{ m.name }}</span>
            <span class="m-value">{{ formatVal(m.value, m.unit) }}</span>
          </div>
        </div>
      </div>

      <!-- 趋势与离群异常 -->
      <div class="quant-duo-grid">
        <div v-if="trends.length > 0" class="duo-col">
          <h5 class="sub-title">趋势演进（{{ trends.length }} 项）</h5>
          <ul class="trend-list">
            <li v-for="(t, idx) in trends.slice(0, 8)" :key="idx" class="trend-item">
              <span class="trend-badge" :class="String(t.direction || '')">
                {{ t.direction === 'up' ? '↑ 增长' : t.direction === 'down' ? '↓ 下降' : '→ 平稳' }}
              </span>
              <span class="trend-desc">
                <b>{{ t.entity || '' }}</b> {{ t.metric }}:
                <span v-if="t.total_change_pct !== null && t.total_change_pct !== undefined">
                  变动 {{ (Number(t.total_change_pct) * 100).toFixed(1) }}%
                </span>
              </span>
            </li>
          </ul>
        </div>

        <div v-if="anomalies.length > 0" class="duo-col">
          <h5 class="sub-title">离群异常与红旗（{{ anomalies.length }} 项）</h5>
          <ul class="anomaly-list">
            <li v-for="(a, idx) in anomalies.slice(0, 8)" :key="idx" class="anomaly-item">
              <span class="anomaly-tag">异动</span>
              <span class="anomaly-text">
                <b>{{ a.entity || '' }}</b> {{ a.metric }} ({{ a.explanation || '偏离行业中枢' }})
              </span>
            </li>
          </ul>
        </div>
      </div>

      <!-- 三表勾稽验证 -->
      <div v-if="crossValidations.length > 0" class="sub-section" style="margin-top: 14px">
        <h5 class="sub-title">财务与三表勾稽验证（{{ crossValidations.length }} 项）</h5>
        <div class="cv-grid">
          <div
            v-for="(cv, idx) in crossValidations"
            :key="idx"
            class="cv-card"
            :class="cv.passed ? 'is-pass' : 'is-warn'"
          >
            <span class="cv-status">{{ cv.passed ? '验证通过' : '勾稽异常' }}</span>
            <span class="cv-name">{{ cv.rule_name || '三表勾稽规则' }}</span>
            <p class="cv-desc muted">{{ cv.explanation || '财务数据逻辑自洽' }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- TAB 4: 维度覆盖与风险 -->
    <div v-else-if="activeTab === 'coverage'" class="tab-content coverage-view">
      <div v-if="dimensionCoverage.length > 0" class="sub-section">
        <h5 class="sub-title">6 维投研覆盖情况</h5>
        <div class="cov-pills">
          <div
            v-for="(cov, idx) in dimensionCoverage"
            :key="idx"
            class="cov-box"
            :class="cov.status === 'covered' ? 'is-covered' : 'is-gap'"
          >
            <div class="cov-head">
              <strong>{{ cov.dimension_label || dimensionLabel(String(cov.dimension || '')) }}</strong>
              <el-tag size="small" :type="cov.status === 'covered' ? 'success' : 'warning'" effect="plain">
                {{ cov.status_label || (cov.status === 'covered' ? '已充分覆盖' : '存在缺口') }}
              </el-tag>
            </div>
            <p class="cov-reason muted">{{ cov.reason || '已完成数据对齐' }}</p>
          </div>
        </div>
      </div>

      <div v-if="risks.length > 0" class="sub-section" style="margin-top: 16px">
        <h5 class="sub-title">投研风险警示（{{ risks.length }} 条）</h5>
        <div class="risk-cards">
          <div v-for="(r, idx) in risks" :key="idx" class="risk-card">
            <span class="risk-badge">风险 #{{ idx + 1 }}</span>
            <span class="risk-content">{{ r.description || r.message || r.risk_code || JSON.stringify(r) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.interpretation-digest {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 1. Hero 综述卡片 */
.summary-hero-card {
  background: linear-gradient(135deg, #fffdf8 0%, #fcf9f2 100%);
  border: 1px solid #ebd9b8;
  border-left: 4px solid var(--rp-gold, #c5a059);
  border-radius: 8px;
  padding: 16px 20px;
  box-shadow: 0 2px 8px rgba(197, 160, 89, 0.08);
}
.hero-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 10px;
}
.hero-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
}
.hero-badge {
  font-size: 10px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 700;
  color: #926620;
  background: #fdf2d8;
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid #ebd49f;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.hero-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--rp-navy, #1e3a5c);
}
.hero-meta {
  display: flex;
  gap: 8px;
}
.stat-pill {
  font-size: 12px;
  background: rgba(255, 255, 255, 0.9);
  border: 1px solid #e5d8c3;
  padding: 2px 8px;
  border-radius: 12px;
  color: #5c431b;
}
.hero-text {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.85;
  color: #2c3e50;
  text-align: justify;
}

/* 标注提示浮条 */
.annotation-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f0fdf4;
  border: 1px solid #86efac;
  border-radius: 6px;
  padding: 8px 14px;
  font-size: 12.5px;
  color: #166534;
}
.annot-icon {
  font-size: 15px;
}
.annot-tag {
  margin: 0 4px;
  font-weight: 600;
}
.annot-tag.is-emp { color: #b45309; }
.annot-tag.is-dbt { color: #d97706; }
.annot-tag.is-rej { color: #dc2626; }
.annot-hint {
  color: #65a30d;
  font-size: 11.5px;
  margin-left: auto;
}

/* 2. Tabs 头部 */
.digest-tabs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--rp-line, #e2e8f0);
}
.tab-filters {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 3. 洞察卡片流 */
.insights-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 14px;
}
.insight-card {
  background: #ffffff;
  border: 1px solid var(--rp-line, #e2e8f0);
  border-radius: 8px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: all 0.2s ease;
}
.insight-card:hover {
  border-color: #cbd5e1;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
}
.insight-card.is-emphasized {
  border: 1.5px solid #f59e0b;
  background: #fffdfa;
}
.insight-card.is-doubted {
  border: 1.5px dashed #f97316;
  background: #fffbf7;
}
.insight-card.is-rejected {
  opacity: 0.55;
  border: 1.5px solid #ef4444;
  background: #fef2f2;
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.head-left {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.insight-idx {
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, monospace;
  color: var(--rp-gold, #c5a059);
  font-weight: 700;
}
.insight-title {
  margin: 0;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--rp-navy, #1e3a5c);
}
.conf-pill {
  font-size: 10.5px;
  padding: 0 5px;
  height: 18px;
  line-height: 16px;
}

/* 标注按钮组 */
.annotation-actions {
  display: flex;
  gap: 4px;
}
.action-chip {
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  border-radius: 4px;
  font-size: 11px;
  color: #64748b;
  padding: 2px 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.action-chip:hover {
  background: #e2e8f0;
  color: #1e293b;
}
.action-chip.active {
  background: #1e3a5c;
  color: #ffffff;
  border-color: #1e3a5c;
}

.insight-conclusion {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.75;
  color: #334155;
  text-align: justify;
}
.insight-significance {
  background: #f8fafc;
  border-left: 2px solid var(--rp-navy, #1e3a5c);
  padding: 6px 10px;
  border-radius: 0 4px 4px 0;
  font-size: 11.5px;
  line-height: 1.6;
}
.sig-label {
  font-weight: 600;
  color: var(--rp-navy, #1e3a5c);
}
.sig-text {
  color: #475569;
}

.card-foot {
  margin-top: auto;
  padding-top: 6px;
  border-top: 1px dashed #edf2f7;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.evidence-cluster {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.evidence-lead {
  font-size: 11px;
  color: #94a3b8;
}
.evidence-tag-interactive {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 10px;
  cursor: pointer;
  transition: all 0.15s;
}
.evidence-tag-interactive:hover {
  color: #1d4ed8;
  border-color: #93c5fd;
  transform: translateY(-1px);
}
.more-tag {
  font-size: 10.5px;
}

/* 事实底稿表格 */
.fact-id-code {
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 11px;
  color: #0369a1;
  background: #f0f9ff;
  padding: 2px 4px;
  border-radius: 3px;
}

/* 量化指标视图 */
.sub-title {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--rp-navy, #1e3a5c);
}
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 10px;
}
.metric-pill-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.m-entity { font-size: 10.5px; }
.m-name { font-size: 12px; font-weight: 600; color: #1e293b; }
.m-value { font-size: 14px; font-weight: 700; color: #0284c7; }

.quant-duo-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 16px;
}
@media (max-width: 768px) {
  .quant-duo-grid { grid-template-columns: 1fr; }
}
.trend-list, .anomaly-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.trend-item, .anomaly-item {
  background: #ffffff;
  border: 1px solid #f1f5f9;
  border-radius: 4px;
  padding: 6px 10px;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.trend-badge {
  font-size: 10.5px;
  padding: 1px 5px;
  border-radius: 3px;
  font-weight: 600;
}
.trend-badge.up { background: #fee2e2; color: #b91c1c; }
.trend-badge.down { background: #dcfce7; color: #15803d; }
.trend-badge.stable { background: #f1f5f9; color: #64748b; }
.anomaly-tag {
  background: #fff7ed;
  color: #c2410c;
  font-size: 10.5px;
  padding: 1px 5px;
  border-radius: 3px;
  font-weight: 600;
}

/* 勾稽卡片 */
.cv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
}
.cv-card {
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 8px 12px;
  background: #ffffff;
}
.cv-card.is-pass { border-left: 3px solid #10b981; }
.cv-card.is-warn { border-left: 3px solid #f59e0b; }
.cv-status { font-size: 11px; font-weight: 600; display: block; margin-bottom: 2px; }
.cv-card.is-pass .cv-status { color: #10b981; }
.cv-card.is-warn .cv-status { color: #f59e0b; }
.cv-name { font-size: 12px; font-weight: 600; color: #1e293b; }
.cv-desc { margin: 2px 0 0; font-size: 11px; }

/* 覆盖率与风险 */
.cov-pills {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 10px;
}
.cov-box {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
}
.cov-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}
.cov-reason { margin: 0; font-size: 11.5px; }

.risk-cards {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.risk-card {
  background: #fffaf0;
  border: 1px solid #fed7aa;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 12px;
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.risk-badge {
  background: #ea580c;
  color: #ffffff;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 3px;
  white-space: nowrap;
}
.risk-content {
  color: #7c2d12;
  line-height: 1.5;
}
</style>
