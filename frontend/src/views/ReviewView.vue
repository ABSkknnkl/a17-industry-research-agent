<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getRun, isMockDataMode, listRevisions, submitReview } from '../api/client'
import { ApiError } from '../api/http'
import {
  STAGE_LABELS,
  STAGE_ORDER,
  type DecisionPackage,
  type ReportFusionData,
  type RevisionListResponse,
  type StageName,
  type StageResult,
  type WorkflowState,
} from '../api/types'
import StatusTag from '../components/StatusTag.vue'
import { hidePipelineOverlay, showPipelineOverlay } from '../composables/usePipelineOverlay'
import StageStepper from '../components/StageStepper.vue'
import StageDigest from '../components/StageDigest.vue'
import MetricCards from '../components/MetricCards.vue'
import QualityPanel from '../components/QualityPanel.vue'
import ReviewActions from '../components/ReviewActions.vue'
import WorkbenchActions from '../components/WorkbenchActions.vue'
import ProjectTree from '../components/ProjectTree.vue'
import ReviewInspectorDrawer from '../components/review/ReviewInspectorDrawer.vue'
import { shouldAutoJumpToDownload } from '../api/reportGate'
import { usePrototypeStore } from '../mock/prototypeRun'

const route = useRoute()
const router = useRouter()
const runId = computed(() => String(route.params.runId ?? ''))
const mockMode = isMockDataMode()
const prototypeStore = mockMode ? usePrototypeStore() : null

const workflow = ref<WorkflowState | null>(null)
const loading = ref(false)
const revisions = ref<RevisionListResponse | null>(null)
const revisionsVisible = ref(false)
const timeByRevision = ref<Record<number, string>>({})
const projectTreeRef = ref<InstanceType<typeof ProjectTree> | null>(null)
const selectedStageOverride = ref<StageName | null>(null)
const inspectorVisible = ref(false)
const inspectorObjectId = ref<string | null>(null)
const inspectorFocus = ref<'sources' | 'citations' | null>(null)
const simulating = ref(false)

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
    workflow.value = await getRun(runId.value)
  } catch (e) {
    if (e instanceof ApiError && e.status !== 401) {
      ElMessage.error(`加载任务失败：${e.message}`)
    }
  }
  await checkAutoJump()
}

/** 全自动任务的完成后自动跳转：首页「一键通过」创建的任务在 run 终态时直达下载页。 */
async function checkAutoJump(): Promise<void> {
  if (mockMode) return
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

// ------------------------------------------------------------------
// 「一键通过」：无红色高风险时自动放行剩余审核门，直到报告就绪
// ------------------------------------------------------------------

const quickApproveBusy = ref(false)

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/** 红色高风险判定：任一阶段带 error，或决策包存在阻断风险码（blocking）。 */
function detectHighRisk(state: WorkflowState): string | null {
  for (const result of Object.values(state.stage_results)) {
    if (!result) continue
    if (result.error) return `${result.error}（${result.stage}）`
    const dp = (result.data as Record<string, unknown> | null)?.decision_package as
      | DecisionPackage
      | undefined
    if (dp?.blocking_risk_codes?.length) {
      return `存在阻断风险：${dp.blocking_risk_codes.join('、')}（${result.stage}）`
    }
  }
  return null
}

/** 自动提交单个待审核阶段（有需确认风险→accept_with_risks，否则 approve）。 */
async function submitPendingStage(
  stage: StageName,
  state: WorkflowState
): Promise<void> {
  const result = state.stage_results[stage]
  const dp = (result?.data as Record<string, unknown> | null)?.decision_package as
    | DecisionPackage
    | undefined
  const ackCodes = dp?.acknowledgement_required_codes ?? []
  await submitReview({
    run_id: runId.value,
    stage,
    expected_revision: state.revision,
    action: ackCodes.length > 0 ? 'accept_with_risks' : 'approve',
    accepted_risk_codes: ackCodes.length > 0 ? ackCodes : undefined,
    decision_id: dp?.decision_id,
    risk_snapshot_sha256: dp?.risk_snapshot_sha256,
  })
}

async function quickApproveAll(): Promise<void> {
  if (mockMode || quickApproveBusy.value || !workflow.value) return
  const risk = detectHighRisk(workflow.value)
  if (risk) {
    await ElMessageBox.alert(
      `检测到红色高风险（${risk}）。为安全起见，请逐阶段人工审核处理，一键通过已停用。`,
      '存在高风险，请人工审核',
      { type: 'error', confirmButtonText: '知道了' },
    )
    return
  }
  try {
    await ElMessageBox.confirm(
      '将自动通过剩余的全部审核门，无需逐个点击：无风险阶段直接通过；中、低风险（如数据缺口、质量降级等需确认项）会一并自动确认并写入报告披露；检测到红色高风险（阶段错误/阻断风险）会立即停下移交人工。完成后自动跳转到报告下载页。',
      '一键通过（跳过审核）',
      {
        confirmButtonText: '确认，一键通过',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  quickApproveBusy.value = true
  showPipelineOverlay('report_fusion', '一键通过')
  try {
    // 每轮拉最新状态：有等待审核阶段→自动提交；否则等待流水线推进。
    // 上限 100 轮 × 3s ≈ 5 分钟防御死循环；超时交还人工。
    for (let round = 0; round < 100; round += 1) {
      const state = await getRun(runId.value)
      workflow.value = state
      const blocked = detectHighRisk(state)
      if (blocked) {
        await ElMessageBox.alert(
          `执行过程中出现红色高风险（${blocked}），已停止自动通过，请人工审核。`,
          '已停止，请人工处理',
          { type: 'error', confirmButtonText: '知道了' },
        )
        return
      }
      const pending = STAGE_ORDER.find(
        (stage) => state.stage_results[stage]?.status === 'waiting_review',
      )
      if (pending) {
        await submitPendingStage(pending, state)
        continue
      }
      if (state.status === 'completed' || state.status === 'approved') {
        await router.push({ name: 'report-download', params: { runId: runId.value } })
        return
      }
      if (state.status === 'cancelled' || state.status === 'rejected' || state.status === 'failed') {
        await ElMessageBox.alert(`任务状态已变为「${state.status}」，自动通过停止。`, '已停止', {
          type: 'warning',
          confirmButtonText: '知道了',
        })
        return
      }
      await sleep(3_000)
    }
    ElMessage.warning('一键通过超过时间上限，已停止，请到工作台手动处理')
  } finally {
    quickApproveBusy.value = false
    hidePipelineOverlay()
    await reload()
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
}

function formatTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN')
}

function onSelectStage(stage: StageName): void {
  const result = workflow.value?.stage_results[stage]
  if (!result) return
  selectedStageOverride.value = stage
  if (mockMode && prototypeStore) prototypeStore.selectStage(stage)
}

function openInspector(objectId: string, focus: 'sources' | 'citations' | null = null): void {
  inspectorObjectId.value = objectId
  inspectorFocus.value = focus
  inspectorVisible.value = true
}

/** 跳转独立报告预览页（阶段五「预览完整报告」入口） */
/** 跳转独立报告预览页（阶段五「预览完整报告」入口）；anchor 用于直达某一章 */
function openReportPreview(anchor?: string): void {
  router.push({
    name: 'report-preview',
    params: { runId: runId.value },
    query: anchor ? { anchor } : {},
  })
}

async function onResetDemo(): Promise<void> {
  prototypeStore?.resetPrototype()
  selectedStageOverride.value = null
  await refreshAll()
  ElMessage.success('演示已重置为初始状态')
}

async function onStartSimulation(): Promise<void> {
  if (!prototypeStore) return
  simulating.value = true
  const rec = await prototypeStore.startSimulation()
  ElMessage[rec.ok ? 'success' : 'error'](rec.message)
  simulating.value = false
  await refreshAll()
}

onMounted(refreshAll)

// 左侧树切换任务时重载工作台
watch(runId, async (next, prev) => {
  if (next && next !== prev) {
    selectedStageOverride.value = null
    await refreshAll()
  }
})

onBeforeUnmount(stopPoll)
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
          <el-tag
            v-if="mockMode"
            type="warning"
            effect="plain"
            size="small"
            data-testid="workbench-demo-tag"
          >
            演示数据
          </el-tag>
        </div>
        <div class="header-actions">
          <el-button
            v-if="!mockMode && workflow"
            type="primary"
            :loading="quickApproveBusy"
            data-testid="btn-quick-approve"
            @click="quickApproveAll"
          >
            <el-icon style="margin-right: 4px"><Select /></el-icon>
            一键通过
          </el-button>
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
          <template v-if="mockMode">
            <el-popconfirm title="将清除演示进度并恢复初始 fixture" @confirm="onResetDemo">
              <template #reference>
                <el-button size="small" data-testid="btn-reset-demo">重置演示</el-button>
              </template>
            </el-popconfirm>
            <el-button
              size="small"
              type="primary"
              plain
              :loading="simulating"
              data-testid="btn-simulate"
              @click="onStartSimulation"
            >
              模拟生成
            </el-button>
          </template>
        </div>
      </div>

      <div v-if="workflow" class="header-meta muted">
        项目 {{ workflow.project_id }} · 任务 {{ runId }} · 版本 r{{ workflow.revision }} · 创建于
        {{ formatTime(workflow.created_at) }}
      </div>

      <el-alert
        v-if="mockMode && simulating"
        type="info"
        show-icon
        :closable="false"
        title="演示模拟执行中，可切换已产出阶段查看内容"
        style="margin-bottom: 10px"
        data-testid="sim-progress"
      />
      <el-alert
        v-else-if="isRunning"
        type="info"
        show-icon
        :closable="false"
        title="流水线执行中，页面每 3 秒自动刷新……"
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
          @inspect="(id, focus) => openInspector(id, focus)"
          @object-receipt="() => refreshAll()"
          @preview-report="(anchor) => openReportPreview(anchor)"
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
            :selected-object-id="prototypeStore?.state.selectedObjectId ?? null"
            @submitted="onSubmitted"
            @conflict="reloadWithSpinner"
          />
        </template>
        <p v-else class="muted" style="margin: 0">
          {{
            currentStageResult.status === 'running' || workflow?.status === 'running'
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

  <ReviewInspectorDrawer
    v-model="inspectorVisible"
    :object-id="inspectorObjectId"
    :source-records="sourceRecords"
    :focus="inspectorFocus"
  />
</template>

<style scoped>
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
