<script setup lang="ts">
import type { UserAnnotation } from '../api/types'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import EvidenceIndexDownload from '../components/EvidenceIndexDownload.vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CloseBold, Download, ArrowDown } from '@element-plus/icons-vue'
import {
  getRun,
  getRunEvents,
  subscribeRunEvents,
  listRevisions,
  cancelRun,
  resumeRun,
  downloadArtifact,
  triggerBlobDownload,
} from '../api/client'
import { ApiError } from '../api/http'
import { showStageError } from '../api/stageStatus'
import {
  STAGE_LABELS,
  STAGE_ORDER,
  type AgentTraceEvent,
  type ArtifactRef,
  type PeerCompsMatrix,
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
import EvidenceDrawer from '../components/EvidenceDrawer.vue'
import {
  artifactDownloadMode,
  classifyReportDownload,
  isReportSignoffOnHold,
  shouldAutoJumpToDownload,
} from '../api/reportGate'

const route = useRoute()
const router = useRouter()
const runId = computed(() => String(route.params.runId ?? ''))

const workflow = ref<WorkflowState | null>(null)
const finalReportReady = computed(() => {
  const final = workflow.value?.stage_results.report_fusion?.data as ReportFusionData | undefined
  return final?.delivery_status === 'ready' && final.quality?.passed === true
})

const loading = ref(false)
const revisions = ref<RevisionListResponse | null>(null)
const revisionsVisible = ref(false)
const timeByRevision = ref<Record<number, string>>({})
const projectTreeRef = ref<InstanceType<typeof ProjectTree> | null>(null)
const selectedStageOverride = ref<StageName | null>(null)
const traceDrawerVisible = ref(false)
const projectTreeOpen = ref(false)
const currentAnnotations = ref<UserAnnotation[]>([])

const evidenceDrawerVisible = ref(false)
const activeEvidenceRecordIds = ref<string[]>([])

function onStageAnnotate(payload: { stage: StageName; annotations: UserAnnotation[] }): void {
  currentAnnotations.value = payload.annotations
}

function onStageViewEvidence(recordIds: string[]): void {
  activeEvidenceRecordIds.value = recordIds
  evidenceDrawerVisible.value = true
}

const currentEvidenceIndex = computed(() => {
  const interpretData = workflow.value?.stage_results?.['data_interpret']?.data
  return (interpretData?.evidence_index || {}) as Record<
    string,
    import('../components/EvidenceDrawer.vue').EvidenceRecordItem
  >
})

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
const stageDurations = ref<Partial<Record<StageName, number>>>({})

const taskProgress = ref<Partial<Record<StageName, AgentTraceEvent>>>({})

function rememberProgress(event: AgentTraceEvent): void {
  if (typeof event.details?.progress_kind !== 'string') return
  const previous = taskProgress.value[event.stage]
  if (!previous || event.timestamp >= previous.timestamp) {
    taskProgress.value[event.stage] = event
  }
}

watch([runId, isRunning], ([id, running], [previousId], onCleanup) => {
  if (id !== previousId) taskProgress.value = {}
  if (id && running) onCleanup(subscribeRunEvents(id, rememberProgress))
})

const currentProgressLabel = computed(() => {
  const stage = workflow.value?.current_stage
  const progress = stage && taskProgress.value[stage]?.details
  if (!progress || typeof progress.completed !== 'number' || typeof progress.total !== 'number') {
    return ''
  }
  const count = `${progress.completed}/${progress.total}`
  switch (progress.progress_kind) {
    case 'fetch_queries':
      return `已取得 ${count} 项问财结果`
    case 'analysis_plan':
      return '正在规划五问的分析口径'
    case 'analysis_questions':
      return `已完成 ${count} 题的证据研判`
    case 'analysis_synthesis':
      return '正在复核并归纳五问结论'
    case 'chart_plans':
      return `已完成 ${count} 题的选图方案`
    case 'chart_reviews':
      return `已核验 ${count} 张模板图`
    case 'chapter_write':
      return progress.completed < progress.total
        ? `已完成 ${count} 章 · 正在撰写第 ${progress.completed + 1} 章`
        : `已完成 ${count} 章 · 正在汇总核验`
    default:
      return ''
  }
})

watch(
  [runId, () => workflow.value?.current_stage, () => workflow.value?.status],
  async ([id], previous, onCleanup) => {
    if (id !== previous[0]) stageDurations.value = {}
    if (!id || workflow.value?.run_id !== id) return
    let stale = false
    onCleanup(() => {
      stale = true
    })
    try {
      const events = await getRunEvents(id)
      if (stale) return
      const started: Partial<Record<StageName, number>> = {}
      const durations: Partial<Record<StageName, number>> = {}
      for (const event of events) {
        rememberProgress(event)
        const time = Date.parse(event.timestamp)
        if (!Number.isFinite(time)) continue
        if (event.event_type === 'agent_start' && started[event.stage] === undefined) {
          started[event.stage] = time
        } else if (event.event_type === 'stage_completed') {
          const start = started[event.stage]
          if (start !== undefined && time >= start) {
            durations[event.stage] = (time - start) / 1000
            delete started[event.stage]
          }
        }
      }
      stageDurations.value = durations
    } catch {
      // 运行状态仍由任务接口提供。
    }
  }
)

const viewingPastStage = computed(() =>
  Boolean(workflow.value && currentStageName.value !== workflow.value.current_stage)
)
const incompletePreviousStages = computed(() => {
  if (!workflow.value || !workflow.value.current_stage) return []
  const currentIndex = STAGE_ORDER.indexOf(workflow.value.current_stage)
  if (currentIndex < 0) return []
  return STAGE_ORDER.slice(0, currentIndex).filter((stage) => {
    const result = workflow.value?.stage_results[stage]
    return result && !['approved', 'completed'].includes(result.status)
  })
})

/**
 * B43（前端 C6）：当前阶段是否正等待人工审阅。
 * 为真时审阅动作卡上移到阶段内容之前——「现在该做什么」必须一眼可见，
 * 而不是滚过指标、摘要、图表后才发现操作区。
 */
const isAwaitingReview = computed(
  () =>
    workflow.value?.status === 'waiting_review' &&
    !!workflow.value?.current_stage &&
    currentStageName.value === workflow.value.current_stage
)

/** 质量面板默认折叠，卡片头给出摘要（分数 / 待确认项） */
const qualityExpanded = ref(false)
const qualitySummary = computed(() => {
  const q = fusionData.value?.quality
  if (!q) return ''
  const parts: string[] = []
  if (typeof q.overall_score === 'number') parts.push(`综合 ${q.overall_score} 分`)
  if (typeof q.consistency_score === 'number') parts.push(`一致性 ${q.consistency_score}`)
  const issues = Array.isArray(q.issues) ? q.issues.length : 0
  if (issues > 0) parts.push(`${issues} 项待确认`)
  else if (q.passed === true) parts.push('检查通过')
  return parts.join(' · ')
})

const currentStageLabel = computed(() => {
  const s = workflow.value?.current_stage
  return s ? STAGE_LABELS[s] || s : '全链路分析'
})

// ------------------------------------------------------------------
// 报告导出功能（支持单份直接下载与全部打包下载）
// ------------------------------------------------------------------
const fusionResult = computed<StageResult | null>(
  () => workflow.value?.stage_results.report_fusion ?? null
)
const fusionArtifacts = computed<ArtifactRef[]>(() => {
  const available = fusionResult.value?.artifacts ?? []
  const state = workflow.value
  if (!state?.report_download) return available
  return available.filter((artifact) => artifactDownloadMode(state, artifact.artifact_id))
})
const hasReportArtifacts = computed(() => fusionArtifacts.value.length > 0)
const reportDownload = computed(() =>
  workflow.value ? classifyReportDownload(workflow.value) : null
)
const draftDownloadable = computed(
  () => reportDownload.value?.mode === 'draft' && reportDownload.value.downloadable
)
const showSignoffHold = computed(() => {
  const result = currentStageResult.value
  return isAwaitingReview.value && result !== null && isReportSignoffOnHold(result)
})

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
    const mode = workflow.value && artifactDownloadMode(workflow.value, target.artifact_id)
    if (!mode) {
      ElMessage.warning('当前版本不允许下载该格式')
      return
    }
    const { blob, filename } = await downloadArtifact(runId.value, target, mode)
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

/**
 * 跨阶段只读补充数据（供人工介入弹窗回填初值）。
 *
 * - 可比公司矩阵由融合阶段产出，A2 的 stage data 里没有 comps_matrix；
 * - 执行摘要文本在 A2，融合阶段 data 里没有该键。
 * 显式传入而不是让弹窗兜底样例，避免「读到假数据 / 提交空串覆盖既有内容」。
 */
const crossStageData = computed(() => {
  const stages = workflow.value?.stage_results
  const fusion = stages?.report_fusion?.data as Record<string, unknown> | undefined
  const interpret = stages?.data_interpret?.data as Record<string, unknown> | undefined
  const summary = interpret?.executive_summary
  return {
    compsMatrix: (fusion?.comps_matrix ?? null) as PeerCompsMatrix | null,
    executiveSummary: typeof summary === 'string' ? summary : null,
  }
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

/** 一键生成任务完成后直达下载页。 */
async function checkAutoJump(): Promise<void> {
  const state = workflow.value
  const id = runId.value
  if (!state || state.run_id !== id || state.status !== 'completed') return
  try {
    if (localStorage.getItem(`autojump:${id}`) !== '1') return
    localStorage.removeItem(`autojump:${id}`)
  } catch {
    return
  }
  await router.push({ name: 'report-download', params: { runId: id } })
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
  if (shouldAutoJumpToDownload(meta?.stage ?? null, meta?.action, state.status)) {
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

const resuming = ref(false)

async function handleResumeStage(stage?: StageName): Promise<void> {
  if (!runId.value) return
  resuming.value = true
  try {
    const updated = await resumeRun(runId.value, stage)
    workflow.value = updated
    const stageText = stage ? `阶段【${STAGE_LABELS[stage] || stage}】` : '流水线'
    ElMessage.success(`已从${stageText}恢复并继续推进`)
    schedulePoll()
    projectTreeRef.value?.reload()
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '恢复执行失败，请重试')
  } finally {
    resuming.value = false
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
    <header class="wb-heading">
      <div class="workbench-header">
        <div class="header-main">
          <h1 class="page-title">任务工作台</h1>
          <StatusTag v-if="workflow" :status="workflow.status" />
        </div>
        <div class="header-actions">
          <el-button
            class="project-tree-toggle"
            :aria-expanded="projectTreeOpen"
            aria-controls="workbench-projects"
            @click="projectTreeOpen = !projectTreeOpen"
          >
            {{ projectTreeOpen ? '收起历史任务' : '历史任务' }}
          </el-button>
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
          </el-button>
          <el-dropdown
            v-if="hasReportArtifacts"
            :disabled="!reportDownload?.downloadable"
            trigger="click"
            @command="handleExportCommand"
          >
            <el-button
              type="success"
              plain
              :loading="exportingKind !== null"
              :disabled="!reportDownload?.downloadable"
              data-testid="btn-export-report"
            >
              <el-icon style="margin-right: 4px"><Download /></el-icon>
              {{ draftDownloadable ? '导出受限草稿' : '导出报告' }}
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
                <el-dropdown-item divided command="all"> 批量打包下载中心... </el-dropdown-item>
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
    </header>

    <aside
      id="workbench-projects"
      class="wb-left"
      :class="{ 'is-open': projectTreeOpen }"
      aria-label="历史任务"
    >
      <el-card class="page-card" shadow="never">
        <ProjectTree
          ref="projectTreeRef"
          :active-run-id="runId"
          @navigate="projectTreeOpen = false"
        />
      </el-card>
    </aside>

    <section class="wb-center" aria-label="任务详情">
      <!-- 当前执行阶段与已用时间 -->
      <div v-if="isRunning" class="live-running-strip" data-testid="live-running-strip">
        <div class="strip-left">
          <span class="strip-pulse-dot" />
          <span class="strip-lead">正在执行</span>
          <span class="strip-stage">{{ currentStageLabel }}</span>
          <span v-if="currentProgressLabel" data-testid="current-stage-progress">
            {{ currentProgressLabel }}
          </span>
        </div>
        <span class="strip-timer">已执行 {{ formattedLiveElapsed }}</span>
      </div>

      <el-alert
        v-if="workflow?.status === 'cancelled'"
        type="warning"
        show-icon
        :closable="false"
        title="该任务已被中途终止。您可以重新发起新任务或查看已产出的中间数据。"
        style="margin-bottom: 10px"
      />
      <el-alert
        v-if="workflow?.status === 'failed'"
        type="error"
        show-icon
        :closable="false"
        title="当前研报流水线在执行过程中遇到异常并已安全暂停。您可以查看下方错误原因，点击「重试 / 断点恢复」继续推进流水线。"
        style="margin-bottom: 10px"
      />

      <!-- 流程节点 -->
      <el-card class="page-card" shadow="never" v-loading="loading">
        <StageStepper
          :stage-results="workflow?.stage_results ?? {}"
          :final-report-ready="finalReportReady"
          :duration-seconds="stageDurations"
          :selected-stage="currentStageName"
          @select="onSelectStage"
        />
      </el-card>

      <!-- 未加载到任务时的空状态 -->
      <el-card v-if="!loading && !workflow" class="page-card" shadow="never">
        <el-empty description="未找到任务数据">
          <el-button @click="router.push({ name: 'runs' })">返回任务列表</el-button>
        </el-empty>
      </el-card>

      <el-alert
        v-if="incompletePreviousStages.length && !isRunning"
        type="warning"
        show-icon
        :closable="false"
        title="任务阶段状态不一致"
        :description="`前序阶段${incompletePreviousStages.map((stage) => STAGE_LABELS[stage]).join('、')}尚未审核，当前报告无法正式签发。请返回原任务完成审核后重新生成。`"
        style="margin-bottom: 10px"
      />

      <!-- 待审阅时的主行动区：置顶，收工只需看这一块（B43 / C6） -->
      <el-card
        v-if="isAwaitingReview && currentStageResult && !incompletePreviousStages.length"
        class="page-card review-primary-card"
        shadow="never"
        data-testid="review-primary-card"
      >
        <template #header>
          <div class="card-header stage-card-header">
            <span class="card-title">
              待你审阅：{{ STAGE_LABELS[currentStageResult.stage] }}
              <StatusTag :status="workflow?.status ?? 'waiting_review'" style="margin-left: 8px" />
            </span>
            <el-button
              v-if="showSignoffHold && draftDownloadable"
              type="primary"
              size="small"
              data-testid="btn-download-draft"
              @click="handleExportCommand('all')"
            >
              下载受限草稿
            </el-button>
            <span v-else-if="!showSignoffHold" class="muted">
              {{
                currentStageResult.stage === 'report_fusion'
                  ? '审核通过后可交付报告'
                  : '通过后自动进入下一阶段'
              }}
            </span>
          </div>
        </template>
        <el-alert
          v-if="showSignoffHold"
          type="warning"
          show-icon
          :closable="false"
          class="stage-error"
          title="正式签发暂缓"
          :description="
            draftDownloadable
              ? '可下载当前草稿。签发前请展开「交付质量与融合检查」核对待补项。'
              : '请查看交付质量明细，处理待补项后重新融合。'
          "
        />
        <ReviewActions
          :key="`${currentStageResult.stage}-${currentStageResult.revision}`"
          :run-id="runId"
          :stage="currentStageResult.stage"
          :result="currentStageResult"
          :revision="workflow!.revision"
          :annotations="currentAnnotations"
          :cross-stage="crossStageData"
          @submitted="onSubmitted"
          @conflict="reloadWithSpinner"
        />
      </el-card>

      <!-- 融合质量：仅在阶段五（report_fusion）时展示；默认折叠，头部给摘要 -->
      <el-card
        v-if="fusionData?.quality && currentStageName === 'report_fusion'"
        class="page-card"
        shadow="never"
      >
        <template #header>
          <div class="card-header stage-card-header">
            <span class="card-title">
              交付质量与融合检查
              <span v-if="qualitySummary" class="quality-summary muted">{{ qualitySummary }}</span>
            </span>
            <el-button
              link
              type="primary"
              size="small"
              data-testid="btn-toggle-quality"
              @click="qualityExpanded = !qualityExpanded"
            >
              {{ qualityExpanded ? '收起明细' : '展开明细' }}
            </el-button>
          </div>
        </template>
        <QualityPanel v-if="qualityExpanded" :fusion="fusionData" />
        <p v-else class="muted quality-collapsed-hint" data-testid="quality-collapsed-hint">
          明细已折叠；确认交付前建议展开核对检查项与评分依据。
        </p>
      </el-card>

      <!-- 当前阶段 -->
      <el-card v-if="currentStageResult" class="page-card" shadow="never">
        <template #header>
          <div class="card-header stage-card-header">
            <span class="card-title">
              {{ viewingPastStage ? '正在查看' : '当前阶段' }}：{{
                STAGE_LABELS[currentStageResult.stage]
              }}
              <StatusTag :status="currentStageResult.status" style="margin-left: 8px" />
            </span>
            <span class="muted">
              <el-button
                v-if="viewingPastStage"
                link
                type="primary"
                data-testid="return-current-stage"
                @click="selectedStageOverride = null"
                >返回当前阶段</el-button
              >
              阶段版本 r{{ currentStageResult.revision }}
            </span>
          </div>
        </template>

        <div
          v-if="
            !isRunning &&
            !showSignoffHold &&
            !isAwaitingReview &&
            showStageError(currentStageResult)
          "
          class="stage-error"
        >
          <el-alert type="error" show-icon :closable="false">
            <template #title>
              <span class="stage-error-heading">
                <span>{{
                  currentStageResult.status === 'failed' ? '阶段执行失败' : '阶段存在待核查问题'
                }}</span>
                <el-button
                  v-if="currentStageResult.status === 'failed' && !viewingPastStage"
                  type="danger"
                  size="small"
                  :loading="resuming"
                  @click="handleResumeStage(currentStageResult.stage)"
                >
                  重试本阶段
                </el-button>
              </span>
            </template>
          </el-alert>
          <details
            v-if="!isAwaitingReview || !currentStageResult.error"
            class="stage-error-details"
          >
            <summary>查看异常明细</summary>
            <p>{{ currentStageResult.error || '执行过程中发生未捕获异常' }}</p>
          </details>
        </div>

        <div
          v-if="
            !isRunning &&
            currentStageResult.error &&
            ['approved', 'completed'].includes(currentStageResult.status)
          "
          class="stage-error"
        >
          <el-alert type="warning" show-icon :closable="false" title="该阶段已通过，仍有质量缺口">
            <template #default>已保留本阶段的质量说明，请结合最终报告质检结果审阅。</template>
          </el-alert>
          <details class="stage-error-details">
            <summary>查看质量说明</summary>
            <p>{{ currentStageResult.error }}</p>
          </details>
        </div>

        <MetricCards :stage="currentStageResult.stage" :data="currentStageResult.data" />

        <el-divider />

        <EvidenceIndexDownload
          v-if="currentStageResult.stage === 'report_fusion'"
          :workflow="workflow"
        />

        <StageDigest
          :stage="currentStageResult.stage"
          :data="currentStageResult.data"
          :source-records="sourceRecords"
          :run-id="runId"
          @preview-report="(anchor) => openReportPreview(anchor)"
          @annotate="onStageAnnotate"
          @view-evidence="onStageViewEvidence"
        />

        <el-divider v-if="!isAwaitingReview" />

        <p v-if="!isAwaitingReview" class="muted" style="margin: 0">
          {{
            workflow?.status === 'cancelled'
              ? '该任务已被中途终止，未继续执行后续阶段。'
              : workflow?.status === 'failed' || currentStageResult.status === 'failed'
                ? '该阶段发生异常暂停。可点击上方「重试本阶段」或顶部「一键断点恢复」继续推进。'
                : currentStageResult.status === 'running' || workflow?.status === 'running'
                  ? '该阶段正在执行，完成后将进入人工审核（若配置了审核门）。'
                  : currentStageName !== workflow?.current_stage
                    ? '正在查看已产出阶段内容；阶段级操作请回到当前等待审核的阶段。'
                    : '该阶段当前无需人工操作。'
          }}
        </p>
      </el-card>

      <!-- 人机协同版本演进对比 (Revision Diff) -->
      <RevisionDiffViewer
        v-if="workflow"
        :run-id="runId"
        :current-revision="workflow.revision"
        @restored="reload"
      />
    </section>
  </div>

  <el-dialog
    v-model="revisionsVisible"
    title="历史版本"
    width="min(640px, calc(100vw - 24px))"
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
    size="min(720px, 100%)"
    :destroy-on-close="false"
    class="agent-trace-drawer"
  >
    <template #header>
      <div class="trace-drawer-header-title">
        <span class="drawer-title-text">智能体微观执行动线与协同底稿</span>
        <el-tag v-if="isRunning" size="small" effect="plain" class="drawer-live-pill">
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

  <!-- 事实穿透与凭证审计抽屉 -->
  <EvidenceDrawer
    v-model="evidenceDrawerVisible"
    :record-ids="activeEvidenceRecordIds"
    :evidence-index="currentEvidenceIndex"
    :source-records="sourceRecords"
  />
</template>

<style scoped>
/* 待审阅主行动卡：左侧金色竖线，和研报刊头呼应，强调「这是当前要做的事」 */
.review-primary-card {
  border-left: 3px solid var(--rp-gold, #b8892b);
}
.quality-summary {
  margin-left: 10px;
  font-size: 12px;
  font-weight: 400;
}
.quality-collapsed-hint {
  margin: 0;
  font-size: 12.5px;
}

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
.strip-timer {
  font-family: var(--rp-serif, serif);
  font-variant-numeric: tabular-nums;
  font-weight: 700;
  font-size: 13px;
  color: var(--rp-gold, #a9853f);
  letter-spacing: 0.5px;
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
  grid-template-columns: clamp(220px, 17vw, 250px) minmax(0, 1fr);
  grid-template-areas:
    'heading heading'
    'projects content';
  gap: 14px 16px;
  align-items: start;
}
.wb-heading {
  grid-area: heading;
  min-width: 0;
  border-bottom: 3px double var(--rp-navy);
  padding-bottom: 10px;
}
.wb-left {
  grid-area: projects;
  position: sticky;
  top: 16px;
  max-height: calc(100dvh - 32px);
  overflow-y: auto;
}
.wb-center {
  grid-area: content;
  min-width: 0;
}
.workbench-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.header-main {
  display: flex;
  align-items: center;
  gap: 10px;
}
.header-main .page-title {
  margin: 0;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.header-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
.header-meta {
  margin-top: 6px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.stage-card-header {
  flex-wrap: wrap;
  gap: 6px 12px;
}
.stage-error {
  margin-bottom: 16px;
}
.stage-error-heading {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.project-tree-toggle {
  display: none;
}
@media (max-width: 1100px) {
  .workbench {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas: 'heading' 'projects' 'content';
    row-gap: 0;
  }
  .wb-heading {
    margin-bottom: 12px;
  }
  .wb-left {
    display: none;
    position: static;
    max-height: 45dvh;
    margin-bottom: 12px;
  }
  .wb-left.is-open {
    display: block;
  }
  .wb-left .page-card {
    margin-bottom: 0;
  }
  .project-tree-toggle {
    display: inline-flex;
  }
}
</style>
