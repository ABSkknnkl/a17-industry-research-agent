<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { isMockDataMode } from '../../api/client'
import { usePrototypeStore } from '../../mock/prototypeRun'
import type { ChartItem } from '../../api/types'

const props = defineProps<{ chart: ChartItem }>()
const emit = defineEmits<{
  (e: 'receipt', action: string, objectIds: string[]): void
}>()

const mockMode = isMockDataMode()
const store = mockMode ? usePrototypeStore() : null

function ack(action: string, objectIds: string[], message: string): void {
  ElMessage.success(message)
  emit('receipt', action, objectIds)
}

async function onRegenerate(): Promise<void> {
  if (!store) {
    ElMessage.info('演示环境可用单图重生成；真实 API 将在 Phase 2 接入')
    return
  }
  const rec = await store.regenerateChart(props.chart.chart_id)
  if (!rec.ok) {
    ElMessage.error(rec.message)
    return
  }
  ack(rec.action, [props.chart.chart_id], rec.message)
}

function onDelete(): void {
  if (!store) return
  const rec = store.deleteChart(props.chart.chart_id)
  if (rec.ok) ack(rec.action, [props.chart.chart_id], rec.message)
}

async function confirmDelete(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确认删除「${props.chart.title || props.chart.chart_id}」？删除后将从报告中移除。`,
      '删除图表',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
  } catch {
    return
  }
  onDelete()
}
</script>

<template>
  <div class="chart-control-menu" data-testid="chart-control-menu">
    <el-tooltip
      :disabled="mockMode"
      content="演示环境可用；真实单图重生成 API 将在后续版本接入"
      placement="top"
    >
      <span class="regen-wrap">
        <el-button
          type="primary"
          plain
          data-testid="chart-regen"
          :loading="chart.status === 'running'"
          :disabled="!mockMode || chart.status === 'running' || chart.status === 'deleted'"
          @click="onRegenerate"
        >
          {{ chart.status === 'running' ? '生成中…' : '重新生成' }}
        </el-button>
      </span>
    </el-tooltip>
    <el-button
      v-if="chart.status !== 'deleted'"
      type="danger"
      plain
      data-testid="chart-delete"
      :disabled="!mockMode"
      @click="confirmDelete"
    >
      删除
    </el-button>
  </div>
</template>

<style scoped>
/**
 * 卡片底部操作行。
 * 左右内边距与卡片头（.chart-head 的 10px 12px 6px）对齐，避免按钮比标题更靠左。
 * 间距统一交给 flex gap，因此必须清掉 Element Plus 给相邻按钮加的 margin-left，
 * 否则 gap + margin 会叠成双倍间距。
 */
.chart-control-menu {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 10px 12px 12px;
  margin-top: auto; /* 卡片为 flex 列时，把操作行压到卡片底部，同排对齐 */
  border-top: 1px solid var(--rp-line);
  background: var(--rp-card);
}
.regen-wrap {
  display: inline-flex;
}
.chart-control-menu :deep(.el-button) {
  height: 32px;
  padding: 0 14px;
  font-size: 13px;
  border-radius: 6px;
  margin-left: 0;
}
/* 相邻按钮的 margin 已在上面清零，这里显式兜底，防止 Element Plus 版本差异 */
.chart-control-menu :deep(.el-button + .el-button) {
  margin-left: 0;
}
/* 窄屏放大触摸目标，接近 44px 可达性基线 */
@media (max-width: 900px) {
  .chart-control-menu {
    gap: 10px;
  }
  .chart-control-menu :deep(.el-button) {
    height: 40px;
    padding: 0 16px;
    font-size: 13.5px;
  }
}
</style>
