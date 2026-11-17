import { onMounted, onUnmounted, ref, type Ref } from 'vue'
import { getHealth } from '../api/client'

/**
 * 后端健康探测（B43 / 前端 A1）。
 *
 * 顶栏的「引擎就绪」必须反映真实状态：`/health` 请求成功且 `agents_ready !== false`
 * 才算在线，请求失败即离线。此前 App.vue 写死了绿色 tag，后端挂掉也会显示就绪，
 * 与系统「状态不伪造」的原则冲突。
 */
export type HealthState = 'checking' | 'online' | 'offline'

export interface HealthCheck {
  state: Ref<HealthState>
  model: Ref<string>
  check: () => Promise<void>
}

export function useHealthCheck(intervalMs = 30_000): HealthCheck {
  const state = ref<HealthState>('checking')
  const model = ref<string>('')
  let timer: ReturnType<typeof setInterval> | null = null
  let disposed = false

  async function check(): Promise<void> {
    try {
      const data = await getHealth()
      if (disposed) return
      // 指纹校验：只有本服务会返回 agents_ready=true。
      // 端口被别的服务占用时（例如本地模型网关也监听 8000），HTTP 200 不代表引擎可用，
      // 必须判定为 offline，否则又会退回「假就绪」。
      state.value = data?.agents_ready === true ? 'online' : 'offline'
      model.value = data?.agents_ready === true ? data?.llm_model?.trim() || '' : ''
    } catch {
      if (disposed) return
      state.value = 'offline'
    }
  }

  onMounted(() => {
    void check()
    timer = setInterval(() => void check(), intervalMs)
  })

  onUnmounted(() => {
    disposed = true
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  })

  return { state, model, check }
}
