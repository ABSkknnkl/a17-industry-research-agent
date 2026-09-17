<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { usePrototypeStore } from '../../mock/prototypeRun'
import type { ClaimItem } from '../../api/types'
import { claimStatusLabel as statusLabel, dimensionLabel } from '../../api/labels'

const emit = defineEmits<{
  (e: 'inspect', objectId: string, focus?: 'sources' | 'citations' | null): void
  (e: 'receipt', action: string, objectIds: string[]): void
}>()

const store = usePrototypeStore()

const rows = computed<ClaimItem[]>(() => store.getClaims())
const selectedId = computed(() => store.state.selectedObjectId)

async function onApprove(row: ClaimItem): Promise<void> {
  const rec = await store.restoreClaim(row.claim_id)
  ElMessage.success(rec.ok ? `已通过并恢复 ${row.claim_id}` : rec.message)
  if (rec.ok) emit('receipt', 'restoreClaim', [row.claim_id])
}

// 重新生成：先弹窗询问用户要修改什么
const regenDialog = ref<{
  visible: boolean
  claimId: string
  statement: string
  instruction: string
}>({
  visible: false,
  claimId: '',
  statement: '',
  instruction: '',
})

function openRegen(row: ClaimItem): void {
  regenDialog.value = {
    visible: true,
    claimId: row.claim_id,
    statement: row.statement,
    instruction: '',
  }
}

async function confirmRegen(): Promise<void> {
  const { claimId, instruction } = regenDialog.value
  regenDialog.value.visible = false
  const rec = await store.regenerateClaim(claimId, instruction)
  ElMessage[rec.ok ? 'success' : 'error'](rec.message)
  if (rec.ok) emit('receipt', rec.action, [claimId, ...rec.affected])
}

async function onRestore(row: ClaimItem): Promise<void> {
  const rec = await store.restoreClaim(row.claim_id)
  ElMessage.success(rec.message)
  if (rec.ok) emit('receipt', rec.action, [row.claim_id])
}

function onViewCitations(row: ClaimItem): void {
  store.selectObject(row.claim_id)
  emit('inspect', row.claim_id, 'citations')
}

function onViewDataSources(row: ClaimItem): void {
  store.selectObject(row.claim_id)
  emit('inspect', row.claim_id, 'sources')
}

// 状态与维度中文映射已统一到 src/api/labels.ts，此处以别名引入，调用点不变。

function statusType(status: string): 'success' | 'warning' | 'danger' | 'info' {
  if (status === 'active') return 'success'
  if (status === 'provisional') return 'warning'
  if (status === 'rejected') return 'danger'
  return 'info'
}
</script>

<template>
  <div class="claim-review" data-testid="claim-review-list">
    <div class="section-head">
      <span class="section-title">结论审核</span>
      <span class="muted">选中结论后可用「修改条件重跑」</span>
    </div>
    <div
      v-for="row in rows"
      :key="row.claim_id"
      class="claim-card"
      :class="{ selected: selectedId === row.claim_id }"
    >
      <div class="claim-head">
        <span class="claim-id">{{ row.claim_id }}</span>
        <el-tag size="small" :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        <span class="muted dim">{{ dimensionLabel(row.dimension) }}</span>
      </div>
      <p class="claim-statement">{{ row.statement }}</p>
      <p class="muted counter">反证条件：{{ row.counter_condition }}</p>
      <div class="claim-ops">
        <el-button
          link
          type="primary"
          size="small"
          data-testid="claim-view"
          @click="onViewCitations(row)"
        >
          查看引用
        </el-button>
        <el-button
          link
          type="primary"
          size="small"
          data-testid="claim-view-sources"
          @click="onViewDataSources(row)"
        >
          查看数据来源
        </el-button>
        <template v-if="row.status !== 'active'">
          <el-button
            link
            type="success"
            size="small"
            data-testid="claim-approve"
            @click="onApprove(row)"
          >
            通过
          </el-button>
        </template>
        <el-button
          link
          type="warning"
          size="small"
          data-testid="claim-regenerate"
          @click="openRegen(row)"
        >
          重新生成本条结论
        </el-button>
        <el-button
          v-if="row.status !== 'active'"
          link
          type="primary"
          size="small"
          data-testid="claim-restore"
          @click="onRestore(row)"
        >
          恢复
        </el-button>
      </div>
    </div>

    <!-- 重新生成结论：先询问用户要修改什么 -->
    <el-dialog
      v-model="regenDialog.visible"
      title="重新生成本条结论"
      width="520px"
      data-testid="claim-regen-dialog"
    >
      <p class="muted claim-regen-statement">当前结论：{{ regenDialog.statement }}</p>
      <p class="muted" style="margin: 8px 0">
        请描述希望如何修改这条结论（例如：修正数据口径、补充反证条件、调整结论强度…）：
      </p>
      <el-input
        v-model="regenDialog.instruction"
        type="textarea"
        :rows="4"
        placeholder="填写具体的修改诉求…"
        data-testid="claim-regen-instruction"
      />
      <template #footer>
        <el-button @click="regenDialog.visible = false">取消</el-button>
        <el-button type="primary" data-testid="claim-regen-confirm" @click="confirmRegen">
          确认重新生成
        </el-button>
      </template>
    </el-dialog>
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
.claim-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 10px 12px;
  margin-bottom: 8px;
  background: var(--el-bg-color);
}
.claim-card.selected {
  border-color: var(--rp-gold);
  box-shadow: 0 1px 4px rgba(30, 58, 92, 0.08);
}
.claim-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.claim-id {
  font-family: var(--rp-serif);
  font-weight: 700;
  color: var(--rp-navy);
  font-size: 12px;
}
.claim-statement {
  margin: 4px 0;
  font-size: 12.5px;
  line-height: 1.7;
}
.counter {
  margin: 0 0 6px;
}
.claim-ops {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}
.claim-regen-statement {
  margin: 0;
  padding: 6px 10px;
  background: var(--rp-paper);
  border-left: 2px solid var(--rp-gold);
  font-size: 12px;
  line-height: 1.7;
}
.dim {
  margin-left: auto;
}
</style>
