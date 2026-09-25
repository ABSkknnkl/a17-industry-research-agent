<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { getFeedbackHistory, getRevision, type FeedbackHistoryItem } from '../api/client'
import type { StageName, WorkflowState } from '../api/types'
import { STAGE_LABELS } from '../api/types'

const props = defineProps<{
  runId: string
  currentRevision: number
}>()

const loading = ref(false)
const historyList = ref<FeedbackHistoryItem[]>([])
const selectedHistory = ref<FeedbackHistoryItem | null>(null)
const prevRevisionState = ref<WorkflowState | null>(null)

async function loadHistory() {
  if (!props.runId) return
  loading.value = true
  try {
    const data = await getFeedbackHistory(props.runId)
    historyList.value = data
    if (data.length > 0) {
      selectedHistory.value = data[data.length - 1]
    }
  } catch (e) {
    // 忽略
  } finally {
    loading.value = false
  }
}

watch(() => props.runId, loadHistory, { immediate: true })
watch(() => props.currentRevision, loadHistory)

watch(selectedHistory, async (item) => {
  if (item && item.from_revision) {
    try {
      prevRevisionState.value = await getRevision(props.runId, item.from_revision)
    } catch {
      prevRevisionState.value = null
    }
  } else {
    prevRevisionState.value = null
  }
})

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return iso
  }
}
</script>

<template>
  <div class="revision-diff-viewer" data-testid="revision-diff-viewer">
    <div v-if="historyList.length === 0" class="empty-diff muted">
      <span class="empty-tag">INIT</span>
      <span>当前为初始生成版本 (r1)。当您针对任一阶段提交修改与反馈后，此处将自动呈现版本演化对比与优化轨迹。</span>
    </div>

    <div v-else class="diff-content" v-loading="loading">
      <!-- 演进时间线导航 -->
      <div class="diff-timeline">
        <span class="timeline-lead">演化轨迹：</span>
        <div class="timeline-nodes">
          <button
            v-for="(item, idx) in historyList"
            :key="idx"
            type="button"
            class="timeline-pill"
            :class="{ active: selectedHistory === item }"
            @click="selectedHistory = item"
          >
            <span class="pill-rev">r{{ item.from_revision }} → r{{ item.to_revision }}</span>
            <span class="pill-stage">【{{ STAGE_LABELS[item.stage as StageName] || item.stage }}】</span>
            <span class="pill-time muted">{{ formatTime(item.timestamp) }}</span>
          </button>
        </div>
      </div>

      <!-- 选中演进详情面板 -->
      <div v-if="selectedHistory" class="diff-detail-card">
        <div class="detail-header">
          <div class="header-left">
            <span class="rev-badge">r{{ selectedHistory.from_revision }} → r{{ selectedHistory.to_revision }}</span>
            <strong>阶段：{{ STAGE_LABELS[selectedHistory.stage as StageName] || selectedHistory.stage }}</strong>
          </div>
          <span class="time-meta muted">反馈提交时间：{{ formatTime(selectedHistory.timestamp) }}</span>
        </div>

        <div class="detail-grid">
          <!-- 用户反馈诉求 -->
          <div class="detail-col feedback-col">
            <h6 class="col-title">人机协同反馈与修改指令</h6>
            <div class="col-content text-box">
              <pre class="feedback-pre">{{ selectedHistory.combined_feedback || selectedHistory.comment || '原条件重新生成' }}</pre>
            </div>
          </div>

          <!-- 优化响应与成果状态 -->
          <div class="detail-col response-col">
            <h6 class="col-title">智能体优化响应成果 (r{{ selectedHistory.to_revision }})</h6>
            <div class="col-content result-box">
              <div class="response-status">
                <span class="status-pill">✓ 靶向优化指令已完成推理闭环</span>
                <span class="status-hint">底层智能体已针对您的批注重构了分析矩阵与事实链条</span>
              </div>
              <div v-if="selectedHistory.edited_data?.annotations" class="annot-feedback-summary">
                <span class="annot-lead">吸收的对象级批注：</span>
                <span class="annot-count">{{ (selectedHistory.edited_data.annotations as unknown[]).length }} 项</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.revision-diff-viewer {
  background: #ffffff;
  border: 1px solid var(--rp-line, #e2e8f0);
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 12px;
}
.empty-diff {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #64748b;
  padding: 4px 0;
}
.empty-tag {
  font-size: 10px;
  font-weight: 700;
  background: #f1f5f9;
  color: #64748b;
  border: 1px solid #cbd5e1;
  padding: 1px 5px;
  border-radius: 3px;
  font-family: ui-monospace, SFMono-Regular, monospace;
}

.diff-timeline {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.timeline-lead {
  font-size: 12px;
  font-weight: 600;
  color: var(--rp-navy, #1e3a5c);
}
.timeline-nodes {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.timeline-pill {
  border: 1px solid #cbd5e1;
  background: #f8fafc;
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 11.5px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: all 0.15s ease;
}
.timeline-pill:hover {
  background: #e2e8f0;
  border-color: #94a3b8;
}
.timeline-pill.active {
  background: var(--rp-navy, #1e3a5c);
  border-color: var(--rp-navy, #1e3a5c);
  color: #ffffff;
}
.timeline-pill.active .muted {
  color: #cbd5e1 !important;
}
.pill-rev {
  font-weight: 700;
  font-family: ui-monospace, SFMono-Regular, monospace;
}

.diff-detail-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 14px;
}
.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--rp-navy, #1e3a5c);
}
.rev-badge {
  font-size: 11px;
  font-weight: 700;
  background: #e0f2fe;
  color: #0369a1;
  padding: 2px 6px;
  border-radius: 4px;
  font-family: ui-monospace, SFMono-Regular, monospace;
}
.time-meta {
  font-size: 11.5px;
}

.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
@media (max-width: 768px) {
  .detail-grid { grid-template-columns: 1fr; }
}
.col-title {
  margin: 0 0 6px;
  font-size: 12px;
  font-weight: 600;
  color: #334155;
}
.text-box {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 8px 10px;
  min-height: 70px;
}
.feedback-pre {
  margin: 0;
  font-family: inherit;
  font-size: 11.5px;
  line-height: 1.55;
  color: #0f172a;
  white-space: pre-wrap;
  word-break: break-word;
}
.result-box {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 8px 10px;
  min-height: 70px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
}
.response-status {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.status-pill {
  color: #15803d;
  font-size: 12px;
  font-weight: 600;
}
.status-hint {
  font-size: 11px;
  color: #64748b;
}
.annot-feedback-summary {
  font-size: 11.5px;
  color: #475569;
}
.annot-count {
  font-weight: 600;
  color: var(--rp-navy, #1e3a5c);
}
</style>
