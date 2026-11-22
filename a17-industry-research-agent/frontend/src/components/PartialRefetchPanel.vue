<script setup lang="ts">
/**
 * 局部子域重采 v2：把「点级重采清单」和「大模型探针」合成一个前端组件。
 *
 * - 清单负责「取什么」：勾到单个数据点，默认只预选缺口与低可信项
 * - 探针负责「怎么取」：改写查询、换 skill、最多 4 轮自纠错
 * - 后端契约保持不变：action_type=partial_refetch + domains + data_point_ids + entities
 *   + query_hint + probe_mode + calibration
 *
 * 清单数据全部来自后端 A1 产出：已采点取 source_records，缺口点取
 * metric_requirements 中 passed=false 的指标项。组件不再内置任何样例数值。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { PropType } from 'vue'
import { metricLabel, normalizeMetricAmount, skillLabel } from '../api/labels'

const props = defineProps({
  data: { type: Object as PropType<Record<string, unknown>>, required: true },
  submitting: { type: Boolean, default: false },
})

const emit = defineEmits<{
  (e: 'submit', payload: { comment: string; edited_data: Record<string, unknown> }): void
}>()

// ---------------------------------------------------------------- 类型
interface RefetchPoint {
  id: string
  label: string
  entity: string
  period: string
  value: string
  source: string
  sourceKind: string
  confidence: number
  gap: string
  checked: boolean
}
interface RefetchGroup {
  id: string
  /** 未经过滤的全量点，用于计算分组覆盖率 */
  allPoints?: RefetchPoint[]
  name: string
  points: RefetchPoint[]
}
interface PointSpec {
  id: string
  label: string
  entity: string
  period: string
  value: string
  source: string
  sourceKind: string
  confidence: number
  gap?: string
}

// ---------------------------------------------------------------- 上下文
function cleanName(raw: string): string {
  return raw
    .replace(/\(.*?\)/g, '')
    .replace(/（.*?）/g, '')
    .trim()
}

const contextEntities = computed<string[]>(() => {
  const recs = (props.data?.source_records || props.data?.records || []) as Array<
    Record<string, unknown>
  >
  const set = new Set<string>()
  for (const r of recs) {
    const name = String(r.entity_name ?? r.entity ?? r.name ?? '')
    const clean = cleanName(name)
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
  return Array.from(set)
})

const topic = computed<string>(() => {
  const raw = String(
    props.data?.industry_topic || props.data?.topic || props.data?.industry || ''
  ).trim()
  if (!raw) return '行业'
  const cleaned = raw.replace(/行业研究报告|行业分析报告|深度研究报告|行业研究报告/g, '').trim()
  return cleaned.endsWith('行业') ? cleaned : `${cleaned}行业`
})

// ---------------------------------------------------------------- 清单
const CALIBER_UNIVERSE_OPTIONS = [
  { value: 'a_share', label: 'A股核心标的' },
  { value: 'hk', label: '港股对标' },
  { value: 'unlisted', label: '未上市龙头' },
  { value: 'global', label: '全球同业' },
]
const CALIBER_BASIS_OPTIONS = [
  { value: 'consolidated', label: '合并报表（年报口径）' },
  { value: 'single_quarter', label: '单季度口径' },
  { value: 'deducted', label: '扣非口径' },
  { value: 'as_reported', label: '按原文披露不调整' },
]

const groups = ref<RefetchGroup[]>([])

function buildPoint(spec: PointSpec): RefetchPoint {
  return {
    id: spec.id,
    label: spec.label,
    entity: spec.entity,
    period: spec.period,
    value: spec.value,
    source: spec.source,
    sourceKind: spec.sourceKind,
    confidence: spec.confidence,
    gap: spec.gap || '',
    checked: !spec.value,
  }
}

/** 后端 domain → 分组展示名（未收录回退原文，不丢信息） */
const DOMAIN_NAMES: Record<string, string> = {
  financials: '财务与经营质量',
  industry: '行业规模与景气',
  industry_chain: '产业链与供给',
  competitors: '竞争格局与标的',
  macro: '宏观与政策',
  news: '事件与催化',
}

function formatRecordValue(raw: unknown, unit: unknown): string {
  if (raw === null || raw === undefined || raw === '') return ''
  const u = String(unit ?? '').trim()
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    const amount = normalizeMetricAmount(raw, u)
    return [amount.value, amount.unit].filter(Boolean).join(' ')
  }
  return [String(raw), u].filter(Boolean).join(' ')
}

/**
 * P0-4：清单必须来自 A1 真实产出的 `source_records[]`。
 *
 * 历史实现写死 18 个点（F-01…P-04）连同假数值/假可信度，而非演示模式下后端
 * `_supplement_demand` 只消费 domains / entities / query_hint / reason / probe_mode，
 * `data_point_ids` 会被静默丢弃 —— 结果是「勾了假点、拿假数值去检索」。
 *
 * 现在：
 *   - 已采点 = source_records，id 用真实 record_id；
 *   - 缺口点 = metric_requirements 里 passed=false 的指标项（后端权威口径）；
 *   - 可信度后端未下发，一律留 0（显示「—」），不再编造 96/91/62。
 */
function initGroups(): void {
  const records = (props.data?.source_records || props.data?.records || []) as Array<
    Record<string, unknown>
  >
  const requirements = (props.data?.metric_requirements || []) as Array<Record<string, unknown>>
  const specs = new Map<string, PointSpec[]>()
  const push = (domain: string, spec: PointSpec) => {
    const key = domain || 'financials'
    if (!specs.has(key)) specs.set(key, [])
    specs.get(key)!.push(spec)
  }

  if (Array.isArray(records)) {
    records.forEach((r, i) => {
      const metric = String(r.metric ?? r.name ?? '').trim()
      if (!metric) return
      push(String(r.domain ?? 'financials'), {
        id: String(r.record_id ?? `R-${i + 1}`),
        label: metricLabel(metric) || metric,
        entity: cleanName(String(r.entity_name ?? r.entity ?? '')) || topic.value,
        period: String(r.period ?? ''),
        value: formatRecordValue(r.value, r.unit),
        source: skillLabel(String(r.skill_name ?? '')) || '—',
        sourceKind: String(r.domain ?? ''),
        confidence: 0,
        gap: '',
      })
    })
  }

  if (Array.isArray(requirements)) {
    for (const req of requirements) {
      if (req.passed !== false) continue
      const terms = Array.isArray(req.metric_terms) ? (req.metric_terms as unknown[]) : []
      const domain = String(req.domain ?? 'financials')
      const label = String(req.label ?? req.requirement_id ?? '未满足的取数要求')
      const termsToShow = terms.length ? terms : [label]
      termsToShow.forEach((term, i) => {
        const metric = String(term)
        push(domain, {
          id: `REQ:${String(req.requirement_id ?? 'unknown')}:${i}`,
          label: metricLabel(metric) || metric,
          entity: topic.value,
          period: '',
          value: '',
          source: '待补采',
          sourceKind: domain,
          confidence: 0,
          gap: label,
        })
      })
    }
  }

  groups.value = Array.from(specs.entries()).map(([id, items]) => ({
    id,
    name: DOMAIN_NAMES[id] ?? id,
    points: items.map(buildPoint),
  }))
}

/** 无真实数据点时整表空态，只保留「清单外补充诉求」通路 */
const hasRealPoints = computed(() => groups.value.some((g) => g.points.length > 0))

initGroups()

// ---------------------------------------------------------------- 筛选与统计
const filter = ref<'all' | 'gap'>('all')

const allPoints = computed<RefetchPoint[]>(() => groups.value.flatMap((g) => g.points))
const totalCount = computed(() => allPoints.value.length)
const missingCount = computed(() => allPoints.value.filter((p) => !p.value).length)
const lowConfCount = computed(
  () => allPoints.value.filter((p) => p.value && p.confidence > 0 && p.confidence < 70).length
)
const selectedPoints = computed(() => allPoints.value.filter((p) => p.checked))

/** 「只看待处理」= 缺值 或 低可信（可信度 < 70），与默认勾选口径一致 */
function needsAttention(point: RefetchPoint): boolean {
  return !point.value || (point.confidence > 0 && point.confidence < 70)
}

const visibleGroups = computed(() =>
  groups.value
    .map((g) => ({
      ...g,
      allPoints: g.points,
      points: filter.value === 'gap' ? g.points.filter(needsAttention) : g.points,
    }))
    .filter((g) => g.points.length > 0)
)

function groupCoverage(group: RefetchGroup): string {
  const pts = group.allPoints ?? group.points
  const got = pts.filter((p) => p.value).length
  return `${got}/${pts.length} 已采到`
}

function groupGapPoints(group: RefetchGroup): RefetchPoint[] {
  return group.points.filter((p) => !p.value)
}

function groupGapsAllOn(group: RefetchGroup): boolean {
  const gaps = groupGapPoints(group)
  return gaps.length > 0 && gaps.every((p) => p.checked)
}

function toggleGroupGaps(group: RefetchGroup): void {
  const allOn = groupGapsAllOn(group)
  for (const p of groupGapPoints(group)) p.checked = !allOn
}

function selectOnlyGaps(): void {
  for (const p of allPoints.value) p.checked = !p.value
}

function clearSelection(): void {
  for (const p of allPoints.value) p.checked = false
}

function confidenceTone(value: number): 'high' | 'mid' | 'low' | 'none' {
  if (!value) return 'none'
  if (value >= 85) return 'high'
  if (value >= 70) return 'mid'
  return 'low'
}

// ---------------------------------------------------------------- 口径
const timeRangeYears = ref(3)
const universe = ref<string[]>(['a_share'])
const financeBasis = ref('consolidated')
const rememberCaliber = ref(true)
const attachWorksheet = ref(true)
const extraNote = ref('')

const TIME_RANGE_OPTIONS = [
  { value: 1, label: '最近 1 年' },
  { value: 3, label: '最近 3 年' },
  { value: 5, label: '最近 5 年' },
]

// ---------------------------------------------------------------- 取数方式
const probeMode = ref<'llm_dynamic' | 'static'>('llm_dynamic')
const probeHint = ref('')

const probeStepList = [
  '组装查询：实体 + 指标 + 期间 + 口径',
  '选择能力：按指标类型挑 skill / 数据源',
  '解析校验：检查字段与口径是否对得上',
  '写入底稿：命中即替换，未命中保留原值',
]

const estimatedRecords = computed(() => selectedPoints.value.length * 6)
const estimatedMinutes = computed(() => {
  const base = (estimatedRecords.value * 5) / 60
  const factor = probeMode.value === 'llm_dynamic' ? 1.5 : 1
  return Math.max(1, Math.round(base * factor))
})
const probeCallBudget = computed(() => selectedPoints.value.length * 4)

// ---------------------------------------------------------------- 提交
const showPayload = ref(false)

function domainOfSelected(): string[] {
  const ids = new Set(selectedPoints.value.map((p) => groupOfPoint(p.id)))
  return Array.from(ids)
}

function groupOfPoint(pointId: string): string {
  const hit = groups.value.find((g) => g.points.some((p) => p.id === pointId))
  return hit?.id || 'financials'
}

function buildQueryHint(): string {
  const list = selectedPoints.value.map((p) => `${p.entity}·${p.label}(${p.period})`).join('；')
  const parts = [
    `补采 ${selectedPoints.value.length} 个数据点：${list}`,
    `时间范围：最近 ${timeRangeYears.value} 年`,
  ]
  if (universe.value.length) {
    const labels = universe.value
      .map((v) => CALIBER_UNIVERSE_OPTIONS.find((o) => o.value === v)?.label || v)
      .join('/')
    parts.push(`标的池：${labels}`)
  }
  const basis = CALIBER_BASIS_OPTIONS.find((o) => o.value === financeBasis.value)?.label
  if (basis) parts.push(`财务口径：${basis}`)
  if (extraNote.value.trim()) parts.push(`补充说明：${extraNote.value.trim()}`)
  if (probeMode.value === 'llm_dynamic' && probeHint.value.trim()) {
    parts.push(`检索约束：${probeHint.value.trim()}`)
  }
  return parts.join('；')
}

const adhocText = computed(() => extraNote.value.trim())
/** 不勾任何点、只填补充诉求：等价于原来的自由文本探针补采 */
const isAdhocOnly = computed(() => selectedPoints.value.length === 0 && adhocText.value.length > 0)

const payloadPreview = computed(() => {
  if (isAdhocOnly.value) {
    return { action_type: 'replenish', demand: buildAdhocDemand() }
  }
  return {
    action_type: 'partial_refetch',
    domains: domainOfSelected(),
    data_point_ids: selectedPoints.value.map((p) => p.id),
    entities: Array.from(
      new Set(
        selectedPoints.value
          .map((p) => p.entity)
          .filter((e) => !['行业大盘', '上游环节', '中游制造', '下游应用', '政策口径'].includes(e))
      )
    ),
    query_hint: buildQueryHint(),
    reason: '局部子域重采',
    probe_mode: probeMode.value,
    calibration: {
      time_range_years: timeRangeYears.value,
      universe: universe.value,
      finance_basis: financeBasis.value,
      remember: rememberCaliber.value,
    },
    attach_worksheet: attachWorksheet.value,
  }
})

const submitLabel = computed(() => {
  if (isAdhocOnly.value) return '补采清单外诉求'
  return probeMode.value === 'llm_dynamic' ? '启动定向补采' : '启动定向补采'
})

function basisLabel(): string {
  return CALIBER_BASIS_OPTIONS.find((o) => o.value === financeBasis.value)?.label || ''
}

/** 清单外诉求沿用后端既有的 replenish 契约，避免动后端 */
function buildAdhocDemand(): Record<string, unknown> {
  const parts = [adhocText.value, `时间范围：最近 ${timeRangeYears.value} 年`]
  if (basisLabel()) parts.push(`财务口径：${basisLabel()}`)
  if (probeHint.value.trim() && probeMode.value === 'llm_dynamic') {
    parts.push(`检索约束：${probeHint.value.trim()}`)
  }
  return {
    domain: 'financials',
    entities: contextEntities.value.slice(0, 3),
    query_hint: parts.join('；'),
    reason: '清单外临时补采（从局部子域重采提交）',
    probe_mode: probeMode.value,
  }
}

function submit(): void {
  if (!selectedPoints.value.length) {
    if (!adhocText.value) {
      ElMessage.warning('请勾选数据点，或在「清单外补充诉求」里写一条')
      return
    }
    emit('submit', {
      comment: `清单外补充诉求：${adhocText.value.slice(0, 40)}`,
      edited_data: { action_type: 'replenish', demand: buildAdhocDemand() },
    })
    return
  }
  if (!universe.value.length) {
    ElMessage.warning('请至少选择一个标的池')
    return
  }
  const payload = payloadPreview.value
  emit('submit', {
    comment: `局部子域重采 ${selectedPoints.value.length} 个数据点（${probeMode.value === 'llm_dynamic' ? '多轮检索' : '常规单次查询'}）`,
    edited_data: payload,
  })
}
</script>

<template>
  <div class="prp">
    <!-- 无真实数据点：整表空态，只保留「清单外补充诉求」通路 -->
    <el-empty
      v-if="!hasRealPoints"
      description="本阶段未回传可补采数据点，可在下方「清单外补充诉求」写明要补的实体、指标与期间"
      :image-size="80"
      data-testid="refetch-empty"
    />

    <!-- 覆盖条 -->
    <div v-if="hasRealPoints" class="prp-coverage">
      <div class="prp-stat">
        <span class="prp-num">{{ totalCount - missingCount }}</span>
        <span class="prp-label">已采数据点 / 共 {{ totalCount }}</span>
      </div>
      <div class="prp-stat warn">
        <span class="prp-num">{{ missingCount }}</span>
        <span class="prp-label">缺失待补</span>
      </div>
      <div class="prp-stat low">
        <span class="prp-num">{{ lowConfCount }}</span>
        <span class="prp-label">低可信待核</span>
      </div>
      <div class="prp-actions">
        <el-button size="small" text @click="selectOnlyGaps">只选缺口</el-button>
        <el-button size="small" text @click="clearSelection">清空</el-button>
        <el-radio-group v-model="filter" size="small">
          <el-radio-button value="all">全部 {{ totalCount }}</el-radio-button>
          <el-radio-button value="gap"
            >只看待处理（{{ missingCount + lowConfCount }}）</el-radio-button
          >
        </el-radio-group>
      </div>
    </div>

    <div v-if="hasRealPoints" class="prp-lead">
      全部
      {{ totalCount }} 个点都列出来，<strong>已采到的不勾</strong>（勾了才会重采、覆盖原值）；只预勾
      {{ missingCount }} 个缺口。要按新口径重抓，手动勾上对应的已采项即可。
    </div>

    <!-- 点级清单 -->
    <div v-if="hasRealPoints" class="prp-groups">
      <div v-for="group in visibleGroups" :key="group.id" class="prp-group">
        <div class="prp-group-head">
          <div class="prp-group-title">
            <span>{{ group.name }}</span>
            <span class="prp-group-meta">&nbsp;{{ groupCoverage(group) }}</span>
          </div>
          <button
            v-if="groupGapPoints(group).length"
            type="button"
            class="prp-link"
            @click="toggleGroupGaps(group)"
          >
            {{
              groupGapsAllOn(group)
                ? '取消本组缺口'
                : `全选本组缺口（${groupGapPoints(group).length}）`
            }}
          </button>
        </div>
        <div class="prp-list">
          <div
            v-for="point in group.points"
            :key="point.id"
            class="prp-row"
            :class="{ on: point.checked, missing: !point.value }"
            @click="point.checked = !point.checked"
          >
            <el-checkbox v-model="point.checked" @click.stop />
            <div class="prp-main">
              <span class="prp-point-label">{{ point.label }}</span>
              <span class="prp-point-sub">{{ point.entity }} · {{ point.period }}</span>
            </div>
            <div class="prp-value" :class="{ empty: !point.value }">
              {{ point.value || '缺失' }}
            </div>
            <div class="prp-source">
              <el-tag
                size="small"
                :type="point.sourceKind === 'annual_report' ? 'success' : 'info'"
              >
                {{ point.source }}
              </el-tag>
            </div>
            <div class="prp-conf" :class="confidenceTone(point.confidence)">
              <span class="prp-dot" />
              <span>{{ point.confidence ? `${point.confidence}%` : '—' }}</span>
            </div>
            <div class="prp-gap">
              {{
                point.gap ||
                (point.confidence > 0 && point.confidence < 70
                  ? '原数据 · 低可信待核'
                  : '原数据可用')
              }}
            </div>
          </div>
        </div>
      </div>
      <el-empty v-if="!visibleGroups.length" description="没有待补数据点" />
    </div>

    <!-- 口径 -->
    <div class="prp-caliber">
      <div class="prp-caliber-head">
        重采口径
        <span>时间范围、标的池、财务口径会一起作为限定条件下发，避免新旧口径打架</span>
      </div>
      <div class="prp-caliber-grid">
        <div class="prp-field">
          <label>时间范围</label>
          <el-select v-model="timeRangeYears" size="small">
            <el-option
              v-for="opt in TIME_RANGE_OPTIONS"
              :key="opt.value"
              :value="opt.value"
              :label="opt.label"
            />
          </el-select>
        </div>
        <div class="prp-field">
          <label>财务口径</label>
          <el-select v-model="financeBasis" size="small">
            <el-option
              v-for="opt in CALIBER_BASIS_OPTIONS"
              :key="opt.value"
              :value="opt.value"
              :label="opt.label"
            />
          </el-select>
        </div>
      </div>
      <div class="prp-field">
        <label>标的池</label>
        <el-checkbox-group v-model="universe" size="small">
          <el-checkbox
            v-for="opt in CALIBER_UNIVERSE_OPTIONS"
            :key="opt.value"
            :value="opt.value"
            border
          >
            {{ opt.label }}
          </el-checkbox>
        </el-checkbox-group>
      </div>

      <!-- 取数方式：与探针合并的核心 -->
      <div class="prp-field">
        <label>取数方式</label>
        <el-radio-group v-model="probeMode" size="small">
          <el-radio-button value="llm_dynamic">多轮检索（AI）</el-radio-button>
          <el-radio-button value="static">常规单次查询</el-radio-button>
        </el-radio-group>
      </div>

      <div v-if="probeMode === 'llm_dynamic'" class="prp-probe">
        <div class="prp-probe-head">
          <span class="prp-probe-title">补采执行方式</span>
          <span class="prp-probe-meta">
            已选 {{ selectedPoints.length }} 点 · 最多 {{ probeCallBudget }} 次改写 / 调用
          </span>
        </div>
        <ol class="prp-steps">
          <li v-for="(step, index) in probeStepList" :key="step">
            <span class="prp-step-index">{{ index + 1 }}</span>
            <span>{{ step }}</span>
          </li>
        </ol>
        <div class="prp-probe-note">
          失败兜底：任意一点连续 4
          轮未命中即放弃该点，<strong>保留原值并标注</strong>，不会把已有数据抹掉。
        </div>
        <el-input
          v-model="probeHint"
          size="small"
          placeholder="检索约束（可选）：例如只取三季报合并口径，港股标的除外"
        />
      </div>
      <div v-else class="prp-static-note">
        常规单次查询：主链路只发一次查询、不改写关键词，冷门指标容易空手而归——只建议用于口径明确的标准指标。
      </div>

      <div class="prp-adhoc">
        <label>清单外补充诉求（可留空）</label>
        <el-input
          v-model="extraNote"
          size="small"
          placeholder="例如：东南亚某国 10 月销量也缺，一并补采。不勾任何数据点、只填这里，等于单跑一次多轮检索补这一条"
        />
      </div>
      <div class="prp-switches">
        <el-checkbox v-model="rememberCaliber" size="small"
          >记住这套口径，下次打开自动带入</el-checkbox
        >
        <el-checkbox v-model="attachWorksheet" size="small">
          重采后生成「数据底稿说明」（可贴报告附录 / 合规备查）
        </el-checkbox>
      </div>
    </div>

    <div class="prp-diff-tip">
      重采完成后会给出新旧对比：哪几个数变了、从多少变成多少、影响哪些章节；未勾选的数据保持原值不动。
    </div>

    <!-- 底部 -->
    <div class="prp-footer">
      <div class="prp-sum">
        <template v-if="selectedPoints.length">
          已选 <strong>{{ selectedPoints.length }}</strong> 个数据点
          <span> · 预计新增 {{ estimatedRecords }} 条记录 · 约 {{ estimatedMinutes }} 分钟</span>
          <span class="prp-keep">
            · 未勾的 {{ totalCount - selectedPoints.length }} 条沿用原数据，不覆盖</span
          >
        </template>
        <template v-else-if="isAdhocOnly">
          未勾选数据点 · 将只按「清单外补充诉求」跑一次{{
            probeMode === 'llm_dynamic' ? '多轮检索' : '单次查询'
          }}
        </template>
        <template v-else> 已选 <strong>0</strong> 个数据点 </template>
      </div>
      <div class="prp-footer-actions">
        <el-button size="small" text @click="showPayload = !showPayload">
          {{ showPayload ? '隐藏' : '查看' }}提交内容
        </el-button>
        <el-button
          type="primary"
          :loading="submitting"
          :disabled="!selectedPoints.length && !isAdhocOnly"
          @click="submit"
        >
          {{ submitLabel }}
        </el-button>
      </div>
    </div>

    <div v-if="showPayload" class="prp-payload">
      <pre>{{ JSON.stringify(payloadPreview, null, 2) }}</pre>
    </div>

    <div class="prp-topic-hint">当前语境：{{ topic }}</div>
  </div>
</template>

<style scoped>
.prp {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.prp-coverage {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 10px 14px;
  background: #f7f8fa;
  border: 1px solid #e5e6eb;
  border-radius: 6px;
}
.prp-stat {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.prp-stat .prp-num {
  font-size: 18px;
  font-weight: 700;
  color: #1f2329;
}
.prp-stat.warn .prp-num {
  color: #d4380d;
}
.prp-stat.low .prp-num {
  color: #d48806;
}
.prp-label {
  font-size: 12px;
  color: #646a73;
}
.prp-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}
.prp-lead {
  font-size: 12.5px;
  color: #646a73;
}
.prp-lead strong {
  color: #1f2329;
}

.prp-groups {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.prp-group {
  flex: none;
  border: 1px solid #e5e6eb;
  border-radius: 6px;
  overflow: hidden;
}
.prp-group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #fafbfc;
  border-bottom: 1px solid #f0f1f3;
}
.prp-group-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: #1f2329;
}
.prp-group-meta {
  font-size: 11.5px;
  font-weight: 400;
  color: #8f959e;
}
.prp-link {
  border: 0;
  background: none;
  padding: 0;
  font-size: 12px;
  color: #1f4f8f;
  cursor: pointer;
}
.prp-list {
  display: flex;
  flex-direction: column;
}
.prp-row {
  display: grid;
  grid-template-columns: 28px 1.5fr 1fr 1fr 90px 1.1fr;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  border-bottom: 1px solid #f5f6f8;
  cursor: pointer;
}
.prp-row:last-child {
  border-bottom: 0;
}
.prp-row.on {
  background: #f0f5ff;
}
.prp-row.missing .prp-point-label {
  color: #1f2329;
}
.prp-main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.prp-point-label {
  font-size: 12.5px;
  color: #1f2329;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.prp-point-sub {
  font-size: 11px;
  color: #8f959e;
}
.prp-value {
  font-size: 12.5px;
  color: #1f2329;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.prp-value.empty {
  color: #d4380d;
  font-weight: 600;
}
.prp-source {
  display: flex;
}
.prp-conf {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  color: #646a73;
}
.prp-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #c9cdd4;
}
.prp-conf.high .prp-dot {
  background: #52c41a;
}
.prp-conf.mid .prp-dot {
  background: #faad14;
}
.prp-conf.low .prp-dot {
  background: #f5222d;
}
.prp-gap {
  font-size: 11.5px;
  color: #8f959e;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.prp-row.missing .prp-gap {
  color: #d48806;
}
.prp-caliber {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px 14px;
  border: 1px dashed #d9dce1;
  border-radius: 6px;
}
.prp-caliber-head {
  font-size: 12.5px;
  font-weight: 600;
  color: #1f2329;
}
.prp-caliber-head span {
  margin-left: 8px;
  font-weight: 400;
  color: #8f959e;
}
.prp-caliber-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.prp-field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.prp-field label {
  font-size: 12px;
  color: #646a73;
}
.prp-probe {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  background: #f4f8ff;
  border: 1px solid #d6e4ff;
  border-radius: 6px;
}
.prp-probe-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.prp-probe-title {
  font-size: 12.5px;
  font-weight: 600;
  color: #1f4f8f;
}
.prp-probe-meta {
  font-size: 11.5px;
  color: #646a73;
}
.prp-steps {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 6px 14px;
}
.prp-steps li {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 11.5px;
  color: #4e5969;
}
.prp-step-index {
  flex: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #1f4f8f;
  color: #fff;
  font-size: 10.5px;
  line-height: 16px;
  text-align: center;
}
.prp-probe-note {
  font-size: 11.5px;
  color: #646a73;
  background: #fff;
  border-radius: 4px;
  padding: 6px 8px;
}
.prp-probe-note strong {
  color: #1f2329;
}
.prp-static-note {
  font-size: 11.5px;
  color: #ad6800;
  background: #fffbe6;
  border: 1px solid #ffe58f;
  border-radius: 4px;
  padding: 6px 8px;
}
.prp-switches {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
}
.prp-diff-tip {
  font-size: 11.5px;
  color: #646a73;
  background: #f7f8fa;
  border-radius: 4px;
  padding: 7px 10px;
}
.prp-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.prp-sum {
  font-size: 12px;
  color: #646a73;
}
.prp-keep {
  color: #8f959e;
}
.prp-sum strong {
  color: #1f2329;
}
.prp-footer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.prp-payload {
  background: #f7f8fa;
  border-radius: 6px;
  padding: 10px 12px;
  max-height: 220px;
  overflow: auto;
}
.prp-payload pre {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  color: #1f2329;
}
.prp-topic-hint {
  font-size: 11px;
  color: #b0b4bc;
}
</style>
