<!--
  Runs.vue - 运行历史列表（只读恢复入口）
  负责人：前端A（UI工程师）

  功能：
  - 分页展示当前用户历史运行的摘要（标题/状态/阶段/修订/产物）
  - 点击"继续审核"跳转 Review 页恢复轮询
  - 点击"版本历史"查看该 run 的全部 revision，并可查看任一版本的只读快照
-->

<template>
  <div class="runs">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span>📚 运行历史</span>
          <div class="header-actions">
            <el-button :loading="loading" size="small" @click="loadRuns">刷新</el-button>
            <el-button size="small" @click="goHome">新建报告</el-button>
          </div>
        </div>
      </template>

      <el-table
        v-loading="loading"
        :data="items"
        empty-text="暂无历史运行"
        class="runs-table"
      >
        <el-table-column prop="title" label="研究主题" min-width="180" show-overflow-tooltip />
        <el-table-column prop="project_id" label="项目" min-width="120" show-overflow-tooltip />
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="当前阶段" width="110">
          <template #default="{ row }">
            {{ stageLabel(row.current_stage) }}
          </template>
        </el-table-column>
        <el-table-column label="修订" prop="revision" width="70" align="center" />
        <el-table-column label="产物" width="70" align="center">
          <template #default="{ row }">
            <span>{{ row.artifact_count }}</span>
            <el-tag v-if="row.report_available" type="success" size="small" class="report-tag">
              报告
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" min-width="160">
          <template #default="{ row }">
            {{ formatTime(row.updated_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button
              size="small"
              type="primary"
              :disabled="!canResume(row.status)"
              @click="resumeRun(row.run_id)"
            >
              继续审核
            </el-button>
            <el-button size="small" @click="openRevisions(row.run_id)">版本历史</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-row">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="loadRuns"
        />
      </div>
    </el-card>

    <!-- 版本历史 + 只读快照 -->
    <el-dialog v-model="revisionDialogVisible" title="版本历史" width="720px">
      <div v-if="revisionLoading" v-loading="true" class="revision-loading" />
      <template v-else>
        <el-timeline v-if="revisions.length">
          <el-timeline-item
            v-for="rev in revisions"
            :key="rev.revision"
            :timestamp="formatTime(rev.updated_at)"
            :type="rev.revision === currentRevision ? 'primary' : undefined"
          >
            <div class="revision-item">
              <span class="revision-label">
                版本 R{{ rev.revision }}
                <el-tag v-if="rev.revision === currentRevision" size="small">当前</el-tag>
              </span>
              <el-tag :type="statusTagType(rev.status)" size="small">
                {{ statusLabel(rev.status) }}
              </el-tag>
              <span class="revision-stage">{{ stageLabel(rev.current_stage) }}</span>
              <el-button
                size="small"
                text
                type="primary"
                :loading="snapshotLoading"
                @click="loadSnapshot(revisionRunId, rev.revision)"
              >
                查看快照
              </el-button>
            </div>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="该运行尚未产生修订历史" :image-size="80" />
      </template>

      <el-divider v-if="snapshot" />

      <div v-if="snapshot" class="snapshot">
        <el-descriptions :column="2" border size="small" title="只读快照">
          <el-descriptions-item label="版本">R{{ snapshot.revision }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="statusTagType(snapshot.status)" size="small">
              {{ statusLabel(snapshot.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="当前阶段">
            {{ stageLabel(snapshot.current_stage) }}
          </el-descriptions-item>
          <el-descriptions-item label="更新时间">
            {{ formatTime(snapshot.updated_at) }}
          </el-descriptions-item>
        </el-descriptions>

        <el-table :data="snapshotRows" size="small" class="snapshot-table">
          <el-table-column label="阶段" width="120">
            <template #default="{ row }">{{ stageLabel(row.stage) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="130">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small">
                {{ statusLabel(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="revision" label="修订" width="70" align="center" />
          <el-table-column prop="artifactCount" label="产物" width="70" align="center" />
          <el-table-column label="错误" min-width="160">
            <template #default="{ row }">
              <span v-if="row.error" class="snapshot-error">{{ row.error }}</span>
              <span v-else class="snapshot-ok">无</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  getRunRevision,
  listRunRevisions,
  listRuns,
} from '@/api/workflow'
import type {
  RevisionListResponse,
  RevisionSummary,
  RunSummary,
  StageName,
  StageStatus,
  WorkflowState,
} from '@/types/workflow'

const router = useRouter()

const loading = ref(false)
const items = ref<RunSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20

const revisionDialogVisible = ref(false)
const revisionLoading = ref(false)
const revisions = ref<RevisionSummary[]>([])
const currentRevision = ref(1)
const revisionRunId = ref('')

const snapshot = ref<WorkflowState | null>(null)
const snapshotLoading = ref(false)

const stageLabels: Record<StageName, string> = {
  data_fetch: '数据采集',
  data_interpret: '数据解读',
  chart_generate: '图表生成',
  chapter_write: '章节撰写',
  report_fusion: '报告融合',
}

const statusLabels: Record<StageStatus, string> = {
  pending: '等待中',
  running: '运行中',
  waiting_review: '待审核',
  approved: '已通过',
  rejected: '已驳回',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

const statusTagTypes: Record<StageStatus, 'primary' | 'success' | 'warning' | 'danger' | 'info'> = {
  pending: 'info',
  running: 'primary',
  waiting_review: 'warning',
  approved: 'success',
  rejected: 'danger',
  completed: 'success',
  failed: 'danger',
  cancelled: 'info',
}

function stageLabel(stage: StageName): string {
  return stageLabels[stage] ?? stage
}

function statusLabel(status: StageStatus): string {
  return statusLabels[status] ?? status
}

function statusTagType(status: StageStatus): 'primary' | 'success' | 'warning' | 'danger' | 'info' {
  return statusTagTypes[status] ?? 'info'
}

function canResume(status: StageStatus): boolean {
  return ['waiting_review', 'running', 'pending'].includes(status)
}

function formatTime(value: string): string {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

async function loadRuns(): Promise<void> {
  loading.value = true
  try {
    const response = await listRuns({
      offset: (page.value - 1) * pageSize,
      limit: pageSize,
    })
    items.value = response.items
    total.value = response.total
  } catch (error) {
    ElMessage.error('加载运行历史失败')
    console.error(error)
  } finally {
    loading.value = false
  }
}

function resumeRun(runId: string): void {
  void router.push(`/review/${runId}`)
}

function goHome(): void {
  void router.push('/')
}

async function openRevisions(runId: string): Promise<void> {
  revisionRunId.value = runId
  revisionDialogVisible.value = true
  snapshot.value = null
  revisionLoading.value = true
  try {
    const response: RevisionListResponse = await listRunRevisions(runId)
    revisions.value = response.revisions
    currentRevision.value = response.current_revision
  } catch (error) {
    ElMessage.error('加载版本历史失败')
    console.error(error)
  } finally {
    revisionLoading.value = false
  }
}

async function loadSnapshot(runId: string, revision: number): Promise<void> {
  snapshotLoading.value = true
  try {
    snapshot.value = await getRunRevision(runId, revision)
  } catch (error) {
    ElMessage.error(`加载版本 R${revision} 快照失败`)
    console.error(error)
  } finally {
    snapshotLoading.value = false
  }
}

const snapshotRows = computed(() => {
  if (!snapshot.value) return []
  return Object.entries(snapshot.value.stage_results).map(([stage, result]) => ({
    stage: stage as StageName,
    status: result.status,
    revision: result.revision,
    artifactCount: result.artifacts.length,
    error: result.error,
  }))
})

onMounted(() => {
  void loadRuns()
})
</script>

<style scoped>
.runs {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.runs-table {
  width: 100%;
}

.report-tag {
  margin-left: 6px;
}

.pagination-row {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.revision-loading {
  min-height: 120px;
}

.revision-item {
  display: flex;
  align-items: center;
  gap: 10px;
}

.revision-label {
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.revision-stage {
  color: #909399;
  font-size: 13px;
}

.snapshot {
  margin-top: 8px;
}

.snapshot-table {
  margin-top: 12px;
}

.snapshot-error {
  color: #f56c6c;
}

.snapshot-ok {
  color: #909399;
}
</style>
