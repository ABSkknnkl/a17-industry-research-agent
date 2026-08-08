<template>
  <el-card class="chart-candidate-card" :class="statusClass">
    <template #header>
      <div class="candidate-header">
        <el-checkbox
          :model-value="selected"
          :disabled="candidate.status === 'hard_blocked'"
          @update:model-value="$emit('toggle', candidate.candidate_id)"
        />
        <span class="candidate-title">{{ candidate.title }}</span>
        <el-tag size="small">{{ candidate.chart_type }}</el-tag>
        <el-tag
          v-if="candidate.status === 'recommended'"
          type="success"
          size="small"
        >
          推荐
        </el-tag>
        <el-tag
          v-if="candidate.status === 'not_recommended'"
          type="info"
          size="small"
        >
          可选
        </el-tag>
        <el-tag
          v-if="candidate.status === 'hard_blocked'"
          type="danger"
          size="small"
        >
          阻断
        </el-tag>
      </div>
    </template>
    <div class="candidate-body">
      <div class="candidate-meta">
        <span>证据: {{ candidate.evidence_ids.join(', ') || '无' }}</span>
        <span>建议章节: {{ candidate.recommended_chapter_id || '未指定' }}</span>
        <span v-if="candidate.conflict_group_id" class="conflict-tag">
          冲突组: {{ candidate.conflict_group_id }}
        </span>
      </div>
      <p v-if="candidate.suppression_reason" class="suppression-reason">
        阻断原因: {{ candidate.suppression_reason }}
      </p>
      <RiskNoticeList
        v-if="candidate.risk_notices.length"
        :notices="candidate.risk_notices"
      />
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ChartCandidateResult } from '@/types/workflow'
import RiskNoticeList from '@/components/review/RiskNoticeList.vue'

const props = defineProps<{
  candidate: ChartCandidateResult
  selected: boolean
}>()

defineEmits<{
  toggle: [candidateId: string]
}>()

const statusClass = computed(() => ({
  'candidate-recommended': props.candidate.status === 'recommended',
  'candidate-optional': props.candidate.status === 'not_recommended',
  'candidate-blocked': props.candidate.status === 'hard_blocked',
}))
</script>

<style scoped>
.chart-candidate-card {
  margin-bottom: 8px;
}
.candidate-recommended {
  border-left: 4px solid #22c55e;
}
.candidate-optional {
  border-left: 4px solid #94a3b8;
}
.candidate-blocked {
  border-left: 4px solid #dc2626;
  opacity: 0.7;
}
.candidate-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.candidate-title {
  font-weight: 600;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.candidate-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.candidate-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #6b7280;
}
.conflict-tag {
  color: #f59e0b;
  font-weight: 500;
}
.suppression-reason {
  color: #dc2626;
  font-size: 13px;
  margin: 0;
}
</style>