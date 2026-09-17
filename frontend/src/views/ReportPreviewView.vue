<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { downloadArtifact, getRun } from '../api/client'
import { ApiError } from '../api/http'
import {
  type ArtifactRef,
  type ReportFusionData,
  type StageResult,
  type WorkflowState,
} from '../api/types'

/**
 * 独立报告预览页（阶段五「预览完整报告」入口）。
 *
 * 取数：GET /runs/{runId} → stage_results.report_fusion 的产物与元信息。
 * 渲染：HTML 产物走 iframe + blob URL（报告自带 <style>，必须隔离，不能插进 Vue 模板）。
 *       报告 HTML 实测为纯静态（无 <script>、无外链资源），因此用最严格的 sandbox=""。
 */
const route = useRoute()
const router = useRouter()
const runId = computed(() => String(route.params.runId ?? ''))

const loading = ref(false)
const loadError = ref('')
const workflow = ref<WorkflowState | null>(null)

const fusionResult = computed<StageResult | null>(
  () => workflow.value?.stage_results.report_fusion ?? null
)

const fusion = computed<ReportFusionData | null>(() => {
  const raw = fusionResult.value?.data
  return raw && typeof raw === 'object' ? (raw as unknown as ReportFusionData) : null
})

const artifacts = computed<ArtifactRef[]>(() => fusionResult.value?.artifacts ?? [])

const htmlArtifact = computed(
  () => artifacts.value.find((a) => a.kind === 'report_html') ?? null
)

const title = computed(() => fusion.value?.title ?? '报告预览')

// ---------------- 报告内嵌预览 ----------------
const objectUrl = ref('')
const frameSrc = ref('')
const frameLoading = ref(false)
const previewError = ref('')

/**
 * 支持外部直达某一章（?anchor=chapter-3，工作台目录结构仍可带锚点进来）。
 * 首次加载就直接带上片段，避免加载完再跳导致的闪动。
 */
const requestedAnchor = computed(() => {
  const raw = route.query.anchor
  return typeof raw === 'string' && raw ? raw : ''
})

/** 释放 blob URL。切换/卸载都必须调用，否则 blob 常驻内存。 */
function revokeFrame(): void {
  if (objectUrl.value) {
    URL.revokeObjectURL(objectUrl.value)
    objectUrl.value = ''
  }
  frameSrc.value = ''
}

async function loadReportHtml(): Promise<void> {
  const artifact = htmlArtifact.value
  if (!artifact) return
  frameLoading.value = true
  previewError.value = ''
  try {
    const { blob } = await downloadArtifact(runId.value, artifact)
    revokeFrame()
    objectUrl.value = URL.createObjectURL(blob)
    frameSrc.value = requestedAnchor.value
      ? `${objectUrl.value}#${requestedAnchor.value}`
      : objectUrl.value
  } catch (e) {
    previewError.value = e instanceof ApiError ? e.message : '报告加载失败，请稍后重试'
  } finally {
    frameLoading.value = false
  }
}

// ---------------- 加载 ----------------
async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    workflow.value = await getRun(runId.value)
    await loadReportHtml()
  } catch (e) {
    loadError.value = e instanceof ApiError ? e.message : '加载任务失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

function goBack(): void {
  router.push({ name: 'review', params: { runId: runId.value } })
}

onMounted(load)
onBeforeUnmount(revokeFrame)
</script>

<template>
  <div class="card-header" style="margin-bottom: 16px">
    <h2 class="page-title" style="margin: 0">
      <el-button
        link
        type="primary"
        data-testid="report-back"
        style="margin-right: 8px"
        @click="goBack"
      >
        ← 返回审核
      </el-button>
      {{ title }}
    </h2>
  </div>

  <el-alert
    v-if="loadError"
    type="error"
    show-icon
    :closable="false"
    :title="loadError"
    style="margin-bottom: 12px"
  />

  <el-card class="page-card report-card" shadow="never" v-loading="loading || frameLoading">
    <template #header>
      <div class="card-header">
        <span class="card-title">
          {{ fusion?.industry_topic ? `${fusion.industry_topic} · ` : '' }}报告正文
        </span>
        <span class="muted">
          <template v-if="fusion?.report_depth">深度 {{ fusion.report_depth }} · </template>
          研究时点 {{ fusion?.research_as_of ?? '—' }}
        </span>
      </div>
    </template>

    <el-alert
      v-if="previewError"
      type="error"
      show-icon
      :closable="false"
      :title="previewError"
      style="margin-bottom: 12px"
    />

    <!--
      报告为纯静态 HTML（无脚本、无外链），用最严格 sandbox 隔离：
      不带 allow-scripts / allow-same-origin，样式与 SVG 仍正常渲染。
    -->
    <iframe
      v-if="frameSrc"
      :src="frameSrc"
      class="report-frame"
      sandbox=""
      referrerpolicy="no-referrer"
      title="报告全文预览"
      data-testid="report-frame"
    />
    <el-empty
      v-else-if="!loading && !previewError"
      :image-size="70"
      description="本次融合未产出可在线预览的 HTML 报告"
    />
  </el-card>
</template>

<style scoped>
.report-card :deep(.el-card__body) {
  padding: 0;
}
.report-frame {
  display: block;
  width: 100%;
  height: calc(100vh - 220px);
  min-height: 480px;
  border: none;
  background: var(--rp-paper);
}
@media (max-width: 1100px) {
  .report-frame {
    height: 70vh;
  }
}
</style>
