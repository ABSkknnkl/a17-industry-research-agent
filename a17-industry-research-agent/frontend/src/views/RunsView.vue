<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { listRuns, deleteRun, clearAllRuns } from '../api/client'
import { ApiError } from '../api/http'
import { STAGE_LABELS, type RunSummary } from '../api/types'
import StatusTag from '../components/StatusTag.vue'

const router = useRouter()

const items = ref<RunSummary[]>([])
const total = ref(0)
const offset = ref(0)
const limit = ref(20)
const loading = ref(false)

/** 状态分桶：后端 StageStatus → 用户能理解的四类 */
type StatusBucket = 'all' | 'running' | 'waiting_review' | 'completed' | 'failed'
const BUCKET_MATCH: Record<Exclude<StatusBucket, 'all'>, ReadonlySet<string>> = {
  running: new Set(['pending', 'running']),
  waiting_review: new Set(['waiting_review']),
  completed: new Set(['approved', 'completed']),
  failed: new Set(['failed', 'cancelled', 'rejected']),
}

const statusFilter = ref<StatusBucket>('all')
const keyword = ref('')

const filteredItems = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return items.value.filter((row) => {
    if (statusFilter.value !== 'all') {
      if (!BUCKET_MATCH[statusFilter.value].has(row.status)) return false
    }
    if (!kw) return true
    return row.title.toLowerCase().includes(kw) || row.run_id.toLowerCase().includes(kw)
  })
})

const isFiltering = computed(() => statusFilter.value !== 'all' || keyword.value.trim() !== '')

function resetFilters(): void {
  statusFilter.value = 'all'
  keyword.value = ''
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await listRuns(offset.value, limit.value)
    items.value = data.items
    total.value = data.total
  } catch (e) {
    if (e instanceof ApiError && e.status !== 401) {
      ElMessage.error(`加载任务列表失败：${e.message}`)
    }
  } finally {
    loading.value = false
  }
}

function pageChange(page: number): void {
  offset.value = (page - 1) * limit.value
  void load()
}

function openRun(row: RunSummary): void {
  void router.push({ name: 'review', params: { runId: row.run_id } })
}

/** 进入独立报告下载页（门控在下载页判定，列表只负责入口） */
function openDownload(row: RunSummary): void {
  void router.push({ name: 'report-download', params: { runId: row.run_id } })
}

async function handleDelete(row: RunSummary): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定要彻底删除任务「${row.title || row.run_id}」及其所有产物文件吗？该操作无法恢复。`,
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
    await deleteRun(row.run_id)
    ElMessage.success('任务已成功删除')
    await load()
  } catch (e) {
    if (e instanceof ApiError) {
      ElMessage.error(`删除失败：${e.message}`)
    }
  }
}

async function handleClearAll(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '确定要彻底清空所有历史研报任务及其全部后端产物数据吗？该操作将从磁盘彻底删除所有数据，无法恢复。',
      '清空所有任务确认',
      {
        confirmButtonText: '确定清空全部',
        cancelButtonText: '取消',
        type: 'error',
      }
    )
  } catch {
    return
  }

  try {
    loading.value = true
    const res = await clearAllRuns()
    ElMessage.success(res.message || '所有历史任务与后端数据已成功清空')
    offset.value = 0
    await load()
  } catch (e) {
    if (e instanceof ApiError) {
      ElMessage.error(`清空失败：${e.message}`)
    }
  } finally {
    loading.value = false
  }
}

function formatTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN')
}

onMounted(load)
</script>

<template>
  <header class="list-heading">
    <h1 class="page-title">任务列表</h1>
    <div class="list-actions">
      <el-button :icon="Refresh" :loading="loading" @click="load">刷新</el-button>
      <el-dropdown v-if="total > 0" trigger="click" @command="handleClearAll">
        <el-button>
          更多
          <el-icon class="el-icon--right"><ArrowDown /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="clear" class="clear-runs">清空所有任务</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <el-button type="primary" :icon="Plus" @click="router.push('/create')"> 新建任务 </el-button>
    </div>
  </header>

  <el-card class="page-card" shadow="never">
    <!-- 状态筛选与搜索（B43）：列表接口无查询参数，这里做当前页内筛选 -->
    <div class="list-toolbar">
      <el-radio-group
        v-model="statusFilter"
        size="small"
        class="status-chips"
        aria-label="按状态筛选任务"
      >
        <el-radio-button value="all" data-testid="filter-all">全部</el-radio-button>
        <el-radio-button value="running" data-testid="filter-running">运行中</el-radio-button>
        <el-radio-button value="waiting_review" data-testid="filter-waiting_review"
          >待审阅</el-radio-button
        >
        <el-radio-button value="completed" data-testid="filter-completed">已完成</el-radio-button>
        <el-radio-button value="failed" data-testid="filter-failed">异常</el-radio-button>
      </el-radio-group>
      <div class="toolbar-right">
        <span v-if="isFiltering" class="filter-hint muted" aria-live="polite">
          本页筛选 {{ filteredItems.length }} / {{ items.length }}
        </span>
        <el-input
          v-model="keyword"
          placeholder="搜索本页主题或任务 ID"
          aria-label="搜索本页的主题或任务 ID"
          clearable
          size="small"
          class="search-input"
          data-testid="runs-search"
        >
          <template #prefix
            ><el-icon><Search /></el-icon
          ></template>
        </el-input>
      </div>
    </div>

    <div v-loading="loading" class="list-results" :aria-busy="loading">
      <table v-if="filteredItems.length" class="runs-table" aria-label="研究任务">
        <thead>
          <tr>
            <th scope="col">研究主题</th>
            <th scope="col" class="status-col">任务进度</th>
            <th scope="col" class="time-col">更新时间</th>
            <th scope="col" class="actions-col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in filteredItems" :key="row.run_id" @click="openRun(row)">
            <td>
              <RouterLink
                :to="{ name: 'review', params: { runId: row.run_id } }"
                class="run-title"
                @click.stop
              >
                {{ row.title || row.run_id }}
              </RouterLink>
              <span class="run-detail muted" data-testid="run-row-id">{{ row.run_id }}</span>
              <time class="run-detail muted mobile-time" :datetime="row.updated_at">
                {{ formatTime(row.updated_at) }}
              </time>
            </td>
            <td>
              <StatusTag :status="row.status" />
              <span class="run-detail muted">
                {{ STAGE_LABELS[row.current_stage] ?? row.current_stage }}
              </span>
            </td>
            <td class="time-col">
              <time :datetime="row.updated_at">{{ formatTime(row.updated_at) }}</time>
              <span class="run-detail muted"
                >r{{ row.revision }} · {{ row.artifact_count }} 件产物</span
              >
            </td>
            <td>
              <div class="run-actions">
                <el-button
                  v-if="row.report_available"
                  link
                  type="primary"
                  size="small"
                  data-testid="run-report-download"
                  @click.stop="openDownload(row)"
                >
                  下载报告
                </el-button>
                <el-button
                  v-else-if="row.draft_available"
                  link
                  type="warning"
                  size="small"
                  data-testid="run-report-draft"
                  @click.stop="openDownload(row)"
                >
                  受限草稿
                </el-button>
                <el-button link type="danger" size="small" @click.stop="handleDelete(row)">
                  删除
                </el-button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <el-empty
        v-else-if="!loading"
        :description="isFiltering ? '本页没有符合条件的任务' : '暂无研究任务'"
        :image-size="72"
      >
        <el-button v-if="isFiltering" data-testid="reset-runs-filters" @click="resetFilters">
          清空筛选
        </el-button>
      </el-empty>
    </div>
    <div v-if="total > 0" class="pager">
      <el-pagination
        layout="total, prev, pager, next"
        :total="total"
        :page-size="limit"
        :pager-count="5"
        :current-page="Math.floor(offset / limit) + 1"
        @current-change="pageChange"
      />
    </div>
  </el-card>
</template>

<style scoped>
.list-heading,
.list-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.list-heading {
  justify-content: space-between;
  margin-bottom: 14px;
}
.list-heading .page-title,
.list-actions :deep(.el-button + .el-button),
.run-actions :deep(.el-button + .el-button) {
  margin: 0;
}
.clear-runs {
  color: var(--el-color-danger);
}
.list-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.filter-hint {
  font-size: 12px;
  white-space: nowrap;
}
.search-input {
  width: 220px;
}
.list-results {
  min-height: 100px;
}
.runs-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.runs-table th,
.runs-table td {
  padding: 10px 12px;
  text-align: left;
  vertical-align: middle;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.runs-table th {
  background: var(--el-fill-color-light);
  color: var(--rp-navy);
  font-weight: 600;
}
.runs-table tbody tr {
  cursor: pointer;
}
.runs-table tbody tr:hover,
.runs-table tbody tr:focus-within {
  background: var(--el-fill-color-lighter);
}
.status-col {
  width: 136px;
}
.time-col {
  width: 180px;
}
.actions-col {
  width: 134px;
}
.run-title {
  color: var(--rp-navy);
  font-weight: 600;
  text-decoration: none;
  overflow-wrap: anywhere;
}
.run-title:hover,
.run-title:focus-visible {
  text-decoration: underline;
}
.run-detail {
  display: block;
  margin-top: 4px;
  line-height: 1.4;
  overflow-wrap: anywhere;
  color: var(--el-color-info);
}
.mobile-time {
  display: none;
}
.run-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 10px;
}
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
@media (max-width: 680px) {
  .toolbar-right,
  .search-input {
    width: 100%;
  }
  .filter-hint {
    order: 1;
  }
  .runs-table th,
  .runs-table td {
    padding: 8px 6px;
  }
  .status-col {
    width: 84px;
  }
  .actions-col {
    width: 68px;
  }
  .time-col {
    display: none;
  }
  .mobile-time {
    display: block;
  }
  .pager {
    justify-content: center;
  }
  .pager :deep(.el-pagination__total) {
    display: none;
  }
}
</style>
