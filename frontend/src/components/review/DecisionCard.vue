<template>
  <el-card class="decision-card">
    <template #header>
      <div class="decision-header">
        <span class="decision-title">图表选择决策</span>
        <el-tag type="warning">
          已选: {{ selectedCount }} / {{ totalCount }}
        </el-tag>
      </div>
    </template>

    <el-alert
      v-if="selectedCount > 8"
      type="warning"
      :closable="false"
      show-icon
    >
      已选择 {{ selectedCount }} 张图表，推荐 5-8 张。超出部分将降低报告信息密度。
    </el-alert>

    <RiskNoticeList
      v-if="riskNotices.length"
      :notices="riskNotices"
    />

    <div v-if="conflictGroups.length" class="conflict-groups">
      <h4>冲突组</h4>
      <div
        v-for="group in conflictGroups"
        :key="group.conflict_group_id"
        class="conflict-group"
      >
        <el-alert type="info" :closable="false">
          <template #title>
            {{ group.reason }}
          </template>
          保留全部风险: {{ group.risk_if_keep_all }}
        </el-alert>
      </div>
    </div>

    <div class="candidates-grid">
      <ChartCandidateCard
        v-for="candidate in candidates"
        :key="candidate.candidate_id"
        :candidate="candidate"
        :selected="selectedIds.has(candidate.candidate_id)"
        @toggle="toggleCandidate"
      />
    </div>

    <div class="decision-actions">
      <el-button type="primary" @click="$emit('accept-recommendation')">
        接受推荐
      </el-button>
      <el-button
        v-if="acknowledgementRequiredCodes.length"
        type="warning"
        @click="$emit('accept-with-risks')"
      >
        接受风险并继续
      </el-button>
      <el-button @click="handleCustomize">
        自定义选择
      </el-button>
      <el-button @click="$emit('regenerate')">
        重新生成
      </el-button>
      <el-button type="danger" @click="$emit('cancel')">
        取消
      </el-button>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import type { ChartCandidateResult, ConflictGroup, RiskNotice } from '@/types/workflow'
import ChartCandidateCard from '@/components/charts/ChartCandidateCard.vue'
import RiskNoticeList from '@/components/review/RiskNoticeList.vue'

const props = defineProps<{
  candidates: ChartCandidateResult[]
  riskNotices: RiskNotice[]
  conflictGroups: ConflictGroup[]
  acknowledgementRequiredCodes: string[]
}>()

const emit = defineEmits<{
  'accept-recommendation': []
  'accept-with-risks': []
  'customize': [selectedIds: string[]]
  'regenerate': []
  'cancel': []
}>()

const selectedIds = ref(new Set<string>(
  props.candidates
    .filter(c => c.status === 'recommended')
    .map(c => c.candidate_id)
))

const totalCount = computed(() => props.candidates.filter(c => c.status !== 'hard_blocked').length)
const selectedCount = computed(() => selectedIds.value.size)

function toggleCandidate(id: string) {
  if (selectedIds.value.has(id)) {
    selectedIds.value.delete(id)
  } else {
    selectedIds.value.add(id)
  }
}

function handleCustomize() {
  emit('customize', Array.from(selectedIds.value))
}
</script>

<style scoped>
.decision-card {
  margin-bottom: 16px;
}
.decision-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.decision-title {
  font-size: 16px;
  font-weight: 600;
}
.conflict-groups {
  margin: 12px 0;
}
.conflict-groups h4 {
  margin: 0 0 8px;
  font-size: 14px;
}
.conflict-group {
  margin-bottom: 8px;
}
.candidates-grid {
  margin: 16px 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.decision-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #e5e7eb;
}
</style>