<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, toRef, watch } from 'vue'
import { Loading, Tools } from '@element-plus/icons-vue'
import { STAGE_LABELS, type AgentEventType, type AgentTraceEvent, type StageName, type WorkflowState } from '../api/types'
import { useAgentTrace } from '../composables/useAgentTrace'

const props = withDefaults(
  defineProps<{
    runId: string
    isRunning?: boolean
    currentStage?: StageName | null
    workflow?: WorkflowState | null
    cancelling?: boolean
  }>(),
  {
    isRunning: false,
    currentStage: null,
    workflow: null,
    cancelling: false,
  }
)

const emit = defineEmits<{
  (e: 'open-drawer'): void
  (e: 'cancel'): void
}>()

const runIdRef = toRef(props, 'runId')
const isRunningRef = toRef(props, 'isRunning')

const { events, latestEvent, activeTool, isStreaming } = useAgentTrace(runIdRef, isRunningRef)

// ------------------------------------------------------------------
// 秒级实时秒表计时器 (Elapsed Stopwatch)
// ------------------------------------------------------------------
const elapsedSeconds = ref(0)
let timerId: ReturnType<typeof setInterval> | null = null

function updateTimer(): void {
  if (props.workflow?.created_at) {
    try {
      const start = new Date(props.workflow.created_at).getTime()
      const now = Date.now()
      const diff = Math.max(0, Math.floor((now - start) / 1000))
      elapsedSeconds.value = diff
      return
    } catch {
      // 容错处理
    }
  }
  elapsedSeconds.value += 1
}

onMounted(() => {
  updateTimer()
  if (props.isRunning) {
    timerId = setInterval(updateTimer, 1000)
  }
})

watch(
  () => props.isRunning,
  (running) => {
    if (running) {
      if (!timerId) {
        timerId = setInterval(updateTimer, 1000)
      }
    } else {
      if (timerId) {
        clearInterval(timerId)
        timerId = null
      }
    }
  }
)

onBeforeUnmount(() => {
  if (timerId) {
    clearInterval(timerId)
    timerId = null
  }
})

const formattedElapsed = computed(() => {
  const s = elapsedSeconds.value
  const mm = String(Math.floor(s / 60)).padStart(2, '0')
  const ss = String(s % 60).padStart(2, '0')
  return `${mm}:${ss}`
})

// ------------------------------------------------------------------
// 微观事件流跑马灯 / Terminal 自动滚动
// ------------------------------------------------------------------
const streamBoxRef = ref<HTMLElement | null>(null)
const recentEvents = computed(() => {
  return events.value.slice(-8)
})

function scrollToBottom(): void {
  nextTick(() => {
    if (streamBoxRef.value) {
      streamBoxRef.value.scrollTop = streamBoxRef.value.scrollHeight
    }
  })
}

watch(
  () => events.value.length,
  () => {
    scrollToBottom()
  }
)

function formatTime(isoStr: string): string {
  if (!isoStr) return ''
  try {
    const d = new Date(isoStr)
    const hh = String(d.getHours()).padStart(2, '0')
    const mm = String(d.getMinutes()).padStart(2, '0')
    const ss = String(d.getSeconds()).padStart(2, '0')
    return `${hh}:${mm}:${ss}`
  } catch {
    return isoStr
  }
}

const EVENT_TYPE_BADGES: Record<string, { label: string; icon: string; cls: string }> = {
  agent_start: { label: '启动', icon: '', cls: 'badge-primary' },
  stage_start: { label: '阶段', icon: '', cls: 'badge-info' },
  stage_end: { label: '完成', icon: '', cls: 'badge-success' },
  stage_completed: { label: '完成', icon: '', cls: 'badge-success' },
  tool_call: { label: '调度', icon: '', cls: 'badge-warning' },
  tool_result: { label: '返回', icon: '', cls: 'badge-success' },
  agent_thought: { label: '思考', icon: '', cls: 'badge-purple' },
  llm_thought: { label: '思考', icon: '', cls: 'badge-purple' },
  agent_decision: { label: '决策', icon: '', cls: 'badge-amber' },
  artifact_created: { label: '产物', icon: '', cls: 'badge-warning' },
  info: { label: '动态', icon: '', cls: 'badge-info' },
  warn: { label: '预警', icon: '', cls: 'badge-danger' },
  warning: { label: '预警', icon: '', cls: 'badge-danger' },
  error: { label: '错误', icon: '', cls: 'badge-danger' },
}

function getEventBadge(eventType: string) {
  return EVENT_TYPE_BADGES[eventType] || { label: '事件', icon: '', cls: 'badge-info' }
}

const stageLabel = computed(() => {
  const s = props.currentStage || props.workflow?.current_stage
  return s ? STAGE_LABELS[s] || s : '全链路分析'
})
</script>

<script lang="ts">
export default { name: 'AgentLiveCockpit' }
</script>

<template>
  <div class="cockpit-card">
    <!-- 顶部状态栏 -->
    <div class="cockpit-header">
      <div class="header-status">
        <div class="radar-dot" :class="{ 'is-active': isRunning }">
          <span class="ping" />
          <span class="dot" />
        </div>
        <div class="status-text-group">
          <span class="cockpit-title">智能体全链路协同指挥舱</span>
          <span class="stage-badge">
            当前阶段：<strong>{{ stageLabel }}</strong>
          </span>
        </div>
      </div>

      <div class="header-metrics">
        <div class="metric-chip timer-chip">
          <span class="chip-label">已执行</span>
          <span class="chip-val">{{ formattedElapsed }}</span>
        </div>
        <div class="metric-chip events-chip">
          <span class="chip-label">捕获事件</span>
          <span class="chip-val">{{ events.length }}</span>
        </div>
        <el-button
          size="small"
          type="primary"
          class="btn-open-drawer"
          data-testid="btn-cockpit-open-drawer"
          @click="emit('open-drawer')"
        >
          查看完整动线与入参 ↗
        </el-button>
        <el-button
          v-if="isRunning"
          size="small"
          type="danger"
          plain
          :loading="cancelling"
          class="btn-cancel"
          data-testid="btn-cockpit-cancel"
          @click="emit('cancel')"
        >
          终止执行
        </el-button>
      </div>
    </div>

    <!-- 中间：当前执行焦点卡片 -->
    <div class="cockpit-focus">
      <div class="focus-lead">
        <span class="focus-tag">
          <span class="pulse-icon">●</span> 当前调度动作
        </span>
        <span v-if="activeTool" class="tool-tag">
          {{ activeTool }}
        </span>
        <span v-if="isStreaming" class="stream-pill">
          SSE 实时高速推流中
        </span>
      </div>

      <div class="focus-message">
        <p v-if="latestEvent" class="message-text">
          {{ latestEvent.message }}
        </p>
        <p v-else class="message-placeholder">
          正在与后台智能体建立高频实时动线连接，初始化投研流水线中
        </p>
      </div>
    </div>

    <!-- 底部：微观实时事件流终端 -->
    <div class="cockpit-feed">
      <div class="feed-header">
        <span class="feed-title">微观执行事件流 (最近 {{ recentEvents.length }} 条实时更新)</span>
        <span class="feed-hint">页面每秒自动捕获底层规划器、量化引擎与技能调度细节</span>
      </div>

      <div ref="streamBoxRef" class="feed-box">
        <div v-if="recentEvents.length === 0" class="feed-empty">
          <el-icon class="is-loading" style="margin-right: 6px"><Loading /></el-icon>
          等待智能体首条微观事件推流...
        </div>
        <div
          v-for="(evt, idx) in recentEvents"
          :key="evt.id || idx"
          class="feed-line"
          :class="{ 'is-latest': idx === recentEvents.length - 1 }"
        >
          <span class="line-time">{{ formatTime(evt.timestamp) }}</span>
          <span class="line-stage">{{ evt.stage_label || evt.stage }}</span>
          <span class="line-badge" :class="getEventBadge(evt.event_type).cls">
            {{ getEventBadge(evt.event_type).label }}
          </span>
          <span v-if="evt.tool" class="line-tool">[{{ evt.tool }}]</span>
          <span class="line-msg">{{ evt.message }}</span>
          <span v-if="idx === recentEvents.length - 1 && isRunning" class="cursor-blink">▌</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cockpit-card {
  background: var(--rp-card, #fffefb);
  border: 1px solid var(--rp-line, #e3ddcd);
  border-top: 3px solid var(--rp-gold, #a9853f);
  box-shadow: 0 2px 8px rgba(30, 58, 92, 0.05);
  border-radius: 4px;
  color: var(--rp-ink, #26251f);
  padding: 14px 18px;
  margin-bottom: 14px;
  position: relative;
  overflow: hidden;
}

/* 头部 */
.cockpit-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--el-border-color-extra-light, #f2eee4);
}

.header-status {
  display: flex;
  align-items: center;
  gap: 10px;
}

.radar-dot {
  position: relative;
  width: 12px;
  height: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.radar-dot .dot {
  width: 7px;
  height: 7px;
  background: var(--rp-gold, #a9853f);
  border-radius: 50%;
}

.radar-dot.is-active .ping {
  position: absolute;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: rgba(169, 133, 63, 0.35);
  animation: pulse-ring 1.8s cubic-bezier(0.215, 0.61, 0.355, 1) infinite;
}

@keyframes pulse-ring {
  0% { transform: scale(0.6); opacity: 1; }
  100% { transform: scale(1.6); opacity: 0; }
}

.status-text-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.cockpit-title {
  font-family: var(--rp-serif, Georgia, 'Songti SC', serif);
  font-size: 15px;
  font-weight: 700;
  color: var(--rp-navy, #1e3a5c);
  letter-spacing: 0.3px;
}

.stage-badge {
  font-size: 12px;
  background: #fbf8f0;
  color: var(--rp-gold, #a9853f);
  border: 1px solid #ebd9b3;
  padding: 1px 7px;
  border-radius: 3px;
}

.header-metrics {
  display: flex;
  align-items: center;
  gap: 8px;
}

.metric-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: #f8f6f0;
  border: 1px solid #e5dfd0;
  border-radius: 3px;
  padding: 3px 8px;
  font-size: 11.5px;
}

.metric-chip .chip-label {
  color: var(--el-text-color-secondary, #8f8a7a);
}

.metric-chip .chip-val {
  font-family: var(--rp-serif, serif);
  font-weight: 700;
  color: var(--rp-navy, #1e3a5c);
}

.timer-chip .chip-val {
  color: var(--rp-gold, #a9853f);
  font-size: 13px;
}

.btn-open-drawer {
  background: var(--rp-navy, #1e3a5c);
  border-color: var(--rp-navy, #1e3a5c);
  color: #fff;
  font-weight: 600;
}

.btn-open-drawer:hover {
  background: #2b4f7a;
  border-color: #2b4f7a;
}

/* 焦点卡片 */
.cockpit-focus {
  margin-top: 10px;
  background: #faf8f5;
  border: 1px solid #eae5d7;
  border-radius: 3px;
  padding: 10px 12px;
}

.focus-lead {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.focus-tag {
  font-size: 11px;
  font-weight: 700;
  color: var(--rp-gold, #a9853f);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.focus-tag .pulse-icon {
  color: #10b981;
  font-size: 10px;
}

.tool-tag {
  font-size: 11px;
  font-family: ui-monospace, Menlo, Monaco, Consolas, monospace;
  background: #f4efe4;
  color: var(--rp-navy, #1e3a5c);
  border: 1px solid #dfd2b5;
  padding: 1px 6px;
  border-radius: 3px;
  display: inline-flex;
  align-items: center;
}

.stream-pill {
  font-size: 11px;
  color: #2e7d32;
  margin-left: auto;
  font-weight: 500;
}

.message-text {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  color: var(--rp-ink, #26251f);
  font-weight: 500;
}

.message-placeholder {
  margin: 0;
  font-size: 12.5px;
  color: var(--el-text-color-secondary, #8f8a7a);
  font-style: italic;
}

/* 底部事件流 */
.cockpit-feed {
  margin-top: 10px;
}

.feed-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--el-text-color-secondary, #8f8a7a);
  margin-bottom: 6px;
}

.feed-title {
  font-weight: 600;
  color: var(--rp-navy, #1e3a5c);
}

.feed-hint {
  font-size: 11px;
  color: var(--el-text-color-secondary, #8f8a7a);
}

.feed-box {
  background: #faf8f5;
  border: 1px solid #e3ddcd;
  border-radius: 4px;
  padding: 6px 10px;
  max-height: 140px;
  overflow-y: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11.5px;
  line-height: 1.6;
}

.feed-empty {
  color: #8f8a7a;
  padding: 10px 0;
  text-align: center;
}

.feed-line {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 2px 0;
  color: #46433a;
  border-bottom: 1px dashed #ede8dc;
}

.feed-line:last-child {
  border-bottom: none;
}

.feed-line.is-latest {
  color: #1e3a5c;
  font-weight: 600;
}

.line-time {
  color: #8f8a7a;
  flex-shrink: 0;
  font-size: 11px;
}

.line-stage {
  color: var(--rp-navy, #1e3a5c);
  flex-shrink: 0;
  font-size: 11px;
  padding: 0 4px;
  background: #f0edf4;
  border-radius: 2px;
}

.line-badge {
  flex-shrink: 0;
  font-size: 11px;
  padding: 0 5px;
  border-radius: 3px;
  font-weight: 600;
}

.badge-primary { background: #f0f4f8; color: var(--rp-navy, #1e3a5c); border: 1px solid #cbd8e6; }
.badge-info { background: #f4f1e9; color: var(--rp-ink, #46433a); border: 1px solid #dfd9c8; }
.badge-success { background: #f0f7f4; color: var(--el-color-success, #3d7a50); border: 1px solid #c2ded0; }
.badge-warning { background: #faf6ee; color: var(--rp-gold, #a9853f); border: 1px solid #ebd9b3; }
.badge-purple { background: #f2f5f7; color: #2c4a6f; border: 1px solid #c5d2e0; }
.badge-amber { background: #faf6ee; color: var(--rp-gold, #a9853f); border: 1px solid #ebd9b3; }
.badge-danger { background: #fdf5f4; color: var(--el-color-danger, #a8402f); border: 1px solid #e8c8bf; }

.line-tool {
  color: var(--rp-gold, #a9853f);
  flex-shrink: 0;
  font-weight: 600;
}

.line-msg {
  color: inherit;
  flex: 1;
  word-break: break-all;
}

.cursor-blink {
  color: var(--rp-gold, #a9853f);
  font-weight: bold;
  animation: blink 0.9s infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
</style>
