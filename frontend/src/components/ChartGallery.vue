<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

/** chart_generate 阶段 data.chart_specs 的宽松类型（与后端 ChartSpec 对齐，仅取渲染所需字段） */
interface ChartSpecLoose {
  chart_id?: string
  title?: string
  chart_type?: string
  option?: Record<string, unknown>
  render_mode?: string
  image_uri?: string | null
  insight_goal?: string | null
  footnotes?: string[]
}

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

/** 渲染 chart 宽度 320px 高度固定，文本统一缩小 */
const BASE_TEXT = 11

function buildOption(option: Record<string, unknown>): Record<string, unknown> {
  return {
    animation: false,
    textStyle: { fontSize: BASE_TEXT },
    ...option,
    grid: (option.grid as Record<string, unknown>) ?? {
      left: 8,
      right: 12,
      top: 40,
      bottom: 8,
      containLabel: true,
    },
  }
}

function renderThumbs(): void {
  disposeThumbs()
  if (props.specs.length === 0) return
  requestAnimationFrame(() => {
    usable.value.forEach((spec, index) => {
      const el = thumbsRef.value[index]
      if (!el || !spec.option) return
      const instance = echarts.init(el)
      instance.setOption(buildOption(spec.option))
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
  dialogInstance.setOption({
    animation: false,
    ...activeSpec.value.option,
  })
}

function typeLabel(type: string | undefined): string {
  if (!type) return '图表'
  return CHART_TYPE_LABELS[type] ?? type
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
      <div v-for="(spec, index) in usable" :key="spec.chart_id ?? index" class="chart-card">
        <div class="chart-head" @click="openChart(index)">
          <span class="chart-title">{{ spec.title ?? '未命名图表' }}</span>
          <el-tag size="small" type="info" effect="plain">{{ typeLabel(spec.chart_type) }}</el-tag>
        </div>
        <!-- echarts 渲染 -->
        <div
          v-if="spec.render_mode !== 'generated_image'"
          :ref="
            (el) => {
              thumbsRef[index] = el as HTMLElement
            }
          "
          class="chart-thumb"
          @click="openChart(index)"
        />
        <!-- AI 生成图（行业链路图等）：仅内联可用的 URI -->
        <div v-else class="chart-thumb chart-img">
          <img
            v-if="spec.image_uri && /^(https?:|data:)/.test(spec.image_uri)"
            :src="spec.image_uri"
            :alt="spec.title ?? ''"
            @click="openChart(index)"
          />
          <div v-else class="chart-img-missing muted">AI 生成图未内联，请从产出物下载查看</div>
        </div>
        <div v-if="spec.insight_goal" class="chart-goal muted">{{ spec.insight_goal }}</div>
      </div>
    </div>

    <el-dialog
      v-model="dialogVisible"
      :title="activeSpec?.title ?? '图表预览'"
      width="780px"
      destroy-on-close
      @opened="nextTickRenderDialog"
    >
      <div ref="dialogRef" class="chart-large" />
      <div v-if="activeSpec?.insight_goal" class="chart-goal muted" style="margin-top: 8px">
        分析目的：{{ activeSpec.insight_goal }}
      </div>
      <template v-if="activeSpec?.footnotes?.length">
        <div v-for="(note, i) in activeSpec.footnotes" :key="i" class="chart-goal muted">
          数据说明：{{ note }}
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.chart-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.chart-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  background: var(--el-bg-color);
  overflow: hidden;
}
.chart-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px 6px;
  cursor: zoom-in;
}
.chart-title {
  font-family: var(--rp-serif);
  font-size: 12.5px;
  font-weight: 700;
  color: var(--rp-navy);
  line-height: 1.4;
}
.chart-thumb {
  width: 100%;
  height: 230px;
  cursor: zoom-in;
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
.chart-goal {
  font-size: 11.5px;
  line-height: 1.6;
  padding: 0 10px 8px;
}
.chart-large {
  width: 100%;
  height: 460px;
}
</style>
