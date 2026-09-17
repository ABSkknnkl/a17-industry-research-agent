<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { downloadArtifact, getRun, triggerBlobDownload } from '../api/client'
import { ApiError } from '../api/http'
import { artifactKindLabel } from '../api/labels'
import { classifyReportDownload, reportArtifacts, type ReportDownloadGate } from '../api/reportGate'
import type { ArtifactRef, ReportFusionData, WorkflowState } from '../api/types'
import StatusTag from '../components/StatusTag.vue'
import ArtifactList from '../components/ArtifactList.vue'

/**
 * 独立「报告下载页」。
 *
 * 定位：任务走完流水线并**通过阶段五审核**后的交付入口。
 * 门控：后端下载接口不看任务状态（api/routes.py 只校验归属与文件存在），
 *       所以「未批准的正式报告不得当交付」这条只能由前端把关 —— 判定逻辑在
 *       api/reportGate.ts，本页是门控的唯一权威（即使自动跳转进来也重新取数再判）。
 *
 * 打包下载：后端没有 zip 接口，采用**纯前端顺序下载**。
 *          逐份触发之间留 400ms 间隔，降低浏览器「多文件下载」抑制导致的丢文件。
 */

const route = useRoute()
const router = useRouter()
const runId = computed(() => String(route.params.runId ?? ''))

const workflow = ref<WorkflowState | null>(null)
const loading = ref(false)
const loadError = ref('')

const EMPTY_GATE: ReportDownloadGate = {
  level: 'blocked',
  downloadable: false,
  reason: '',
  alertType: 'info',
  artifactCount: 0,
}
const gate = ref<ReportDownloadGate>(EMPTY_GATE)

const fusion = computed<ReportFusionData | null>(() => {
  const raw = workflow.value?.stage_results.report_fusion?.data
  return raw && typeof raw === 'object' ? (raw as unknown as ReportFusionData) : null
})

const title = computed(() => fusion.value?.title ?? '报告下载')

/** 固定下载/展示顺序：正文 → 网页 → PDF → 产物清单（真实 4 份；mock 只有前 3 份） */
const KIND_ORDER = ['report_markdown', 'report_html', 'report_pdf', 'artifact_manifest']

/**
 * 产物大小映射：ArtifactRef 不含 size_bytes，
 * 从融合 manifest（data.artifacts）按 artifact_id 关联。
 */
const artifactSizeById = computed<Record<string, number>>(() => {
  const map: Record<string, number> = {}
  for (const entry of fusion.value?.artifacts ?? []) {
    if (entry.artifact_id && typeof entry.size_bytes === 'number') {
      map[entry.artifact_id] = entry.size_bytes
    }
  }
  return map
})

// ---------------- 下载项 ----------------
type ItemStatus = 'pending' | 'downloading' | 'done' | 'failed'
interface DownloadItem {
  artifact: ArtifactRef
  label: string
  status: ItemStatus
}

const items = ref<DownloadItem[]>([])
const phase = ref<'idle' | 'downloading' | 'done' | 'partial' | 'error'>('idle')
const completedCount = ref(0)
const failedItems = ref<DownloadItem[]>([])
let cancelled = false

/** ArtifactList 展示的产物（与批量下载同一顺序） */
const tableArtifacts = computed<ArtifactRef[]>(() => items.value.map((item) => item.artifact))

const total = computed(() => items.value.length)
const progressPercent = computed(() =>
  total.value === 0 ? 0 : Math.round((completedCount.value / total.value) * 100)
)
const currentItem = computed(() => items.value.find((item) => item.status === 'downloading') ?? null)

const INTER_DOWNLOAD_MS = 400
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const state = await getRun(runId.value)
    workflow.value = state
    gate.value = classifyReportDownload(state)
    items.value = reportArtifacts(state)
      .slice()
      .sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind))
      .map((artifact) => ({
        artifact,
        label: artifactKindLabel(artifact.kind) || artifact.artifact_id,
        status: 'pending' as ItemStatus,
      }))
  } catch (e) {
    loadError.value = e instanceof ApiError ? e.message : '加载任务失败，请稍后重试'
  } finally {
    loading.value = false
  }
}

async function downloadAll(): Promise<void> {
  if (!gate.value.downloadable || phase.value === 'downloading' || total.value === 0) return
  cancelled = false
  phase.value = 'downloading'
  failedItems.value = []
  completedCount.value = 0
  items.value.forEach((item) => (item.status = 'pending'))

  let done = 0
  for (const item of items.value) {
    if (cancelled) break
    item.status = 'downloading'
    try {
      const { blob, filename } = await downloadArtifact(runId.value, item.artifact)
      // 取到之后也要复查：用户可能在这期间取消了，不该再落一份
      if (cancelled) break
      triggerBlobDownload(blob, filename)
      item.status = 'done'
      completedCount.value = ++done
    } catch {
      item.status = 'failed'
      failedItems.value.push(item)
    }
    if (!cancelled) await sleep(INTER_DOWNLOAD_MS)
  }

  if (cancelled) {
    phase.value = 'idle'
    return
  }
  phase.value = failedItems.value.length === 0 ? 'done' : done > 0 ? 'partial' : 'error'
  if (phase.value === 'error') ElMessage.error('下载失败，请稍后重试')
}

function retryFailed(): void {
  items.value = failedItems.value.map((item) => ({ ...item, status: 'pending' as ItemStatus }))
  void downloadAll()
}

function cancelDownload(): void {
  cancelled = true
}

function goBack(): void {
  router.push({ name: 'review', params: { runId: runId.value } })
}

onMounted(load)
// 卸载即中止循环，避免"离开页面后还在后台继续落文件"
onBeforeUnmount(() => {
  cancelled = true
})
</script>

<template>
  <div class="card-header" style="margin-bottom: 16px">
    <h2 class="page-title" style="margin: 0">
      <el-button
        link
        type="primary"
        data-testid="report-download-back"
        style="margin-right: 8px"
        @click="goBack"
      >
        ← 返回工作台
      </el-button>
      {{ title }}
    </h2>
    <div class="view-actions">
      <StatusTag v-if="workflow" :status="workflow.status" />
    </div>
  </div>

  <el-alert
    v-if="loadError"
    type="error"
    show-icon
    :closable="false"
    :title="loadError"
    style="margin-bottom: 12px"
  />

  <!-- 门控结论：blocked / exception 必须给出原因 -->
  <el-alert
    v-if="!loadError && gate.reason"
    :type="gate.alertType"
    show-icon
    :closable="false"
    :title="gate.level === 'exception' ? '异常终态交付提醒' : '暂时无法下载'"
    :description="gate.reason"
    style="margin-bottom: 12px"
    data-testid="report-download-gate"
  />

  <el-card class="page-card" shadow="never" v-loading="loading">
    <template #header>
      <div class="card-header">
        <span class="card-title">交付产物（{{ gate.artifactCount }} 份）</span>
        <span v-if="fusion?.research_as_of" class="muted">
          研究时点 {{ fusion.research_as_of }}
        </span>
      </div>
    </template>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="浏览器可能提示「是否允许下载多个文件」，请选择允许。"
      description="若个别文件未能保存，可点击「重试失败项」再次获取。"
      style="margin-bottom: 12px"
    />

    <div class="download-bar">
      <el-button
        type="primary"
        :disabled="!gate.downloadable || total === 0"
        :loading="phase === 'downloading'"
        data-testid="report-download-all"
        @click="downloadAll"
      >
        全部打包下载
      </el-button>
      <el-button
        v-if="phase === 'downloading'"
        data-testid="report-download-cancel"
        @click="cancelDownload"
      >
        取消
      </el-button>
      <el-button
        v-if="phase === 'partial' || phase === 'error'"
        type="primary"
        plain
        data-testid="report-download-retry"
        @click="retryFailed"
      >
        重试失败项
      </el-button>
      <span v-if="phase === 'downloading' && total > 0" class="muted" data-testid="report-download-progress">
        正在下载 {{ Math.min(completedCount + 1, total) }}/{{ total }}：{{
          currentItem?.label ?? ''
        }}
      </span>
      <span v-else-if="phase === 'done'" class="download-done" data-testid="report-download-result">
        已下载全部 {{ total }} 份产物
      </span>
      <span v-else-if="phase === 'partial'" class="download-warn" data-testid="report-download-result">
        部分成功：{{ completedCount }} 份已下载，{{ failedItems.length }} 份失败
      </span>
      <span v-else-if="phase === 'error'" class="download-warn" data-testid="report-download-result">
        下载失败，请重试
      </span>
    </div>

    <el-progress
      v-if="phase !== 'idle' && total > 0"
      class="download-progress"
      :percentage="progressPercent"
      :stroke-width="8"
      :show-text="false"
    />

    <ul v-if="failedItems.length > 0" class="failed-list">
      <li v-for="item in failedItems" :key="item.artifact.artifact_id" class="muted">
        {{ item.label }}（{{ item.artifact.artifact_id }}）未能下载
      </li>
    </ul>

    <el-empty
      v-if="!loading && total === 0 && !loadError"
      :image-size="70"
      description="本次任务未产出可下载的报告产物"
    />

    <ArtifactList
      v-if="total > 0"
      :run-id="runId"
      :artifacts="tableArtifacts"
      :size-by-id="artifactSizeById"
      :disabled="!gate.downloadable"
    />
  </el-card>
</template>

<style scoped>
.view-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.download-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.download-done {
  font-size: 13px;
  color: var(--el-color-success);
}
.download-warn {
  font-size: 13px;
  color: var(--el-color-warning);
}
.download-progress {
  margin-top: 12px;
}
.failed-list {
  margin: 10px 0 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.8;
}
</style>
