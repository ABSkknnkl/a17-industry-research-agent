<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { listRuns } from '../api/client'
import { ApiError } from '../api/http'
import { STAGE_LABELS, type RunSummary } from '../api/types'
import StatusTag from '../components/StatusTag.vue'

const router = useRouter()

const items = ref<RunSummary[]>([])
const total = ref(0)
const offset = ref(0)
const limit = ref(20)
const loading = ref(false)

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

function formatTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN')
}

onMounted(load)
</script>

<template>
  <div class="card-header" style="margin-bottom: 16px">
    <h2 class="page-title" style="margin: 0">任务列表</h2>
    <el-button :loading="loading" @click="load">
      <el-icon style="margin-right: 4px"><Refresh /></el-icon>
      刷新
    </el-button>
  </div>

  <el-card class="page-card" shadow="never">
    <el-table v-loading="loading" :data="items" style="width: 100%" @row-click="openRun">
      <el-table-column prop="run_id" label="任务 ID" width="280" show-overflow-tooltip />
      <el-table-column prop="title" label="主题" min-width="180" show-overflow-tooltip />
      <el-table-column label="当前阶段" width="120">
        <template #default="{ row }">{{
          STAGE_LABELS[row.current_stage as keyof typeof STAGE_LABELS] ?? row.current_stage
        }}</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <StatusTag :status="row.status" />
        </template>
      </el-table-column>
      <el-table-column prop="revision" label="版本" width="70" />
      <el-table-column prop="artifact_count" label="产物数" width="80" />
      <el-table-column label="报告" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.report_available" type="success" size="small">可下载</el-tag>
          <span v-else class="muted">—</span>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="170">
        <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
      </el-table-column>
    </el-table>
    <div class="pager">
      <el-pagination
        layout="total, prev, pager, next"
        :total="total"
        :page-size="limit"
        :current-page="Math.floor(offset / limit) + 1"
        @current-change="pageChange"
      />
    </div>
  </el-card>
</template>

<style scoped>
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
:deep(.el-table__row) {
  cursor: pointer;
}
</style>
