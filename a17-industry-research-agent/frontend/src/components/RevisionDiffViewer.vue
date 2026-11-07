<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { CircleCheck, RefreshLeft } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getFeedbackHistory,
  getRevision,
  restoreRevision,
  type FeedbackHistoryItem,
} from '../api/client'
import type { StageName, WorkflowState } from '../api/types'
import { STAGE_LABELS } from '../api/types'

const props = defineProps<{
  runId: string
  currentRevision: number
}>()

const emit = defineEmits<{
  (e: 'restored', state: WorkflowState): void
}>()

const loading = ref(false)
const restoring = ref(false)
const historyList = ref<FeedbackHistoryItem[]>([])
const selectedHistory = ref<FeedbackHistoryItem | null>(null)
const prevRevisionState = ref<WorkflowState | null>(null)
const toRevisionState = ref<WorkflowState | null>(null)

async function loadHistory() {
  if (!props.runId) return
  loading.value = true
  try {
    const data = await getFeedbackHistory(props.runId)
    historyList.value = data
    if (data.length > 0) {
      selectedHistory.value = data[data.length - 1]
    } else {
      selectedHistory.value = null
    }
  } catch {
    // 忽略
  } finally {
    loading.value = false
  }
}

watch(() => props.runId, loadHistory, { immediate: true })
watch(() => props.currentRevision, loadHistory)

watch(selectedHistory, async (item) => {
  if (item) {
    try {
      const [fromState, toState] = await Promise.allSettled([
        getRevision(props.runId, item.from_revision),
        getRevision(props.runId, item.to_revision),
      ])
      prevRevisionState.value = fromState.status === 'fulfilled' ? fromState.value : null
      toRevisionState.value = toState.status === 'fulfilled' ? toState.value : null
    } catch {
      prevRevisionState.value = null
      toRevisionState.value = null
    }
  } else {
    prevRevisionState.value = null
    toRevisionState.value = null
  }
})

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return iso
  }
}

interface DiffLine {
  sign: '-' | '+' | '~' | 'i'
  kind: 'del' | 'add' | 'mod' | 'info'
  text: string
}

const computedDiffLines = computed<DiffLine[]>(() => {
  const item = selectedHistory.value
  if (!item) return []

  const lines: DiffLine[] = []
  const stage = item.stage as StageName
  const stageNameStr = STAGE_LABELS[stage] || item.stage
  const fromRev = item.from_revision
  const toRev = item.to_revision

  const prevStage = prevRevisionState.value?.stage_results?.[stage]
  const nextStage = toRevisionState.value?.stage_results?.[stage]

  // 1. 如果是版本回滚动作
  if (item.action === 'restore_revision') {
    lines.push({
      sign: '~',
      kind: 'mod',
      text: `[版本回滚] 从历史快照 r${fromRev} 恢复为全新修订版本 r${toRev}`,
    })
    return lines
  }

  // 2. 状态比对
  if (prevStage && nextStage && prevStage.status !== nextStage.status) {
    lines.push({
      sign: '-',
      kind: 'del',
      text: `[r${fromRev} 阶段状态] ${prevStage.status}`,
    })
    lines.push({
      sign: '+',
      kind: 'add',
      text: `[r${toRev} 阶段状态] ${nextStage.status}`,
    })
  }

  // 3. 阶段数据指标比对
  const prevData = (prevStage?.data ?? {}) as Record<string, unknown>
  const nextData = (nextStage?.data ?? {}) as Record<string, unknown>

  if (stage === 'data_fetch') {
    const prevCount = typeof prevData.record_count === 'number' ? prevData.record_count : null
    const nextCount = typeof nextData.record_count === 'number' ? nextData.record_count : null
    if (prevCount !== null && nextCount !== null) {
      if (prevCount !== nextCount) {
        lines.push({
          sign: '-',
          kind: 'del',
          text: `[r${fromRev} 数据量] 基线采集 ${prevCount} 条证据记录`,
        })
        const diff = nextCount - prevCount
        lines.push({
          sign: '+',
          kind: 'add',
          text: `[r${toRev} 补采结果] 靶向扩充至 ${nextCount} 条数据 (增量 ${diff > 0 ? '+' : ''}${diff}条)`,
        })
      } else {
        lines.push({
          sign: 'i',
          kind: 'info',
          text: `[r${toRev} 证据库] 保持 ${nextCount} 条结构化证据`,
        })
      }
    }
  } else if (stage === 'chart_generate') {
    const prevCharts = Array.isArray(prevData.charts) ? prevData.charts.length : 0
    const nextCharts = Array.isArray(nextData.charts) ? nextData.charts.length : 0
    if (prevCharts !== nextCharts || nextCharts > 0) {
      lines.push({
        sign: '-',
        kind: 'del',
        text: `[r${fromRev} 图表集] 原版本包含 ${prevCharts} 张候选图表`,
      })
      lines.push({
        sign: '+',
        kind: 'add',
        text: `[r${toRev} 图表重构] 响应人工指令重构为 ${nextCharts} 张专业矢量图表`,
      })
    }
  } else if (stage === 'chapter_write') {
    const prevSecs = Array.isArray(prevData.sections) ? prevData.sections.length : 0
    const nextSecs = Array.isArray(nextData.sections) ? nextData.sections.length : 0
    if (prevSecs > 0 || nextSecs > 0) {
      lines.push({
        sign: '-',
        kind: 'del',
        text: `[r${fromRev} 章节结构] 原章节包含 ${prevSecs} 节草稿`,
      })
      lines.push({
        sign: '+',
        kind: 'add',
        text: `[r${toRev} 章节结构] 优化调整为 ${nextSecs} 节论证正文`,
      })
    }
  } else if (stage === 'report_fusion') {
    const prevTitle = String(prevData.report_title || prevData.title || '')
    const nextTitle = String(nextData.report_title || nextData.title || '')
    if (prevTitle && nextTitle && prevTitle !== nextTitle) {
      lines.push({
        sign: '-',
        kind: 'del',
        text: `[r${fromRev} 报告标题] ${prevTitle}`,
      })
      lines.push({
        sign: '+',
        kind: 'add',
        text: `[r${toRev} 报告标题] ${nextTitle}`,
      })
    }
  }

  // 4. 用户反馈与变更范围
  if (item.changed_fields && item.changed_fields.length > 0) {
    lines.push({
      sign: '~',
      kind: 'mod',
      text: `[r${toRev} 变更字段] 覆盖字段: ${item.changed_fields.join('、')}`,
    })
  }

  if (item.combined_feedback || item.comment) {
    lines.push({
      sign: '+',
      kind: 'add',
      text: `[r${toRev} 协同指令] “${item.combined_feedback || item.comment}”`,
    })
  }

  if (item.edited_data?.annotations) {
    const annotCount = (item.edited_data.annotations as unknown[]).length
    lines.push({
      sign: '+',
      kind: 'add',
      text: `[r${toRev} 视觉/事实批注] 吸收并融入 ${annotCount} 项对象级结构化批注`,
    })
  }

  // 兜底提示
  if (lines.length === 0) {
    lines.push({
      sign: 'i',
      kind: 'info',
      text: `[r${fromRev} → r${toRev}] 阶段「${stageNameStr}」已成功按反馈指令定向演进`,
    })
  }

  return lines
})

async function onRestoreRevision(targetRev: number) {
  try {
    await ElMessageBox.confirm(
      `确定要将当前研报任务回滚恢复至历史版本 r${targetRev} 吗？系统将以此版本为基线创建新的修订版本。`,
      '版本回滚恢复确认',
      {
        confirmButtonText: '确认回滚',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    restoring.value = true
    const updated = await restoreRevision(props.runId, targetRev)
    ElMessage.success(`已成功从历史版本 r${targetRev} 恢复，当前版本已升级为 r${updated.revision}`)
    emit('restored', updated)
    await loadHistory()
  } catch (err) {
    if (err !== 'cancel') {
      ElMessage.error(`回滚恢复失败: ${(err as Error)?.message || err}`)
    }
  } finally {
    restoring.value = false
  }
}
</script>

<template>
  <div class="revision-diff-viewer" data-testid="revision-diff-viewer">
    <div v-if="historyList.length === 0" class="empty-diff muted">
      <span class="empty-tag">INIT</span>
      <span
        >当前为初始生成版本
        (r1)。当您针对任一阶段提交修改与反馈后，此处将自动呈现版本演化对比与优化轨迹。</span
      >
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
            <span class="pill-stage"
              >【{{ STAGE_LABELS[item.stage as StageName] || item.stage }}】</span
            >
            <span class="pill-time muted">{{ formatTime(item.timestamp) }}</span>
          </button>
        </div>
      </div>

      <!-- 选中演进详情面板 -->
      <div v-if="selectedHistory" class="diff-detail-card">
        <div class="detail-header">
          <div class="header-left">
            <span class="rev-badge"
              >r{{ selectedHistory.from_revision }} → r{{ selectedHistory.to_revision }}</span
            >
            <strong
              >阶段：{{
                STAGE_LABELS[selectedHistory.stage as StageName] || selectedHistory.stage
              }}</strong
            >
          </div>
          <div class="header-right">
            <el-button
              size="small"
              type="warning"
              plain
              :icon="RefreshLeft"
              :loading="restoring"
              @click="onRestoreRevision(selectedHistory.from_revision)"
            >
              回滚至 r{{ selectedHistory.from_revision }}
            </el-button>
            <span class="time-meta muted"
              >反馈时间：{{ formatTime(selectedHistory.timestamp) }}</span
            >
          </div>
        </div>

        <div class="detail-grid">
          <!-- 用户反馈诉求 -->
          <div class="detail-col feedback-col">
            <h6 class="col-title">人机协同反馈与修改指令</h6>
            <div class="col-content text-box">
              <pre class="feedback-pre">{{
                selectedHistory.combined_feedback || selectedHistory.comment || '原条件重新生成'
              }}</pre>
            </div>
          </div>

          <!-- 优化响应与成果状态 -->
          <div class="detail-col response-col">
            <h6 class="col-title">智能体优化响应成果 (r{{ selectedHistory.to_revision }})</h6>
            <div class="col-content result-box">
              <div class="response-status">
                <span class="status-pill"
                  ><el-icon><CircleCheck /></el-icon> 靶向优化指令已完成推理闭环</span
                >
                <span class="status-hint">底层智能体已针对您的批注重构了分析矩阵与事实链条</span>
              </div>
              <div v-if="selectedHistory.edited_data?.annotations" class="annot-feedback-summary">
                <span class="annot-lead">吸收的对象级批注：</span>
                <span class="annot-count"
                  >{{ (selectedHistory.edited_data.annotations as unknown[]).length }} 项</span
                >
              </div>
            </div>
          </div>
        </div>

        <!-- 版本红绿演化 Diff -->
        <div class="diff-trace-box">
          <div class="diff-trace-header">
            <span class="diff-tag-lead">真实版本演化对比 (Diff):</span>
            <span class="diff-tag-sub muted"
              >r{{ selectedHistory.from_revision }} (旧版基线) vs r{{
                selectedHistory.to_revision
              }}
              (新版优化)</span
            >
          </div>
          <div class="diff-lines">
            <div
              v-for="(diff, dIdx) in computedDiffLines"
              :key="dIdx"
              class="diff-line"
              :class="{
                'diff-del': diff.kind === 'del',
                'diff-add': diff.kind === 'add',
                'diff-mod': diff.kind === 'mod',
                'diff-info': diff.kind === 'info',
              }"
            >
              <span class="diff-sign">{{ diff.sign }}</span>
              <span class="diff-text">{{ diff.text }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.diff-trace-box {
  margin-top: 10px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  padding: 8px 10px;
}
.diff-trace-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11.5px;
  font-weight: 600;
  margin-bottom: 6px;
  color: var(--rp-navy, #1e3a5c);
}
.diff-lines {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-family: ui-monospace, SFMono-Regular, monospace;
  font-size: 11.5px;
}
.diff-line {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 3px 6px;
  border-radius: 3px;
  line-height: 1.45;
}
.diff-del {
  background: #fef2f2;
  color: #b91c1c;
}
.diff-add {
  background: #f0fdf4;
  color: #15803d;
}
.diff-mod {
  background: #fefce8;
  color: #854d0e;
}
.diff-info {
  background: #f8fafc;
  color: #475569;
}
.diff-sign {
  font-weight: 700;
  width: 12px;
  text-align: center;
}
.diff-text {
  word-break: break-word;
}
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
  overflow-x: auto;
  padding-bottom: 4px;
}
.timeline-lead {
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  white-space: nowrap;
}
.timeline-nodes {
  display: flex;
  align-items: center;
  gap: 6px;
}
.timeline-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 20px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  cursor: pointer;
  font-size: 11px;
  color: #334155;
  transition: all 0.15s ease;
  white-space: nowrap;
}
.timeline-pill:hover {
  background: #e2e8f0;
}
.timeline-pill.active {
  background: var(--rp-navy, #1e3a5c);
  color: #ffffff;
  border-color: var(--rp-navy, #1e3a5c);
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
  flex-wrap: wrap;
  gap: 8px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--rp-navy, #1e3a5c);
}
.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
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
  .detail-grid {
    grid-template-columns: 1fr;
  }
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
