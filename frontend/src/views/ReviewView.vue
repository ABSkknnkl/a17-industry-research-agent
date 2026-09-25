<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CloseBold, Download, ArrowDown } from '@element-plus/icons-vue'
import { getRun, listRevisions, cancelRun, downloadArtifact, triggerBlobDownload } from '../api/client'
import { ApiError } from '../api/http'
import {
  STAGE_LABELS,
  STAGE_ORDER,
  type ArtifactRef,
  type ReportFusionData,
  type RevisionListResponse,
  type StageName,
  type StageResult,
  type WorkflowState,
} from '../api/types'
import StatusTag from '../components/StatusTag.vue'
import StageStepper from '../components/StageStepper.vue'
import StageDigest from '../components/StageDigest.vue'
import MetricCards from '../components/MetricCards.vue'
import QualityPanel from '../components/QualityPanel.vue'
import ReviewActions from '../components/ReviewActions.vue'
import WorkbenchActions from '../components/WorkbenchActions.vue'
import ProjectTree from '../components/ProjectTree.vue'
import AgentLiveTrace from '../components/AgentLiveTrace.vue'
import RevisionDiffViewer from '../components/RevisionDiffViewer.vue'
import { shouldAutoJumpToDownload } from '../api/reportGate'

const route = useRoute()
const router = useRouter()
const runId = computed(() => String(route.params.runId ?? ''))

const workflow = ref<WorkflowState | null>(null)
const loading = ref(false)
const revisions = ref<RevisionListResponse | null>(null)
const revisionsVisible = ref(false)
const timeByRevision = ref<Record<number, string>>({})
const projectTreeRef = ref<InstanceType<typeof ProjectTree> | null>(null)
const selectedStageOverride = ref<StageName | null>(null)
const traceDrawerVisible = ref(false)
const currentAnnotations = ref<any[]>([])

function onStageAnnotate(payload: { stage: StageName; annotations: any[] }): void {
  currentAnnotations.value = payload.annotations
}

let pollTimer: ReturnType<typeof setTimeout> | null = null
const POLL_INTERVAL_MS = 3_000

const currentStageName = computed<StageName | null>(() => {
  if (selectedStageOverride.value) return selectedStageOverride.value
  return workflow.value?.current_stage ?? null
})

const currentStageResult = computed<StageResult | null>(() => {
  const stage = currentStageName.value
  if (!stage || !workflow.value) return null
  return workflow.value.stage_results[stage] ?? null
})

const isRunning = computed(() => workflow.value?.status === 'running')

const currentStageLabel = computed(() => {
  const s = currentStageName.value || workflow.value?.current_stage
  return s ? STAGE_LABELS[s] || s : '全链路分析'
})

// ------------------------------------------------------------------
// 报告导出功能（支持单份直接下载与全部打包下载）
// ------------------------------------------------------------------
const fusionResult = computed<StageResult | null>(
  () => workflow.value?.stage_results.report_fusion ?? null
)
const fusionArtifacts = computed<ArtifactRef[]>(() => fusionResult.value?.artifacts ?? [])
const hasReportArtifacts = computed(() => fusionArtifacts.value.length > 0)

const pdfArtifact = computed(
  () => fusionArtifacts.value.find((a) => a.kind === 'report_pdf') ?? null
)
const htmlArtifact = computed(
  () => fusionArtifacts.value.find((a) => a.kind === 'report_html') ?? null
)
const mdArtifact = computed(
  () => fusionArtifacts.value.find((a) => a.kind === 'report_markdown') ?? null
)

const exportingKind = ref<string | null>(null)

async function handleExportCommand(cmd: string): Promise<void> {
  if (cmd === 'all') {
    await router.push({ name: 'report-download', params: { runId: runId.value } })
    return
  }
  let target: ArtifactRef | null = null
  if (cmd === 'pdf') target = pdfArtifact.value
  else if (cmd === 'html') target = htmlArtifact.value
  else if (cmd === 'markdown') target = mdArtifact.value

  if (!target) {
    ElMessage.warning('该格式产物尚未生成')
    return
  }

  exportingKind.value = cmd
  try {
    const { blob, filename } = await downloadArtifact(runId.value, target)
    triggerBlobDownload(blob, filename)
    ElMessage.success(`《${filename}》导出成功`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导出失败，请重试')
  } finally {
    exportingKind.value = null
  }
}

// ------------------------------------------------------------------
// 主屏实时执行计时器 (用于轻量状态条与动线按钮徽标)
// ------------------------------------------------------------------
const liveElapsedSeconds = ref(0)
let liveTimerId: ReturnType<typeof setInterval> | null = null

function updateLiveTimer(): void {
  if (workflow.value?.created_at) {
    try {
      const start = new Date(workflow.value.created_at).getTime()
      const now = Date.now()
      liveElapsedSeconds.value = Math.max(0, Math.floor((now - start) / 1000))
      return
    } catch {
      // 容错
    }
  }
  liveElapsedSeconds.value += 1
}

function stopLiveTimer(): void {
  if (liveTimerId) {
    clearInterval(liveTimerId)
    liveTimerId = null
  }
}

const formattedLiveElapsed = computed(() => {
  const s = liveElapsedSeconds.value
  const mm = String(Math.floor(s / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  return `${mm}:${ss}`
})

watch(
  isRunning,
  (running) => {
    if (running) {
      updateLiveTimer()
      if (!liveTimerId) {
        liveTimerId = setInterval(updateLiveTimer, 1000)
      }
      schedulePoll()
    } else {
      stopLiveTimer()
      stopPoll()
    }
  },
  { immediate: true }
)

/** report_fusion 产出（宽松读取，字段与后端 ReportFusionResult 一致） */
const fusionData = computed<ReportFusionData | null>(() => {
  const raw = workflow.value?.stage_results.report_fusion?.data
  if (!raw || typeof raw !== 'object') return null
  return raw as unknown as ReportFusionData
})

/** A1 采集明细：从完整 stage_results 取 data_fetch，供结论「查看数据来源」关联 */
const sourceRecords = computed<Record<string, unknown>[]>(() => {
  const raw = workflow.value?.stage_results.data_fetch?.data
  if (!raw || typeof raw !== 'object') return []
  const list = (raw as Record<string, unknown>).source_records
  return Array.isArray(list) ? (list as Record<string, unknown>[]) : []
})

async function reload(): Promise<void> {
  try {
    const prevStatus = workflow.value?.status
    const prevStage = workflow.value?.current_stage
    workflow.value = await getRun(runId.value)
    if (prevStatus !== workflow.value?.status || prevStage !== workflow.value?.current_stage) {
      projectTreeRef.value?.reload()
    }
  } catch (e) {
    if (e instanceof ApiError && e.status !== 401) {
      ElMessage.error(`加载任务失败：${e.message}`)
    }
  }
  await checkAutoJump()
}

/** 全自动任务的完成后自动跳转：首页「一键通过」创建的任务在 run 终态时直达下载页。 */
async function checkAutoJump(): Promise<void> {
  const key = `autojump:${runId.value}`
  let flagged = false
  try {
    flagged = localStorage.getItem(key) === '1'
  } catch {
    return
  }
  if (!flagged) return
  const state = workflow.value
  if (state && (state.status === 'completed' || state.status === 'approved')) {
    try {
      localStorage.removeItem(key)
    } catch {
      /* 忽略 */
    }
    await router.push({ name: 'report-download', params: { runId: runId.value } })
  }
}

async function reloadWithSpinner(): Promise<void> {
  loading.value = true
  await reload()
  loading.value = false
}

function schedulePoll(): void {
  stopPoll()
  if (isRunning.value) {
    pollTimer = setTimeout(async () => {
      await reload()
      schedulePoll()
    }, POLL_INTERVAL_MS)
  }
}

function stopPoll(): void {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
}

async function onSubmitted(
  state: WorkflowState,
  meta?: { stage: StageName; action: string }
): Promise<void> {
  workflow.value = state
  selectedStageOverride.value = null
  schedulePoll()
  // 阶段五通过 → 报告已定稿，直接带去下载页（其余动作/阶段留在工作台）
  if (shouldAutoJumpToDownload(meta?.stage ?? null, meta?.action)) {
    await router.push({ name: 'report-download', params: { runId: runId.value } })
  }
}

/** 加载历史版本（同时构建 revision → 更新时间映射，供产物列表展示） */
async function loadRevisions(): Promise<void> {
  try {
    revisions.value = await listRevisions(runId.value)
    const map: Record<number, string> = {}
    for (const item of revisions.value.revisions) {
      map[item.revision] = item.updated_at
    }
    timeByRevision.value = map
  } catch (e) {
    if (e instanceof ApiError) ElMessage.error(`加载历史版本失败：${e.message}`)
  }
}

async function openRevisions(): Promise<void> {
  await loadRevisions()
  revisionsVisible.value = true
}

async function refreshAll(): Promise<void> {
  await Promise.all([reloadWithSpinner(), loadRevisions()])
  projectTreeRef.value?.reload()
  if (isRunning.value) {
    schedulePoll()
  }
}

const cancelling = ref(false)

async function handleCancelInFlight(): Promise<void> {
  if (cancelling.value || !workflow.value) return
  try {
    await ElMessageBox.confirm(
      '确定要强行中断当前正在执行的智能体流水线吗？正在进行的分析与生成将被立即终止。',
      '中断任务确认',
      {
        confirmButtonText: '立即中断',
        cancelButtonText: '继续执行',
        type: 'warning',
      }
    )
  } catch {
    return
  }

  cancelling.value = true
  try {
    const updated = await cancelRun(runId.value)
    workflow.value = updated
    stopPoll()
    ElMessage.warning('任务已成功中途终止')
    projectTreeRef.value?.reload()
  } catch (e) {
    if (e instanceof ApiError) {
      ElMessage.error(`中断任务失败：${e.message}`)
    } else {
      ElMessage.error('中断任务失败')
    }
  } finally {
    cancelling.value = false
  }
}

function formatTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN')
}

function onSelectStage(stage: StageName): void {
  const result = workflow.value?.stage_results[stage]
  if (!result) return
  selectedStageOverride.value = stage
}

/** 跳转独立报告预览页（阶段五「预览完整报告」入口）；anchor 用于直达某一章 */
function openReportPreview(anchor?: string): void {
  router.push({
    name: 'report-preview',
    params: { runId: runId.value },
    query: anchor ? { anchor } : {},
  })
}

onMounted(refreshAll)

// 左侧树切换任务时重载工作台
watch(runId, async (next, prev) => {
  if (next && next !== prev) {
    selectedStageOverride.value = null
    await refreshAll()
  }
})

onBeforeUnmount(() => {
  stopPoll()
  stopLiveTimer()
})
</script>

<script lang="ts">
export default { name: 'ReviewView' }
</script>

<template>
  <div class="workbench">
    <!-- 左栏：项目导航树 -->
    <aside class="wb-left">
      <el-card class="page-card" shadow="never">
        <ProjectTree ref="projectTreeRef" :active-run-id="runId" />
      </el-card>
    </aside>

    <!-- 中栏：任务工作台 -->
    <main class="wb-center">
      <div class="workbench-header">
        <div class="header-main">
          <h2 class="page-title" style="margin: 0">任务工作台</h2>
          <StatusTag v-if="workflow" :status="workflow.status" />
        </div>
        <div class="header-actions">
          <el-button
            v-if="isRunning"
            type="danger"
            plain
            :loading="cancelling"
            data-testid="btn-in-flight-cancel"
            @click="handleCancelInFlight"
          >
            <el-icon style="margin-right: 4px"><CloseBold /></el-icon>
            中断任务
          </el-button>
          <el-button
            class="btn-trace-trigger"
            :class="{ 'is-live': isRunning }"
            data-testid="btn-open-trace-drawer"
            @click="traceDrawerVisible = true"
          >
            <span v-if="isRunning" class="live-pulse-dot" />
            <span>智能体执行动线</span>
            <span v-if="isRunning" class="btn-live-badge">{{ formattedLiveElapsed }}</span>
          </el-button>
          <el-dropdown
            v-if="hasReportArtifacts"
            trigger="click"
            @command="handleExportCommand"
          >
            <el-button
              type="success"
              plain
              :loading="exportingKind !== null"
              data-testid="btn-export-report"
            >
              <el-icon style="margin-right: 4px"><Download /></el-icon>
              导出报告
              <el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="pdf" :disabled="!pdfArtifact">
                  导出 PDF 格式（出版级排版）
                </el-dropdown-item>
                <el-dropdown-item command="html" :disabled="!htmlArtifact">
                  导出 HTML 格式（全交互离线单页）
                </el-dropdown-item>
                <el-dropdown-item command="markdown" :disabled="!mdArtifact">
                  导出 Markdown 格式（纯文本结构化）
                </el-dropdown-item>
                <el-dropdown-item divided command="all">
                  批量打包下载中心...
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <WorkbenchActions
            v-if="workflow"
            :key="`${workflow.current_stage}-${workflow.revision}`"
            :run-id="runId"
            :stage="workflow.current_stage"
            :revision="workflow.revision"
            :status="workflow.status"
            @submitted="onSubmitted"
            @conflict="reloadWithSpinner"
            @history="openRevisions"
          />
        </div>
      </div>

      <div v-if="workflow" class="header-meta muted">
        项目 {{ workflow.project_id }} · 任务 {{ runId }} · 版本 r{{ workflow.revision }} · 创建于
        {{ formatTime(workflow.created_at) }}
      </div>

      <!-- 智能体实时执行提示条（经典研报风，不割裂主屏，提供实时进度与动线抽屉入口） -->
      <div v-if="isRunning" class="live-running-strip" data-testid="live-running-strip">
        <div class="strip-left">
          <span class="strip-pulse-dot" />
          <span class="strip-lead">全链路智能体执行中：</span>
          <span class="strip-stage">{{ currentStageLabel }}</span>
          <span class="strip-divider">·</span>
          <span class="strip-hint">实时调度金融量化与问财技能链</span>
        </div>
        <div class="strip-right">
          <span class="strip-timer">已执行 {{ formattedLiveElapsed }}</span>
          <el-button
            link
            type="primary"
            class="strip-drawer-link"
            data-testid="strip-open-drawer"
            @click="traceDrawerVisible = true"
          >
            查看微观动线与调度 ↗
          </el-button>
        </div>
      </div>

      <el-alert
        v-if="workflow?.status === 'cancelled'"
        type="warning"
        show-icon
        :closable="false"
        title="该任务已被中途终止。您可以重新发起新任务或查看已产出的中间数据。"
        style="margin-bottom: 10px"
      />

      <!-- 流程节点 -->
      <el-card class="page-card" shadow="never" v-loading="loading">
        <StageStepper
          :stage-results="workflow?.stage_results ?? {}"
          :selected-stage="currentStageName"
          @select="onSelectStage"
        />
      </el-card>

      <!-- 人机协同版本演进对比 (Revision Diff) -->
      <RevisionDiffViewer
        v-if="workflow"
        :run-id="runId"
        :current-revision="workflow.revision"
      />

      <!-- 未加载到任务时的空状态 -->
      <el-card v-if="!loading && !workflow" class="page-card" shadow="never">
        <el-empty description="未找到任务数据，请在首页创建新任务或在左侧选择历史任务" />
      </el-card>

      <!-- 融合质量：仅在阶段五（report_fusion）时展示 -->
      <el-card
        v-if="fusionData?.quality && currentStageName === 'report_fusion'"
        class="page-card"
        shadow="never"
      >
        <template #header>
          <span class="card-title">交付质量与融合检查</span>
        </template>
        <QualityPanel :fusion="fusionData" />
      </el-card>

      <!-- 当前阶段 -->
      <el-card v-if="currentStageResult" class="page-card" shadow="never">
        <template #header>
          <div class="card-header">
            <span class="card-title">
              当前阶段：{{ STAGE_LABELS[currentStageResult.stage] }}
              <StatusTag :status="currentStageResult.status" style="margin-left: 8px" />
            </span>
            <span class="muted">阶段版本 r{{ currentStageResult.revision }}</span>
          </div>
        </template>

        <MetricCards :stage="currentStageResult.stage" :data="currentStageResult.data" />

        <el-divider />

        <StageDigest
          :stage="currentStageResult.stage"
          :data="currentStageResult.data"
          :source-records="sourceRecords"
          :run-id="runId"
          @preview-report="(anchor) => openReportPreview(anchor)"
          @annotate="onStageAnnotate"
        />

        <el-divider />

        <template
          v-if="
            workflow?.status === 'waiting_review' && currentStageName === workflow?.current_stage
          "
        >
          <ReviewActions
            :key="`${currentStageResult.stage}-${currentStageResult.revision}`"
            :run-id="runId"
            :stage="currentStageResult.stage"
            :result="currentStageResult"
            :revision="workflow!.revision"
            :annotations="currentAnnotations"
            @submitted="onSubmitted"
            @conflict="reloadWithSpinner"
          />
        </template>
        <p v-else class="muted" style="margin: 0">
          {{
            workflow?.status === 'cancelled'
              ? '该任务已被中途终止，未继续执行后续阶段。'
              : currentStageResult.status === 'running' || workflow?.status === 'running'
                ? '该阶段正在执行，完成后将进入人工审核（若配置了审核门）。'
                : currentStageName !== workflow?.current_stage
                  ? '正在查看已产出阶段内容；阶段级操作请回到当前等待审核的阶段。'
                  : '该阶段当前无需人工操作。'
          }}
        </p>
      </el-card>
    </main>
  </div>

  <el-dialog
    v-model="revisionsVisible"
    title="历史版本"
    width="640px"
    data-testid="revisions-dialog"
  >
    <el-table v-if="revisions" :data="revisions.revisions" size="small" border>
      <el-table-column prop="revision" label="版本" width="80" />
      <el-table-column label="状态" width="120">
        <template #default="{ row }"><StatusTag :status="row.status" /></template>
      </el-table-column>
      <el-table-column label="当前阶段" width="120">
        <template #default="{ row }">
          {{ STAGE_LABELS[row.current_stage as keyof typeof STAGE_LABELS] ?? row.current_stage }}
        </template>
      </el-table-column>
      <el-table-column label="更新时间">
        <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
      </el-table-column>
    </el-table>
  </el-dialog>

  <!-- 智能体微观执行动线抽屉（右侧滑出抽屉） -->
  <el-drawer
    v-model="traceDrawerVisible"
    direction="rtl"
    size="720px"
    :destroy-on-close="false"
    class="agent-trace-drawer"
  >
    <template #header>
      <div class="trace-drawer-header-title">
        <span class="drawer-title-text">智能体微观执行动线与协同底稿</span>
        <el-tag
          v-if="isRunning"
          size="small"
          effect="plain"
          class="drawer-live-pill"
        >
          ● 实时推流中 ({{ formattedLiveElapsed }})
        </el-tag>
      </div>
    </template>
    <AgentLiveTrace
      v-if="runId"
      :run-id="runId"
      :is-running="isRunning"
      :active-stage="currentStageName"
      :workflow="workflow"
      mode="drawer"
      @cancel="handleCancelInFlight"
      @stage-change="reload"
    />
  </el-drawer>
</template>

<style scoped>
/* 智能体动线呼出按钮：研报工作台雅致风格 */
.btn-trace-trigger {
  border-color: var(--rp-line, #e3ddcd);
  background: var(--rp-card, #fffefb);
  color: var(--rp-navy, #1e3a5c);
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border-radius: 3px;
  transition: all 0.2s ease;
}
.btn-trace-trigger:hover {
  border-color: var(--rp-gold, #a9853f);
  color: var(--rp-gold, #a9853f);
  background: #fbf9f4;
}
.btn-trace-trigger.is-live {
  background: #faf6ee;
  border-color: #ebd9b3;
  color: var(--rp-navy, #1e3a5c);
}
.btn-live-badge {
  font-family: var(--rp-serif, serif);
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  font-size: 11px;
  background: #f0e8d5;
  color: var(--rp-gold, #a9853f);
  padding: 1px 5px;
  border-radius: 2px;
  border: 1px solid #dfd2b6;
  margin-left: 2px;
}
/* 实时运行轻量提示条 (精品研报风) */
.live-running-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  background: var(--rp-card, #fffefb);
  border: 1px solid var(--rp-line, #e3ddcd);
  border-left: 3px solid var(--rp-gold, #a9853f);
  border-radius: 2px;
  padding: 7px 14px;
  margin-bottom: 12px;
  box-shadow: 0 1px 3px rgba(30, 58, 92, 0.03);
}
.strip-left {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
}
.strip-pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--rp-gold, #a9853f);
  box-shadow: 0 0 0 0 rgba(169, 133, 63, 0.6);
  animation: btn-pulse-gold 1.8s infinite;
}
.strip-lead {
  font-weight: 600;
  color: var(--rp-navy, #1e3a5c);
}
.strip-stage {
  color: var(--rp-gold, #a9853f);
  font-weight: 700;
}
.strip-divider {
  color: var(--el-text-color-secondary, #8f8a7a);
}
.strip-hint {
  color: var(--el-text-color-secondary, #8f8a7a);
  font-size: 12px;
}
.strip-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
.strip-timer {
  font-family: var(--rp-serif, serif);
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  font-size: 13px;
  color: var(--rp-gold, #a9853f);
  letter-spacing: 0.5px;
}
.strip-drawer-link {
  font-size: 12px;
  font-weight: 600;
  color: var(--rp-navy, #1e3a5c);
  padding: 0;
}
.strip-drawer-link:hover {
  color: var(--rp-gold, #a9853f);
}
.live-pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--rp-gold, #a9853f);
  box-shadow: 0 0 0 0 rgba(169, 133, 63, 0.6);
  animation: btn-pulse-gold 1.8s infinite;
}
@keyframes btn-pulse-gold {
  0% {
    transform: scale(0.95);
    box-shadow: 0 0 0 0 rgba(169, 133, 63, 0.6);
  }
  70% {
    transform: scale(1);
    box-shadow: 0 0 0 5px rgba(169, 133, 63, 0);
  }
  100% {
    transform: scale(0.95);
    box-shadow: 0 0 0 0 rgba(169, 133, 63, 0);
  }
}
.trace-drawer-header-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.drawer-title-text {
  font-family: var(--rp-serif, serif);
  font-size: 15px;
  font-weight: 700;
  color: var(--rp-navy, #1e3a5c);
  letter-spacing: 0.3px;
}
.drawer-live-pill {
  background-color: var(--rp-navy, #1e3a5c) !important;
  border-color: var(--rp-navy, #1e3a5c) !important;
  color: #fff !important;
  font-size: 11px;
}

.workbench {
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.wb-left {
  position: sticky;
  top: 16px;
}
.workbench-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}
.header-main {
  display: flex;
  align-items: center;
  gap: 10px;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.header-meta {
  margin: 4px 0 10px;
}
@media (max-width: 1400px) {
  .workbench {
    grid-template-columns: 220px minmax(0, 1fr);
  }
}
@media (max-width: 1100px) {
  .workbench {
    grid-template-columns: 1fr;
  }
  .wb-left {
    position: static;
  }
}
@media (max-width: 1024px) {
  .workbench {
    grid-template-columns: 1fr;
    overflow-x: hidden;
  }
}
</style>
