<script setup lang="ts">
import { computed } from 'vue'
import { STAGE_LABELS, type ReportFusionData, type StageName } from '../api/types'

/** 融合检查项与交付质量评分，全部基于 report_fusion 阶段已有的 quality 字段聚合。 */
const props = defineProps<{ fusion: ReportFusionData }>()

const quality = computed(() => props.fusion.quality ?? {})

/**
 * 评分基准（分母）由后端下发，前端**不写死** 7 / 21 —— 后端调整大纲时前端自动跟随。
 * 兜底值仅用于历史 run（其 quality 缺基准字段），保证不回归。
 */
const BASELINE_FALLBACK = { chapters: 7, sections: 21 }
const expectedChapters = computed(
  () => quality.value.expected_chapter_count ?? BASELINE_FALLBACK.chapters
)
const expectedSections = computed(
  () => quality.value.expected_section_count ?? BASELINE_FALLBACK.sections
)

/** 结构/覆盖率子项评分（0-100），全部来自后端原始数值的前端聚合 */
const subScores = computed(() => {
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
    {
      label: '章节完整度',
      value: chapterScore,
      hint: `章节数 / 标准 ${expectedChapters.value} 章`,
    },
    {
      label: '结构完整度',
      value: structureScore,
      hint: `小节数 / 标准 ${expectedSections.value} 节`,
    },
    { label: '证据覆盖率', value: coverageScore, hint: '正文证据引用覆盖' },
  ]
})

/** 总评分 = 可用子项的简单平均（前端聚合口径，非后端字段） */
const overallScore = computed<number | null>(() => {
  const available = subScores.value.filter(
    (item): item is { label: string; value: number; hint: string } => item.value !== null
  )
  if (available.length === 0) return null
  return Math.round(available.reduce((sum, item) => sum + item.value, 0) / available.length)
})

const scoreColor = (value: number): string => {
  if (value >= 90) return 'var(--el-color-success)'
  if (value >= 70) return 'var(--el-color-warning)'
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
  // 阻断项与提示项一并展示。后端 consistency.warnings（如「拒绝了某段落的编辑」）
  // 原先在适配层被整段丢弃，用户只能看到一句「质量门通过」。
  const seen = new Set<string>()
  for (const text of [...(quality.value.issues ?? []), ...(quality.value.warnings ?? [])]) {
    if (text && !seen.has(text)) {
      seen.add(text)
      items.push({ text, level: 'warning' })
    }
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
        <div class="score-note muted">前端聚合口径：章节/结构/覆盖率均值</div>
      </div>
      <div class="score-bars">
        <div v-for="sub in subScores" :key="sub.label" class="score-bar-row">
          <span class="bar-label">{{ sub.label }}</span>
          <el-progress
            class="bar-track"
            :percentage="sub.value ?? 0"
            :stroke-width="8"
            :show-text="false"
            :color="sub.value === null ? 'var(--el-color-info-light-5)' : scoreColor(sub.value)"
          />
          <span class="bar-value" :class="{ muted: sub.value === null }">
            {{ sub.value === null ? '—' : `${sub.value}%` }}
          </span>
          <el-tooltip :content="sub.hint" placement="top">
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
        <!-- 交付状态：后端真实下发（ready / ready_with_limits / blocked）。
             上方 release_mode 后端从未下发，保留仅为兼容历史数据。 -->
        <el-tag v-if="fusion.delivery_status === 'ready_with_limits'" type="warning" effect="plain"
          >有限交付</el-tag
        >
        <el-tag v-else-if="fusion.delivery_status === 'blocked'" type="danger" effect="plain"
          >已阻断</el-tag
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
  grid-template-columns: 260px 1fr;
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
  font-size: 23px;
  font-weight: 700;
  line-height: 1.2;
}
.score-caption {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.score-note {
  margin-top: 2px;
  font-size: 10.5px;
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
  width: 70px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  flex-shrink: 0;
}
.bar-track {
  flex: 1;
}
.bar-value {
  width: 40px;
  text-align: right;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
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
  font-size: 13px;
  font-weight: 600;
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
  color: var(--el-color-success);
  margin-top: 4px;
}
.icon-warning {
  color: var(--el-color-warning);
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
