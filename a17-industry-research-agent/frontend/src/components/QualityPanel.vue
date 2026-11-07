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

/** 结构/覆盖率/数据合规子项评分（0-100），全部来自后端原始数值与审计质检的前端聚合 */
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

  const list: Array<{ label: string; value: number | null; hint: string; weight: number }> = [
    {
      label: '章节完整度',
      value: chapterScore,
      hint: `章节数 / 标准 ${expectedChapters.value} 章`,
      weight: 0.1,
    },
    {
      label: '结构完整度',
      value: structureScore,
      hint: `小节数 / 标准 ${expectedSections.value} 节`,
      weight: 0.1,
    },
    {
      label: '核心论据引用率',
      value: coverageScore,
      hint: '已引用的核心论据 ID / 核心论据 ID 总数；不代表事实准确率',
      weight: 0.4,
    },
  ]

  return list
})

const scoreColor = (value: number): string => {
  if (value >= 90) return 'var(--el-color-success)'
  if (value >= 70) return 'var(--el-color-warning)'
  return 'var(--el-color-danger)'
}

/** 交付质检与投研合规审计项：质量门结果 + 防幻觉拦截亮点 + 投研边界合规披露 */
const checkItems = computed(() => {
  const items: Array<{ text: string; level: 'success' | 'info' | 'warning' | 'danger' }> = []
  if (quality.value.passed === true) {
    items.push({
      text: props.fusion.validation_version
        ? '本轮正式质量门禁通过；仍需结合原始披露审阅。'
        : '历史检查记录为通过；尚未按当前规则复验。',
      level: 'success',
    })
  } else if (quality.value.passed === false) {
    items.push({ text: '融合质量门未通过（存在阻断问题）', level: 'danger' })
  }

  const rawIssues = quality.value.issues ?? []
  const deduplicated: string[] = []
  let rejectedCount = 0

  for (const iss of rawIssues) {
    const s = String(iss).trim()
    if (!s) continue
    if (s.startsWith('拒绝了 P-') && s.includes('的编辑')) {
      rejectedCount++
      continue
    }
    const guardMatch = s.match(/(?:审校防幻觉拦截|已拦截)\D*(\d+)\D*处/)
    if (guardMatch) {
      rejectedCount = Math.max(rejectedCount, Number(guardMatch[1]) || 1)
      continue
    }
    let isSubsumed = false
    for (let i = 0; i < deduplicated.length; i++) {
      const existing = deduplicated[i]
      if (s === existing) {
        isSubsumed = true
        break
      }
      if (existing.startsWith(s) || (s.length >= 15 && existing.includes(s))) {
        isSubsumed = true
        break
      }
      if (s.startsWith(existing) || (existing.length >= 15 && s.includes(existing))) {
        deduplicated[i] = s
        isSubsumed = true
        break
      }
    }
    if (!isSubsumed) {
      deduplicated.push(s)
    }
  }

  // 1. 事实合规护栏（以绿色成功标呈现：核心安全壁垒）
  if (rejectedCount > 0) {
    items.push({
      text: `已拦截 ${rejectedCount} 处未获证据授权的编辑；这不证明其余断言全部正确。`,
      level: 'success',
    })
  }

  // 2. 投研口径与合规边界披露（以蓝色 info 标呈现：对标中金/高盛投研报告标准附注与研究边界）
  for (const issue of deduplicated) {
    let displayText = issue
    let level: 'info' | 'warning' | 'danger' = 'info'

    if (
      issue.includes('阻断') ||
      issue.includes('致命') ||
      issue.toLowerCase().includes('failed')
    ) {
      level = 'danger'
      displayText = `【阻断问题】${issue}`
    } else if (issue.includes('冲突') || issue.includes('矛盾') || issue.includes('不一致')) {
      level = 'warning'
      displayText = `【数据核对提示】${issue}`
    } else {
      displayText = issue
    }

    items.push({ text: displayText, level })
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
      <p class="muted">结构与引用检查，不代表事实准确率。</p>
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

      <h4 class="check-title">交付质检与投研合规审计（{{ checkItems.length }}）</h4>
      <div v-if="checkItems.length === 0" class="muted">暂无审计项输出</div>
      <ul v-else class="check-list">
        <li v-for="(item, idx) in checkItems" :key="idx" class="check-item">
          <el-icon :class="`icon-${item.level}`">
            <CircleCheckFilled v-if="item.level === 'success'" />
            <InfoFilled v-else-if="item.level === 'info'" />
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
.icon-info {
  color: var(--el-color-primary);
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
