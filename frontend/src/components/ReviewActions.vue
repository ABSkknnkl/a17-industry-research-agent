<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiError } from '../api/http'
import { submitReview } from '../api/client'
import {
  STAGE_ORDER,
  type ChartCandidate,
  type DecisionPackage,
  type ReviewAction,
  type ReviewRequest,
  type StageName,
  type StageResult,
  type WorkflowState,
} from '../api/types'
import { showPipelineOverlay, hidePipelineOverlay } from '../composables/usePipelineOverlay'

const props = defineProps<{
  runId: string
  stage: StageName
  result: StageResult
  revision: number
}>()

const emit = defineEmits<{
  (e: 'submitted', state: WorkflowState): void
  (e: 'conflict'): void
}>()

const submitting = ref(false)
const reviseDialogVisible = ref(false)
const reviseComment = ref('')
const reviseQuestions = ref('')

/** 阶段结果 data 中的决策包（chart/data_fetch 等带风险的阶段才会附带） */
const decisionPackage = computed<DecisionPackage | null>(() => {
  const raw = (props.result.data as Record<string, unknown>).decision_package
  return raw && typeof raw === 'object' ? (raw as DecisionPackage) : null
})

const ackRequiredCodes = computed<string[]>(
  () => decisionPackage.value?.acknowledgement_required_codes ?? []
)

const hasError = computed(() => Boolean(props.result.error))

/** 运行时预算告警（阶段耗尽重试上限/超时时由后端写入 result.data） */
const runtimeAlert = computed<{ code?: string; recoverable?: boolean } | null>(() => {
  const raw = (props.result.data as Record<string, unknown>).runtime_alert
  return raw && typeof raw === 'object' ? (raw as { code?: string; recoverable?: boolean }) : null
})

/** 不可恢复（如重试上限耗尽）：重跑类按钮全部禁用，只留取消 */
const recoveryBlocked = computed(() => runtimeAlert.value?.recoverable === false)

/**
 * 渲染单条风险提示。
 * 类型断言刻意放在 script 内：Prettier 的 HTML 解析器会把 `Record<string, unknown>`
 * 中的 `<string,` 误判为标签，进而隐式闭合 `<li>` 导致 `format:check` 报语法错误。
 */
function riskText(risk: unknown): string {
  const r = risk as Record<string, unknown>
  return String(r.title || r.description || r.message || JSON.stringify(risk).slice(0, 150))
}

/** 错误码 → 可读说明与恢复指引 */
const errorGuide = computed(() => {
  const guide: Record<string, string> = {
    intent_clarification_required:
      '智能体无法将研究问题路由到可执行的数据查询。请查看阶段数据中的「待澄清问题」，使用「修改条件重跑」补充更明确的问题（行业/公司 + 指标 + 时间范围）。',
    analysis_input_invalid:
      '阶段输入未通过校验。请查看阶段数据中「INPUT-VALIDATION」协作请求指名的具体字段，修正后通过「修改条件重跑」提交；若反复出现相同错误，请取消任务并反馈，不要盲目重试。',
    required_data_unavailable:
      '部分研究需求未查询到数据。可勾选下方风险确认后继续生成（报告将明确标注数据缺口），或通过「修改条件重跑」调整指标/企业/时间范围。',
    requested_calculation_data_unavailable:
      '用户指定的计算指标缺少原始数据。可勾选下方风险确认后继续生成（该指标将在报告中标注为缺口），或改用可直接查询的原始指标后重跑。',
    analysis_quality_degraded:
      'Agent 2 质量门未通过。可勾选下方风险确认后继续生成（章节将条件性表达并披露限制），或修改条件重跑分析。',
    workflow_deadline_exceeded:
      '任务超出整体时间预算（自创建起按墙钟计算，等待审核期间同样计入）。请取消任务后重新创建；需要更长预算请联系管理员调整。',
    stage_timeout: '单阶段执行超时，可「重新生成」重试。',
    stage_unhandled_exception: '阶段内部异常，可「重新生成」重试。',
    stage_attempt_limit_exceeded:
      '该阶段重试次数已耗尽，任务不可恢复。请取消任务后重新创建（修订内容不会丢失，可在新任务中重新提交）。',
  }
  return (
    guide[props.result.error ?? ''] ??
    '阶段结果携带未解决错误。若下方展示风险确认项，可确认后继续生成；否则请修订或重生成，或取消任务。'
  )
})

/** 图表候选（customize 需要） */
const charts = computed<ChartCandidate[]>(() => {
  const raw = (props.result.data as Record<string, unknown>).charts
  return Array.isArray(raw) ? (raw as ChartCandidate[]) : []
})

const selectedChartIds = ref<string[]>([])
const releaseMode = ref<'formal' | 'draft_with_warnings'>('formal')
const acceptedCodes = ref<string[]>([])

type ReviewPayload = Omit<ReviewRequest, 'run_id' | 'stage' | 'expected_revision'>

/** 执行类动作时展示的全局等待遮罩文案（cancel 即时返回，不展示） */
const ACTION_LABELS: Partial<Record<ReviewAction, string>> = {
  approve: '审核通过',
  accept_with_risks: '确认风险并通过',
  customize: '自定义图表并继续',
  revise: '修改条件重跑',
  regenerate: '重新生成',
}

/** 决策类动作通过后执行下一阶段；revise/regenerate 重跑当前阶段 */
function executingStageFor(action: ReviewAction): StageName {
  if (action === 'approve' || action === 'accept_with_risks' || action === 'customize') {
    const idx = STAGE_ORDER.indexOf(props.stage)
    return STAGE_ORDER[Math.min(idx + 1, STAGE_ORDER.length - 1)] ?? props.stage
  }
  return props.stage
}

async function run(payload: ReviewPayload): Promise<void> {
  submitting.value = true
  const actionLabel = ACTION_LABELS[payload.action]
  if (actionLabel && payload.action !== 'cancel') {
    showPipelineOverlay(executingStageFor(payload.action), actionLabel)
  }
  try {
    const state = await submitReview({
      run_id: props.runId,
      stage: props.stage,
      expected_revision: props.revision,
      ...payload,
    })
    ElMessage.success('操作已提交')
    emit('submitted', state)
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      // 透出后端冲突详情（Revision conflict / Stage conflict），帮助用户
      // 判断是版本过期还是阶段已推进，而非笼统的“版本冲突”。
      ElMessage.warning(
        e.message
          ? `${e.message}，已请求刷新最新状态，请重新操作`
          : '任务已被其他操作更新（版本冲突），已请求刷新最新状态，请重新操作'
      )
      emit('conflict')
    } else if (e instanceof ApiError) {
      ElMessage.error(`${e.message}${e.code ? `（${e.code}）` : ''}`)
    } else {
      ElMessage.error('提交失败，请稍后重试')
    }
  } finally {
    submitting.value = false
    hidePipelineOverlay()
  }
}

// ---- 决策类动作 ----

function buildDecisionFields(): Partial<ReviewRequest> {
  const fields: Partial<ReviewRequest> = {}
  const dp = decisionPackage.value
  if (dp && dp.decision_id && dp.risk_snapshot_sha256) {
    fields.decision_id = dp.decision_id
    fields.risk_snapshot_sha256 = dp.risk_snapshot_sha256
  }
  return fields
}

async function approve(): Promise<void> {
  await run({ action: 'approve', ...buildDecisionFields() })
}

async function acceptWithRisks(): Promise<void> {
  await run({
    action: 'accept_with_risks',
    accepted_risk_codes: [...ackRequiredCodes.value],
    ...buildDecisionFields(),
  })
}

async function customize(): Promise<void> {
  if (selectedChartIds.value.length === 0) {
    ElMessage.warning('请至少选择一张图表')
    return
  }
  await run({
    action: 'customize',
    selected_chart_ids: [...selectedChartIds.value],
    ...buildDecisionFields(),
  })
}

async function submitRevise(): Promise<void> {
  const questions = reviseQuestions.value
    .split('\n')
    .map((q) => q.trim())
    .filter(Boolean)
  const comment = reviseComment.value.trim()
  if (!comment && questions.length === 0) {
    ElMessage.warning('请填写修改备注或修订后的研究问题')
    return
  }
  const edited: Record<string, unknown> = {}
  // data_fetch 与 data_interpret 的修订契约均允许 focus_questions
  // （2026-09-01 修复：此前 data_fetch 静默丢弃用户修订的研究问题，
  // advisory 升级门下用户“删除某段问题”的诉求无法送达后端）
  if ((props.stage === 'data_fetch' || props.stage === 'data_interpret') && questions.length > 0) {
    edited['focus_questions'] = questions
  }
  await run({
    action: 'revise',
    comment: comment || null,
    edited_data: Object.keys(edited).length > 0 ? edited : null,
  })
  reviseDialogVisible.value = false
}

async function regenerate(): Promise<void> {
  try {
    await ElMessageBox.confirm('将按当前条件重新执行该阶段，确认继续？', '重新生成', {
      confirmButtonText: '重新生成',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    // 用户点「取消」/ESC 时 ElMessageBox 以 reject 结束；静默吞掉，
    // 避免 Uncaught (in promise) 'cancel' 污染控制台并误导用户以为按钮损坏。
    return
  }
  await run({ action: 'regenerate' })
}

async function cancelRun(): Promise<void> {
  try {
    await ElMessageBox.confirm('取消后任务将终止且不可恢复，确认取消？', '取消任务', {
      confirmButtonText: '确认取消',
      cancelButtonText: '返回',
      type: 'warning',
    })
  } catch {
    // 同 regenerate：确认框取消属正常路径，静默返回。
    return
  }
  await run({ action: 'cancel' })
}

function openReviseDialog(): void {
  reviseComment.value = ''
  reviseQuestions.value = ''
  reviseDialogVisible.value = true
}
</script>

<template>
  <div class="review-actions">
    <el-alert
      v-if="hasError"
      type="error"
      show-icon
      :closable="false"
      :title="`阶段错误: ${result.error}`"
      :description="errorGuide"
      style="margin-bottom: 16px"
    />

    <!-- 决策包风险提示 -->
    <template v-if="decisionPackage && (decisionPackage.risk_notices ?? []).length > 0">
      <el-alert type="warning" show-icon :closable="false" style="margin-bottom: 16px">
        <template #title>该阶段附带风险提示，请确认后选择处理方式</template>
        <ul class="risk-list">
          <li v-for="(risk, idx) in decisionPackage.risk_notices" :key="idx">
            {{ riskText(risk) }}
          </li>
        </ul>
      </el-alert>
    </template>

    <!-- customize：图表选择 -->
    <template v-if="!hasError && stage === 'chart_generate' && charts.length > 0">
      <h4 class="action-title">图表选择（可选，用于自定义保留哪些图表）</h4>
      <el-checkbox-group v-model="selectedChartIds">
        <div v-for="chart in charts" :key="chart.chart_id" class="chart-row">
          <el-checkbox :value="chart.chart_id">
            {{ chart.title || chart.chart_id }}（{{ chart.chart_type }}）
          </el-checkbox>
        </div>
      </el-checkbox-group>
      <div style="margin-top: 8px">
        <el-button size="small" :disabled="submitting" @click="customize">
          使用选中的图表继续
        </el-button>
      </div>
    </template>

    <!-- report_fusion：发布模式 -->
    <template v-if="!hasError && stage === 'report_fusion'">
      <h4 class="action-title">发布模式</h4>
      <el-radio-group v-model="releaseMode">
        <el-radio value="formal">正式报告</el-radio>
        <el-radio value="draft_with_warnings">草稿（附风险警告）</el-radio>
      </el-radio-group>
    </template>

    <!-- 不可恢复告警（重试上限耗尽等）：重跑类按钮全部禁用，只留取消 -->
    <el-alert
      v-if="recoveryBlocked"
      type="error"
      show-icon
      :closable="false"
      title="该任务已不可恢复（运行时预算耗尽）"
      description="继续点击重跑类按钮只会被后端拒绝。请取消任务后重新创建；修订内容可在新任务中重新提交。"
      style="margin-bottom: 16px"
    />

    <!-- 操作按钮区 -->
    <div class="action-bar">
      <!-- 有决策包（用户裁决门）时即使携带 error 也展示「确认风险并继续」；
           纯 error（无决策包）仍只有修订/重生成/取消三条路。 -->
      <template v-if="decisionPackage || !hasError">
        <el-button
          v-if="ackRequiredCodes.length === 0 && !hasError"
          type="primary"
          :loading="submitting"
          @click="approve"
        >
          通过并继续
        </el-button>
        <template v-if="ackRequiredCodes.length > 0">
          <el-alert
            type="warning"
            show-icon
            :closable="false"
            title="以下风险需要逐项确认后方可通过"
            style="margin-bottom: 8px"
          />
          <el-checkbox-group v-model="acceptedCodes" class="ack-list">
            <el-checkbox v-for="code in ackRequiredCodes" :key="code" :value="code">
              {{ code }}
            </el-checkbox>
          </el-checkbox-group>
          <el-button
            type="primary"
            :disabled="acceptedCodes.length < ackRequiredCodes.length"
            :loading="submitting"
            @click="acceptWithRisks"
          >
            {{ hasError ? '确认风险并继续生成' : '确认全部风险并通过' }}
          </el-button>
        </template>
      </template>

      <el-button :disabled="submitting || recoveryBlocked" @click="openReviseDialog">
        修改条件重跑
      </el-button>
      <el-button :disabled="submitting || recoveryBlocked" @click="regenerate">
        原条件重新生成
      </el-button>
      <el-button type="danger" plain :disabled="submitting" @click="cancelRun">取消任务</el-button>
    </div>

    <!-- 修订对话框 -->
    <el-dialog v-model="reviseDialogVisible" title="修改条件后重跑" width="560px">
      <el-form label-position="top">
        <el-form-item label="修改备注（反馈给智能体）">
          <el-input
            v-model="reviseComment"
            type="textarea"
            :rows="3"
            maxlength="2000"
            show-word-limit
            placeholder="如：请额外关注宁德时代的毛利率变化；时间范围扩大到近 5 年"
          />
        </el-form-item>
        <el-form-item
          v-if="stage === 'data_fetch' || stage === 'data_interpret'"
          label="修订后的研究问题（每行一个，将替换原研究问题）"
        >
          <el-input
            v-model="reviseQuestions"
            type="textarea"
            :rows="4"
            maxlength="2000"
            show-word-limit
            placeholder="请写明具体行业/公司、指标与时间范围，例如：&#10;锂电池行业2024-2025年营业收入与净利润增速如何？&#10;宁德时代、比亚迪、亿纬锂能2024年市占率与毛利率对比？"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviseDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitRevise">
          提交修订并重跑
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.action-title {
  margin: 16px 0 8px;
  font-size: 14px;
  font-weight: 600;
}
.chart-row {
  line-height: 1.8;
}
.ack-list {
  margin-bottom: 12px;
  display: flex;
  flex-direction: column;
}
.action-bar {
  margin-top: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.risk-list {
  margin: 4px 0 0;
  padding-left: 18px;
}
</style>
