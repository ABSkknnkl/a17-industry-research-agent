<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { STAGE_LABELS, STAGE_ORDER } from '../api/types'
import { usePipelineOverlayState } from '../composables/usePipelineOverlay'

const overlay = usePipelineOverlayState()

const elapsed = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

const currentLabel = computed(() => (overlay.stage ? STAGE_LABELS[overlay.stage] : '流水线'))

const currentIndex = computed(() => (overlay.stage ? STAGE_ORDER.indexOf(overlay.stage) : -1))

const elapsedText = computed(() => {
  const total = Math.floor(elapsed.value)
  const mm = String(Math.floor(total / 60)).padStart(2, '0')
  const ss = String(total % 60).padStart(2, '0')
  return `${mm}:${ss}`
})

watch(
  () => overlay.visible,
  (visible) => {
    if (visible) {
      elapsed.value = 0
      if (timer) clearInterval(timer)
      timer = setInterval(() => {
        elapsed.value = (Date.now() - overlay.startedAt) / 1000
      }, 1000)
    } else if (timer) {
      clearInterval(timer)
      timer = null
    }
  }
)

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<script lang="ts">
export default { name: 'PipelineOverlay' }
</script>

<template>
  <Teleport to="body">
    <Transition name="po-fade">
      <div v-if="overlay.visible" class="po-mask" role="alert" aria-live="polite">
        <div class="po-card">
          <!-- 罗盘扫描动画：外环顺时针、内环逆时针、中心"研"字脉冲 -->
          <div class="compass" aria-hidden="true">
            <div class="ring ring-outer" />
            <div class="ring ring-inner" />
            <div class="sweep" />
            <span class="core">研</span>
          </div>

          <div class="po-action">{{ overlay.action || '流水线执行中' }}</div>
          <div class="po-stage">
            正在执行：<b>{{ currentLabel }}</b>
          </div>

          <!-- 五阶段点阵 -->
          <div class="po-dots">
            <template v-for="(stage, idx) in STAGE_ORDER" :key="stage">
              <div
                class="dot"
                :class="{
                  done: currentIndex > idx,
                  active: currentIndex === idx,
                  todo: currentIndex < idx || currentIndex === -1,
                }"
              >
                <span class="dot-core">{{ currentIndex > idx ? '✓' : '' }}</span>
              </div>
              <div v-if="idx < STAGE_ORDER.length - 1" class="dot-line" />
            </template>
          </div>
          <div class="po-dots-labels">
            <span
              v-for="(stage, idx) in STAGE_ORDER"
              :key="stage"
              class="dot-label"
              :class="{ on: currentIndex === idx, passed: currentIndex > idx }"
            >
              {{ STAGE_LABELS[stage] }}
            </span>
          </div>

          <div class="po-timer">已执行 {{ elapsedText }}</div>
          <div class="po-hint muted">
            同步执行可能需要数分钟，请勿关闭或刷新页面，完成后自动进入审核
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style>
.po-mask {
  position: fixed;
  inset: 0;
  z-index: 2600;
  background: rgba(246, 244, 239, 0.94);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
}
.po-fade-enter-active,
.po-fade-leave-active {
  transition: opacity 0.25s ease;
}
.po-fade-enter-from,
.po-fade-leave-to {
  opacity: 0;
}
.po-card {
  text-align: center;
  padding: 32px 48px;
}
/* ---- 罗盘 ---- */
.compass {
  position: relative;
  width: 96px;
  height: 96px;
  margin: 0 auto 20px;
}
.ring {
  position: absolute;
  border-radius: 50%;
}
.ring-outer {
  inset: 0;
  border: 3px solid transparent;
  border-top-color: var(--rp-gold);
  border-right-color: rgba(169, 133, 63, 0.35);
  animation: po-spin 1.6s linear infinite;
}
.ring-inner {
  inset: 12px;
  border: 2px solid transparent;
  border-bottom-color: var(--rp-navy);
  border-left-color: rgba(30, 58, 92, 0.3);
  animation: po-spin 2.4s linear infinite reverse;
}
.sweep {
  position: absolute;
  inset: 24px;
  border-radius: 50%;
  background: conic-gradient(
    from 0deg,
    rgba(169, 133, 63, 0.28) 0deg,
    transparent 70deg,
    transparent 360deg
  );
  animation: po-spin 3.2s linear infinite;
}
.core {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--rp-serif);
  font-size: 30px;
  font-weight: 700;
  color: var(--rp-navy);
  animation: po-pulse 1.8s ease-in-out infinite;
}
@keyframes po-spin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes po-pulse {
  0%,
  100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.12);
    opacity: 0.75;
  }
}
/* ---- 文案 ---- */
.po-action {
  font-family: var(--rp-serif);
  font-size: 17px;
  font-weight: 700;
  color: var(--rp-navy);
  letter-spacing: 2px;
}
.po-stage {
  margin-top: 6px;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.po-stage b {
  color: var(--rp-gold);
  font-weight: 700;
}
/* ---- 五阶段点阵 ---- */
.po-dots {
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 22px 0 6px;
}
.dot {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  flex-shrink: 0;
}
.dot.done {
  background: var(--rp-navy);
  color: #fff;
}
.dot.active {
  background: var(--rp-gold);
  color: #fff;
  animation: po-dot-pulse 1.4s ease-in-out infinite;
}
.dot.todo {
  border: 1.5px solid var(--el-border-color);
  background: var(--el-bg-color);
}
@keyframes po-dot-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(169, 133, 63, 0.45);
  }
  50% {
    box-shadow: 0 0 0 7px rgba(169, 133, 63, 0);
  }
}
.dot-line {
  width: 34px;
  height: 1.5px;
  background: var(--el-border-color-lighter);
}
.po-dots-labels {
  display: flex;
  justify-content: center;
  gap: 0;
}
.dot-label {
  width: 68px;
  font-size: 10.5px;
  color: var(--el-text-color-secondary);
  line-height: 1.4;
}
.dot-label.on {
  color: var(--rp-gold);
  font-weight: 700;
}
.dot-label.passed {
  color: var(--rp-navy);
}
/* ---- 计时与提示 ---- */
.po-timer {
  margin-top: 18px;
  font-size: 13px;
  color: var(--rp-navy);
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}
.po-hint {
  margin-top: 6px;
  font-size: 12px;
}
</style>
