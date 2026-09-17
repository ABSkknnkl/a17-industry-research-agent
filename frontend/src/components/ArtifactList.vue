<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { downloadArtifact, triggerBlobDownload } from '../api/client'
import { artifactKindLabel } from '../api/labels'
import type { ArtifactRef } from '../api/types'

/**
 * 产物列表：版本、时间、文件大小信息。
 * - 版本：ArtifactRef.revision（后端原始字段）
 * - 时间：由父组件传入 revision → 更新时间 映射（GET /revisions 已有输出，前端聚合）
 * - 大小：由父组件传入 artifact_id → size_bytes 映射（report_fusion manifest 已有输出，前端聚合）
 */
const props = withDefaults(
  defineProps<{
    runId: string
    artifacts: ArtifactRef[]
    sizeById?: Record<string, number>
    timeByRevision?: Record<number, string>
    /** 门控未放行时禁止单项下载（下载页 waiting_review 未批准场景） */
    disabled?: boolean
  }>(),
  { disabled: false }
)

const downloadingId = ref('')

async function download(artifact: ArtifactRef): Promise<void> {
  downloadingId.value = artifact.artifact_id
  try {
    const { blob, filename } = await downloadArtifact(props.runId, artifact)
    triggerBlobDownload(blob, filename)
  } catch {
    ElMessage.error('下载失败，请稍后重试')
  } finally {
    downloadingId.value = ''
  }
}

function basename(uri: string): string {
  return uri.split(/[\\/]/).pop() || uri
}

// 产物类型中文映射已统一到 src/api/labels.ts（artifactKindLabel），
// 下载页与本组件共用同一套文案，避免两处漂移。

function formatSize(bytes: number | undefined): string {
  if (typeof bytes !== 'number' || bytes <= 0) return '—'
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

function formatTime(value: string | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN')
}

function sizeOf(artifact: ArtifactRef): number | undefined {
  return props.sizeById?.[artifact.artifact_id]
}

function timeOf(artifact: ArtifactRef): string | undefined {
  return props.timeByRevision?.[artifact.revision]
}

const sorted = computed(() => [...props.artifacts].sort((a, b) => b.revision - a.revision))
</script>

<template>
  <el-table :data="sorted" size="small" border>
    <el-table-column label="文件名" min-width="200" show-overflow-tooltip>
      <template #default="{ row }">{{ basename(row.uri) }}</template>
    </el-table-column>
    <el-table-column label="类型" width="140">
      <template #default="{ row }">
        <el-tag size="small" effect="plain" type="info">{{ artifactKindLabel(row.kind) }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column label="版本" width="70" align="center">
      <template #default="{ row }">r{{ row.revision }}</template>
    </el-table-column>
    <el-table-column label="大小" width="90" align="right">
      <template #default="{ row }">{{ formatSize(sizeOf(row)) }}</template>
    </el-table-column>
    <el-table-column label="时间" width="160">
      <template #default="{ row }">{{ formatTime(timeOf(row)) }}</template>
    </el-table-column>
    <el-table-column label="操作" width="90" fixed="right">
      <template #default="{ row }">
        <el-button
          size="small"
          type="primary"
          link
          :disabled="disabled"
          :loading="downloadingId === row.artifact_id"
          @click="download(row)"
        >
          下载
        </el-button>
      </template>
    </el-table-column>
  </el-table>
</template>
