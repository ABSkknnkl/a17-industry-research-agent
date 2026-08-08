<!--
  Review.vue - 人机协同审核页面
  集成 DecisionCard 和 ExportDecisionCard，用于用户在审核门做出决策
-->
<template>
  <div class="review-page">
    <el-card class="review-header-card" shadow="hover">
      <template #header>
        <div class="review-header">
          <span class="review-title">审核决策</span>
          <el-tag v-if="workflowState" :type="stageTagType">
            {{ currentStageLabel }}
          </el-tag>
        </div>
      </template>

      <el-descriptions v-if="workflowState" :column="3" border size="small">
        <el-descriptions-item label="运行ID">{{ workflowState.run_id }}</el-descriptions-item>
        <el-descriptions-item label="当前阶段">{{ currentStageLabel }}</el-descriptions-item>
        <el-descriptions-item label="修订版本">R{{ workflowState.revision }}</el-descriptions-item>
      </el-descriptions>

      <el-empty v-else description="加载中..." />
    </el-card>

    <!-- Agent 3 图表选择决策 -->
    <DecisionCard
      v-if="showChartDecision"
      :candidates="chartCandidates"
      :risk-notices="chartRiskNotices"
      :conflict-groups="conflictGroups"
      :acknowledgement-required-codes="ackRequiredCodes"
      @accept-recommendation="handleAcceptRecommendation"
      @accept-with-risks="handleAcceptWithRisks"
      @customize="handleCustomize"
      @regenerate="handleRegenerate"
      @cancel="handleCancel"
    />

    <!-- Agent 5 报告导出决策 -->
    <ExportDecisionCard
      v-if="showExportDecision"
      :formal-eligible="exportFormalEligible"
      :draft-eligible="exportDraftEligible"
      :blocking-count="exportBlockingCount"
      :advisory-count="exportAdvisoryCount"
      :blocking-issues="exportBlockingIssues"
      :advisory-issues="exportAdvisoryIssues"
      @export-formal="handleExportFormal"
      @export-draft="handleExportDraft"
      @back-to-edit="handleBackToEdit"
      @cancel="handleCancel"
    />

    <!-- 非审核状态 -->
    <el-card v-if="!showChartDecision && !showExportDecision && workflowState" class="status-card">
      <el-result
        v-if="workflowState.status === 'completed'"
        icon="success"
        title="工作流已完成"
        sub-title="报告已生成，可在下方查看产物"
      />
      <el-result
        v-else-if="workflowState.status === 'failed'"
        icon="error"
        title="工作流失败"
        :sub-title="failureReason"
      />
      <el-result
        v-else-if="workflowState.status === 'cancelled'"
        icon="warning"
        title="工作流已取消"
      />
      <el-result
        v-else
        icon="info"
        :title="`当前状态: ${workflowState.status}`"
        sub-title="等待中..."
      />
    </el-card>

    <!-- 产物下载 -->
    <el-card v-if="reportResult" class="artifacts-card">
      <template #header>
        <span>报告产物</span>
      </template>
      <div class="artifact-list">
        <div
          v-for="artifact in reportResult.artifacts"
          :key="artifact.artifact_id"
          class="artifact-item"
        >
          <el-tag :type="artifactKindTag(artifact.kind)">
            {{ artifactKindLabel(artifact.kind) }}
          </el-tag>
          <el-button
            size="small"
            type="primary"
            link
            @click="downloadArtifact(artifact)"
          >
            下载
          </el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import type {
  WorkflowState,
  ChartCandidateResult,
  ConflictGroup,
  RiskNotice,
  ReportFusionResult,
  ReportArtifactManifestEntry,
} from '@/types/workflow'
import DecisionCard from '@/components/review/DecisionCard.vue'
import ExportDecisionCard from '@/components/report/ExportDecisionCard.vue'

const route = useRoute()
const runId = computed(() => route.params.runId as string)

const workflowState = ref<WorkflowState | null>(null)
const pollingTimer = ref<ReturnType<typeof setInterval> | null>(null)

// Decision package data from Agent 3
const chartCandidates = ref<ChartCandidateResult[]>([])
const chartRiskNotices = ref<RiskNotice[]>([])
const conflictGroups = ref<ConflictGroup[]>([])
const ackRequiredCodes = ref<string[]>([])

// Export decision data from Agent 5
const exportFormalEligible = ref(false)
const exportDraftEligible = ref(false)
const exportBlockingCount = ref(0)
const exportAdvisoryCount = ref(0)
const exportBlockingIssues = ref<string[]>([])
const exportAdvisoryIssues = ref<string[]>([])

// Report result
const reportResult = ref<ReportFusionResult | null>(null)

const currentStageLabel = computed(() => {
  if (!workflowState.value) return ''
  const labels: Record<string, string> = {
    data_fetch: '数据采集',
    data_interpret: '数据分析',
    chart_generate: '图表生成',
    chapter_write: '章节撰写',
    report_fusion: '报告融合',
  }
  return labels[workflowState.value.current_stage] || workflowState.value.current_stage
})

const stageTagType = computed(() => {
  if (!workflowState.value) return 'info'
  if (workflowState.value.status === 'waiting_review') return 'warning'
  if (workflowState.value.status === 'completed') return 'success'
  if (workflowState.value.status === 'failed') return 'danger'
  return 'info'
})

const showChartDecision = computed(() => {
  if (!workflowState.value) return false
  return (
    workflowState.value.status === 'waiting_review' &&
    workflowState.value.current_stage === 'chart_generate'
  )
})

const showExportDecision = computed(() => {
  if (!workflowState.value) return false
  return (
    workflowState.value.status === 'waiting_review' &&
    workflowState.value.current_stage === 'report_fusion'
  )
})

const failureReason = computed(() => {
  if (!workflowState.value) return ''
  const stageResult = workflowState.value.stage_results[workflowState.value.current_stage]
  return stageResult?.error || '未知错误'
})

function parseDecisionPackage() {
  if (!workflowState.value) return
  const chartResult = workflowState.value.stage_results.chart_generate
  if (!chartResult?.data) return

  const dp = chartResult.data.decision_package as Record<string, unknown> | undefined
  if (!dp) return

  chartCandidates.value = (dp.all_candidates as ChartCandidateResult[]) || []
  chartRiskNotices.value = (dp.risk_notices as RiskNotice[]) || []
  conflictGroups.value = (dp.conflict_groups as ConflictGroup[]) || []
  ackRequiredCodes.value = (dp.acknowledgement_required_codes as string[]) || []
}

function parseExportDecision() {
  if (!workflowState.value) return
  const reportResult = workflowState.value.stage_results.report_fusion
  if (!reportResult?.data) return

  const data = reportResult.data as Record<string, unknown>
  exportFormalEligible.value = (data.formal_eligible as boolean) || false
  exportDraftEligible.value = (data.draft_eligible as boolean) || false
  exportBlockingCount.value = ((data.blocking_issues as string[]) || []).length
  exportAdvisoryCount.value = ((data.advisory_issues as string[]) || []).length
  exportBlockingIssues.value = (data.blocking_issues as string[]) || []
  exportAdvisoryIssues.value = (data.advisory_issues as string[]) || []
}

function parseReportResult() {
  if (!workflowState.value) return
  const reportStage = workflowState.value.stage_results.report_fusion
  if (!reportStage?.data) return

  const data = reportStage.data as Record<string, unknown>
  if (data.report_id) {
    reportResult.value = data as unknown as ReportFusionResult
  }
}

async function fetchWorkflowState() {
  try {
    const response = await fetch(`/api/v1/runs/${runId.value}`)
    if (!response.ok) return
    const data = await response.json()
    workflowState.value = data as WorkflowState

    parseDecisionPackage()
    parseExportDecision()
    parseReportResult()

    // 如果不再需要审核，停止轮询
    if (
      data.status === 'completed' ||
      data.status === 'failed' ||
      data.status === 'cancelled'
    ) {
      stopPolling()
    }
  } catch {
    // 忽略网络错误，继续轮询
  }
}

function startPolling() {
  stopPolling()
  fetchWorkflowState()
  pollingTimer.value = setInterval(fetchWorkflowState, 3000)
}

function stopPolling() {
  if (pollingTimer.value) {
    clearInterval(pollingTimer.value)
    pollingTimer.value = null
  }
}

async function submitReview(payload: Record<string, unknown>) {
  try {
    const response = await fetch(`/api/v1/runs/${runId.value}/reviews`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!response.ok) {
      const error = await response.json()
      console.error('Review submission failed:', error)
      return
    }
    // 审核提交后立即刷新状态
    await fetchWorkflowState()
  } catch (err) {
    console.error('Review submission error:', err)
  }
}

function handleAcceptRecommendation() {
  submitReview({
    run_id: runId.value,
    stage: 'chart_generate',
    action: 'accept_recommendation',
    expected_revision: workflowState.value?.revision || 1,
  })
}

function handleAcceptWithRisks() {
  submitReview({
    run_id: runId.value,
    stage: 'chart_generate',
    action: 'accept_with_risks',
    expected_revision: workflowState.value?.revision || 1,
    accepted_risk_codes: ackRequiredCodes.value,
    release_mode: 'draft_with_warnings',
  })
}

function handleCustomize(selectedIds: string[]) {
  submitReview({
    run_id: runId.value,
    stage: 'chart_generate',
    action: 'customize',
    expected_revision: workflowState.value?.revision || 1,
    selected_chart_ids: selectedIds,
    placement_overrides: {},
  })
}

function handleRegenerate() {
  submitReview({
    run_id: runId.value,
    stage: 'chart_generate',
    action: 'regenerate',
    expected_revision: workflowState.value?.revision || 1,
  })
}

function handleExportFormal() {
  submitReview({
    run_id: runId.value,
    stage: 'report_fusion',
    action: 'accept_recommendation',
    expected_revision: workflowState.value?.revision || 1,
    release_mode: 'formal',
  })
}

function handleExportDraft() {
  submitReview({
    run_id: runId.value,
    stage: 'report_fusion',
    action: 'accept_with_risks',
    expected_revision: workflowState.value?.revision || 1,
    accepted_risk_codes: ['REPORT-QUALITY-ADVISORY'],
    release_mode: 'draft_with_warnings',
  })
}

function handleBackToEdit() {
  submitReview({
    run_id: runId.value,
    stage: 'report_fusion',
    action: 'revise',
    expected_revision: workflowState.value?.revision || 1,
  })
}

function handleCancel() {
  submitReview({
    run_id: runId.value,
    stage: workflowState.value?.current_stage || 'chart_generate',
    action: 'cancel',
    expected_revision: workflowState.value?.revision || 1,
  })
}

function artifactKindTag(kind: string): string {
  if (kind === 'report_pdf') return 'danger'
  if (kind === 'report_html') return 'warning'
  if (kind === 'report_markdown') return 'success'
  return 'info'
}

function artifactKindLabel(kind: string): string {
  const labels: Record<string, string> = {
    report_markdown: 'Markdown',
    report_html: 'HTML',
    report_pdf: 'PDF',
    artifact_manifest: 'Manifest',
  }
  return labels[kind] || kind
}

function downloadArtifact(artifact: ReportArtifactManifestEntry) {
  const url = `/api/v1/runs/${runId.value}/artifacts/${artifact.artifact_id}`
  window.open(url, '_blank')
}

onMounted(() => {
  startPolling()
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.review-page {
  max-width: 900px;
  margin: 0 auto;
}

.review-header-card {
  margin-bottom: 16px;
}

.review-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.review-title {
  font-size: 18px;
  font-weight: 600;
}

.status-card {
  margin-bottom: 16px;
}

.artifacts-card {
  margin-bottom: 16px;
}

.artifact-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.artifact-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: #f9fafb;
  border-radius: 6px;
}
</style>