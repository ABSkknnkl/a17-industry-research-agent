<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listRuns, deleteRun } from '../api/client'
import { ApiError } from '../api/http'
import type { RunSummary, StageStatus } from '../api/types'

/** 左栏研究报告列表：进行中 / 已完成分组，搜索过滤，新建报告跳创建页。 */
const props = defineProps<{ activeRunId: string }>()

const emit = defineEmits<{
  (e: 'navigate'): void
}>()

const router = useRouter()

const runs = ref<RunSummary[]>([])
const loading = ref(false)
const keyword = ref('')
const expanded = ref<Record<string, boolean>>({ active: true, done: true })

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await listRuns(0, 100)
    runs.value = data.items
  } catch (e) {
    if (e instanceof ApiError && e.status !== 401) {
      ElMessage.error(`加载报告列表失败：${e.message}`)
    }
  } finally {
    loading.value = false
  }
}

function isActiveStatus(status: StageStatus | string): boolean {
  return (
    status === 'running' ||
    status === 'waiting_review' ||
    status === 'pending' ||
    status === 'rejected' ||
    status === 'failed'
  )
}

const filtered = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  if (!q) return runs.value
  return runs.value.filter(
    (r) =>
      r.title.toLowerCase().includes(q) ||
      r.run_id.toLowerCase().includes(q) ||
      r.project_id.toLowerCase().includes(q)
  )
})

const activeList = computed(() => filtered.value.filter((r) => isActiveStatus(r.status)))
/** 已完成区最多展示 10 条，避免侧栏过长 */
const doneList = computed(() =>
  filtered.value.filter((r) => !isActiveStatus(r.status)).slice(0, 10)
)

function openRun(run: RunSummary): void {
  if (run.run_id === props.activeRunId) return
  void router.push({ name: 'review', params: { runId: run.run_id } })
  emit('navigate')
}

function goCreate(): void {
  void router.push({ name: 'create' })
}

async function handleDelete(run: RunSummary): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定要彻底删除任务「${run.title || run.run_id}」及其所有产物文件吗？该操作无法恢复。`,
      '删除确认',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
  } catch {
    return
  }

  try {
    await deleteRun(run.run_id)
    ElMessage.success('任务已成功删除')
    await load()
    if (run.run_id === props.activeRunId) {
      if (runs.value.length > 0) {
        void router.push({ name: 'review', params: { runId: runs.value[0].run_id } })
      } else {
        void router.push({ name: 'create' })
      }
    }
  } catch (e) {
    if (e instanceof ApiError) {
      ElMessage.error(`删除失败：${e.message}`)
    }
  }
}

function statusDot(status: string): string {
  if (status === 'running') return 'var(--rp-navy)'
  if (status === 'waiting_review') return 'var(--rp-gold)'
  if (status === 'completed' || status === 'approved') return 'var(--el-color-success)'
  if (status === 'failed' || status === 'rejected') return 'var(--el-color-danger)'
  return 'var(--el-color-info-light-5)'
}

function statusLabel(status: string): string {
  const map: Record<string, string> = {
    pending: '待启动',
    running: '数据处理中',
    waiting_review: '等待审核',
    approved: '已通过',
    completed: '已完成',
    failed: '执行失败',
    rejected: '已驳回',
    cancelled: '已取消',
  }
  return map[status] ?? status
}

function statusType(status: string): 'warning' | 'primary' | 'success' | 'danger' | 'info' {
  if (status === 'waiting_review') return 'warning'
  if (status === 'running') return 'primary'
  if (status === 'completed' || status === 'approved') return 'success'
  if (status === 'failed' || status === 'rejected') return 'danger'
  return 'info'
}

function formatTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function toggle(key: 'active' | 'done'): void {
  expanded.value = { ...expanded.value, [key]: !expanded.value[key] }
}

const groups = computed(() => [
  {
    key: 'active' as const,
    label: '进行中',
    list: activeList.value,
    empty: '暂无进行中的报告',
  },
  {
    key: 'done' as const,
    label: '已完成',
    list: doneList.value,
    empty: '暂无已完成报告',
  },
])

defineExpose({ reload: load })

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="report-nav" data-testid="report-nav">
    <h3 class="nav-title">研究报告</h3>

    <el-button class="create-btn" type="primary" data-testid="btn-new-report" @click="goCreate">
      <el-icon style="margin-right: 4px"><Plus /></el-icon>
      新建报告
    </el-button>

    <div class="nav-lists">
      <!-- 进行中 / 已完成：同一套 run-card 结构 -->
      <div v-for="group in groups" :key="group.key" class="group">
        <button
          class="group-head"
          type="button"
          :data-testid="`group-${group.key}`"
          @click="toggle(group.key)"
        >
          <el-icon class="caret" :class="{ collapsed: !expanded[group.key] }"><ArrowDown /></el-icon>
          <span>{{ group.label }}</span>
          <span class="count">{{ group.list.length }}</span>
        </button>
        <div v-if="expanded[group.key]" class="group-body">
          <div
            v-for="run in group.list"
            :key="run.run_id"
            class="run-card"
            :class="{ active: run.run_id === activeRunId }"
            :data-testid="`run-item-${run.run_id}`"
            @click="openRun(run)"
          >
            <div class="run-title-row">
              <span class="status-dot" :style="{ background: statusDot(run.status) }" />
              <span class="run-title" :title="run.title || run.run_id">
                {{ run.title || run.run_id }}
              </span>
              <el-button
                class="delete-btn"
                link
                type="danger"
                size="small"
                title="删除任务"
                @click.stop="handleDelete(run)"
              >
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <div class="run-meta-row">
              <el-tag size="small" effect="plain" :type="statusType(run.status)">
                {{ statusLabel(run.status) }}
              </el-tag>
              <span class="run-meta">更新时间：{{ formatTime(run.updated_at) }}</span>
            </div>
          </div>
          <div v-if="group.list.length === 0" class="empty-line muted">{{ group.empty }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.report-nav {
  min-height: calc(100vh - 96px);
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  gap: 4px;
}
.nav-title {
  margin: 0 0 12px;
  font-family: var(--rp-serif);
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 1px;
  color: var(--rp-navy);
  padding-bottom: 8px;
  border-bottom: 2px solid var(--rp-navy);
}
.create-btn {
  width: 100%;
  margin-bottom: 10px;
  letter-spacing: 1px;
}
.group-head {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  border: none;
  background: transparent;
  padding: 6px 2px;
  cursor: pointer;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--el-text-color-regular);
  letter-spacing: 0.5px;
}
.group-head:hover {
  color: var(--rp-navy);
}
.caret {
  font-size: 12px;
  transition: transform 0.15s;
}
.caret.collapsed {
  transform: rotate(-90deg);
}
.count {
  margin-left: auto;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  font-weight: 400;
}
.nav-lists {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  gap: 2px;
  min-height: 0;
}
.group {
  margin-bottom: 8px;
}
.group-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
/* 进行中 / 已完成共用同一套卡片规格（与同花顺 ProjectTree 一致） */
.run-card {
  border: 1px solid transparent;
  border-radius: 3px;
  min-height: 64px;
  padding: 12px 12px 10px;
  cursor: pointer;
  background: var(--el-fill-color-lighter);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 8px;
  transition:
    border-color 0.15s,
    background 0.15s;
}
.run-card:hover {
  border-color: var(--el-border-color-light);
  background: var(--el-bg-color);
}
.run-card.active {
  border-color: var(--rp-gold);
  background: var(--el-bg-color);
  box-shadow: inset 3px 0 0 var(--rp-gold);
}
.run-title-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  min-width: 0;
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-top: 5px;
}
.run-title {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  font-weight: 600;
  line-height: 1.45;
  color: var(--el-text-color-primary);
  white-space: normal;
  word-break: break-word;
  overflow-wrap: anywhere;
  text-overflow: clip;
  overflow: visible;
}
.run-card.active .run-title {
  color: var(--rp-navy);
}
.run-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-left: 13px;
  min-width: 0;
}
.run-meta {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.empty-line {
  padding: 10px 4px;
  font-size: 12px;
}
.delete-btn {
  display: none;
  padding: 0 2px;
  margin-left: 2px;
  font-size: 13px;
  flex-shrink: 0;
}
.run-card:hover .delete-btn {
  display: inline-flex;
}
</style>
