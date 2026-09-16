<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import type { ChartSpec } from '../api/types'

/** chart_generate 阶段 data.chart_specs 的宽松类型（与后端 ChartSpec 对齐，仅取渲染所需字段） */
type ChartSpecLoose = Partial<ChartSpec>

const props = defineProps<{ specs: ChartSpecLoose[] }>()

/** 与后端 presentation.CHART_TYPE_LABELS 对齐 */
const CHART_TYPE_LABELS: Record<string, string> = {
  line: '折线图',
  bar: '柱状图',
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
  props.specs.filter((spec) => spec && spec.option && typeof spec.option === 'object')
)

const thumbsRef = ref<HTMLElement[]>([])
const thumbInstances: echarts.ECharts[] = []
let resizeObserver: ResizeObserver | null = null

function chartFootnotes(spec: ChartSpecLoose | null): string[] {
  return [...new Set([...(spec?.footnotes ?? []), ...(spec?.option?.footnotes ?? [])])]
}

function renderThumbs(): void {
  disposeThumbs()
  if (props.specs.length === 0) return
  requestAnimationFrame(() => {
    usable.value.forEach((spec, index) => {
      const el = thumbsRef.value[index]
      if (!el || !spec.option) return
      const instance = echarts.init(el)
      instance.setOption(spec.option)
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

const activeSpec = computed(() => usable.value[activeIndex.value] ?? null)

function openChart(index: number): void {
  activeIndex.value = index
  dialogVisible.value = true
}

watch(dialogVisible, async (visible) => {
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
  dialogInstance?.dispose()
  dialogInstance = echarts.init(dialogRef.value)
  dialogInstance.setOption(activeSpec.value.option)
}

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
  <div>
    <el-empty
      v-if="usable.length === 0"
      description="暂无图表规格（chart_generate 阶段完成后可用）"
      :image-size="60"
    />
    <div v-else class="chart-list">
      <article
        v-for="(spec, index) in usable"
        :key="spec.chart_id ?? index"
        class="chart-card"
        :aria-labelledby="chartTitleId(spec, index)"
      >
        <div class="chart-head" @click="openChart(index)">
          <h3 :id="chartTitleId(spec, index)" class="chart-title">
            {{ spec.title ?? '未命名图表' }}
          </h3>
          <el-tag size="small" type="info" effect="plain">{{ typeLabel(spec.chart_type) }}</el-tag>
        </div>
        <div
          class="chart-surface"
          role="button"
          tabindex="0"
          :aria-label="chartPreviewLabel(spec)"
          @click="openChart(index)"
          @keydown.enter="openChart(index)"
          @keydown.space.prevent="openChart(index)"
        >
          <!-- echarts 渲染 -->
          <div
            v-if="spec.render_mode !== 'generated_image'"
            :ref="
              (el) => {
                thumbsRef[index] = el as HTMLElement
              }
            "
            class="chart-thumb"
          />
          <!-- AI 生成图（行业链路图等）：仅内联可用的 URI -->
          <div v-else class="chart-thumb chart-img">
            <img
              v-if="spec.image_uri && /^(https?:|data:)/.test(spec.image_uri)"
              :src="spec.image_uri"
              :alt="spec.title ?? ''"
            />
            <div v-else class="chart-img-missing muted">AI 生成图未内联，请从产出物下载查看</div>
          </div>
        </div>
        <p v-if="spec.insight_goal" class="chart-insight">
          <span>分析目的</span>{{ spec.insight_goal }}
        </p>
        <div v-if="chartFootnotes(spec).length" class="chart-notes">
          <p v-for="(note, i) in chartFootnotes(spec)" :key="i" class="chart-footnote">
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
      @opened="nextTickRenderDialog"
    >
      <div ref="dialogRef" class="chart-large" />
      <div v-if="activeSpec?.insight_goal" class="chart-goal muted" style="margin-top: 8px">
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
  flex-direction: column;
  gap: 18px;
}
.chart-card {
  min-width: 0;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 14px;
  background: var(--el-bg-color);
  overflow: hidden;
}
.chart-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 22px 8px;
  cursor: zoom-in;
}
.chart-title {
  min-width: 0;
  margin: 0;
  font-family: var(--rp-serif);
  font-size: 18px;
  font-weight: 700;
  color: var(--rp-navy);
  line-height: 1.35;
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
  height: clamp(320px, 42vw, 460px);
}
.chart-img {
  display: flex;
  align-items: center;
  justify-content: center;
}
.chart-img img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}
.chart-img-missing {
  font-size: 12px;
  padding: 20px;
}
.chart-insight {
  margin: 4px 22px 0;
  padding: 14px 0 12px;
  border-top: 1px solid var(--el-border-color-extra-light);
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.6;
}
.chart-insight span {
  color: var(--rp-navy);
  font-weight: 700;
  margin-right: 10px;
}
.chart-notes {
  padding: 0 22px 14px;
}
.chart-footnote {
  margin: 2px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 11.5px;
  line-height: 1.55;
}
.chart-large {
  width: 100%;
  height: min(66vh, 640px);
  min-height: 480px;
}

@media (max-width: 720px) {
  .chart-card {
    border-radius: 12px;
  }
  .chart-head {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
    padding: 16px 16px 6px;
  }
  .chart-title {
    font-size: 16px;
  }
  .chart-surface {
    margin: 0;
  }
  .chart-thumb {
    height: 320px;
  }
  .chart-insight {
    margin-inline: 16px;
  }
  .chart-notes {
    padding-inline: 16px;
  }
  .chart-large {
    min-height: 360px;
    height: 58vh;
  }
}
</style>
