<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ApiError } from '../api/http'
import { submitReview } from '../api/client'
import {
  STAGE_ORDER,
  type DecisionPackage,
  type ReviewAction,
  type ReviewRequest,
  type StageName,
  type StageResult,
  type WorkflowState,
} from '../api/types'
import { showPipelineOverlay, hidePipelineOverlay } from '../composables/usePipelineOverlay'
import StageInterventionModal from './StageInterventionModal.vue'

const props = defineProps<{
  runId: string
  stage: StageName
  result: StageResult
  revision: number
  selectedObjectId?: string | null
  annotations?: any[]
}>()

const emit = defineEmits<{
  (e: 'submitted', state: WorkflowState, meta: { stage: StageName; action: string }): void
  (e: 'conflict'): void
}>()

const submitting = ref(false)

/** 阶段结果 data 中的决策包（chart/data_fetch 等带风险的阶段才会附带） */
const decisionPackage = computed<DecisionPackage | null>(() => {
  const raw = (props.result.data as Record<string, unknown>).decision_package
  return raw && typeof raw === 'object' ? (raw as DecisionPackage) : null
})

const ackRequiredCodes = computed<string[]>(() => {
  return decisionPackage.value?.acknowledgement_required_codes ?? []
})

const hasError = computed(() => Boolean(props.result.error))

/** 运行时预算告警（阶段耗尽重试上限/超时时由后端写入 result.data） */
const runtimeAlert = computed<{ code?: string; recoverable?: boolean } | null>(() => {
  const raw = (props.result.data as Record<string, unknown>).runtime_alert
  return raw && typeof raw === 'object' ? (raw as { code?: string; recoverable?: boolean }) : null
})

/** 不可恢复（如重试上限耗尽）：重跑类按钮全部禁用，只留取消 */
const recoveryBlocked = computed(() => runtimeAlert.value?.recoverable === false)

function riskText(risk: unknown): string {
  if (typeof risk === 'string') return risk
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

const releaseMode = ref<'formal' | 'draft_with_warnings'>('formal')
const riskDialogVisible = ref(false)

type ReviewPayload = Omit<ReviewRequest, 'run_id' | 'stage' | 'expected_revision'>

/** 执行类动作时展示的全局等待遮罩文案（cancel 即时返回，不展示） */
const ACTION_LABELS: Partial<Record<ReviewAction, string>> = {
  approve: '审核通过',
  accept_with_risks: '确认风险并通过',
  customize: '自定义图表并继续',
  revise: '修改条件重跑',
  regenerate: '重新生成',
  direct_edit: '保存局部微调',
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
    emit('submitted', state, { stage: props.stage, action: payload.action })
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
    } else if (e instanceof Error) {
      ElMessage.error(e.message)
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

/** 有风险时：打开风险提示，用户点同意后进入下一阶段 */
async function acceptWithRisks(): Promise<void> {
  riskDialogVisible.value = false
  await run({
    action: 'accept_with_risks',
    accepted_risk_codes: [...ackRequiredCodes.value],
    ...buildDecisionFields(),
  })
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

/**
 * 阶段五（报告融合）用报告语义的按钮文案，其余阶段沿用通用文案。
 */
const isFusionStage = computed(() => props.stage === 'report_fusion')
const approveLabel = computed(() => {
  const map: Record<StageName, string> = {
    data_fetch: '确认数据完备，进入解读分析',
    data_interpret: '确认解读逻辑，进入图表生成',
    chart_generate: '确认图表库，进入章节撰写',
    chapter_write: '确认全文报告，进入终审融合',
    report_fusion: '出版级核准签发与完成交付',
  }
  return map[props.stage] || (isFusionStage.value ? '通过并完成研究' : '通过并继续')
})

const stageTitle = computed(() => {
  const map: Record<StageName, string> = {
    data_fetch: '【阶段一：数据采集智能体】人机协同控制区',
    data_interpret: '【阶段二：数据解读智能体】人机协同控制区',
    chart_generate: '【阶段三：图表生成智能体】人机协同控制区',
    chapter_write: '【阶段四：章节撰写智能体】人机协同控制区',
    report_fusion: '【阶段五：报告融合智能体】人机协同控制区',
  }
  return map[props.stage] || '阶段人机协同控制区'
})

const stageDescription = computed(() => {
  const map: Record<StageName, string> = {
    data_fetch: '支持增量数据单点精准补采、按子领域局部重采与脏数据清洗剔除，拒绝低效全盘重跑。',
    data_interpret: '支持可比公司标的池动态增删与梯队调整、核心研判论点精修与行业异常信号人工裁决。',
    chart_generate: '支持图表形态类型自由切换（柱状/折线/水平/堆叠）、图表显隐排除编排与定向新增图表。',
    chapter_write: '支持指定单章定向重写（仅重写单一章节，其余6章完全保留）、正文段落就地精修与行文风格引导。',
    report_fusion: '支持 8 张核心指标卡深度定制、行业投资建议评级定稿、执行摘要精修与出版级交付。',
  }
  return map[props.stage] || '提供专业差异化的人机协同干预能力。'
})

// 专业协同弹窗状态
const stageInterventionVisible = ref(false)
const stageInterventionTab = ref('replenish')

function openStageModal(tab: string): void {
  stageInterventionTab.value = tab
  stageInterventionVisible.value = true
}

async function onStageReviseSubmit(payload: { comment: string; edited_data?: Record<string, unknown> | null }): Promise<void> {
  await run({
    action: 'revise',
    comment: payload.comment || null,
    edited_data: payload.edited_data || null,
  })
}

async function onStageDirectEditSubmit(payload: { edited_data: Record<string, unknown>; comment?: string }): Promise<void> {
  await run({
    action: 'direct_edit',
    comment: payload.comment || '用户阶段精准微调',
    edited_data: payload.edited_data,
  })
}

</script>

<template>
  <div class="review-actions" data-testid="review-actions">
    <el-alert
      v-if="hasError"
      type="error"
      show-icon
      :closable="false"
      :title="`阶段错误: ${result.error}`"
      :description="errorGuide"
      style="margin-bottom: 16px"
    />

    <!-- report_fusion：发布模式（仅正式报告） -->
    <template v-if="!hasError && stage === 'report_fusion'">
      <h4 class="action-title">发布模式</h4>
      <el-radio-group v-model="releaseMode">
        <el-radio value="formal">正式报告</el-radio>
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

    <!-- 阶段差异化人机协同控制区 -->
    <div class="stage-intervention-card" data-testid="stage-intervention-hub">
      <div class="intervention-header">
        <div class="header-left">
          <span class="intervention-badge">人机协同分工模式</span>
          <h4 class="intervention-title">{{ stageTitle }}</h4>
        </div>
        <div class="header-right">
          <span class="intervention-desc">{{ stageDescription }}</span>
          <el-button
            type="danger"
            link
            size="small"
            :disabled="submitting"
            data-testid="btn-cancel"
            class="btn-cancel-task"
            @click="cancelRun"
          >
            取消任务
          </el-button>
        </div>
      </div>

      <!-- 阶段专属精准介入按钮组 -->
      <div class="intervention-actions">
        <!-- 阶段专属主通过按钮 -->
        <template v-if="decisionPackage || !hasError">
          <el-button
            v-if="ackRequiredCodes.length === 0 && !hasError"
            type="primary"
            size="large"
            class="btn-primary-action"
            :loading="submitting"
            data-testid="btn-approve"
            @click="approve"
          >
            {{ approveLabel }}
          </el-button>
          <el-button
            v-else-if="ackRequiredCodes.length > 0"
            type="primary"
            size="large"
            class="btn-primary-action"
            :loading="submitting"
            data-testid="btn-risk-notice"
            @click="riskDialogVisible = true"
          >
            风险提示（{{ ackRequiredCodes.length }}）
          </el-button>
        </template>

        <!-- 阶段 1：数据采集 (data_fetch) 专属介入 -->
        <template v-if="stage === 'data_fetch'">
          <el-button
            type="primary"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('replenish')"
          >
            增量数据补采
          </el-button>
          <el-button
            type="primary"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('partial_refetch')"
          >
            局部子域重采
          </el-button>
          <el-button
            type="warning"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('clean')"
          >
            脏数据清洗与剔除
          </el-button>
        </template>

        <!-- 阶段 2：数据解读 (data_interpret) 专属介入 -->
        <template v-else-if="stage === 'data_interpret'">
          <el-button
            type="primary"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('comps')"
          >
            标的池与可比公司调整
          </el-button>
          <el-button
            type="primary"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('findings')"
          >
            核心研判论点精修
          </el-button>
          <el-button
            type="warning"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('risks')"
          >
            异常指标与风险裁决
          </el-button>
        </template>

        <!-- 阶段 3：图表生成 (chart_generate) 专属介入 -->
        <template v-else-if="stage === 'chart_generate'">
          <el-button
            type="primary"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('morph')"
          >
            图表形态与类型切换
          </el-button>
          <el-button
            type="primary"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('new_chart')"
          >
            新增定向图表诉求
          </el-button>
        </template>

        <!-- 阶段 4：章节撰写 (chapter_write) 专属介入 -->
        <template v-else-if="stage === 'chapter_write'">
          <el-button
            type="primary"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('single_chapter')"
          >
            指定单章定向重写
          </el-button>
          <el-button
            type="primary"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('inline_polish')"
          >
            正文段落就地精修
          </el-button>
          <el-button
            type="warning"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('style_guide')"
          >
            研报行文风格引导
          </el-button>
        </template>

        <!-- 阶段 5：报告融合 (report_fusion) 专属介入 -->
        <template v-else-if="stage === 'report_fusion'">
          <el-button
            type="primary"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('metric_cards')"
          >
            8 张核心指标卡定制
          </el-button>
          <el-button
            type="primary"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('summary_rating')"
          >
            投资评级与执行摘要定稿
          </el-button>
        </template>
      </div>

    </div>

    <!-- 阶段差异化专业人机协同工作台 -->
    <StageInterventionModal
      v-model:visible="stageInterventionVisible"
      :stage="stage"
      :revision="revision"
      :data="(result.data as Record<string, unknown>) || {}"
      :annotations="annotations"
      :initial-tab="stageInterventionTab"
      :submitting="submitting"
      @submit-revise="onStageReviseSubmit"
      @submit-direct-edit="onStageDirectEditSubmit"
      @approve="approve"
    />

    <!-- 风险提示确认窗 -->
    <el-dialog v-model="riskDialogVisible" title="风险提示" width="480px" data-testid="risk-dialog">
      <el-alert type="warning" show-icon :closable="false" style="margin-bottom: 12px">
        <template #title
          >本阶段检测到 {{ ackRequiredCodes.length }} 项风险，同意后进入下一阶段</template
        >
      </el-alert>
      <ul class="risk-list">
        <li v-for="code in ackRequiredCodes" :key="code" data-testid="risk-item">
          <el-tag size="small" type="warning" effect="plain">{{ code }}</el-tag>
          <span class="risk-desc">{{ riskText(code) }}</span>
        </li>
      </ul>
      <template #footer>
        <el-button data-testid="risk-cancel" @click="riskDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="submitting"
          data-testid="risk-agree"
          @click="acceptWithRisks"
        >
          同意并继续
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
.stage-intervention-card {
  margin-top: 16px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  padding: 16px 20px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.04);
}
.intervention-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  flex-wrap: wrap;
  gap: 10px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.intervention-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  border: 1px solid var(--el-color-primary-light-7);
}
.intervention-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.intervention-desc {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.btn-cancel-task {
  font-size: 13px;
  color: var(--el-color-danger);
  padding: 0 4px;
}
.btn-cancel-task:hover {
  text-decoration: underline;
}
.intervention-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 0;
}
.btn-primary-action {
  font-weight: 600;
  padding: 12px 22px;
}
.risk-list {
  margin: 0;
  padding-left: 4px;
  list-style: none;
}
.risk-list li {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 12.5px;
  line-height: 1.6;
}
.risk-desc {
  color: var(--el-text-color-regular);
}
</style>
