<script setup lang="ts">
import { computed } from 'vue'
import type { StageName } from '../api/types'

const props = defineProps<{ stage: StageName; data: Record<string, unknown> }>()

interface MetricItem {
  label: string
  value: string
  hint?: string
  tone?: 'primary' | 'success' | 'warning' | 'info'
}

const d = computed(() => props.data)

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : []
}

function countOf(key: string): number {
  return asArray<unknown>(d.value[key]).length
}

const intentPlanCount = computed(() => {
  const routing = d.value.intent_routing as Record<string, unknown> | undefined
  const plans = routing && typeof routing === 'object' ? routing.plans : undefined
  return plans && typeof plans === 'object' ? Object.keys(plans).length : 0
})

/** data_interpret：结论引用的证据去重数量 */
const evidenceCount = computed(() => {
  const claims = asArray<Record<string, unknown>>(d.value.claims)
  const ids = new Set<string>()
  for (const claim of claims) {
    for (const id of asArray<unknown>(claim.evidence_ids)) ids.add(String(id))
  }
  return ids.size
})

/** chapter_write：小节数与正文字数（按段落文本长度聚合） */
const chapterStats = computed(() => {
  const chapters = asArray<Record<string, unknown>>(d.value.chapters ?? d.value.sections)
  let sectionCount = 0
  let words = 0
  for (const chapter of chapters) {
    const sections = asArray<Record<string, unknown>>(chapter.sections)
    sectionCount += sections.length
    for (const section of sections) {
      for (const paragraph of asArray<Record<string, unknown>>(section.paragraphs)) {
        const text = paragraph.text
        if (typeof text === 'string') words += text.length
      }
    }
  }
  return { chapters: chapters.length, sections: sectionCount, words }
})

/** report_fusion：产物总大小（manifest 提供 size_bytes） */
const fusionStats = computed(() => {
  const entries = asArray<Record<string, unknown>>(d.value.artifacts)
  let totalBytes = 0
  for (const entry of entries) {
    const size = entry.size_bytes
    if (typeof size === 'number') totalBytes += size
  }
  const quality = d.value.quality as Record<string, unknown> | undefined
  return { artifactCount: entries.length, totalBytes, quality }
})

function humanSize(bytes: number): string {
  if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

function coveragePercent(): string {
  const quality = fusionStats.value.quality
  const coverage = quality?.evidence_coverage
  if (typeof coverage !== 'number') return '—'
  return `${Math.round(coverage * 100)}%`
}

const metrics = computed<MetricItem[]>(() => {
  switch (props.stage) {
    case 'data_fetch':
      return [
        {
          label: '研究问题',
          value: String(intentPlanCount.value),
          hint: '已分解的意图计划数',
          tone: 'primary',
        },
        {
          label: '采集来源',
          value: String(countOf('source_records')),
          hint: '检索到的来源记录',
          tone: 'success',
        },
        {
          label: '待澄清',
          value: String(countOf('collaboration_requests')),
          hint: '智能体发起的澄清请求',
          tone: countOf('collaboration_requests') > 0 ? 'warning' : 'info',
        },
      ]
    case 'data_interpret':
      return [
        {
          label: '结论主张',
          value: String(countOf('claims')),
          hint: '分析产出的核心结论',
          tone: 'primary',
        },
        {
          label: '引用证据',
          value: String(evidenceCount.value),
          hint: '结论引用的去重证据数',
          tone: 'success',
        },
        {
          label: '覆盖维度',
          value: String(countOf('dimension_coverage')),
          hint: '分析覆盖的维度',
          tone: 'info',
        },
        {
          label: '风险提示',
          value: String(countOf('risks')),
          hint: '识别出的风险',
          tone: countOf('risks') > 0 ? 'warning' : 'info',
        },
      ]
    case 'chart_generate':
      return [
        {
          label: '图表候选',
          value: String(countOf('charts')),
          hint: '规划生成的图表数',
          tone: 'primary',
        },
        {
          label: '图表规格',
          value: String(countOf('chart_specs')),
          hint: '图表规格定义数',
          tone: 'info',
        },
      ]
    case 'chapter_write':
      return [
        {
          label: '章节',
          value: String(chapterStats.value.chapters),
          hint: '撰写完成的章节',
          tone: 'primary',
        },
        {
          label: '小节',
          value: String(chapterStats.value.sections),
          hint: '章节内小节总数',
          tone: 'primary',
        },
        {
          label: '正文字数',
          value: chapterStats.value.words.toLocaleString(),
          hint: '段落文本长度合计',
          tone: 'success',
        },
      ]
    case 'report_fusion': {
      const quality = fusionStats.value.quality as Record<string, unknown> | undefined
      return [
        {
          label: '章节 / 小节',
          value: `${quality?.chapter_count ?? '—'} / ${quality?.section_count ?? '—'}`,
          hint: '报告结构（标准 7 章 21 节）',
          tone: 'primary',
        },
        {
          label: '嵌入图表',
          value: String(quality?.included_chart_count ?? countOf('included_chart_ids') ?? '—'),
          hint: '最终嵌入报告的图表',
          tone: 'primary',
        },
        {
          label: '证据覆盖率',
          value: coveragePercent(),
          hint: '正文证据引用覆盖率',
          tone: 'success',
        },
        {
          label: '交付产物',
          value: `${fusionStats.value.artifactCount} 个 · ${humanSize(fusionStats.value.totalBytes)}`,
          hint: '报告文件总大小',
          tone: 'info',
        },
      ]
    }
    default:
      return []
  }
})
</script>

<template>
  <div v-if="metrics.length > 0" class="metric-cards">
    <div
      v-for="metric in metrics"
      :key="metric.label"
      class="metric-card"
      :class="`tone-${metric.tone ?? 'info'}`"
    >
      <div class="metric-value">{{ metric.value }}</div>
      <div class="metric-label">{{ metric.label }}</div>
      <div v-if="metric.hint" class="metric-hint">{{ metric.hint }}</div>
    </div>
  </div>
</template>

<style scoped>
.metric-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 8px;
}
.metric-card {
  padding: 8px 12px;
  border-radius: 3px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  position: relative;
  overflow: hidden;
}
.metric-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 2px;
}
.tone-primary::before {
  background: var(--rp-navy);
}
.tone-success::before {
  background: var(--el-color-success);
}
.tone-warning::before {
  background: var(--rp-gold);
}
.tone-info::before {
  background: var(--el-color-info);
}
.metric-value {
  font-size: 19px;
  font-weight: 700;
  line-height: 1.3;
  color: var(--rp-navy);
}
.metric-label {
  margin-top: 1px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.3px;
  color: var(--el-text-color-regular);
}
.metric-hint {
  margin-top: 1px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
</style>
