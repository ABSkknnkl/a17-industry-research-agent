<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { ChartOption, ChartSpec } from '../api/types'

/** chart_generate 阶段 data.chart_specs 的宽松类型（与后端 ChartSpec 对齐，仅取渲染所需字段） */
type ChartSpecLoose = Partial<ChartSpec>

const props = defineProps<{ specs: ChartSpecLoose[] }>()

/** 与后端 presentation.CHART_TYPE_LABELS 对齐 */
const CHART_TYPE_LABELS: Record<string, string> = {
  line: '折线图',
  bar: '柱状图',
  comparison_bar: '涨跌幅对比图',
  pie: '饼图',
  radar: '雷达图',
  industry_chain: '产业链图',
  combo: '双轴组合图',
  area: '面积图',
  scatter: '散点图',
  bubble: '气泡图',
  heatmap: '热力图',
  boxplot: '箱线图',
  treemap: '矩形树图',
}

const usable = computed(() =>
  props.specs.filter((spec) => {
    if (!spec) return false
    if (spec.render_mode === 'generated_image') return Boolean(spec.image_uri)
    return Boolean(spec.option)
  })
)

// ---- 图表布局分类（与后端 display_size 契约一致）----
/** 数据点达到该数量即视为「长图表」：独占一整行（full），否则每行 2 个（half）。 */
const FULL_MIN_POINTS = 10

type DisplaySize = 'full' | 'half'

/** 后端已下发 display_size 时直接采用；旧产物/缺字段时按 option 数据量兜底估算。 */
function estimateDisplaySize(spec: ChartSpecLoose): DisplaySize {
  if (spec.chart_type === 'industry_chain') return 'full'
  const opt = spec.option
  const lengths: number[] = []
  const rawXAxis = opt?.xAxis
  if (Array.isArray(rawXAxis)) {
    for (const axis of rawXAxis) {
      if (axis && Array.isArray((axis as { data?: unknown[] }).data)) {
        lengths.push((axis as { data: unknown[] }).data.length)
      }
    }
  } else if (rawXAxis && Array.isArray((rawXAxis as { data?: unknown[] }).data)) {
    lengths.push((rawXAxis as { data: unknown[] }).data.length)
  }
  for (const series of Array.isArray(opt?.series)
    ? (opt.series as Array<Record<string, unknown>>)
    : []) {
    if (series && Array.isArray(series.data)) lengths.push((series.data as unknown[]).length)
  }
  return Math.max(0, ...lengths) >= FULL_MIN_POINTS ? 'full' : 'half'
}

function displaySizeOf(spec: ChartSpecLoose): DisplaySize {
  if (spec.display_size === 'full' || spec.display_size === 'half') return spec.display_size
  return estimateDisplaySize(spec)
}

/** 全宽长图表在前，半宽小图表在后。 */
const ordered = computed(() =>
  [...usable.value].sort((a, b) => {
    const rank = (spec: ChartSpecLoose): number => (displaySizeOf(spec) === 'full' ? 0 : 1)
    return rank(a) - rank(b)
  })
)

/** 渲染用 option：剥离绘图区内的纯文本注释（挪到卡片下方 footnotes），并统一 category 轴标签采样。 */
function sanitizedOption(spec: ChartSpecLoose): ChartOption | null {
  if (!spec.option) return null
  const graphic = Array.isArray(spec.option.graphic) ? spec.option.graphic : []
  const textGraphics = graphic.filter((g) => g && g.type === 'text')
  const option =
    textGraphics.length === 0 ? (spec.option as ChartOption) : stripTextGraphics(spec.option)
  uniformCategoryAxisLabels(option)
  sanitizeAxes(option)
  return option
}

/** 常见英文字段名 -> 中文规范业务标签字典 */
const TECHNICAL_NAME_MAP: Record<string, string> = {
  close_price: '收盘价',
  change_pct: '涨跌幅',
  trade_volume: '成交量',
  volume: '成交量',
  turnover: '成交额',
  open_price: '开盘价',
  high_price: '最高价',
  low_price: '最低价',
  debt_ratio: '资产负债率',
  parent_net_profit: '归母净利润',
  revenue: '营业收入',
  net_profit: '净利润',
  operating_cash_flow: '经营活动现金流',
  gross_margin: '毛利率',
  net_margin: '净利率',
}

function hasLargeOrDecimalValues(option: ChartOption): boolean {
  const series = Array.isArray(option.series) ? option.series : option.series ? [option.series] : []
  for (const s of series) {
    if (!s || !Array.isArray(s.data)) continue
    for (const val of s.data) {
      const num = typeof val === 'number' ? val : Array.isArray(val) ? Number(val[1]) : Number(val)
      if (!Number.isNaN(num) && (Math.abs(num) >= 10000 || (Math.abs(num) > 0 && Math.abs(num) < 0.01))) {
        return true
      }
    }
  }
  return false
}

function formatAxisValue(val: number | string): string {
  const num = Number(val)
  if (Number.isNaN(num)) return String(val)
  const abs = Math.abs(num)
  if (abs >= 1e8) return `${Number((num / 1e8).toFixed(1))}亿`
  if (abs >= 1e4) return `${Number((num / 1e4).toFixed(1))}万`
  if (abs >= 1000) return `${Math.round(num)}`
  if (abs >= 1) return `${Number(num.toFixed(2))}`
  if (abs > 0) return `${Number(num.toFixed(3))}`
  return '0'
}

function sanitizeAxes(option: ChartOption): void {
  const needsScaleDefense = hasLargeOrDecimalValues(option)
  const allAxes = [
    ...(Array.isArray(option.xAxis) ? option.xAxis : option.xAxis ? [option.xAxis] : []),
    ...(Array.isArray(option.yAxis) ? option.yAxis : option.yAxis ? [option.yAxis] : []),
  ] as Record<string, unknown>[]

  for (const axis of allAxes) {
    if (!axis || typeof axis !== 'object') continue
    const isCategory = axis.type === 'category' || (!axis.type && Array.isArray(axis.data))
    if (isCategory && Array.isArray(axis.data)) {
      let changed = false
      const mapped = axis.data.map((item) => {
        if (typeof item === 'string') {
          const trimmed = item.trim()
          const clean = TECHNICAL_NAME_MAP[trimmed] ?? TECHNICAL_NAME_MAP[trimmed.toLowerCase()]
          if (clean && clean !== trimmed) {
            changed = true
            return clean
          }
        }
        return item
      })
      const nonNull = mapped.filter((x) => x !== null && x !== undefined && x !== '')
      if (mapped.length > 1 && nonNull.length === mapped.length && new Set(nonNull).size === 1) {
        axis.data = mapped.map((val, idx) => `${val} #${idx + 1}`)
      } else if (changed) {
        axis.data = mapped
      }
    } else if (needsScaleDefense && (!axis.type || axis.type === 'value')) {
      const axisLabel = (axis.axisLabel ??= {}) as Record<string, unknown>
      if (!axisLabel.formatter) {
        axisLabel.formatter = formatAxisValue
      }
      if (axis.splitNumber === undefined) {
        axis.splitNumber = 4
      }
    }
  }

  const seriesList = (Array.isArray(option.series) ? option.series : option.series ? [option.series] : []) as Record<string, unknown>[]
  for (const s of seriesList) {
    if (s && typeof s.name === 'string') {
      const trimmed = s.name.trim()
      const clean = TECHNICAL_NAME_MAP[trimmed] ?? TECHNICAL_NAME_MAP[trimmed.toLowerCase()]
      if (clean) s.name = clean
    }
  }

  if (option.legend && typeof option.legend === 'object') {
    const leg = option.legend as Record<string, unknown>
    if (Array.isArray(leg.data)) {
      leg.data = leg.data.map((item) => {
        if (typeof item === 'string') {
          const trimmed = item.trim()
          return TECHNICAL_NAME_MAP[trimmed] ?? TECHNICAL_NAME_MAP[trimmed.toLowerCase()] ?? trimmed
        }
        return item
      })
    }
  }
}

/** 移除绘图区内的纯文本注释，保留参考线/遮蔽等非文字 graphic。 */
function stripTextGraphics(option: Record<string, unknown>): ChartOption {
  const cleaned = JSON.parse(JSON.stringify(option)) as Record<string, unknown>
  const graphic = Array.isArray(option.graphic) ? option.graphic : []
  const kept = graphic.filter((g) => !g || g.type !== 'text')
  if (kept.length > 0) cleaned.graphic = kept
  else delete cleaned.graphic
  return cleaned as ChartOption
}

/** 与后端 uniform_category_axis_labels 相同的采样规则：卡片/预览/报告三处标签一致；小数据图表不做改动。 */
const CATEGORY_MAX_LABELS = 12

function uniformCategoryAxisLabels(option: ChartOption): void {
  const rawAxes = option.xAxis as unknown
  const axes = Array.isArray(rawAxes) ? rawAxes : [rawAxes]
  for (const rawAxis of axes) {
    if (!rawAxis || typeof rawAxis !== 'object') continue
    const axis = rawAxis as Record<string, unknown>
    if (String(axis.type ?? 'category') !== 'category') continue
    const data = axis.data
    if (!Array.isArray(data) || data.length <= CATEGORY_MAX_LABELS) continue
    ;((axis as Record<string, Record<string, unknown>>).axisLabel ??= {}).interval =
      Math.ceil(data.length / CATEGORY_MAX_LABELS) - 1
  }
}

// ---- 缩略图渲染 ----
const thumbsRef = ref<HTMLElement[]>([])
const thumbInstances: echarts.ECharts[] = []
let resizeObserver: ResizeObserver | null = null

function chartFootnotes(spec: ChartSpecLoose | null): string[] {
  const notes = [
    ...new Set([
      ...(spec?.footnotes ?? []),
      ...(spec?.option?.footnotes ?? []),
      ...graphicTextNotes(spec?.option?.graphic as unknown),
    ]),
  ]
  return notes
}

/** 从 ECharts option.graphic 中收集纯文本注释（渲染时已从绘图区剥离，落到卡片下方）。 */
function graphicTextNotes(graphic: unknown): string[] {
  if (!Array.isArray(graphic)) return []
  const notes: string[] = []
  for (const item of graphic) {
    if (
      item &&
      (item as { type?: string }).type === 'text' &&
      typeof (item as { style?: { text?: unknown } }).style?.text === 'string'
    ) {
      notes.push((item as { style: { text: string } }).style.text)
    }
  }
  return notes
}

function renderThumbs(): void {
  disposeThumbs()
  if (props.specs.length === 0) return
  requestAnimationFrame(() => {
    ordered.value.forEach((spec, index) => {
      const el = thumbsRef.value[index]
      if (!el || !spec.option || spec.render_mode === 'generated_image') return
      const instance = echarts.init(el)
      instance.setOption(sanitizedOption(spec) ?? spec.option)
      thumbInstances.push(instance)
    })
    if (thumbInstances.length > 0) {
      resizeObserver = new ResizeObserver(() => {
        for (const instance of thumbInstances) instance.resize()
      })
      for (const instance of thumbInstances) {
        const dom = instance.getDom()
        if (dom.parentElement) resizeObserver.observe(dom.parentElement)
      }
    }
  })
}

function disposeThumbs(): void {
  resizeObserver?.disconnect()
  resizeObserver = null
  for (const instance of thumbInstances) instance.dispose()
  thumbInstances.length = 0
}

// ---- 大图预览 ----
const dialogVisible = ref(false)
const activeIndex = ref(0)
const dialogRef = ref<HTMLElement | null>(null)
let dialogInstance: echarts.ECharts | null = null

const activeSpec = computed(() => ordered.value[activeIndex.value] ?? null)

function openChart(index: number): void {
  activeIndex.value = index
  dialogVisible.value = true
}

watch(dialogVisible, (visible) => {
  if (!visible) {
    dialogInstance?.dispose()
    dialogInstance = null
  }
})

watch(activeSpec, async () => {
  if (!dialogVisible.value) return
  await nextTickRenderDialog()
})

async function nextTickRenderDialog(): Promise<void> {
  await new Promise((resolve) => requestAnimationFrame(resolve))
  if (!dialogRef.value || !activeSpec.value?.option) return
  if (activeSpec.value.render_mode === 'generated_image') return
  dialogInstance?.dispose()
  dialogInstance = echarts.init(dialogRef.value)
  dialogInstance.setOption(sanitizedOption(activeSpec.value) ?? activeSpec.value.option)
}

// ---- 展示辅助 ----
function typeLabel(type: string | undefined): string {
  if (!type) return '图表'
  return CHART_TYPE_LABELS[type] ?? type
}

function chartTitleId(spec: ChartSpecLoose, index: number): string {
  return `chart-title-${spec.chart_id ?? index}`
}

function chartPreviewLabel(spec: ChartSpecLoose): string {
  return `查看“${spec.title ?? '未命名图表'}”大图`
}

/** 版本号：spec 上有 unit_revision 时读取 */
function unitRevision(spec: ChartSpecLoose): number | null {
  return typeof spec.unit_revision === 'number' ? spec.unit_revision : null
}

function isLatest(spec: ChartSpecLoose): boolean {
  const rev = unitRevision(spec)
  if (rev === null) return false
  const revs = usable.value.map((s) => unitRevision(s)).filter((n): n is number => n !== null)
  return rev === Math.max(...revs)
}

function sourceLabel(spec: ChartSpecLoose): string | null {
  return spec.source_name ? spec.source_name : null
}

function updatedAtLabel(spec: ChartSpecLoose): string | null {
  const raw = spec.updated_at
  if (!raw) return null
  try {
    return new Date(raw).toLocaleString('zh-CN')
  } catch {
    return null
  }
}

onMounted(renderThumbs)
watch(
  () => props.specs,
  () => renderThumbs(),
  { deep: false }
)
onBeforeUnmount(disposeThumbs)
</script>

<script lang="ts">
export default { name: 'ChartGallery' }
</script>

<template>
  <div data-testid="chart-gallery">
    <el-empty
      v-if="usable.length === 0"
      description="暂无图表规格（chart_generate 阶段完成后可用）"
      :image-size="60"
    />
    <div v-else class="chart-list">
      <article
        v-for="(spec, index) in ordered"
        :key="spec.chart_id ?? index"
        :class="['chart-card', displaySizeOf(spec) === 'full' ? 'chart-full' : 'chart-half']"
        :aria-labelledby="chartTitleId(spec, index)"
      >
        <div class="chart-head" @click="openChart(index)">
          <div class="card-title-row">
            <h3 :id="chartTitleId(spec, index)" class="chart-title">
              {{ spec.title ?? '未命名图表' }}
            </h3>
            <span class="card-badges">
              <el-tag
                v-if="unitRevision(spec) !== null"
                size="small"
                type="primary"
                effect="plain"
                data-testid="chart-version-badge"
              >
                v{{ unitRevision(spec) }}
              </el-tag>
              <el-tag
                v-if="isLatest(spec)"
                size="small"
                type="warning"
                data-testid="chart-latest-badge"
              >
                最新
              </el-tag>
              <el-tag size="small" type="info" effect="plain">
                {{ typeLabel(spec.chart_type) }}
              </el-tag>
            </span>
          </div>
          <div class="card-meta">
            <span v-if="sourceLabel(spec)">来源：{{ sourceLabel(spec) }}</span>
            <span v-if="updatedAtLabel(spec)" class="meta-sep">·</span>
            <span v-if="updatedAtLabel(spec)">{{ updatedAtLabel(spec) }}</span>
          </div>
        </div>
        <!-- echarts 渲染 -->
        <div
          v-if="spec.render_mode !== 'generated_image'"
          class="chart-surface chart-thumb"
          role="button"
          tabindex="0"
          :aria-label="chartPreviewLabel(spec)"
          :ref="
            (el) => {
              thumbsRef[index] = el as HTMLElement
            }
          "
          @click="openChart(index)"
          @keydown.enter="openChart(index)"
          @keydown.space.prevent="openChart(index)"
        />
        <!-- AI 生成图 / SVG 产业链图：内联 URI -->
        <div v-else class="chart-thumb chart-img">
          <img
            v-if="spec.image_uri && /^(https?:|data:)/.test(spec.image_uri)"
            :src="spec.image_uri"
            :alt="spec.title ?? ''"
            data-testid="chart-svg-image"
          />
          <div v-else class="chart-img-missing muted">AI 生成图未内联，请从产出物下载查看</div>
        </div>
        <div v-if="spec.insight_goal" class="chart-insight">
          <span>分析目的</span>
          {{ spec.insight_goal }}
        </div>
        <div v-if="chartFootnotes(spec).length" class="chart-notes">
          <p v-for="(note, i) in chartFootnotes(spec)" :key="i" class="chart-footnote muted">
            {{ note }}
          </p>
        </div>
      </article>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="activeSpec?.title ?? '图表预览'"
      width="min(1120px, 94vw)"
      destroy-on-close
      data-testid="chart-preview-dialog"
      @opened="nextTickRenderDialog"
    >
      <div
        v-if="activeSpec?.render_mode === 'generated_image' && activeSpec.image_uri"
        class="chart-svg-preview"
      >
        <img :src="activeSpec.image_uri" :alt="activeSpec.title ?? ''" />
      </div>
      <div v-else ref="dialogRef" class="chart-large" />
      <div v-if="activeSpec?.insight_goal" class="chart-goal muted">
        分析目的：{{ activeSpec.insight_goal }}
      </div>
      <div
        v-for="(note, i) in chartFootnotes(activeSpec)"
        :key="i"
        class="chart-goal chart-footnote muted"
      >
        {{ note }}
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.chart-list {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.chart-card {
  min-width: 0;
  border: 1px solid var(--rp-line);
  border-radius: 12px;
  background: var(--rp-card);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
/* 长图表独占一整行；小图表每行放置 2 个，等宽填满行内空缺 */
.chart-full {
  width: 100%;
}
.chart-half {
  width: calc(50% - 6px);
}
@media (max-width: 900px) {
  .chart-half {
    width: 100%;
  }
}
.chart-head {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
  padding: 12px 14px 6px;
  cursor: zoom-in;
}
.card-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.card-badges {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.card-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 0;
  font-size: 12px;
  color: var(--rp-ink);
  opacity: 0.65;
}
.meta-sep {
  margin: 0 6px;
}
.chart-title {
  min-width: 0;
  margin: 0;
  font-family: var(--rp-serif);
  font-size: 15px;
  font-weight: 700;
  color: var(--rp-navy);
  line-height: 1.4;
}
.chart-surface {
  border-radius: 10px;
  margin: 0 10px;
  cursor: zoom-in;
  outline: none;
}
.chart-surface:focus-visible {
  box-shadow: 0 0 0 3px var(--el-color-primary-light-7);
}
.chart-thumb {
  width: 100%;
  height: 260px;
  background: var(--rp-paper);
}
/* 小图表保持充裕刻度空间，避免坐标轴与图例挤压重叠 */
.chart-half .chart-thumb {
  height: 240px;
}
.chart-img {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--rp-paper);
}
.chart-img img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}
.chart-img-missing {
  font-size: 12px;
  padding: 20px;
  color: var(--el-text-color-secondary);
}
.chart-insight {
  margin: 6px 14px 0;
  padding: 10px 0 8px;
  border-top: 1px solid var(--el-border-color-extra-light);
  color: var(--el-text-color-regular);
  font-size: 12.5px;
  line-height: 1.6;
}
.chart-insight span {
  color: var(--rp-navy);
  font-weight: 700;
  margin-right: 8px;
}
.chart-notes {
  padding: 0 14px 10px;
}
.chart-footnote {
  margin: 2px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 11.5px;
  line-height: 1.55;
}
/* 预览弹窗内说明 */
.chart-goal {
  font-size: 12px;
  line-height: 1.6;
}
.chart-goal.muted {
  color: var(--rp-ink);
  opacity: 0.7;
}
.chart-large {
  width: 100%;
  height: min(66vh, 640px);
  min-height: 440px;
}
.chart-svg-preview {
  display: flex;
  justify-content: center;
  background: var(--rp-paper);
  padding: 8px;
}
.chart-svg-preview img {
  max-width: 100%;
  height: auto;
}
</style>
