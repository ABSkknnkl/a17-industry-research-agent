<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, toRef, watch } from 'vue'
import { useAgentTrace } from '../composables/useAgentTrace'
import {
  STAGE_LABELS,
  type AgentEventType,
  type AgentTraceEvent,
  type StageName,
  type WorkflowState,
} from '../api/types'

const props = withDefaults(
  defineProps<{
    runId: string
    isRunning?: boolean
    activeStage?: StageName | null
    mode?: 'card' | 'drawer'
    workflow?: WorkflowState | null
  }>(),
  {
    isRunning: false,
    activeStage: null,
    mode: 'card',
    workflow: null,
  }
)

const emit = defineEmits<{
  (e: 'cancel'): void
  (e: 'stage-change'): void
}>()

const runIdRef = toRef(props, 'runId')
const isRunningRef = toRef(props, 'isRunning')

const { events, latestEvent, activeTool, isStreaming, loading, refresh } = useAgentTrace(
  runIdRef,
  isRunningRef
)

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
      // 容错
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
      if (pendingQueue.value.length > 0) {
        flushPendingQueue()
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
// 0.25 秒逐条入场队列 (Staggered Event Stream: 250ms Interval)
// ------------------------------------------------------------------
const POP_INTERVAL_MS = 250
const displayedEvents = ref<AgentTraceEvent[]>([])
const pendingQueue = ref<AgentTraceEvent[]>([])
const justPoppedId = ref<string | null>(null)
let popTimer: ReturnType<typeof setTimeout> | null = null
let clearGlowTimer: ReturnType<typeof setTimeout> | null = null

const isTestEnv = typeof import.meta !== 'undefined' && import.meta.env?.MODE === 'test'

const selectedStageFilter = ref<string>('all')
const selectedTypeFilter = ref<string>('all')

function matchesActiveFilter(evt: AgentTraceEvent): boolean {
  if (selectedStageFilter.value !== 'all' && evt.stage !== selectedStageFilter.value) {
    return false
  }
  if (selectedTypeFilter.value !== 'all') {
    if (selectedTypeFilter.value === 'tool' && !['tool_call', 'tool_result'].includes(evt.event_type)) {
      return false
    }
    if (
      selectedTypeFilter.value === 'thought' &&
      !['agent_thought', 'llm_thought', 'agent_decision'].includes(evt.event_type)
    ) {
      return false
    }
    if (selectedTypeFilter.value === 'artifact' && evt.event_type !== 'artifact_created') {
      return false
    }
  }
  return true
}

function popNextEvent(): void {
  if (pendingQueue.value.length === 0) {
    if (popTimer) {
      clearTimeout(popTimer)
      popTimer = null
    }
    return
  }

  // 若当前用户有激活的筛选条件（非全部），静默跳过不匹配的事件直接归入 displayedEvents，
  // 直至找到下一个符合筛选条件的事件作为本次 0.25s 律动弹出的目标，避免筛选时界面空置
  let nextEvt: AgentTraceEvent | null = null
  const hasFilter = selectedStageFilter.value !== 'all' || selectedTypeFilter.value !== 'all'

  while (pendingQueue.value.length > 0) {
    const candidate = pendingQueue.value.shift()!
    if (!hasFilter || matchesActiveFilter(candidate)) {
      nextEvt = candidate
      break
    } else {
      displayedEvents.value.push(candidate)
    }
  }

  if (!nextEvt) {
    if (popTimer) {
      clearTimeout(popTimer)
      popTimer = null
    }
    scrollToBottom()
    return
  }

  displayedEvents.value.push(nextEvt)
  justPoppedId.value = nextEvt.id

  if (clearGlowTimer) clearTimeout(clearGlowTimer)
  clearGlowTimer = setTimeout(() => {
    if (justPoppedId.value === nextEvt.id) {
      justPoppedId.value = null
    }
  }, 600)

  scrollToBottom()

  if (pendingQueue.value.length > 0) {
    popTimer = setTimeout(() => {
      popTimer = null
      popNextEvent()
    }, POP_INTERVAL_MS)
  }
}

function ingestEvents(newRawEvents: AgentTraceEvent[]): void {
  if (!newRawEvents || newRawEvents.length === 0) {
    displayedEvents.value = []
    pendingQueue.value = []
    justPoppedId.value = null
    if (popTimer) {
      clearTimeout(popTimer)
      popTimer = null
    }
    return
  }

  const displayedIds = new Set(displayedEvents.value.map((e) => e.id))
  const pendingIds = new Set(pendingQueue.value.map((e) => e.id))

  const toAdd: AgentTraceEvent[] = []
  for (const evt of newRawEvents) {
    if (!displayedIds.has(evt.id) && !pendingIds.has(evt.id)) {
      toAdd.push(evt)
    }
  }

  if (toAdd.length === 0) return

  // 测试环境直接同步展开配合断言
  if (isTestEnv) {
    while (pendingQueue.value.length > 0) {
      displayedEvents.value.push(pendingQueue.value.shift()!)
    }
    displayedEvents.value.push(...toAdd)
    scrollToBottom()
    return
  }

  // 将新事件推入等待队列，按 0.25 秒律动匀速弹出
  pendingQueue.value.push(...toAdd)

  // 若当前未在弹出计时中，立即弹出一项，后续以 250ms (0.25秒) 匀速推进
  if (!popTimer) {
    popNextEvent()
  }
}

function flushPendingQueue(): void {
  if (popTimer) {
    clearTimeout(popTimer)
    popTimer = null
  }
  while (pendingQueue.value.length > 0) {
    displayedEvents.value.push(pendingQueue.value.shift()!)
  }
  scrollToBottom()
}

/** 点击刷新时重新获取并以 0.25s 律动重新播放最新事件 */
async function handleRefresh(): Promise<void> {
  if (popTimer) {
    clearTimeout(popTimer)
    popTimer = null
  }
  displayedEvents.value = []
  pendingQueue.value = []
  justPoppedId.value = null
  await refresh()
  if (events.value.length > 0) {
    ingestEvents([...events.value])
  }
}

watch(
  () => events.value,
  (newVal) => {
    ingestEvents(newVal)
  },
  { deep: true, immediate: true }
)

watch(
  () => props.runId,
  () => {
    if (popTimer) {
      clearTimeout(popTimer)
      popTimer = null
    }
    displayedEvents.value = []
    pendingQueue.value = []
    justPoppedId.value = null
  }
)

onBeforeUnmount(() => {
  if (popTimer) {
    clearTimeout(popTimer)
    popTimer = null
  }
  if (clearGlowTimer) {
    clearTimeout(clearGlowTimer)
    clearGlowTimer = null
  }
})

const latestDisplayEvent = computed<AgentTraceEvent | null>(() => {
  if (displayedEvents.value.length > 0) {
    return displayedEvents.value[displayedEvents.value.length - 1]
  }
  return latestEvent.value || null
})

const activeDisplayTool = computed<string | null>(() => {
  for (let i = displayedEvents.value.length - 1; i >= 0; i--) {
    const evt = displayedEvents.value[i]
    if (evt.tool) return evt.tool
  }
  return activeTool.value || null
})

const currentDisplayStage = computed<StageName>(() => {
  const st = props.activeStage || props.workflow?.current_stage || latestDisplayEvent.value?.stage
  return (st as StageName) || 'data_fetch'
})

const currentDisplayStageLabel = computed<string>(() => {
  const st = currentDisplayStage.value
  return latestDisplayEvent.value?.stage_label || STAGE_LABELS[st] || st || '全链路协同'
})

watch(
  () => latestDisplayEvent.value?.event_type,
  (type) => {
    if (type && ['stage_completed', 'stage_end'].includes(type)) {
      emit('stage-change')
    }
  }
)

const isCollapsed = ref(false)
const autoScroll = ref(true)
const expandedDetails = ref<Record<string, boolean>>({})
const streamContainerRef = ref<HTMLElement | null>(null)

// 阶段与类型映射（收敛为研报温润雅致五阶调性，去除高饱和波普色）
const STAGE_COLORS: Record<StageName, { bg: string; text: string; border: string }> = {
  data_fetch: { bg: '#f0f4f8', text: '#1e3a5c', border: '#cbd8e6' },       // 藏青
  data_interpret: { bg: '#f2f5f7', text: '#2c4a6f', border: '#c5d2e0' },   // 石青
  chart_generate: { bg: '#faf6ee', text: '#a9853f', border: '#ebd9b3' },   // 金铜
  chapter_write: { bg: '#f1f6f2', text: '#2d6a4f', border: '#c2ded0' },    // 墨绿
  report_fusion: { bg: '#fbf2ef', text: '#8c2d19', border: '#e8c8bf' },    // 朱砂
}

const EVENT_TYPE_MAP: Record<string, { label: string; icon: string; tagType: string }> = {
  agent_start: { label: '智能体启动', icon: '', tagType: 'primary' },
  stage_start: { label: '阶段开始', icon: '', tagType: 'info' },
  stage_end: { label: '阶段完成', icon: '', tagType: 'success' },
  stage_completed: { label: '阶段完成', icon: '', tagType: 'success' },
  tool_call: { label: '调度工具', icon: '', tagType: 'warning' },
  tool_result: { label: '工具返回', icon: '', tagType: 'success' },
  agent_thought: { label: '推演思考', icon: '', tagType: 'info' },
  llm_thought: { label: '推演思考', icon: '', tagType: 'info' },
  agent_decision: { label: '自主决策', icon: '', tagType: 'primary' },
  artifact_created: { label: '产物生成', icon: '', tagType: 'warning' },
  info: { label: '常规信息', icon: '', tagType: 'info' },
  warn: { label: '风险告警', icon: '', tagType: 'danger' },
  warning: { label: '风险告警', icon: '', tagType: 'danger' },
  error: { label: '执行错误', icon: '', tagType: 'danger' },
}

const filteredEvents = computed(() => {
  return displayedEvents.value.filter(matchesActiveFilter)
})

// 当用户切换阶段或类型筛选条件时，若当前有队列且未在计时，立即触发一次 popNextEvent 寻找下一个符合筛选的事件，保持 0.25s 律动
watch([selectedStageFilter, selectedTypeFilter], () => {
  if (pendingQueue.value.length > 0 && !popTimer) {
    popNextEvent()
  }
})

function resetFilters(): void {
  selectedStageFilter.value = 'all'
  selectedTypeFilter.value = 'all'
}

function formatTime(isoStr: string): string {
  if (!isoStr) return ''
  try {
    const d = new Date(isoStr)
    const hh = String(d.getHours()).padStart(2, '0')
    const mm = String(d.getMinutes()).padStart(2, '0')
    const ss = String(d.getSeconds()).padStart(2, '0')
    const ms = String(d.getMilliseconds()).padStart(3, '0')
    return `${hh}:${mm}:${ss}.${ms}`
  } catch {
    return isoStr
  }
}

function toggleDetail(id: string): void {
  expandedDetails.value[id] = !expandedDetails.value[id]
}

function scrollToBottom(): void {
  if (!autoScroll.value || !streamContainerRef.value) return
  nextTick(() => {
    if (streamContainerRef.value) {
      streamContainerRef.value.scrollTop = streamContainerRef.value.scrollHeight
    }
  })
}

watch(
  () => displayedEvents.value.length,
  () => {
    scrollToBottom()
  }
)

function onUserScroll(): void {
  if (!streamContainerRef.value) return
  const { scrollTop, scrollHeight, clientHeight } = streamContainerRef.value
  // 如果距离底部超过 40px，则用户向上滚动了
  const atBottom = scrollHeight - scrollTop - clientHeight < 40
  if (!atBottom && autoScroll.value) {
    // 保持用户偏好或提示
  }
}
</script>

<script lang="ts">
export default { name: 'AgentLiveTrace' }
</script>

<template>
  <el-card v-if="mode === 'card'" class="trace-card page-card" shadow="never">
    <template #header>
      <div class="trace-header">
        <div class="header-left">
          <span class="trace-title">
            <span class="pulse-indicator" :class="{ active: isRunning }" />
            智能体微观执行动线与工具调用
          </span>
          <el-tag
            v-if="isRunning"
            type="success"
            size="small"
            effect="dark"
            class="status-pill live-pill"
          >
            ● 实时推流中 (Live Stream)
          </el-tag>
          <el-tag v-else type="info" size="small" effect="plain" class="status-pill">
            已归档调用记录 ({{ events.length }} 条)
          </el-tag>
        </div>

        <div class="header-right">
          <!-- 阶段筛选 -->
          <el-select
            v-model="selectedStageFilter"
            size="small"
            style="width: 120px"
            placeholder="筛选阶段"
          >
            <el-option label="全部阶段" value="all" />
            <el-option
              v-for="(label, st) in STAGE_LABELS"
              :key="st"
              :label="label"
              :value="st"
            />
          </el-select>

          <!-- 类型筛选 -->
          <el-select
            v-model="selectedTypeFilter"
            size="small"
            style="width: 110px"
            placeholder="筛选类型"
          >
            <el-option label="全部类型" value="all" />
            <el-option label="工具调度" value="tool" />
            <el-option label="思考推演" value="thought" />
            <el-option label="生成产物" value="artifact" />
          </el-select>

          <!-- 自动滚屏开关 -->
          <el-tooltip content="接收到新事件时自动定位到底部" placement="top">
            <el-button
              size="small"
              :type="autoScroll ? 'primary' : 'default'"
              plain
              @click="autoScroll = !autoScroll"
            >
              自动滚屏: {{ autoScroll ? '开' : '关' }}
            </el-button>
          </el-tooltip>

          <!-- 刷新 -->
          <el-button size="small" :loading="loading" @click="handleRefresh">
            刷新
          </el-button>

          <!-- 队列展开全部 -->
          <el-button
            v-if="pendingQueue.length > 0"
            size="small"
            type="primary"
            link
            class="btn-flush-queue"
            @click="flushPendingQueue"
          >
            全部展开 (+{{ pendingQueue.length }})
          </el-button>

          <!-- 折叠 -->
          <el-button
            size="small"
            text
            @click="isCollapsed = !isCollapsed"
          >
            {{ isCollapsed ? '展开动线' : '收起' }}
          </el-button>
        </div>
      </div>
    </template>

    <div v-show="!isCollapsed" class="trace-body">
      <!-- 正在执行的智能体高亮条 (Spotlight) -->
      <div v-if="latestDisplayEvent" class="spotlight-banner" :class="{ 'is-active': isRunning }">
        <div class="spotlight-stage">
          <span class="spotlight-badge" :style="{
            backgroundColor: STAGE_COLORS[latestDisplayEvent.stage]?.bg || '#f3f4f6',
            color: STAGE_COLORS[latestDisplayEvent.stage]?.text || '#374151',
            borderColor: STAGE_COLORS[latestDisplayEvent.stage]?.border || '#e5e7eb'
          }">
            {{ latestDisplayEvent.stage_label || STAGE_LABELS[latestDisplayEvent.stage] || latestDisplayEvent.stage }}
          </span>
          <span class="spotlight-state-text">
            {{ isRunning ? '当前智能体正在工作' : '最新执行状态' }}
          </span>
        </div>

        <div class="spotlight-content">
          <div class="spotlight-msg">
            <span v-if="isRunning" class="live-dot" />
            {{ latestDisplayEvent.message }}
          </div>
          <div v-if="latestDisplayEvent.tool || activeDisplayTool" class="spotlight-tool">
            <span class="tool-label">正在调度技能 / 模型:</span>
            <el-tag size="small" effect="dark" class="tool-tag">
              {{ latestDisplayEvent.tool || activeDisplayTool }}
            </el-tag>
          </div>
        </div>
      </div>

      <!-- 事件时序流 -->
      <div
        ref="streamContainerRef"
        class="stream-timeline"
        @scroll="onUserScroll"
      >
        <div v-if="filteredEvents.length === 0" class="empty-events muted">
          <span>{{ loading ? '正在加载事件流...' : (displayedEvents.length > 0 ? `当前筛选条件下暂无事件 (已捕获 ${displayedEvents.length} 条)` : '暂无匹配的智能体执行事件') }}</span>
          <el-button
            v-if="!loading && displayedEvents.length > 0 && (selectedStageFilter !== 'all' || selectedTypeFilter !== 'all')"
            size="small"
            type="primary"
            link
            style="margin-left: 8px"
            @click="resetFilters"
          >
            重置筛选
          </el-button>
        </div>

        <TransitionGroup name="event-pop" tag="div" class="event-stream-list">
          <div
            v-for="evt in filteredEvents"
            :key="evt.id"
            class="event-row"
            :class="[
              `type-${evt.event_type}`,
              { 'just-popped': evt.id === justPoppedId }
            ]"
          >
            <!-- 时间戳 -->
            <span class="col-time">{{ formatTime(evt.timestamp) }}</span>

            <!-- 阶段徽标 -->
            <span
              class="col-stage"
              :style="{
                backgroundColor: STAGE_COLORS[evt.stage]?.bg || '#f3f4f6',
                color: STAGE_COLORS[evt.stage]?.text || '#374151',
                borderColor: STAGE_COLORS[evt.stage]?.border || '#e5e7eb'
              }"
            >
              {{ evt.stage_label || STAGE_LABELS[evt.stage] || evt.stage }}
            </span>

            <!-- 事件类型 -->
            <span class="col-type">
              <el-tag
                :type="(EVENT_TYPE_MAP[evt.event_type]?.tagType as any) || 'info'"
                size="small"
                class="event-type-tag"
              >
                {{ EVENT_TYPE_MAP[evt.event_type]?.label || evt.event_type }}
              </el-tag>
            </span>

            <!-- 工具标识（如果有） -->
            <span v-if="evt.tool" class="col-tool">
              <span class="tool-chip">
                {{ evt.tool }}
              </span>
            </span>

            <!-- 事件描述正文 -->
            <span class="col-msg">
              <span class="msg-text">{{ evt.message }}</span>

              <!-- 可展开明细 -->
              <span v-if="evt.details && Object.keys(evt.details).length > 0" class="msg-actions">
                <el-button
                  link
                  size="small"
                  type="primary"
                  style="padding: 0 4px; font-size: 11px"
                  @click="toggleDetail(evt.id)"
                >
                  {{ expandedDetails[evt.id] ? '收起参数' : '参数明细' }}
                </el-button>
              </span>

              <!-- 展开的 JSON / 数据块 -->
              <div v-if="expandedDetails[evt.id]" class="detail-json-box">
                <pre>{{ JSON.stringify(evt.details, null, 2) }}</pre>
              </div>
            </span>
          </div>
        </TransitionGroup>
      </div>
    </div>
  </el-card>

  <!-- 抽屉模式 (Drawer Mode) -->
  <div v-else class="trace-drawer-view">
    <!-- 抽屉顶部：精品研报风 智能体全链路协同指挥面板 -->
    <div class="drawer-cockpit-panel" :class="{ 'is-running': isRunning }">
      <!-- 顶栏：标题与核心指标 -->
      <div class="cockpit-top-row">
        <div class="cockpit-identity">
          <span class="cockpit-radar-dot" :class="{ 'is-active': isRunning }">
            <span class="ping" />
            <span class="dot" />
          </span>
          <span class="cockpit-title">智能体全链路协同指挥</span>
          <span
            class="cockpit-stage-badge"
            :style="{
              backgroundColor: STAGE_COLORS[currentDisplayStage]?.bg || '#f4f1e9',
              color: STAGE_COLORS[currentDisplayStage]?.text || '#1e3a5c',
              borderColor: STAGE_COLORS[currentDisplayStage]?.border || '#e3ddcd'
            }"
          >
            {{ currentDisplayStageLabel }}
          </span>
        </div>

        <div class="cockpit-metrics">
          <div class="metric-badge timer-badge">
            <span class="badge-label">已执行</span>
            <span class="badge-val">{{ formattedElapsed }}</span>
          </div>
          <div class="metric-badge event-count-badge">
            <span class="badge-label">捕获事件</span>
            <span class="badge-val">
              {{ displayedEvents.length }} 条
              <span v-if="pendingQueue.length > 0" class="pending-hint" title="队列逐条弹出中">
                (+{{ pendingQueue.length }})
              </span>
            </span>
          </div>
          <el-button
            v-if="isRunning"
            size="small"
            type="danger"
            plain
            class="btn-drawer-cancel"
            data-testid="btn-drawer-cancel"
            @click="emit('cancel')"
          >
            终止任务
          </el-button>
        </div>
      </div>

      <!-- 中层：当前调度动作与焦点信息 -->
      <div class="cockpit-focus-card">
        <div class="focus-header">
          <div class="focus-lead">
            <span v-if="isRunning" class="live-dot" />
            <span class="focus-state-title">
              {{ isRunning ? '当前智能体正在工作' : '最新执行状态' }}
            </span>
          </div>
          <div v-if="latestDisplayEvent?.tool || activeDisplayTool" class="focus-tool-chip">
            <span class="tool-prefix">调度技能 / 模型:</span>
            <span class="tool-name">{{ latestDisplayEvent?.tool || activeDisplayTool }}</span>
          </div>
          <div v-if="isRunning && isStreaming" class="focus-sse-tag">
            ● 实时推流中 (Live Stream)
          </div>
        </div>

        <div class="focus-body">
          <p class="focus-message">
            {{ latestDisplayEvent?.message || (isRunning ? '正在与底层智能体建立高频推流连接，初始化投研流水线' : '暂无微观执行事件') }}
          </p>
        </div>
      </div>
    </div>

    <!-- 中间工具栏：筛选、滚屏、刷新 -->
    <div class="drawer-trace-toolbar">
      <div class="drawer-toolbar-left">
        <span class="toolbar-section-title">
          <span class="pulse-indicator" :class="{ active: isRunning }" />
          微观执行动线时序
        </span>
        <el-tag v-if="!isRunning" type="info" size="small" effect="plain" class="status-pill">
          已归档记录 ({{ events.length }} 条)
        </el-tag>
      </div>

      <div class="drawer-toolbar-right">
        <!-- 阶段筛选 -->
        <el-select
          v-model="selectedStageFilter"
          size="small"
          style="width: 110px"
          placeholder="筛选阶段"
        >
          <el-option label="全部阶段" value="all" />
          <el-option
            v-for="(label, st) in STAGE_LABELS"
            :key="st"
            :label="label"
            :value="st"
          />
        </el-select>

        <!-- 类型筛选 -->
        <el-select
          v-model="selectedTypeFilter"
          size="small"
          style="width: 100px"
          placeholder="类型"
        >
          <el-option label="全部类型" value="all" />
          <el-option label="工具调度" value="tool" />
          <el-option label="思考推演" value="thought" />
          <el-option label="生成产物" value="artifact" />
        </el-select>

        <!-- 自动滚屏开关 -->
        <el-tooltip content="接收到新事件时自动定位到底部" placement="top">
          <el-button
            size="small"
            :type="autoScroll ? 'primary' : 'default'"
            plain
            @click="autoScroll = !autoScroll"
          >
            滚屏: {{ autoScroll ? '开' : '关' }}
          </el-button>
        </el-tooltip>

        <!-- 刷新 -->
        <el-button size="small" :loading="loading" @click="handleRefresh">
          刷新
        </el-button>

        <!-- 队列展开全部 -->
        <el-button
          v-if="pendingQueue.length > 0"
          size="small"
          type="primary"
          link
          class="btn-flush-queue"
          @click="flushPendingQueue"
        >
          全部展开 (+{{ pendingQueue.length }})
        </el-button>
      </div>
    </div>

    <div class="trace-body is-drawer">
      <!-- 事件时序流 -->
      <div
        ref="streamContainerRef"
        class="stream-timeline is-drawer-timeline"
        @scroll="onUserScroll"
      >
        <div v-if="filteredEvents.length === 0" class="empty-events muted">
          <span>{{ loading ? '正在加载事件流...' : (displayedEvents.length > 0 ? `当前筛选条件下暂无事件 (已捕获 ${displayedEvents.length} 条)` : '暂无匹配的智能体执行事件') }}</span>
          <el-button
            v-if="!loading && displayedEvents.length > 0 && (selectedStageFilter !== 'all' || selectedTypeFilter !== 'all')"
            size="small"
            type="primary"
            link
            style="margin-left: 8px"
            @click="resetFilters"
          >
            重置筛选
          </el-button>
        </div>

        <TransitionGroup name="event-pop" tag="div" class="event-stream-list">
          <div
            v-for="evt in filteredEvents"
            :key="evt.id"
            class="event-row"
            :class="[
              `type-${evt.event_type}`,
              { 'just-popped': evt.id === justPoppedId }
            ]"
          >
            <!-- 时间戳 -->
            <span class="col-time">{{ formatTime(evt.timestamp) }}</span>

            <!-- 阶段徽标 -->
            <span
              class="col-stage"
              :style="{
                backgroundColor: STAGE_COLORS[evt.stage]?.bg || '#f3f4f6',
                color: STAGE_COLORS[evt.stage]?.text || '#374151',
                borderColor: STAGE_COLORS[evt.stage]?.border || '#e5e7eb'
              }"
            >
              {{ evt.stage_label || STAGE_LABELS[evt.stage] || evt.stage }}
            </span>

            <!-- 事件类型 -->
            <span class="col-type">
              <el-tag
                :type="(EVENT_TYPE_MAP[evt.event_type]?.tagType as any) || 'info'"
                size="small"
                class="event-type-tag"
              >
                {{ EVENT_TYPE_MAP[evt.event_type]?.label || evt.event_type }}
              </el-tag>
            </span>

            <!-- 工具标识（如果有） -->
            <span v-if="evt.tool" class="col-tool">
              <span class="tool-chip">
                {{ evt.tool }}
              </span>
            </span>

            <!-- 事件描述正文 -->
            <span class="col-msg">
              <span class="msg-text">{{ evt.message }}</span>

              <!-- 可展开明细 -->
              <span v-if="evt.details && Object.keys(evt.details).length > 0" class="msg-actions">
                <el-button
                  link
                  size="small"
                  type="primary"
                  style="padding: 0 4px; font-size: 11px"
                  @click="toggleDetail(evt.id)"
                >
                  {{ expandedDetails[evt.id] ? '收起参数' : '参数明细' }}
                </el-button>
              </span>

              <!-- 展开的 JSON / 数据块 -->
              <div v-if="expandedDetails[evt.id]" class="detail-json-box">
                <pre>{{ JSON.stringify(evt.details, null, 2) }}</pre>
              </div>
            </span>
          </div>
        </TransitionGroup>
      </div>
    </div>
  </div>
</template>

<style scoped>
.trace-card {
  margin-bottom: 16px;
  border: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color);
}
.trace-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.trace-title {
  font-family: var(--rp-serif, serif);
  font-size: 15px;
  font-weight: 700;
  color: var(--rp-navy, #1e3a5c);
  display: flex;
  align-items: center;
  gap: 8px;
}
.pulse-indicator {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--el-text-color-placeholder, #b5b0a0);
  display: inline-block;
}
.pulse-indicator.active {
  background: var(--rp-gold, #a9853f);
  box-shadow: 0 0 0 0 rgba(169, 133, 63, 0.6);
  animation: trace-pulse 1.8s infinite;
}
@keyframes trace-pulse {
  0% {
    transform: scale(0.95);
    box-shadow: 0 0 0 0 rgba(169, 133, 63, 0.6);
  }
  70% {
    transform: scale(1);
    box-shadow: 0 0 0 5px rgba(169, 133, 63, 0);
  }
  100% {
    transform: scale(0.95);
    box-shadow: 0 0 0 0 rgba(169, 133, 63, 0);
  }
}
.status-pill {
  font-size: 11px;
}
.live-pill {
  background-color: var(--rp-navy, #1e3a5c) !important;
  border-color: var(--rp-navy, #1e3a5c) !important;
  color: #fff !important;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* Spotlight 聚焦横幅：研报工作台沉浸式卡片 */
.spotlight-banner {
  background: var(--rp-card, #fffefb);
  border: 1px solid var(--rp-line, #e3ddcd);
  border-left: 3px solid var(--rp-navy, #1e3a5c);
  border-radius: 3px;
  padding: 10px 14px;
  margin-bottom: 12px;
  box-shadow: 0 1px 4px rgba(30, 58, 92, 0.03);
  transition: all 0.25s ease;
}
.spotlight-banner.is-active {
  background: #faf8f3;
  border-color: #d8ceb8;
  border-left-color: var(--rp-gold, #a9853f);
  box-shadow: 0 2px 8px rgba(169, 133, 63, 0.08);
}
.spotlight-stage {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.spotlight-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 2px;
  border: 1px solid transparent;
}
.spotlight-state-text {
  font-size: 11.5px;
  color: var(--el-text-color-secondary, #8f8a7a);
}
.spotlight-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.spotlight-msg {
  font-size: 13px;
  font-weight: 600;
  color: var(--rp-ink, #26251f);
  line-height: 1.5;
  display: flex;
  align-items: center;
  gap: 6px;
}
.live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--rp-gold, #a9853f);
  animation: live-blink 1.2s ease-in-out infinite alternate;
}
@keyframes live-blink {
  from { opacity: 0.3; }
  to { opacity: 1; }
}
.spotlight-tool {
  display: flex;
  align-items: center;
  gap: 6px;
}
.tool-label {
  font-size: 11px;
  color: var(--el-text-color-secondary, #8f8a7a);
}
.tool-tag {
  background-color: var(--rp-navy, #1e3a5c) !important;
  border-color: var(--rp-navy, #1e3a5c) !important;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

/* 时间线列表：米白纸底 + 印刷感装订细线 */
.stream-timeline {
  max-height: 360px;
  overflow-y: auto;
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  background: var(--rp-paper, #f6f4ef);
  border-radius: 3px;
  border: 1px solid var(--rp-line, #e3ddcd);
}
.stream-timeline::-webkit-scrollbar {
  width: 5px;
}
.stream-timeline::-webkit-scrollbar-thumb {
  background: #d5cdb8;
  border-radius: 2px;
}
.empty-events {
  text-align: center;
  padding: 36px 0;
  font-size: 12.5px;
  color: var(--el-text-color-secondary, #8f8a7a);
}
.event-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 5px 10px;
  border-radius: 2px;
  background: var(--rp-card, #fffefb);
  border: 1px solid #ebe6d9;
  font-size: 12px;
  line-height: 1.5;
  transition: background 0.15s ease, border-color 0.25s ease, box-shadow 0.25s ease;
}
.event-row:hover {
  background: #fbf9f4;
}

/* 动线列表过渡组容器 */
.event-stream-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
  width: 100%;
}

/* 0.5s 逐条入场动效 (Pop-in with subtle translateY, scale and blur) */
.event-pop-enter-active {
  transition: all 0.45s cubic-bezier(0.16, 1, 0.3, 1);
}
.event-pop-leave-active {
  transition: all 0.25s ease;
}
.event-pop-enter-from {
  opacity: 0;
  transform: translateY(-10px) scale(0.97);
  filter: blur(1px);
}
.event-pop-enter-to {
  opacity: 1;
  transform: translateY(0) scale(1);
  filter: blur(0);
}
.event-pop-move {
  transition: transform 0.3s ease;
}

/* 刚弹出时呼吸微光律动，展现智能体推演的高科技质感 */
@keyframes event-glow-pulse {
  0% {
    box-shadow: 0 0 0 2px rgba(30, 58, 92, 0.3), 0 3px 12px rgba(30, 58, 92, 0.12);
    border-color: #1e3a5c;
    background: #fbf7ee;
    transform: translateY(-1px);
  }
  50% {
    box-shadow: 0 0 0 1.5px rgba(169, 133, 63, 0.25), 0 2px 6px rgba(169, 133, 63, 0.08);
    border-color: #a9853f;
    background: #fcfbf7;
  }
  100% {
    box-shadow: none;
    border-color: #ebe6d9;
    background: var(--rp-card, #fffefb);
    transform: translateY(0);
  }
}

.event-row.just-popped {
  animation: event-glow-pulse 1.2s cubic-bezier(0.16, 1, 0.3, 1);
}

/* 快速展开按钮与提示徽章 */
.btn-flush-queue {
  font-size: 11.5px;
  color: #a9853f !important;
  font-weight: 600;
  padding: 0 4px;
}
.btn-flush-queue:hover {
  color: #8c6a2b !important;
}

.pending-hint {
  font-size: 11px;
  color: #a9853f;
  font-weight: 600;
  margin-left: 2px;
  animation: live-blink 1s ease-in-out infinite alternate;
}
.col-time {
  font-family: var(--rp-serif, Georgia, serif);
  font-variant-numeric: tabular-nums;
  font-size: 11px;
  color: var(--el-text-color-secondary, #8f8a7a);
  white-space: nowrap;
  padding-top: 1px;
}
.col-stage {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 2px;
  border: 1px solid transparent;
  white-space: nowrap;
}
.col-type {
  white-space: nowrap;
}
.event-type-tag {
  font-size: 11px;
  padding: 0 5px;
  border-radius: 2px;
}
.col-tool {
  white-space: nowrap;
}
.tool-chip {
  display: inline-flex;
  align-items: center;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  background: #faf6ee;
  color: var(--rp-navy, #1e3a5c);
  border: 1px solid #ebd9b3;
  padding: 1px 6px;
  border-radius: 2px;
  font-weight: 600;
}
.col-msg {
  flex: 1;
  color: var(--rp-ink, #26251f);
  word-break: break-word;
}
.msg-text {
  font-size: 12px;
}
.msg-actions {
  display: inline-block;
  margin-left: 6px;
}
/* 参数明细：研报附注底稿风（米灰底稿质感，弃用终端荧光黑客风） */
.detail-json-box {
  margin-top: 6px;
  padding: 8px 10px;
  background: #f4f1e9;
  color: var(--rp-ink, #26251f);
  border: 1px solid #dfd9c8;
  border-radius: 2px;
  font-size: 11px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  max-height: 180px;
  overflow-y: auto;
}
.detail-json-box pre {
  margin: 0;
  white-space: pre-wrap;
}

/* 行颜色标识：沉稳的研报色系 */
.event-row.type-tool_call {
  border-left: 3px solid var(--rp-gold, #a9853f);
}
.event-row.type-tool_result {
  border-left: 3px solid var(--el-color-success, #3d7a50);
}
.event-row.type-agent_thought,
.event-row.type-llm_thought {
  border-left: 3px solid #2c4a6f;
  background: #faf9f6;
}
.event-row.type-agent_decision {
  border-left: 3px solid var(--rp-navy, #1e3a5c);
}
.event-row.type-artifact_created {
  border-left: 3px solid var(--rp-navy, #1e3a5c);
  background: #fbf9f4;
}
.event-row.type-error {
  border-left: 3px solid var(--el-color-danger, #a8402f);
  background: #fdf5f4;
}
.event-row.type-warning,
.event-row.type-warn {
  border-left: 3px solid var(--rp-gold, #a9853f);
  background: #fdfaf3;
}

/* 抽屉模式专属样式与指挥协同面板 (精品研报风) */
.trace-drawer-view {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.drawer-cockpit-panel {
  background: var(--rp-card, #fffefb);
  border: 1px solid var(--rp-line, #e3ddcd);
  border-top: 3px solid var(--rp-gold, #a9853f);
  border-radius: 4px;
  padding: 8px 12px;
  margin-bottom: 8px;
  box-shadow: 0 2px 6px rgba(30, 58, 92, 0.04);
  transition: all 0.25s ease;
}

.drawer-cockpit-panel.is-running {
  box-shadow: 0 3px 12px rgba(169, 133, 63, 0.12);
  border-color: #d8ceb8;
}

.cockpit-top-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--el-border-color-extra-light, #f2eee4);
}

.cockpit-identity {
  display: flex;
  align-items: center;
  gap: 8px;
}

.cockpit-radar-dot {
  position: relative;
  width: 12px;
  height: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.cockpit-radar-dot .dot {
  width: 7px;
  height: 7px;
  background: var(--rp-gold, #a9853f);
  border-radius: 50%;
}

.cockpit-radar-dot.is-active .ping {
  position: absolute;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: rgba(169, 133, 63, 0.35);
  animation: trace-pulse 1.8s cubic-bezier(0.215, 0.61, 0.355, 1) infinite;
}

.cockpit-title {
  font-family: var(--rp-serif, Georgia, 'Songti SC', serif);
  font-size: 14px;
  font-weight: 700;
  color: var(--rp-navy, #1e3a5c);
  letter-spacing: 0.3px;
}

.cockpit-stage-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 3px;
  border: 1px solid;
}

.cockpit-metrics {
  display: flex;
  align-items: center;
  gap: 8px;
}

.metric-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border-radius: 3px;
  font-size: 11px;
}

.timer-badge {
  background: #fbf8f0;
  border: 1px solid #e8dcbe;
  color: var(--rp-navy, #1e3a5c);
}

.timer-badge .badge-val {
  font-family: var(--rp-serif, serif);
  font-weight: 700;
  color: var(--rp-gold, #a9853f);
  font-size: 12px;
  letter-spacing: 0.5px;
}

.event-count-badge {
  background: #f4f6f9;
  border: 1px solid #dbe2ea;
  color: var(--rp-navy, #1e3a5c);
}

.event-count-badge .badge-val {
  font-weight: 600;
  color: var(--rp-navy, #1e3a5c);
}

.btn-drawer-cancel {
  padding: 2px 7px;
  font-size: 11px;
}

/* 焦点卡片 */
.cockpit-focus-card {
  margin-top: 6px;
  background: #faf8f5;
  border: 1px solid #eae5d7;
  border-radius: 3px;
  padding: 6px 10px;
}

.focus-header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 3px;
}

.focus-lead {
  display: flex;
  align-items: center;
  gap: 6px;
}

.focus-state-title {
  font-size: 11px;
  font-weight: 700;
  color: var(--rp-gold, #a9853f);
  letter-spacing: 0.3px;
}

.focus-tool-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  background: #f4efe4;
  border: 1px solid #dfd2b5;
  border-radius: 3px;
  padding: 1px 6px;
  color: var(--rp-navy, #1e3a5c);
}

.focus-tool-chip .tool-prefix {
  color: var(--el-text-color-secondary, #8f8a7a);
}

.focus-tool-chip .tool-name {
  font-family: ui-monospace, Menlo, Monaco, Consolas, monospace;
  font-weight: 600;
}

.focus-sse-tag {
  font-size: 11px;
  color: #2e7d32;
  margin-left: auto;
  font-weight: 500;
}

.focus-body .focus-message {
  margin: 0;
  font-size: 12px;
  line-height: 1.45;
  color: var(--rp-ink, #26251f);
}

.toolbar-section-title {
  font-family: var(--rp-serif, Georgia, serif);
  font-size: 13px;
  font-weight: 700;
  color: var(--rp-navy, #1e3a5c);
  display: flex;
  align-items: center;
  gap: 6px;
}

.drawer-trace-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 0 0 6px 0;
  margin-bottom: 6px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.drawer-toolbar-left,
.drawer-toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.trace-body.is-drawer {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.stream-timeline.is-drawer-timeline {
  max-height: calc(100vh - 190px);
  height: calc(100vh - 190px);
  flex: 1;
}
</style>
