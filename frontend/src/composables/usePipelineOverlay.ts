import { reactive } from 'vue'
import type { StageName } from '../api/types'

/**
 * 流水线等待遮罩的全局单例状态。
 * 同步接口（POST /runs、POST /reviews）执行一个阶段可能耗时数分钟，
 * 提交方 show() 指明即将执行的阶段与动作文案，完成/失败后 hide()。
 * 支持嵌套计数（理论上单请求场景，防御性处理）。
 */
interface PipelineOverlayState {
  visible: boolean
  /** 正在执行的阶段（用于五阶段点阵高亮） */
  stage: StageName | null
  /** 触发动作文案（创建任务 / 审核通过 / 重新融合 / 修改指令重跑） */
  action: string
  startedAt: number
}

const state = reactive<PipelineOverlayState>({
  visible: false,
  stage: null,
  action: '',
  startedAt: 0,
})

let openCount = 0

export function showPipelineOverlay(stage: StageName | null, action: string): void {
  if (openCount === 0) {
    state.startedAt = Date.now()
  }
  openCount += 1
  state.visible = true
  state.stage = stage
  state.action = action
}

export function hidePipelineOverlay(): void {
  openCount = Math.max(0, openCount - 1)
  if (openCount === 0) {
    state.visible = false
    state.stage = null
    state.action = ''
  }
}

export function usePipelineOverlayState(): PipelineOverlayState {
  return state
}
