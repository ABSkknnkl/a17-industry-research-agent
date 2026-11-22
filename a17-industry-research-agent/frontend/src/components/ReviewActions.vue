<script setup lang="ts">
import type { ChainDeliveryInfo, UserAnnotation } from '../api/types'
import { computed, ref, watch } from 'vue'
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
import { Cpu, View, EditPen, Promotion } from '@element-plus/icons-vue'
import StageInterventionModal from './StageInterventionModal.vue'
import { isReportSignoffBlocked, isReportSignoffOnHold } from '../api/reportGate'

const props = defineProps<{
  runId: string
  stage: StageName
  result: StageResult
  revision: number
  selectedObjectId?: string | null
  annotations?: UserAnnotation[]
  /** 跨阶段只读补充：A2 标的池取融合阶段矩阵，A5 摘要回退 A2 文本 */
  crossStage?: {
    compsMatrix?: import('../api/types').PeerCompsMatrix | null
    executiveSummary?: string | null
  }
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

const blockingRisks = computed(() =>
  (decisionPackage.value?.risks ?? []).filter((risk) => risk.blocking === true)
)
const hasBlockingRisks = computed(() => Boolean(decisionPackage.value?.blocking_risk_codes?.length))
const ackRequiredCodes = computed<string[]>(() => {
  return decisionPackage.value?.acknowledgement_required_codes ?? []
})

type RiskSeverity = 'high' | 'medium' | 'low'

interface RiskGroup {
  title: string
  severity: RiskSeverity
  count: number
  codes: string[]
}

const SEVERITY_RANK: Record<RiskSeverity, number> = { high: 0, medium: 1, low: 2 }

function normalizeSeverity(value: unknown): RiskSeverity {
  return value === 'high' || value === 'low' ? value : 'medium'
}

/**
 * 决策包里的确认项只有哈希码，可读标题在 risks[] 内。
 * 同标题风险（如多个「离群异常: roe」）聚合为一行，避免几十条同质条目刷屏。
 */
const groupedRisks = computed<RiskGroup[]>(() => {
  const packageValue = decisionPackage.value
  const codes = packageValue?.acknowledgement_required_codes ?? []
  if (!packageValue || codes.length === 0) return []

  const byCode = new Map<string, Record<string, unknown>>()
  for (const risk of packageValue.risks ?? []) {
    if (typeof risk?.code === 'string' && risk.code) byCode.set(risk.code, risk)
  }

  const groups = new Map<string, RiskGroup>()
  for (const code of codes) {
    const risk = byCode.get(code)
    const title = String(risk?.title || risk?.description || risk?.message || code)
    const severity = normalizeSeverity(risk?.severity)
    const existing = groups.get(title)
    if (existing) {
      existing.count += 1
      existing.codes.push(code)
      if (SEVERITY_RANK[severity] < SEVERITY_RANK[existing.severity]) {
        existing.severity = severity
      }
    } else {
      groups.set(title, { title, severity, count: 1, codes: [code] })
    }
  }

  return [...groups.values()].sort(
    (a, b) =>
      SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] ||
      b.count - a.count ||
      a.title.localeCompare(b.title, 'zh-Hans-CN')
  )
})

const hasError = computed(() => Boolean(props.result.error))
const demoProbePending = computed(
  () => props.stage === 'data_fetch' && props.result.data.demo_probe_pending === true
)

// The chapter writer reports content gaps in quality.issues. Only derive
// guidance from those entries, so timeouts and unrelated errors keep their own recovery path.
const chapterGapNumbers = computed(() => {
  if (props.stage !== 'chapter_write' || !hasError.value) return []
  const quality = props.result.data.quality as { issues?: unknown } | undefined
  const issues = Array.isArray(quality?.issues) ? quality.issues : []
  const numbers = issues.flatMap((issue: unknown) => {
    if (typeof issue !== 'string' || !issue.includes('段落资料缺口')) return []
    return [...issue.matchAll(/CH-(\d{2})/g)].map((match) => Number(match[1]))
  })
  return [...new Set(numbers)].sort((a, b) => a - b)
})
const chapterGapLabel = computed(() => `第 ${chapterGapNumbers.value.join('、')} 章`)
const chapterRepairSuggestion = computed(
  () =>
    `请重点修订${chapterGapLabel.value}：核对数值的公司、年份、指标口径和证据来源，删除重复内容。无法核实的数据请明确标注资料缺口，不要推测或编造。`
)
const useChapterRepairSuggestion = ref(false)
const canContinueChapterWithGaps = computed(
  () =>
    props.stage === 'chapter_write' &&
    props.result.status === 'waiting_review' &&
    props.result.data.agent_status === 'partial' &&
    chapterGapNumbers.value.length > 0 &&
    props.result.data.hard_blocked !== true &&
    !recoveryBlocked.value &&
    !hasBlockingRisks.value &&
    ackRequiredCodes.value.length > 0
)

/** 运行时预算告警（阶段耗尽重试上限/超时时由后端写入 result.data） */
const runtimeAlert = computed<{ code?: string; recoverable?: boolean } | null>(() => {
  const raw = (props.result.data as Record<string, unknown>).runtime_alert
  return raw && typeof raw === 'object' ? (raw as { code?: string; recoverable?: boolean }) : null
})

/** 不可恢复（如重试上限耗尽）：重跑类按钮全部禁用，只留取消 */
const recoveryBlocked = computed(() => runtimeAlert.value?.recoverable === false)

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
watch([() => props.revision, () => decisionPackage.value?.decision_id], () => {
  riskDialogVisible.value = false
})

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
    const certifying = payload.edited_data?.certify_chain === true
    showPipelineOverlay(
      certifying ? 'chart_generate' : executingStageFor(payload.action),
      certifying ? '认证后重新生成' : actionLabel
    )
  }
  try {
    const state = await submitReview({
      run_id: props.runId,
      stage: props.stage,
      expected_revision: props.revision,
      ...payload,
    })
    const fusion = state.stage_results?.report_fusion?.data
    if (payload.action === 'direct_edit' && props.stage === 'report_fusion') {
      if (fusion?.exports_stale === true) {
        ElMessage.warning(
          String(fusion.export_notice || '修改已保存，需重新融合以生成当前导出文件')
        )
      } else {
        const formats = Array.isArray(fusion?.formats) ? fusion.formats : []
        const labels = formats.map((format) => String(format).toUpperCase()).join('、')
        const pdfNotice = formats.includes('pdf') ? '' : '；PDF 需重新融合后生成'
        ElMessage.success(`修改已保存${labels ? `，已更新 ${labels}` : ''}${pdfNotice}`)
      }
    } else {
      ElMessage.success(
        payload.edited_data?.certify_chain === true
          ? '认证已记录，正在重新生成图表、章节和报告'
          : '操作已提交'
      )
    }
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
  if (signoffBlocked.value || hasBlockingRisks.value || demoProbePending.value) return
  if (decisionPackage.value?.blocking_risk_codes?.length) {
    ElMessage.error('当前阶段存在硬阻塞风险，不能批准或通过接受风险绕过')
    return
  }
  if (ackRequiredCodes.value.length) {
    riskDialogVisible.value = true
    return
  }
  await run({ action: 'approve', ...buildDecisionFields() })
}

// ---- B42：产业链认证通路（后端 B36-P7：approve + edited_data.certify_chain=true） ----

const chainDelivery = computed<ChainDeliveryInfo | null>(() => {
  const raw = (props.result.data as Record<string, unknown>).chain_delivery
  return raw && typeof raw === 'object' ? (raw as ChainDeliveryInfo) : null
})

const chainRequested = computed(() => chainDelivery.value?.requested === true)
const chainCertified = computed(() => chainDelivery.value?.status === 'complete')

/** 仅 report_fusion、bundle 存在且未认证时提供认证入口 */
const canCertifyChain = computed(
  () =>
    isFusionStage.value &&
    Boolean(chainDelivery.value?.certification_available) &&
    !chainCertified.value
)

async function certifyChain(): Promise<void> {
  const fields = buildDecisionFields()
  try {
    await ElMessageBox.confirm(
      '认证表示您已人工核验产业链环节归属与代表企业。正式交付还需要有原文支持的工序关系。确认后将从图表生成阶段开始，重新生成图表、章节和报告；最终交付状态以重新核验结果为准。确认认证？',
      '认证产业链归属',
      { confirmButtonText: '确认认证', cancelButtonText: '返回', type: 'warning' }
    )
  } catch {
    return
  }
  if (fields.decision_id !== decisionPackage.value?.decision_id) return
  await run({ action: 'approve', edited_data: { certify_chain: true }, ...fields })
}

async function continueChapterWithGaps(): Promise<void> {
  const fields = buildDecisionFields()
  const codes = [...ackRequiredCodes.value]
  try {
    await ElMessageBox.confirm(
      `${chapterGapLabel.value}存在资料缺口。继续后将生成报告并进行最终质检，结果可能仍为受限草稿，不能保证正式交付。确认继续？`,
      '确认章节缺口',
      { confirmButtonText: '确认并继续质检', cancelButtonText: '返回修订', type: 'warning' }
    )
  } catch {
    return
  }
  if (fields.decision_id !== decisionPackage.value?.decision_id) return
  await run({
    action: 'accept_with_risks',
    comment: '已知晓章节内容缺口，继续生成报告并接受最终质检',
    accepted_risk_codes: codes,
    ...fields,
  })
}

/** 有风险时：打开风险提示，用户点同意后进入下一阶段 */
async function acceptWithRisks(): Promise<void> {
  const decisionFields = buildDecisionFields()
  if (!decisionFields.decision_id || !decisionFields.risk_snapshot_sha256) {
    ElMessage.error('缺少可校验的决策包，请重新执行该阶段后再审核')
    return
  }
  riskDialogVisible.value = false
  await run({
    action: 'accept_with_risks',
    accepted_risk_codes: [...ackRequiredCodes.value],
    ...decisionFields,
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
const signoffBlocked = computed(
  () => isFusionStage.value && isReportSignoffBlocked(props.result.data)
)
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

/**
 * 当前待审阶段的「下一步」说明。
 *
 * 为什么放在控制区顶部：审核人打开工作台的第一件事是判断「我现在该做什么」。
 * 只给通过按钮而不说明通过后会进入哪个阶段，会把流程语义留给用户自己猜；
 * 渠道里出现过「停在章节审核不知道下一步」的反馈（计划 T5）。
 */
const NEXT_STEP_HINTS: Record<StageName, string> = {
  data_fetch: '下一步：进入数据解读，分析指标变化与跨来源一致性',
  data_interpret: '下一步：进入图表生成，按已核验证据选择图表',
  chart_generate: '下一步：进入章节撰写，生成七章正文',
  chapter_write: '下一步：进入报告融合，生成摘要、核验与 PDF 交付',
  report_fusion: '下一步：完成交付，可在下载页获取正式或受限文件',
}
const nextStepHint = computed(() => NEXT_STEP_HINTS[props.stage] ?? '')

const stageTitle = computed(() => {
  const map: Record<StageName, string> = {
    data_fetch: '【阶段一：数据获取智能体】审核确认检索范围与关键词',
    data_interpret: '【阶段二：数据解读智能体】补充背景知识与修正判断',
    chart_generate: '【阶段三：可视化图表智能体】选择图表样式与强调重点',
    chapter_write: '【阶段四：分章节内容智能体】提出修改意见与补充要求',
    report_fusion: '【阶段五：报告融合智能体】整体审核并提出修订方向',
  }
  return map[props.stage] || '阶段人机协同控制区'
})

const stageDescription = computed(() => {
  const map: Record<StageName, string> = {
    data_fetch: '用户可审核确认检索范围与核心关键词，支持单点精准补采。',
    data_interpret: '用户可补充行业专家背景知识先验，并对AI核心研判进行逐条修正与裁决。',
    chart_generate: '用户可选择图表呈现样式（柱/折/条/堆），并指定核心标的高亮与基准线强调重点。',
    chapter_write: '用户可按章节提出修改意见与补充要求，支持单章定向重写与正文就地精修。',
    report_fusion: '用户可进行全篇整体质量审核，指定宏观修订方向，并终审定稿核心指标卡与投资评级。',
  }
  return map[props.stage] || '提供专业差异化的人机协同干预能力。'
})

// 专业协同弹窗状态
const stageInterventionVisible = ref(false)
const stageInterventionTab = ref('scope_keywords')

function openStageModal(tab: string): void {
  useChapterRepairSuggestion.value = false
  stageInterventionTab.value = tab
  stageInterventionVisible.value = true
}

function openChapterRepair(): void {
  useChapterRepairSuggestion.value = true
  stageInterventionTab.value = 'revision_requirements'
  stageInterventionVisible.value = true
}

async function onStageReviseSubmit(payload: {
  comment: string
  edited_data?: Record<string, unknown> | null
}): Promise<void> {
  await run({
    action: 'revise',
    comment: payload.comment || null,
    edited_data: payload.edited_data || null,
  })
}

async function onStageDirectEditSubmit(payload: {
  edited_data: Record<string, unknown>
  comment?: string
}): Promise<void> {
  await run({
    action: 'direct_edit',
    comment: payload.comment || '用户阶段精准微调',
    edited_data: payload.edited_data,
  })
}
</script>

<template>
  <!-- B43：语义分组 + aria-label，让读屏用户知道这是一组「审阅决策」而非普通按钮 -->
  <div
    class="review-actions"
    data-testid="review-actions"
    role="group"
    aria-label="当前阶段审阅决策"
  >
    <div v-if="hasError && !isReportSignoffOnHold(result)" class="review-error">
      <el-alert
        type="error"
        show-icon
        :closable="false"
        :title="chapterGapNumbers.length ? '部分章节需要修订' : '阶段处理需要关注'"
        :description="
          chapterGapNumbers.length
            ? `${chapterGapLabel}有内容未通过质量核验，存在资料缺口。请修订后重新检查；证据不足时需补充资料。`
            : errorGuide
        "
      />
      <el-button
        v-if="chapterGapNumbers.length && !recoveryBlocked"
        type="primary"
        plain
        :disabled="submitting"
        data-testid="repair-chapters"
        @click="openChapterRepair"
        >修订问题章节</el-button
      >
      <el-button
        v-if="canContinueChapterWithGaps"
        :disabled="submitting"
        :loading="submitting"
        data-testid="continue-with-gaps"
        @click="continueChapterWithGaps"
        >确认缺口并继续质检</el-button
      >
      <details class="stage-error-details">
        <summary>查看异常明细</summary>
        <p>{{ result.error }}</p>
      </details>
    </div>

    <section v-if="blockingRisks.length" class="stage-error-details" aria-label="待处理的阻断项">
      <h4>待处理的阻断项</h4>
      <ul>
        <li v-for="risk in blockingRisks" :key="String(risk.code)">{{ risk.title }}</li>
      </ul>
    </section>

    <!-- report_fusion：发布模式（仅正式报告） -->
    <template v-if="!hasError && isFusionStage && !signoffBlocked">
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
      <!-- 人机协同四步闭环指示栏 -->
      <div class="closed-loop-stepper">
        <div class="loop-step">
          <el-icon class="step-icon"><Cpu /></el-icon>
          <span class="step-text">AI辅助推荐</span>
        </div>
        <div class="step-arrow">→</div>
        <div class="loop-step active">
          <el-icon class="step-icon"><View /></el-icon>
          <span class="step-text">人工审核把关</span>
        </div>
        <div class="step-arrow">→</div>
        <div class="loop-step">
          <el-icon class="step-icon"><EditPen /></el-icon>
          <span class="step-text">反馈优化调整</span>
        </div>
        <div class="step-arrow">→</div>
        <div class="loop-step">
          <el-icon class="step-icon"><Promotion /></el-icon>
          <span class="step-text">AI改进生效</span>
        </div>
      </div>

      <p
        v-if="nextStepHint && !signoffBlocked && !hasError"
        class="next-step-hint"
        data-testid="next-step-hint"
      >
        {{ nextStepHint }}
      </p>

      <!-- B42：产业链认证卡（数据源 = fusion data.chain_delivery；仅链路 run 的终审阶段出现） -->
      <div
        v-if="isFusionStage && chainDelivery && chainRequested"
        class="chain-certify-card"
        data-testid="chain-certify-card"
      >
        <div class="chain-certify-head">
          <span class="chain-certify-title">产业链证据包</span>
          <el-tag
            v-if="chainCertified"
            type="success"
            size="small"
            data-testid="chain-certified-badge"
          >
            {{
              chainDelivery?.scope === 'business_position' ? '已核验业务定位' : '已认证 · 完整交付'
            }}
          </el-tag>
          <el-tag v-else type="warning" size="small" data-testid="chain-partial-badge">
            未认证 · 受限交付
          </el-tag>
        </div>
        <div class="chain-certify-meta">
          <span>参与企业 {{ chainDelivery.accepted_participations ?? 0 }}</span>
          <span>已核关系 {{ chainDelivery.verified_relations ?? 0 }}</span>
        </div>
        <p v-if="chainDelivery.reason" class="chain-certify-reason">{{ chainDelivery.reason }}</p>
        <el-button
          v-if="canCertifyChain"
          type="warning"
          :loading="submitting"
          data-testid="btn-certify-chain"
          class="btn-certify-chain"
          @click="certifyChain"
        >
          认证产业链归属并重新生成
        </el-button>
      </div>

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
        <template
          v-if="
            !signoffBlocked &&
            !hasBlockingRisks &&
            !demoProbePending &&
            (decisionPackage || !hasError)
          "
        >
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
            风险提示（{{ groupedRisks.length }} 类 / {{ ackRequiredCodes.length }} 处）
          </el-button>
        </template>

        <!-- 阶段 1：数据获取 (data_fetch) 专属介入 -->
        <template v-if="stage === 'data_fetch'">
          <el-button
            type="primary"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('scope_keywords')"
          >
            审核确认检索范围与关键词
          </el-button>
          <el-button
            type="info"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('partial_refetch')"
          >
            定向补采
          </el-button>
        </template>

        <!-- 阶段 2：数据解读 (data_interpret) 专属介入 -->
        <template v-else-if="stage === 'data_interpret'">
          <el-button
            type="primary"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('knowledge_judgment')"
          >
            补充背景知识与修正判断
          </el-button>
          <el-button
            type="info"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('comps')"
          >
            标的池与可比公司调整
          </el-button>
        </template>

        <!-- 阶段 3：图表生成 (chart_generate) 专属介入 -->
        <template v-else-if="stage === 'chart_generate'">
          <el-button
            type="primary"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('morph_emphasis')"
          >
            选择图表样式与强调重点
          </el-button>
          <el-button
            type="info"
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
            @click="openStageModal('revision_requirements')"
          >
            提出修改意见与补充要求
          </el-button>
          <el-button
            type="info"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('inline_polish')"
          >
            正文段落就地精修
          </el-button>
        </template>

        <!-- 阶段 5：报告融合 (report_fusion) 专属介入 -->
        <template v-else-if="stage === 'report_fusion'">
          <el-button
            v-if="result.data.needs_reexport"
            type="primary"
            size="large"
            :disabled="submitting || recoveryBlocked"
            data-testid="btn-reaudit-edits"
            @click="run({ action: 'regenerate' })"
          >
            重新融合并核验
          </el-button>
          <el-button
            type="primary"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('audit_steering')"
          >
            整体审核并提出修订方向
          </el-button>
          <el-button
            type="info"
            plain
            size="large"
            :disabled="submitting || recoveryBlocked"
            @click="openStageModal('metric_cards')"
          >
            8 张核心指标卡定制
          </el-button>
          <el-button
            type="info"
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
      :cross-stage="crossStage"
      :initial-tab="stageInterventionTab"
      :chapter-repair="
        useChapterRepairSuggestion
          ? { chapters: chapterGapNumbers, instruction: chapterRepairSuggestion }
          : undefined
      "
      :submitting="submitting"
      @submit-revise="onStageReviseSubmit"
      @submit-direct-edit="onStageDirectEditSubmit"
      @approve="approve"
    />

    <!-- 风险提示确认窗 -->
    <el-dialog
      v-model="riskDialogVisible"
      title="风险提示"
      width="720px"
      class="risk-notice-dialog"
      data-testid="risk-dialog"
    >
      <el-alert type="warning" show-icon :closable="false" style="margin-bottom: 12px">
        <template #title
          >本阶段检出 {{ groupedRisks.length }} 类风险（共
          {{ ackRequiredCodes.length }} 处），确认后进入下一阶段</template
        >
      </el-alert>
      <ul class="risk-list">
        <li
          v-for="group in groupedRisks"
          :key="group.title"
          :title="group.title"
          data-testid="risk-item"
        >
          <span class="risk-dot" :class="`is-${group.severity}`" aria-hidden="true" />
          <span class="risk-title">{{ group.title }}</span>
          <span v-if="group.count > 1" class="risk-count">×{{ group.count }}</span>
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
.next-step-hint {
  margin: 0 0 12px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.review-error {
  margin-bottom: 16px;
}
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
.closed-loop-stepper {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 8px;
  background: linear-gradient(135deg, rgba(64, 158, 255, 0.06) 0%, rgba(103, 194, 58, 0.06) 100%);
  border: 1px solid rgba(64, 158, 255, 0.18);
  border-radius: 6px;
  padding: 8px 14px;
  margin-bottom: 14px;
}
.loop-step {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12.5px;
  color: var(--el-text-color-secondary);
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 500;
}
.loop-step.active {
  color: var(--el-color-primary);
  background: rgba(64, 158, 255, 0.12);
  font-weight: 600;
}
.step-arrow {
  color: var(--el-text-color-placeholder);
  font-size: 13px;
  font-weight: bold;
}
.step-icon {
  font-size: 14px;
  display: inline-flex;
  align-items: center;
}
.step-text {
  letter-spacing: 0.3px;
}
.chain-certify-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
  margin: 4px 0 20px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.chain-certify-head,
.chain-certify-meta,
.chain-tier-badges {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}
.chain-certify-head {
  gap: 8px;
}
.chain-certify-title {
  color: var(--el-text-color-primary);
  font-size: 15px;
  font-weight: 700;
}
.chain-certify-meta {
  gap: 8px 16px;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.5;
}
.chain-certify-meta > span:not(.chain-tier-badges) {
  white-space: nowrap;
}
.chain-tier-badges {
  gap: 6px;
}
.chain-certify-reason {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.btn-certify-chain {
  max-width: 100%;
  min-height: 36px;
  height: auto;
  white-space: normal;
  line-height: 1.4;
}
@media (max-width: 480px) {
  .closed-loop-stepper {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 6px;
  }
  .step-arrow {
    display: none;
  }
  .loop-step {
    white-space: nowrap;
  }
  .chain-certify-card {
    align-items: stretch;
  }
  .btn-certify-chain {
    min-height: 44px;
  }
  .header-left,
  .header-right {
    flex-wrap: wrap;
  }
  .intervention-badge {
    white-space: nowrap;
  }
  .intervention-actions {
    align-items: stretch;
    flex-direction: column;
  }
  .intervention-actions :deep(.el-button) {
    width: 100%;
    min-height: 44px;
    height: auto;
    margin: 0;
    white-space: normal;
  }
}
@media (max-width: 360px) {
  .closed-loop-stepper {
    grid-template-columns: 1fr;
  }
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
/* 风险确认窗：内容区限高滚动，避免几十条把页面顶出屏幕 */
:global(.risk-notice-dialog .el-dialog__body) {
  max-height: 62vh;
  overflow: auto;
  padding-top: 4px;
}
.risk-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.risk-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  margin: 0;
  padding: 8px 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
  font-size: 12.5px;
  line-height: 1.5;
}
.risk-dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
}
.risk-dot.is-high {
  background: var(--el-color-danger);
}
.risk-dot.is-medium {
  background: var(--el-color-warning);
}
.risk-dot.is-low {
  background: var(--el-color-info);
}
.risk-title {
  flex: 1;
  min-width: 0;
  color: var(--el-text-color-regular);
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.risk-count {
  flex: none;
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
}
@media (max-width: 720px) {
  .risk-list {
    grid-template-columns: 1fr;
  }
}
</style>
