<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { usePrototypeStore } from '../../mock/prototypeRun'
import type { EvidenceItem } from '../../api/types'
import { evidenceCategoryLabel as categoryLabel, evidenceStatusLabel } from '../../api/labels'

const emit = defineEmits<{
  (e: 'inspect', objectId: string): void
  (e: 'receipt', action: string, objectIds: string[]): void
}>()

const store = usePrototypeStore()
const excludeReasons: Record<string, string> = {}

const rows = computed<EvidenceItem[]>(() => store.getEvidence())

const selectedId = computed(() => store.state.selectedObjectId)

function reasonOf(id: string): string {
  return excludeReasons[id] || '口径不符'
}

function setReason(id: string, reason: string): void {
  excludeReasons[id] = reason
}

async function onExclude(row: EvidenceItem): Promise<void> {
  const receipt = await store.excludeEvidence(row.evidence_id, reasonOf(row.evidence_id))
  ElMessage[receipt.ok ? 'success' : 'error'](receipt.message)
  if (receipt.ok) emit('receipt', receipt.action, [row.evidence_id, ...receipt.affected])
}

async function onRestore(row: EvidenceItem): Promise<void> {
  const receipt = await store.restoreEvidence(row.evidence_id)
  ElMessage[receipt.ok ? 'success' : 'error'](receipt.message)
  if (receipt.ok) emit('receipt', receipt.action, [row.evidence_id, ...receipt.affected])
}

function onView(row: EvidenceItem): void {
  store.selectObject(row.evidence_id)
  emit('inspect', row.evidence_id)
}

// 来源类型中文映射已统一到 src/api/labels.ts（evidenceCategoryLabel），
// 此处以别名 categoryLabel 引入，避免改动下方多处调用点。

/**
 * 编号：按证据列表顺序生成，供用户阅读与口头引用（“第 3 条证据”）。
 *
 * 为什么不直接显示 evidence_id：真实环境下它是内容指纹
 * （`E-` + sha256 前 16 位，如 E-47d2f5e751a3e6de），普通用户无法识别；
 * 而且它是个外键（被结论、图表、段落引用），不能改名。
 * 所以完整识别码收进悬浮提示 + 点击复制，表格里只留可读编号。
 */
const numberById = computed<Record<string, number>>(() => {
  const map: Record<string, number> = {}
  rows.value.forEach((row, idx) => {
    map[row.evidence_id] = idx + 1
  })
  return map
})

function labelOf(row: EvidenceItem): string {
  return `#${numberById.value[row.evidence_id] ?? '?'}`
}

async function copyEvidenceId(id: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(id)
    ElMessage.success(`已复制识别码：${id}`)
  } catch {
    // 剪贴板不可用（非 https / 无权限）时退化为提示，至少让用户能手动复制
    ElMessage.warning(`复制失败，识别码：${id}`)
  }
}

const editingReasonId = ref('')

function rowClassName({ row }: { row: EvidenceItem }): string {
  return row.status === 'excluded' ? 'row-excluded' : ''
}
</script>

<template>
  <div class="evidence-review" data-testid="evidence-review-table">
    <div class="section-head">
      <span class="section-title">证据审核</span>
      <span class="muted">排除不是删除 · 行保留并标记</span>
      <span class="muted">· 编号可点击复制完整识别码</span>
    </div>
    <el-table :data="rows" size="small" border :row-class-name="rowClassName">
      <el-table-column label="编号" width="76">
        <template #default="{ row }">
          <el-tooltip :content="`识别码 ${row.evidence_id}（点击复制）`" placement="top">
            <span class="ev-no" data-testid="ev-no" @click="copyEvidenceId(row.evidence_id)">
              {{ labelOf(row) }}
            </span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="标题" min-width="180" show-overflow-tooltip>
        <template #default="{ row }">
          <span
            class="ev-title"
            :class="{ selected: selectedId === row.evidence_id }"
            @click="onView(row)"
          >
            {{ row.title }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="来源类型" width="96">
        <template #default="{ row }">
          <el-tag size="small" effect="plain">{{ categoryLabel(row.source_type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="as_of_date" label="日期" width="100" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag
            size="small"
            :type="
              row.status === 'active' ? 'success' : row.status === 'excluded' ? 'info' : 'warning'
            "
          >
            {{ evidenceStatusLabel(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button link type="primary" size="small" data-testid="ev-view" @click="onView(row)">
            查看
          </el-button>
          <template v-if="row.status !== 'excluded'">
            <el-select
              v-if="editingReasonId === row.evidence_id || true"
              :model-value="reasonOf(row.evidence_id)"
              size="small"
              style="width: 88px; margin: 0 4px"
              data-testid="ev-reason"
              @update:model-value="(v: string) => setReason(row.evidence_id, v)"
            >
              <el-option label="口径不符" value="口径不符" />
              <el-option label="来源可疑" value="来源可疑" />
              <el-option label="重复覆盖" value="重复覆盖" />
            </el-select>
            <el-button
              link
              type="danger"
              size="small"
              data-testid="ev-exclude"
              @click="onExclude(row)"
            >
              排除
            </el-button>
          </template>
          <el-button
            v-else
            link
            type="primary"
            size="small"
            data-testid="ev-restore"
            @click="onRestore(row)"
          >
            恢复
          </el-button>
        </template>
      </el-table-column>
    </el-table>
    <p class="muted demo-banner">演示数据，不代表真实研究结论</p>
  </div>
</template>

<style scoped>
.section-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 8px;
}
.section-title {
  font-weight: 700;
  font-size: 13px;
  color: var(--rp-navy);
}
.ev-title {
  cursor: pointer;
  border-bottom: 1px dashed transparent;
}
.ev-title.selected {
  color: var(--rp-gold);
  border-bottom-color: var(--rp-gold);
}
.ev-no {
  cursor: pointer;
  font-variant-numeric: tabular-nums;
  color: var(--el-color-primary);
  border-bottom: 1px dashed transparent;
}
.ev-no:hover {
  border-bottom-color: var(--el-color-primary);
}
.demo-banner {
  margin-top: 8px;
}
:deep(.row-excluded) {
  opacity: 0.55;
  background: var(--el-fill-color-light);
}
</style>
