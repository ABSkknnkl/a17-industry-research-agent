<script setup lang="ts">
import { computed } from 'vue'
import { STAGE_LABELS, STAGE_ORDER, type StageName, type StageResult } from '../api/types'

const props = defineProps<{ stageResults: Partial<Record<string, StageResult>> }>()

interface StepItem {
  name: StageName
  title: string
  status: 'wait' | 'process' | 'finish' | 'error' | 'success'
  /** 执行小结：基于阶段已有产出聚合，只读原始字段 */
  description: string
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
          : {}
      const records = asArray<unknown>(data.source_records).length
      const clarifications = asArray<unknown>(data.collaboration_requests).length
      const parts = [`路由 ${Object.keys(plans).length} 个问题`, `采集 ${records} 条来源`]
      if (clarifications > 0) parts.push(`${clarifications} 项待澄清`)
      return parts.join(' · ')
    }
    case 'data_interpret': {
      const claims = asArray<Record<string, unknown>>(data.claims)
      const evidenceIds = new Set<string>()
      for (const claim of claims) {
        for (const id of asArray<unknown>(claim.evidence_ids)) evidenceIds.add(String(id))
      }
      const dims = asArray<unknown>(data.dimension_coverage).length
      return `${claims.length} 条结论 · ${evidenceIds.size} 条证据支撑 · 覆盖 ${dims} 个维度`
    }
    case 'chart_generate': {
      const charts = asArray<Record<string, unknown>>(data.charts)
      const ready = charts.filter((chart) => chart.status === 'ready').length
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
            if (typeof paragraph.text === 'string') words += paragraph.text.length
          }
        }
      }
      return `${chapters.length} 章 ${sections} 节 · 约 ${words.toLocaleString()} 字`
    }
    case 'report_fusion': {
      const formats = asArray<unknown>(data.formats)
      const delivery = data.delivery_status
      const parts: string[] = []
      if (formats.length > 0)
        parts.push(
          `已生成 ${formats
            .map(String)
            .map((f) => f.toUpperCase())
            .join(' / ')}`
        )
      if (typeof delivery === 'string') parts.push(`交付状态 ${delivery}`)
      return parts.length > 0 ? parts.join(' · ') : '报告融合完成'
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
    return { name, title: STAGE_LABELS[name], status, description: summarize(name, result) }
  })
})
</script>

<template>
  <el-steps :active="steps.length" align-center>
    <el-step
      v-for="step in steps"
      :key="step.name"
      :title="step.title"
      :description="step.description"
      :status="step.status"
    />
  </el-steps>
</template>
