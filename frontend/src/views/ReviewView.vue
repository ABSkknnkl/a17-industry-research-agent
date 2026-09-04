<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getRun, listRevisions } from '../api/client'
import { ApiError } from '../api/http'
import {
  STAGE_LABELS,
  type ChapterDraftLoose,
  type ReportFusionData,
  type RevisionListResponse,
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
import ArtifactList from '../components/ArtifactList.vue'
import ReportPreview from '../components/ReportPreview.vue'
import ReportReader from '../components/ReportReader.vue'
import ChartGallery from '../components/ChartGallery.vue'
import ProjectTree from '../components/ProjectTree.vue'

const route = useRoute()
const runId = computed(() => String(route.params.runId ?? ''))

const workflow = ref<WorkflowState | null>(null)
const loading = ref(false)
const revisions = ref<RevisionListResponse | null>(null)
const revisionsVisible = ref(false)
const timeByRevision = ref<Record<number, string>>({})
const projectTreeRef = ref<InstanceType<typeof ProjectTree> | null>(null)

let pollTimer: ReturnType<typeof setTimeout> | null = null
const POLL_INTERVAL_MS = 3_000

const allStageResults = computed<StageResult[]>(() => {
  const state = workflow.value
  if (!state) return []
  return Object.values(state.stage_results).filter((r): r is StageResult => Boolean(r))
})

const currentStageName = computed(() => workflow.value?.current_stage ?? null)
const currentStageResult = computed<StageResult | null>(() => {
  const stage = currentStageName.value
  if (!stage || !workflow.value) return null
  return workflow.value.stage_results[stage] ?? null
})

const isRunning = computed(() => workflow.value?.status === 'running')

const allArtifacts = computed<StageResult['artifacts']>(() => {
  const result: StageResult['artifacts'] = []
  for (const stageResult of allStageResults.value) {
    result.push(...stageResult.artifacts)
  }
  return result
})

/** report_fusion 产出（宽松读取，字段与后端 ReportFusionResult 一致） */
const fusionData = computed<ReportFusionData | null>(() => {
  const raw = workflow.value?.stage_results.report_fusion?.data
  if (!raw || typeof raw !== 'object') return null
  return raw as unknown as ReportFusionData
})

/** chapter_write 产出章节（用于报告目录预览） */
const chapters = computed<ChapterDraftLoose[]>(() => {
  const raw = workflow.value?.stage_results.chapter_write?.data
  if (!raw || typeof raw !== 'object') return []
  const list = (raw as Record<string, unknown>).chapters
  return Array.isArray(list) ? (list as ChapterDraftLoose[]) : []
})

/** artifact_id → 文件大小（融合 manifest 已有 size_bytes，前端聚合） */
const sizeById = computed<Record<string, number>>(() => {
  const map: Record<string, number> = {}
  for (const entry of fusionData.value?.artifacts ?? []) {
    if (entry.artifact_id && typeof entry.size_bytes === 'number') {
      map[entry.artifact_id] = entry.size_bytes
    }
  }
  return map
})

/** 报告 Markdown 产物（正文阅读器数据源） */
const markdownArtifact = computed<StageResult['artifacts'][number] | null>(() => {
  for (const entry of allArtifacts.value) {
    if (entry && entry.kind === 'report_markdown') return entry
  }
  return null
})

/** chart_generate 图表规格（ECharts option，前端直接渲染） */
const chartSpecs = computed<Record<string, unknown>[]>(() => {
  const raw = workflow.value?.stage_results.chart_generate?.data
  if (!raw || typeof raw !== 'object') return []
  const list = (raw as Record<string, unknown>).chart_specs
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

async function onSubmitted(state: WorkflowState): Promise<void> {
  workflow.value = state
  schedulePoll()
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

onMounted(refreshAll)

// 左侧树切换任务时重载工作台
watch(runId, async (next, prev) => {
  if (next && next !== prev) await refreshAll()
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
        </div>
        <div class="header-actions">
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
          <el-button size="small" :loading="loading" @click="refreshAll">
            <el-icon style="margin-right: 4px"><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </div>

      <div v-if="workflow" class="header-meta muted">
        项目 {{ workflow.project_id }} · 任务 {{ runId }} · 版本 r{{ workflow.revision }} · 创建于
        {{ formatTime(workflow.created_at) }}
      </div>

      <el-alert
        v-if="isRunning"
        type="info"
        show-icon
        :closable="false"
        title="流水线执行中，页面每 3 秒自动刷新……"
        style="margin-bottom: 10px"
      />

      <!-- 流程节点 -->
      <el-card class="page-card" shadow="never" v-loading="loading">
        <StageStepper :stage-results="workflow?.stage_results ?? {}" />
      </el-card>

      <!-- 融合质量（有融合产出时展示） -->
      <el-card v-if="fusionData?.quality" class="page-card" shadow="never">
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

        <StageDigest :stage="currentStageResult.stage" :data="currentStageResult.data" />

        <el-divider />

        <template v-if="workflow?.status === 'waiting_review'">
          <ReviewActions
            :key="`${currentStageResult.stage}-${currentStageResult.revision}`"
            :run-id="runId"
            :stage="currentStageResult.stage"
            :result="currentStageResult"
            :revision="workflow!.revision"
            @submitted="onSubmitted"
            @conflict="reloadWithSpinner"
          />
        </template>
        <p v-else class="muted" style="margin: 0">
          {{
            currentStageResult.status === 'running' || workflow?.status === 'running'
              ? '该阶段正在执行，完成后将进入人工审核（若配置了审核门）。'
              : '该阶段当前无需人工操作。'
          }}
        </p>
      </el-card>
    </main>

    <!-- 右栏：报告预览 / 产出物 -->
    <aside class="wb-right">
      <el-card class="page-card" shadow="never">
        <el-tabs>
          <el-tab-pane>
            <template #label>
              <span class="tab-label"
                ><el-icon><Document /></el-icon> 报告预览</span
              >
            </template>
            <div class="right-scroll">
              <ReportPreview :fusion="fusionData" :chapters="chapters" />
            </div>
          </el-tab-pane>
          <el-tab-pane>
            <template #label>
              <span class="tab-label"
                ><el-icon><Reading /></el-icon> 正文</span
              >
            </template>
            <div class="right-scroll">
              <ReportReader :run-id="runId" :markdown-artifact="markdownArtifact" />
            </div>
          </el-tab-pane>
          <el-tab-pane>
            <template #label>
              <span class="tab-label">
                <el-icon><DataLine /></el-icon> 图表（{{ chartSpecs.length }}）
              </span>
            </template>
            <div class="right-scroll">
              <ChartGallery :specs="chartSpecs" />
            </div>
          </el-tab-pane>
          <el-tab-pane>
            <template #label>
              <span class="tab-label">
                <el-icon><Files /></el-icon> 产出物（{{ allArtifacts.length }}）
              </span>
            </template>
            <div class="right-scroll">
              <el-empty v-if="allArtifacts.length === 0" description="暂无产物" :image-size="60" />
              <ArtifactList
                v-else
                :run-id="runId"
                :artifacts="allArtifacts"
                :size-by-id="sizeById"
                :time-by-revision="timeByRevision"
              />
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </aside>
  </div>

  <el-dialog v-model="revisionsVisible" title="历史版本" width="640px">
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
</template>

<style scoped>
.workbench {
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr) 360px;
  gap: 16px;
  align-items: start;
}
.wb-left {
  position: sticky;
  top: 16px;
}
.wb-right {
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
.right-scroll {
  max-height: calc(100vh - 220px);
  overflow: auto;
}
.tab-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
@media (max-width: 1400px) {
  .workbench {
    grid-template-columns: 220px minmax(0, 1fr) 320px;
  }
}
@media (max-width: 1100px) {
  .workbench {
    grid-template-columns: 1fr;
  }
  .wb-left,
  .wb-right {
    position: static;
  }
}
</style>
