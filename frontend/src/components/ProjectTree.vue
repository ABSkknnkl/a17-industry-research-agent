<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { listRuns } from '../api/client'
import { ApiError } from '../api/http'
import { STAGE_LABELS, type RunSummary } from '../api/types'

/** 左侧项目导航树：GET /runs 聚合为 项目 → 任务 两级结构，点击任务切换工作台。 */
const props = defineProps<{ activeRunId: string }>()

const emit = defineEmits<{
  (e: 'navigate'): void
}>()

const route = useRoute()
const router = useRouter()

const runs = ref<RunSummary[]>([])
const loading = ref(false)

interface TreeNode {
  key: string
  label: string
  isProject: boolean
  run?: RunSummary
  children?: TreeNode[]
}

const treeData = computed<TreeNode[]>(() => {
  const groups = new Map<string, RunSummary[]>()
  for (const run of runs.value) {
    const list = groups.get(run.project_id) ?? []
    list.push(run)
    groups.set(run.project_id, list)
  }
  return Array.from(groups.entries()).map(([projectId, projectRuns]) => ({
    key: `project:${projectId}`,
    label: projectId,
    isProject: true,
    children: projectRuns.map((run) => ({
      key: `run:${run.run_id}`,
      label: run.title || run.run_id,
      isProject: false,
      run,
    })),
  }))
})

async function load(): Promise<void> {
  loading.value = true
  try {
    const data = await listRuns(0, 100)
    runs.value = data.items
  } catch (e) {
    if (e instanceof ApiError && e.status !== 401) {
      ElMessage.error(`加载项目导航失败：${e.message}`)
    }
  } finally {
    loading.value = false
  }
}

/** 当前激活任务 key，用于高亮 */
const activeKey = computed(() => `run:${props.activeRunId}`)

const currentNodeKey = computed(() => {
  const keys: string[] = []
  for (const project of treeData.value) {
    if (project.children?.some((child) => child.key === activeKey.value)) {
      keys.push(project.key)
    }
  }
  return keys
})

function handleClick(node: TreeNode): void {
  if (node.isProject || !node.run) return
  if (node.run.run_id === props.activeRunId) return
  void router.push({ name: 'review', params: { runId: node.run.run_id } })
  emit('navigate')
}

function statusDotType(status: string): string {
  if (status === 'running') return 'var(--el-color-primary)'
  if (status === 'completed' || status === 'approved') return 'var(--el-color-success)'
  if (status === 'failed' || status === 'rejected') return 'var(--el-color-danger)'
  if (status === 'waiting_review') return 'var(--el-color-warning)'
  return 'var(--el-color-info-light-5)'
}

defineExpose({ reload: load })

onMounted(load)

const stageLabel = (name: string): string => STAGE_LABELS[name as keyof typeof STAGE_LABELS] ?? name
const isReviewRoute = computed(() => route.name === 'review')
</script>

<template>
  <div v-loading="loading" class="project-tree">
    <div class="tree-header">
      <span class="tree-title">项目 / 任务</span>
      <el-button size="small" text :disabled="loading" @click="load">
        <el-icon><Refresh /></el-icon>
      </el-button>
    </div>
    <el-empty v-if="!loading && treeData.length === 0" description="暂无任务" :image-size="60" />
    <el-tree
      v-else
      :data="treeData"
      node-key="key"
      :default-expanded-keys="isReviewRoute ? currentNodeKey : []"
      :props="{ children: 'children', label: 'label' }"
      :expand-on-click-node="false"
      :current-node-key="activeKey"
      highlight-current
    >
      <template #default="{ data }">
        <div
          class="tree-node"
          :class="{ active: data.key === activeKey }"
          @click="handleClick(data as TreeNode)"
        >
          <template v-if="data.isProject">
            <el-icon class="node-icon"><Folder /></el-icon>
            <span class="node-label project-label" :title="data.label">{{ data.label }}</span>
          </template>
          <template v-else>
            <span
              class="status-dot"
              :style="{ background: statusDotType(data.run?.status ?? '') }"
            />
            <span class="node-label" :title="data.label">{{ data.label }}</span>
            <span class="node-meta">{{ stageLabel(data.run?.current_stage ?? '') }}</span>
          </template>
        </div>
      </template>
    </el-tree>
  </div>
</template>

<style scoped>
.project-tree {
  min-height: 200px;
}
.tree-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.tree-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}
.tree-node {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  overflow: hidden;
  padding: 2px 0;
}
.node-icon {
  color: var(--el-color-primary);
  flex-shrink: 0;
}
.node-label {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.project-label {
  font-weight: 600;
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.node-meta {
  margin-left: auto;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
  padding-left: 6px;
}
.tree-node.active .node-label {
  color: var(--el-color-primary);
  font-weight: 600;
}
</style>
