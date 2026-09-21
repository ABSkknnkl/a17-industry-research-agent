<script setup lang="ts">
import { computed } from 'vue'
import {
  STAGE_LABELS,
  type ReportFusionData,
  type ScoreBreakdownItem,
  type StageName,
} from '../api/types'

/** 交付质量评分：优先渲染后端确定性 100 分制；历史 run 缺字段时前端聚合兜底。 */
const props = defineProps<{ fusion: ReportFusionData }>()

const quality = computed(() => props.fusion.quality ?? {})

/** 后端维度稳定标识 → 界面中文（与 backend quality.py DIM_* 一致） */
const DIMENSION_LABELS: Record<string, string> = {
  structure: '结构完整度',
  evidence_coverage: '证据覆盖率',
  citation_consistency: '引用一致性',
  dimension_coverage: '维度覆盖',
  risk_disclosure: '风险披露',
}

const DIMENSION_ORDER = [
  'structure',
  'evidence_coverage',
  'citation_consistency',
  'dimension_coverage',
  'risk_disclosure',
]

/**
 * 评分基准（分母）由后端下发，前端**不写死** 7 / 21。
 * 兜底值仅用于历史 run（其 quality 缺基准字段）。
 */
const BASELINE_FALLBACK = { chapters: 7, sections: 21 }
const expectedChapters = computed(
  () => quality.value.expected_chapter_count ?? BASELINE_FALLBACK.chapters
)
const expectedSections = computed(
  () => quality.value.expected_section_count ?? BASELINE_FALLBACK.sections
)

/** 是否采用后端确定性总分（有 total_score 且为数字） */
const useBackendScore = computed(
  () => typeof quality.value.total_score === 'number' && !Number.isNaN(quality.value.total_score)
)

const backendThresholds = computed(() => quality.value.thresholds ?? {})
const goodThreshold = computed(
  () => (backendThresholds.value.good as number | undefined) ?? 90
)
const warnThreshold = computed(
  () => (backendThresholds.value.warn as number | undefined) ?? 70
)

/** 后端 score_breakdown → 界面行（按固定维度顺序，缺维不补假数据） */
const backendRows = computed(() => {
  const items = (quality.value.score_breakdown ?? []).filter(
    (item): item is ScoreBreakdownItem =>
      !!item && typeof item.dimension === 'string' && typeof item.score === 'number'
  )
  const byDim = new Map(items.map((item) => [item.dimension as string, item]))
  const ordered: typeof items = []
  for (const dim of DIMENSION_ORDER) {
    const hit = byDim.get(dim)
    if (hit) ordered.push(hit)
  }
  // 合约外维度放在末尾，避免静默丢分
  for (const item of items) {
    if (!DIMENSION_ORDER.includes(item.dimension as string)) ordered.push(item)
  }
  return ordered.map((item) => {
    const max = item.max_score ?? item.weight ?? 0
    const score = item.score ?? 0
    const pct = max > 0 ? Math.min(100, Math.round((score / max) * 100)) : null
    return {
      key: item.dimension as string,
      label: DIMENSION_LABELS[item.dimension as string] ?? (item.dimension as string),
      score,
      max,
      pct,
      reason: item.reason ?? '',
      hint:
        item.reason ||
        (max > 0 ? `后端评分 ${score} / ${max}` : `后端评分 ${score}`),
    }
  })
})

/** 历史 run 兜底：章节/小节/覆盖率三项（前端聚合，与旧版一致） */
const legacySubScores = computed(() => {
  const chapterCount = quality.value.chapter_count
  const sectionCount = quality.value.section_count
  const coverage = quality.value.evidence_coverage
  const chapterScore =
    typeof chapterCount === 'number'
      ? Math.min(100, Math.round((chapterCount / expectedChapters.value) * 100))
      : null
  const structureScore =
    typeof sectionCount === 'number'
      ? Math.min(100, Math.round((sectionCount / expectedSections.value) * 100))
      : null
  const coverageScore = typeof coverage === 'number' ? Math.round(coverage * 100) : null
  return [
    { label: '章节完整度', value: chapterScore, hint: `章节数 / 标准 ${expectedChapters.value} 章` },
    {
      label: '结构完整度',
      value: structureScore,
      hint: `小节数 / 标准 ${expectedSections.value} 节`,
    },
    { label: '证据覆盖率', value: coverageScore, hint: '正文证据引用覆盖' },
  ]
})

const legacyOverall = computed<number | null>(() => {
  const available = legacySubScores.value.filter(
    (item): item is { label: string; value: number; hint: string } => item.value !== null
  )
  if (available.length === 0) return null
  return Math.round(available.reduce((sum, item) => sum + item.value, 0) / available.length)
})

/** 环上总分：后端 total_score，否则前端均值兜底 */
const overallScore = computed<number | null>(() => {
  if (useBackendScore.value) return quality.value.total_score ?? null
  return legacyOverall.value
})

/** 分项：有 breakdown 用后端七维，否则用旧三项 */
const displayRows = computed(() =>
  useBackendScore.value && backendRows.value.length > 0
    ? backendRows.value.map((row) => ({
        label: row.label,
        // 进度条用相对满分比例；数值展示分数/满分
        value: row.pct,
        display: row.max > 0 ? `${row.score}/${row.max}` : String(row.score),
        hint: row.hint,
      }))
    : legacySubScores.value.map((item) => ({
        label: item.label,
        value: item.value,
        display: item.value === null ? '—' : `${item.value}%`,
        hint: item.hint,
      }))
)

const scoreSourceNote = computed(() =>
  useBackendScore.value
    ? `后端确定性评分 · 优≥${goodThreshold.value} 警≥${warnThreshold.value}`
    : '历史数据前端聚合口径：章节/结构/覆盖率均值'
)

const scoreColor = (value: number): string => {
  if (value >= goodThreshold.value) return 'var(--rp-navy)'
  if (value >= warnThreshold.value) return 'var(--rp-gold)'
  return 'var(--el-color-danger)'
}

const barColor = (value: number | null): string => {
  if (value === null) return 'var(--el-color-info-light-5)'
  // 分项条：满分红用藏青、合格用金、不足用警示色
  if (value >= 100) return 'var(--rp-navy)'
  if (value >= warnThreshold.value) return 'var(--rp-gold)'
  return 'var(--el-color-danger)'
}

/** 融合检查项：质量门结果 + 全部 issues 逐项展示 */
const checkItems = computed(() => {
  const items: Array<{ text: string; level: 'success' | 'warning' | 'danger' }> = []
  if (quality.value.passed === true) {
    items.push({ text: '融合质量门通过（无阻断问题）', level: 'success' })
  } else if (quality.value.passed === false) {
    items.push({ text: '融合质量门未通过（存在阻断问题）', level: 'danger' })
  }
  for (const issue of quality.value.issues ?? []) {
    items.push({ text: issue, level: 'warning' })
  }
  return items
})

const sourceRevisions = computed(() =>
  (props.fusion.source_revisions ?? []).map((item) => ({
    stage: item.stage ? (STAGE_LABELS[item.stage as StageName] ?? item.stage) : '',
    revision: item.revision,
  }))
)
</script>

<template>
  <div class="quality-panel">
    <div class="quality-left">
      <div v-if="overallScore !== null" class="score-ring">
        <el-progress
          type="dashboard"
          :percentage="overallScore"
          :width="104"
          :stroke-width="9"
          :color="scoreColor(overallScore)"
        >
          <template #default>
            <div class="score-value" :style="{ color: scoreColor(overallScore) }">
              {{ overallScore }}
            </div>
            <div class="score-caption">交付质量评分</div>
          </template>
        </el-progress>
        <div class="score-note muted">{{ scoreSourceNote }}</div>
      </div>
      <div class="score-bars">
        <div v-for="row in displayRows" :key="row.label" class="score-bar-row">
          <span class="bar-label">{{ row.label }}</span>
          <el-progress
            class="bar-track"
            :percentage="row.value ?? 0"
            :stroke-width="8"
            :show-text="false"
            :color="barColor(row.value)"
          />
          <span class="bar-value" :class="{ muted: row.value === null }">
            {{ row.display }}
          </span>
          <el-tooltip :content="row.hint" placement="top">
            <el-icon class="bar-help"><QuestionFilled /></el-icon>
          </el-tooltip>
        </div>
      </div>
    </div>

    <div class="quality-right">
      <div class="quality-meta">
        <el-tag v-if="fusion.release_mode === 'draft_with_warnings'" type="warning" effect="plain"
          >草稿模式</el-tag
        >
        <el-tag v-if="fusion.release_mode === 'formal'" type="success" effect="plain"
          >正式模式</el-tag
        >
        <el-tag
          v-for="format in fusion.formats ?? []"
          :key="format"
          effect="plain"
          type="info"
          size="small"
        >
          {{ format.toUpperCase() }}
        </el-tag>
      </div>

      <h4 class="check-title">融合检查项（{{ checkItems.length }}）</h4>
      <div v-if="checkItems.length === 0" class="muted">暂无检查项输出</div>
      <ul v-else class="check-list">
        <li v-for="(item, idx) in checkItems" :key="idx" class="check-item">
          <el-icon :class="`icon-${item.level}`">
            <CircleCheckFilled v-if="item.level === 'success'" />
            <WarningFilled v-else-if="item.level === 'warning'" />
            <CircleCloseFilled v-else />
          </el-icon>
          <span>{{ item.text }}</span>
        </li>
      </ul>

      <div v-if="sourceRevisions.length > 0" class="source-line">
        <span class="muted">来源版本：</span>
        <el-tag
          v-for="(source, idx) in sourceRevisions"
          :key="idx"
          size="small"
          effect="plain"
          style="margin-right: 6px"
        >
          {{ source.stage }} r{{ source.revision ?? '?' }}
        </el-tag>
      </div>

      <template v-if="(fusion.unresolved_risks ?? []).length > 0">
        <h4 class="check-title">未消除风险（{{ (fusion.unresolved_risks ?? []).length }}）</h4>
        <ul class="check-list">
          <li v-for="(risk, idx) in fusion.unresolved_risks" :key="idx" class="check-item">
            <el-icon class="icon-warning"><WarningFilled /></el-icon>
            <span>{{ risk }}</span>
          </li>
        </ul>
      </template>
    </div>
  </div>
</template>

<style scoped>
.quality-panel {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 18px;
  align-items: start;
}
.quality-left {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.score-ring {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.score-value {
  font-family: var(--rp-serif);
  font-size: 23px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--rp-navy);
}
.score-caption {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.score-note {
  margin-top: 2px;
  font-size: 10.5px;
  text-align: center;
  max-width: 240px;
  line-height: 1.45;
}
.score-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.score-bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.bar-label {
  width: 72px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  flex-shrink: 0;
}
.bar-track {
  flex: 1;
}
.bar-value {
  width: 48px;
  text-align: right;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  font-family: var(--rp-serif);
  color: var(--rp-navy);
}
.bar-value.muted {
  font-family: inherit;
  color: var(--el-text-color-secondary);
}
.bar-help {
  color: var(--el-text-color-placeholder);
  cursor: help;
}
.quality-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 4px;
}
.check-title {
  margin: 12px 0 6px;
  font-family: var(--rp-serif);
  font-size: 13px;
  font-weight: 600;
  color: var(--rp-navy);
  letter-spacing: 0.5px;
}
.check-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.check-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 13px;
  line-height: 1.7;
}
.icon-success {
  color: var(--rp-navy);
  margin-top: 4px;
}
.icon-warning {
  color: var(--rp-gold);
  margin-top: 4px;
}
.icon-danger {
  color: var(--el-color-danger);
  margin-top: 4px;
}
.source-line {
  margin-top: 10px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  font-size: 12px;
}
@media (max-width: 1100px) {
  .quality-panel {
    grid-template-columns: 1fr;
  }
}
</style>
