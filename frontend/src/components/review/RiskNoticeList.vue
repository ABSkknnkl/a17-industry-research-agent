<template>
  <div class="risk-notice-list">
    <div
      v-for="notice in notices"
      :key="notice.risk_code"
      class="risk-notice"
      :class="`risk-${notice.severity}`"
    >
      <div class="risk-header">
        <el-tag
          :type="severityTag(notice.severity)"
          size="small"
        >
          {{ severityLabel(notice.severity) }}
        </el-tag>
        <span class="risk-title">{{ notice.title }}</span>
      </div>
      <p class="risk-detail">{{ notice.detail }}</p>
      <div class="risk-actions">
        <p class="risk-recommendation">
          <strong>建议：</strong>{{ notice.recommendation }}
        </p>
        <p class="risk-consequence">
          <strong>后果：</strong>{{ notice.consequence }}
        </p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { RiskNotice } from '@/types/workflow'

defineProps<{
  notices: RiskNotice[]
}>()

function severityTag(severity: string): string {
  const map: Record<string, string> = {
    info: 'info',
    warning: 'warning',
    high: 'danger',
    critical: 'danger',
  }
  return map[severity] || 'info'
}

function severityLabel(severity: string): string {
  const map: Record<string, string> = {
    info: '建议',
    warning: '注意',
    high: '需确认',
    critical: '阻断',
  }
  return map[severity] || severity
}
</script>

<style scoped>
.risk-notice-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.risk-notice {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px 16px;
  background: #fff;
}
.risk-notice.risk-critical {
  border-color: #dc2626;
  background: #fef2f2;
}
.risk-notice.risk-high {
  border-color: #f59e0b;
  background: #fffbeb;
}
.risk-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.risk-title {
  font-weight: 600;
  font-size: 14px;
}
.risk-detail {
  color: #6b7280;
  font-size: 13px;
  margin: 4px 0;
}
.risk-actions {
  margin-top: 8px;
  font-size: 13px;
}
.risk-recommendation {
  color: #059669;
  margin: 2px 0;
}
.risk-consequence {
  color: #dc2626;
  margin: 2px 0;
}
</style>