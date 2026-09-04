<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { submitReview } from '../api/client'
import { ApiError } from '../api/http'
import type { ReviewAction, StageName, StageStatus, WorkflowState } from '../api/types'
import { showPipelineOverlay, hidePipelineOverlay } from '../composables/usePipelineOverlay'

/**
 * 业务动作按钮区（复用已有 POST /reviews 接口，不新增参数）：
 * - 重新融合：report_fusion 阶段 regenerate
 * - 修改指令提交：当前阶段 revise（fetch/interpret 允许替换研究问题）
 * - 版本历史：交由父组件打开既有对话框
 * waiting_review 时由 ReviewActions 承担决策流，避免重复入口。
 */
const props = defineProps<{
  runId: string
  stage: StageName
  revision: number
  status: StageStatus
}>()

const emit = defineEmits<{
  (e: 'submitted', state: WorkflowState): void
  (e: 'conflict'): void
  (e: 'history'): void
}>()

const submitting = ref(false)
const reviseDialogVisible = ref(false)
const reviseComment = ref('')
const reviseQuestions = ref('')

const busy = computed(() => submitting.value || props.status === 'running')

/** 重新融合仅在融合阶段且非等待审核时显示（等待审核时 ReviewActions 已提供同能力） */
const showRefusion = computed(
  () =>
    props.stage === 'report_fusion' &&
    props.status !== 'running' &&
    props.status !== 'waiting_review'
)

/** 修改指令提交：非执行中且非等待审核时显示（等待审核时走 ReviewActions 的修订入口） */
const showRevise = computed(
  () =>
    props.status !== 'running' && props.status !== 'waiting_review' && props.status !== 'cancelled'
)

async function run(payload: {
  action: ReviewAction
  comment?: string | null
  edited_data?: Record<string, unknown> | null
}): Promise<void> {
  submitting.value = true
  showPipelineOverlay(props.stage, payload.action === 'regenerate' ? '重新生成' : '修改指令重跑')
  try {
    const state = await submitReview({
      run_id: props.runId,
      stage: props.stage,
      expected_revision: props.revision,
      ...payload,
    })
    ElMessage.success('操作已提交，流水线开始执行')
    emit('submitted', state)
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      // 透出后端冲突详情（Revision conflict / Stage conflict）。
      ElMessage.warning(
        e.message
          ? `${e.message}，已刷新最新状态，请重新操作`
          : '任务已被其他操作更新（版本冲突），已刷新最新状态，请重新操作'
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

async function refusion(): Promise<void> {
  await ElMessageBox.confirm(
    '将基于当前章节与图表重新执行报告融合（重新生成产物并更新版本），确认继续？',
    '重新融合',
    { confirmButtonText: '重新融合', cancelButtonText: '取消', type: 'warning' }
  )
  await run({ action: 'regenerate' })
}

function openReviseDialog(): void {
  reviseComment.value = ''
  reviseQuestions.value = ''
  reviseDialogVisible.value = true
}

async function submitRevise(): Promise<void> {
  const questions = reviseQuestions.value
    .split('\n')
    .map((q) => q.trim())
    .filter(Boolean)
  const comment = reviseComment.value.trim()
  if (!comment && questions.length === 0) {
    ElMessage.warning('请填写修改指令或修订后的研究问题')
    return
  }
  const edited: Record<string, unknown> = {}
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
</script>

<template>
  <div class="workbench-actions">
    <el-button v-if="showRefusion" type="primary" plain :disabled="busy" @click="refusion">
      <el-icon style="margin-right: 4px"><RefreshRight /></el-icon>
      重新融合
    </el-button>
    <el-button v-if="showRevise" :disabled="busy" @click="openReviseDialog">
      <el-icon style="margin-right: 4px"><EditPen /></el-icon>
      修改指令提交
    </el-button>
    <el-button :disabled="status === 'running'" @click="emit('history')">
      <el-icon style="margin-right: 4px"><Clock /></el-icon>
      版本历史
    </el-button>

    <el-dialog v-model="reviseDialogVisible" title="修改指令提交" width="560px">
      <el-alert
        type="info"
        show-icon
        :closable="false"
        title="指令将提交给当前阶段重新执行（修订当前版本）"
        style="margin-bottom: 12px"
      />
      <el-form label-position="top">
        <el-form-item label="修改指令（反馈给智能体）">
          <el-input
            v-model="reviseComment"
            type="textarea"
            :rows="3"
            maxlength="2000"
            show-word-limit
            placeholder="如：请额外关注毛利率变化；时间范围扩大到近 5 年"
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
            placeholder="请写明具体行业/公司、指标与时间范围，例如：&#10;锂电池行业2024-2025年营业收入与净利润增速如何？"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reviseDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitRevise"
          >提交并重新执行</el-button
        >
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.workbench-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
