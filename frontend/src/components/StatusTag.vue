<script setup lang="ts">
import { computed } from 'vue'
import type { StageStatus } from '../api/types'

const props = defineProps<{ status: StageStatus }>()

const meta = computed(() => {
  switch (props.status) {
    case 'pending':
      return { label: '待执行', type: 'info' as const }
    case 'running':
      return { label: '执行中', type: 'primary' as const }
    case 'waiting_review':
      return { label: '待审核', type: 'warning' as const }
    case 'approved':
      return { label: '已审核通过', type: 'success' as const }
    case 'rejected':
      return { label: '已驳回', type: 'danger' as const }
    case 'completed':
      return { label: '已完成', type: 'success' as const }
    case 'failed':
      return { label: '失败', type: 'danger' as const }
    case 'cancelled':
      return { label: '已取消', type: 'info' as const }
    default:
      return { label: props.status, type: 'info' as const }
  }
})
</script>

<template>
  <el-tag :type="meta.type" effect="light">{{ meta.label }}</el-tag>
</template>
