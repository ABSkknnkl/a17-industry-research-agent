<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { downloadEvidenceIndex, triggerBlobDownload } from '../api/client'
import { ApiError } from '../api/http'
import type { WorkflowState } from '../api/types'

const props = defineProps<{ workflow: WorkflowState | null }>()
const mode = computed(() => props.workflow?.report_download?.compact_mode)
const downloading = ref(false)
let controller: AbortController | null = null

async function download(): Promise<void> {
  const state = props.workflow
  if (!state || !mode.value || downloading.value) return
  const request = new AbortController()
  controller = request
  downloading.value = true
  try {
    const { blob, filename } = await downloadEvidenceIndex(
      state.run_id,
      state.revision,
      mode.value,
      request.signal
    )
    if (
      !request.signal.aborted &&
      state.run_id === props.workflow?.run_id &&
      state.revision === props.workflow.revision
    ) {
      triggerBlobDownload(blob, filename)
    }
  } catch (error) {
    if (request.signal.aborted) return
    ElMessage.error(
      error instanceof ApiError && error.status === 409
        ? '报告版本或下载资格已变化，请刷新后重试。'
        : '证据索引下载失败，请稍后重试。'
    )
  } finally {
    controller = null
    downloading.value = false
  }
}

onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <el-button
    v-if="mode"
    plain
    :loading="downloading"
    data-testid="download-evidence-index"
    @click="download"
  >
    {{ mode === 'draft' ? '草稿证据索引 CSV' : '证据索引 CSV' }}
  </el-button>
</template>
