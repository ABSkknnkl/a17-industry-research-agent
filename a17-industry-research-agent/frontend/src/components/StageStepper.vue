<script setup lang="ts">
import { computed } from 'vue'
import { isReportSignoffOnHold } from '../api/reportGate'
import { showStageError } from '../api/stageStatus'
import { STAGE_LABELS, STAGE_ORDER, type StageName, type StageResult } from '../api/types'

const props = defineProps<{
  stageResults: Partial<Record<string, StageResult>>
  selectedStage?: StageName | null
  finalReportReady?: boolean
  durationSeconds?: Partial<Record<StageName, number>>
}>()

const emit = defineEmits<{ (e: 'select', stage: StageName): void }>()

interface StepItem {
  name: StageName
  title: string
  status: 'wait' | 'process' | 'finish' | 'error' | 'success'
  /** 执行小结：基于阶段已有产出聚合，只读原始字段 */
  description: string
  elapsed?: string
  modelCalls?: number
  clickable: boolean
}

const d = (result: StageResult): Record<string, unknown> => result.data ?? {}

const asArray = <T,>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : [])

function summarize(name: StageName, result: StageResult | undefined): string {
  if (!result) return '待执行'
  if (isReportSignoffOnHold(result)) return '正式签发暂缓'
  if (result.status === 'running') return '正在执行…'
  if (result.status === 'pending') return '待执行'
  if (result.error && ['approved', 'completed'].includes(result.status) && name !== 'chapter_write')
    return '已通过，存在质量缺口'
  if (result.status === 'waiting_review' && result.error) return '待审核，需处理问题'
  if (showStageError(result)) return '有异常，查看阶段详情'
  const data = d(result)
  switch (name) {
    case 'data_fetch': {
      const routing = data.intent_routing as Record<string, unknown> | undefined
      const plans =
        routing && typeof routing === 'object' && routing.plans instanceof Object
          ? (routing.plans as Record<string, unknown>)
          : ((data.queries as Record<string, unknown> | unknown[]) ?? {})
      const plansCount = Array.isArray(plans) ? plans.length : Object.keys(plans).length
      const records =
        (typeof data.total_records === 'number' ? data.total_records : null) ??
        (typeof data.evidence_count === 'number' ? data.evidence_count : null) ??
        asArray<unknown>(data.source_records).length
      const clarifications = asArray<unknown>(
        data.collaboration_requests ?? data.intent_clarifications
      ).length
      const liveFetch = data.live_fetch as Record<string, unknown> | undefined
      const liveCount = liveFetch?.live_observation_count
      const supplements = liveFetch?.archive_supplement_count
      const parts = [
        typeof liveCount === 'number' ? `同花顺 ${liveCount} 条` : `采集 ${records} 条来源`,
      ]
      if (typeof supplements === 'number' && supplements > 0) {
        parts.push(`核验补齐 ${supplements} 条`)
      }
      if (plansCount > 0) parts.unshift(`分解 ${plansCount} 个问题`)
      if (clarifications > 0) parts.push(`${clarifications} 项待澄清`)
      return parts.join(' · ')
    }
    case 'data_interpret': {
      const items = asArray<Record<string, unknown>>(
        data.claims ?? data.insights ?? data.knowledge_facts
      )
      const evidenceIds = new Set<string>()
      for (const item of items) {
        for (const id of asArray<unknown>(item.evidence_ids ?? item.evidence_record_ids)) {
          evidenceIds.add(String(id))
        }
      }
      const dims = asArray<{ status?: string }>(data.dimension_coverage).filter(
        (dimension) => dimension.status === 'covered'
      ).length
      const conclCount = items.length || asArray<unknown>(data.knowledge_facts).length
      return `${conclCount} 条结论 · ${evidenceIds.size} 条证据支撑 · 覆盖 ${dims} 个维度`
    }
    case 'chart_generate': {
      const charts = asArray<Record<string, unknown>>(data.charts ?? data.chart_specs)
      const ready = charts.filter(
        (chart) => chart.status === 'ready' || (!chart.status && chart.svg_uri)
      ).length
      const label = ready > 0 ? `${ready}/${charts.length} 张就绪` : `${charts.length} 张图表`
      return label
    }
    case 'chapter_write': {
      const chapters = asArray<Record<string, unknown>>(data.chapters ?? data.sections)
      let sections = 0
      let words = 0
      for (const chapter of chapters) {
        const chapterSections = asArray<Record<string, unknown>>(chapter.sections)
        sections += chapterSections.length
        for (const section of chapterSections) {
          for (const paragraph of asArray<Record<string, unknown>>(section.paragraphs)) {
            let pText = ''
            if (typeof paragraph.text === 'string') {
              pText = paragraph.text
            } else if (typeof paragraph.text === 'object' && paragraph.text !== null) {
              const pt = paragraph.text as Record<string, unknown>
              if (typeof pt.text === 'string') pText = pt.text
            } else if (typeof paragraph.content === 'string') {
              pText = paragraph.content
            }
            words += pText.length
          }
        }
      }
      const count = `${chapters.length} 章 ${sections} 节`
      if (result.error && ['approved', 'completed'].includes(result.status)) {
        if (!chapters.length) return '已完成，质量待复核'
        if (props.finalReportReady) return `${count} · 终审核验通过`
        return `${count} · 待终审复核`
      }
      return `${count} · 约 ${words.toLocaleString()} 字`
    }
    case 'report_fusion': {
      const formats = asArray<unknown>(data.formats)
      if (formats.length === 0) return '报告融合完成'
      const labels = formats
        .map(String)
        .map((f) => f.toUpperCase())
        .join(' / ')
      return `已生成 ${labels}`
    }
    default:
      return ''
  }
}

const steps = computed<StepItem[]>(() => {
  return STAGE_ORDER.map((name) => {
    const result = props.stageResults[name]
    let status: StepItem['status'] = 'wait'
    if (result) {
      switch (result.status) {
        case 'running':
        case 'waiting_review':
          status = 'process'
          break
        case 'approved':
        case 'completed':
          status = 'success'
          break
        case 'failed':
        case 'rejected':
        case 'cancelled':
          status = 'error'
          break
        default:
          status = 'wait'
      }
    }
    const duration = props.durationSeconds?.[name]
    const elapsed =
      status === 'success' && duration !== undefined
        ? duration < 1
          ? '用时不到 1 秒'
          : `用时 ${duration.toFixed(1)} 秒`
        : undefined
    const modelExecution = result?.data?.model_execution as
      { successful_requests?: number } | undefined
    const modelCalls = modelExecution?.successful_requests
    const clickable = Boolean(result) && result?.status !== 'pending'
    return {
      name,
      title: STAGE_LABELS[name],
      status,
      description: summarize(name, result),
      elapsed,
      modelCalls,
      clickable,
    }
  })
})

function onStepClick(step: StepItem): void {
  if (!step.clickable) return
  emit('select', step.name)
}
</script>

<template>
  <el-steps :active="steps.length" align-center class="stage-steps">
    <el-step
      v-for="step in steps"
      :key="step.name"
      :status="step.status"
      :class="{
        'step-clickable': step.clickable,
        'step-selected': selectedStage === step.name,
      }"
      :data-testid="`stage-step-${step.name}`"
      @click="onStepClick(step)"
    >
      <template #title>
        <button
          v-if="step.clickable"
          type="button"
          class="step-button"
          :aria-pressed="selectedStage === step.name"
          @click.stop="onStepClick(step)"
        >
          {{ step.title }}
        </button>
        <span v-else>{{ step.title }}</span>
      </template>
      <template #description>
        <div>{{ step.description }}</div>
        <div v-if="step.elapsed || step.modelCalls" class="step-elapsed">
          <span v-if="step.elapsed">{{ step.elapsed }}</span>
          <span v-if="step.elapsed && step.modelCalls"> · </span>
          <span v-if="step.modelCalls">模型响应 {{ step.modelCalls }} 次</span>
        </div>
      </template>
    </el-step>
  </el-steps>
</template>

<style scoped>
.step-elapsed {
  font-variant-numeric: tabular-nums;
}

.step-clickable {
  cursor: pointer;
}
.step-button {
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  padding: 0 2px;
  cursor: pointer;
}
.step-button:focus-visible {
  outline: 2px solid var(--rp-navy);
  outline-offset: 2px;
}
.stage-steps :deep(.el-step__description) {
  overflow-wrap: anywhere;
}
.step-clickable :deep(.el-step__title) {
  transition: color 0.15s;
}
.step-clickable:hover :deep(.el-step__title) {
  color: var(--rp-gold);
}
.step-selected :deep(.el-step__title) {
  color: var(--rp-navy);
  font-weight: 700;
}
.step-selected :deep(.el-step__head.is-success .el-step__icon) {
  background: var(--rp-gold);
  border-color: var(--rp-gold);
}
@media (max-width: 600px) {
  .stage-steps :deep(.el-step__title) {
    font-size: 12px;
    line-height: 1.5;
    margin-top: 4px;
  }
  .stage-steps :deep(.el-step__description) {
    display: none;
  }
}
</style>
