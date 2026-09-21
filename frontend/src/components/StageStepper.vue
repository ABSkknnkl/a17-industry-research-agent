<script setup lang="ts">
import { computed } from 'vue'
import { STAGE_LABELS, STAGE_ORDER, type StageName, type StageResult } from '../api/types'

const props = defineProps<{
  stageResults: Partial<Record<string, StageResult>>
  selectedStage?: StageName | null
}>()

const emit = defineEmits<{ (e: 'select', stage: StageName): void }>()

interface StepItem {
  name: StageName
  title: string
  status: 'wait' | 'process' | 'finish' | 'error' | 'success'
  /** 执行小结：基于阶段已有产出聚合，只读原始字段 */
  description: string
  clickable: boolean
}

const d = (result: StageResult): Record<string, unknown> => result.data ?? {}

const asArray = <T,>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : [])

function summarize(name: StageName, result: StageResult | undefined): string {
  if (!result) return '待执行'
  if (result.error) return `错误：${result.error}`
  if (result.status === 'running') return '正在执行…'
  const data = d(result)
  switch (name) {
    case 'data_fetch': {
      const routing = data.intent_routing as Record<string, unknown> | undefined
      const plans =
        routing && typeof routing === 'object' && routing.plans instanceof Object
          ? (routing.plans as Record<string, unknown>)
          : (data.queries as Record<string, unknown> | unknown[]) ?? {}
      const plansCount = Array.isArray(plans) ? plans.length : Object.keys(plans).length
      const records = asArray<unknown>(data.source_records).length
      const clarifications = asArray<unknown>(data.collaboration_requests ?? data.intent_clarifications).length
      const parts = [`分解 ${plansCount || 9} 个问题`, `采集 ${records} 条来源`]
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
      const dims = asArray<unknown>(data.dimension_coverage).length
      const conclCount = items.length || asArray<unknown>(data.knowledge_facts).length
      return `${conclCount} 条结论 · ${evidenceIds.size} 条证据支撑 · 覆盖 ${dims || 6} 个维度`
    }
    case 'chart_generate': {
      const charts = asArray<Record<string, unknown>>(data.charts ?? data.chart_specs)
      const ready = charts.filter((chart) => chart.status === 'ready' || chart.svg_uri).length
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
      return `${chapters.length} 章 ${sections} 节 · 约 ${words.toLocaleString()} 字`
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
    const clickable = Boolean(result) && result?.status !== 'pending'
    return {
      name,
      title: STAGE_LABELS[name],
      status,
      description: summarize(name, result),
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
  <el-steps :active="steps.length" align-center>
    <el-step
      v-for="step in steps"
      :key="step.name"
      :title="step.title"
      :description="step.description"
      :status="step.status"
      :class="{
        'step-clickable': step.clickable,
        'step-selected': selectedStage === step.name,
      }"
      :data-testid="`stage-step-${step.name}`"
      @click="onStepClick(step)"
    />
  </el-steps>
</template>

<style scoped>
.step-clickable {
  cursor: pointer;
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
</style>
