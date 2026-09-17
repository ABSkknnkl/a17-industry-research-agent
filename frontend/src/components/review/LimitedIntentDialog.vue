<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

/**
 * 共享受限修改对话框：拒绝按钮型指令，合法意图先预览再确认。
 */
const props = withDefaults(
  defineProps<{
    modelValue: boolean
    mode: 'revise' | 'instruct'
    stageLabel: string
    objectLabel: string
    objectVersion: string
    allowQuestions?: boolean
  }>(),
  { allowQuestions: false }
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'confirm', payload: { comment: string; questions: string[] }): void
}>()

const BANNED = [
  '删除',
  '排除',
  '恢复',
  '通过',
  '驳回',
  '重新生成',
  '换模板',
  '换颜色',
  '下载',
  '换配色',
]
const BANNED_BUTTON_HINT: Record<string, string> = {
  删除: '删除',
  排除: '排除',
  恢复: '恢复',
  通过: '通过并继续',
  驳回: '驳回',
  重新生成: '原条件重新生成',
  换模板: '换模板',
  换颜色: '换配色',
  换配色: '换配色',
  下载: '下载',
}

const comment = ref('')
const questions = ref('')
const previewed = ref(false)
const highlighted = ref('')

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const bannedHit = computed(() => {
  const text = comment.value + questions.value
  return BANNED.find((w) => text.includes(w)) ?? null
})

const canPreview = computed(() => {
  if (bannedHit.value) return false
  const q = questions.value
    .split('\n')
    .map((x) => x.trim())
    .filter(Boolean)
  return comment.value.trim().length > 0 || q.length > 0
})

watch(visible, (v) => {
  if (v) {
    comment.value = ''
    questions.value = ''
    previewed.value = false
    highlighted.value = ''
  }
})

function onPreview(): void {
  if (!canPreview.value) {
    if (bannedHit.value) highlighted.value = 'object-actions'
    return
  }
  highlighted.value = ''
  previewed.value = true
}

function onConfirm(): void {
  if (!previewed.value) {
    ElMessage.warning('请先预览修改')
    return
  }
  emit('confirm', {
    comment: comment.value.trim(),
    questions: questions.value
      .split('\n')
      .map((x) => x.trim())
      .filter(Boolean),
  })
  visible.value = false
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="mode === 'revise' ? '修改条件后重跑' : '修改指令提交'"
    width="560px"
    data-testid="limited-intent-dialog"
  >
    <el-alert type="info" show-icon :closable="false" style="margin-bottom: 12px">
      <template #title>
        当前对象：{{ objectLabel }} · 版本 {{ objectVersion }} · 阶段 {{ stageLabel }}
      </template>
      <div class="muted">
        允许：描述需保留内容、应避免表达、口径与范围调整。<br />
        禁止：删除 / 排除 / 恢复 / 通过 / 驳回 / 重新生成 / 换模板 / 换颜色 / 下载 ——
        这些操作已有明确按钮。
      </div>
    </el-alert>

    <el-form label-position="top">
      <el-form-item label="修改说明">
        <el-input
          v-model="comment"
          type="textarea"
          :rows="3"
          maxlength="2000"
          show-word-limit
          data-testid="intent-comment"
          placeholder="如：保留封装约束段落，避免绝对化表述"
        />
      </el-form-item>
      <el-form-item v-if="allowQuestions" label="修订后的研究问题（每行一个）">
        <el-input
          v-model="questions"
          type="textarea"
          :rows="3"
          maxlength="2000"
          show-word-limit
          data-testid="intent-questions"
        />
      </el-form-item>
    </el-form>

    <el-alert
      v-if="bannedHit"
      type="warning"
      show-icon
      :closable="false"
      data-testid="intent-reject"
      class="mb12"
    >
      <template #title>
        该操作已有明确按钮，请关闭窗口并使用「{{ BANNED_BUTTON_HINT[bannedHit] }}」按钮
      </template>
    </el-alert>

    <div
      v-if="highlighted === 'object-actions'"
      class="highlight-box"
      data-testid="intent-highlight"
    >
      请在对象卡或阶段操作区使用对应按钮完成该操作。
    </div>

    <el-alert
      v-if="previewed"
      type="success"
      show-icon
      :closable="false"
      class="mb12"
      data-testid="intent-preview"
    >
      <template #title>修改预览（确认后才会写入）</template>
      <ul class="preview-list">
        <li>修改对象：{{ objectLabel }}</li>
        <li>准备调整：{{ comment || '（研究问题）' }}</li>
        <li>不受影响：证据物理内容、已排除状态、其他未选中对象</li>
        <li>将增加版本：是</li>
      </ul>
    </el-alert>

    <template #footer>
      <el-button data-testid="intent-close" @click="visible = false">关闭</el-button>
      <el-button :disabled="!canPreview" data-testid="intent-preview-btn" @click="onPreview">
        预览修改
      </el-button>
      <el-button
        type="primary"
        :disabled="!previewed"
        data-testid="intent-confirm"
        @click="onConfirm"
      >
        确认执行
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.mb12 {
  margin-bottom: 12px;
}
.preview-list {
  margin: 4px 0 0;
  padding-left: 18px;
}
.highlight-box {
  border: 1px dashed var(--rp-gold);
  background: var(--rp-paper);
  padding: 8px 10px;
  margin-bottom: 12px;
  font-size: 12px;
}
</style>
