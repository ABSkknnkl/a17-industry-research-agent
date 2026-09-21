import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { getRunEvents, subscribeRunEvents } from '../api/client'
import type { AgentTraceEvent, StageName } from '../api/types'
import { updatePipelineOverlayTrace } from './usePipelineOverlay'

export interface UseAgentTraceReturn {
  events: Ref<AgentTraceEvent[]>
  latestEvent: Ref<AgentTraceEvent | null>
  activeTool: Ref<string | null>
  isStreaming: Ref<boolean>
  loading: Ref<boolean>
  refresh: () => Promise<void>
  startStream: () => void
  stopStream: () => void
}

export function useAgentTrace(
  runIdRef: Ref<string>,
  isRunningRef?: Ref<boolean>
): UseAgentTraceReturn {
  const events = ref<AgentTraceEvent[]>([])
  const loading = ref(false)
  const isStreaming = ref(false)
  let unsubscribe: (() => void) | null = null

  const latestEvent = computed<AgentTraceEvent | null>(() => {
    if (events.value.length === 0) return null
    return events.value[events.value.length - 1]
  })

  const activeTool = computed<string | null>(() => {
    // 倒序寻找最近一个带 tool 的事件
    for (let i = events.value.length - 1; i >= 0; i--) {
      const evt = events.value[i]
      if (evt.tool) return evt.tool
    }
    return null
  })

  function appendEvent(evt: AgentTraceEvent): void {
    const exists = events.value.some((e) => e.id === evt.id)
    if (!exists) {
      events.value.push(evt)
      // 联动全屏遮罩实时动线
      updatePipelineOverlayTrace(evt.message, evt.tool ?? undefined)
    }
  }

  async function refresh(): Promise<void> {
    const runId = runIdRef.value
    if (!runId) {
      events.value = []
      return
    }
    loading.value = true
    try {
      const list = await getRunEvents(runId, 200)
      events.value = list
      if (list.length > 0) {
        const last = list[list.length - 1]
        updatePipelineOverlayTrace(last.message, last.tool ?? undefined)
      }
    } catch {
      // 容错处理
    } finally {
      loading.value = false
    }
  }

  function startStream(): void {
    stopStream()
    const runId = runIdRef.value
    if (!runId) return

    isStreaming.value = true
    unsubscribe = subscribeRunEvents(
      runId,
      (evt) => {
        appendEvent(evt)
      },
      () => {
        // SSE 出错或关闭
        isStreaming.value = false
      }
    )
  }

  function stopStream(): void {
    if (unsubscribe) {
      unsubscribe()
      unsubscribe = null
    }
    isStreaming.value = false
  }

  watch(
    runIdRef,
    async (newRunId) => {
      stopStream()
      if (newRunId) {
        await refresh()
        if (isRunningRef?.value) {
          startStream()
        }
      } else {
        events.value = []
      }
    },
    { immediate: true }
  )

  if (isRunningRef) {
    watch(isRunningRef, (running) => {
      if (running) {
        startStream()
      } else {
        stopStream()
        refresh()
      }
    })
  }

  onBeforeUnmount(() => {
    stopStream()
  })

  return {
    events,
    latestEvent,
    activeTool,
    isStreaming,
    loading,
    refresh,
    startStream,
    stopStream,
  }
}
