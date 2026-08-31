<script setup lang="ts">
import { computed } from 'vue'
import type { ChapterDraftLoose, ReportFusionData } from '../api/types'

/** 报告封面与目录摘要预览：封面取 report_fusion 字段，目录取 chapter_write 章节（均为已有产出，前端聚合）。 */
const props = defineProps<{
  fusion: ReportFusionData | null
  chapters: ChapterDraftLoose[]
}>()

const coverTitle = computed(() => props.fusion?.title ?? '报告尚未生成')

const depthLabel = computed(() => {
  return props.fusion?.report_depth ?? ''
})

function formatTime(value: string | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN')
}
</script>

<template>
  <div class="report-preview">
    <!-- 封面 -->
    <div class="cover">
      <div class="cover-band" />
      <div class="cover-body">
        <div class="cover-kicker">行业研究报告</div>
        <h3 class="cover-title">{{ coverTitle }}</h3>
        <div v-if="fusion?.industry_topic" class="cover-topic">
          研究主题：{{ fusion.industry_topic }}
        </div>
        <div class="cover-meta">
          <span>研究时点 {{ fusion?.research_as_of ?? '—' }}</span>
          <span v-if="fusion?.generated_at">生成于 {{ formatTime(fusion.generated_at) }}</span>
          <span v-if="depthLabel">深度 {{ depthLabel }}</span>
        </div>
        <div class="cover-tags">
          <el-tag v-if="fusion?.delivery_status === 'ready'" type="success" size="small">
            可正式交付
          </el-tag>
          <el-tag
            v-else-if="fusion?.delivery_status === 'ready_with_limits'"
            type="warning"
            size="small"
          >
            附限制交付
          </el-tag>
          <el-tag v-else-if="fusion?.delivery_status === 'blocked'" type="danger" size="small">
            交付受阻
          </el-tag>
          <el-tag
            v-if="fusion?.release_mode === 'draft_with_warnings'"
            type="warning"
            size="small"
            effect="plain"
          >
            草稿
          </el-tag>
          <el-tag
            v-for="format in fusion?.formats ?? []"
            :key="format"
            size="small"
            effect="plain"
            type="info"
          >
            {{ format.toUpperCase() }}
          </el-tag>
        </div>
      </div>
    </div>

    <!-- 目录摘要 -->
    <div class="toc">
      <div class="toc-title">目录摘要（{{ chapters.length }} 章）</div>
      <div v-if="chapters.length === 0" class="muted toc-empty">章节撰写完成后展示目录</div>
      <ol v-else class="toc-list">
        <li v-for="(chapter, idx) in chapters" :key="chapter.chapter_id ?? idx" class="toc-chapter">
          <div class="toc-chapter-title">
            <span class="toc-index">{{ String(idx + 1).padStart(2, '0') }}</span>
            <span>{{ chapter.title ?? '未命名章节' }}</span>
          </div>
          <div v-if="chapter.summary" class="toc-summary muted">{{ chapter.summary }}</div>
          <ol v-if="(chapter.sections ?? []).length > 0" class="toc-sections">
            <li
              v-for="section in chapter.sections"
              :key="section.section_id ?? section.title"
              class="toc-section"
            >
              {{ section.section_id }} {{ section.title }}
            </li>
          </ol>
        </li>
      </ol>
    </div>
  </div>
</template>

<style scoped>
.report-preview {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
/* 研报封面：纸面底 + 藏青/金双条 + 双线框 */
.cover {
  border: 1px solid var(--el-border-color);
  outline: 3px double var(--el-color-primary);
  outline-offset: -6px;
  border-radius: 3px;
  overflow: hidden;
  background: #fbf9f4;
}
.cover-band {
  height: 4px;
  background: var(--rp-navy);
  border-bottom: 2px solid var(--rp-gold);
}
.cover-body {
  padding: 18px 16px 14px;
}
.cover-kicker {
  font-size: 11px;
  letter-spacing: 6px;
  color: var(--rp-gold);
  font-weight: 600;
}
.cover-title {
  margin: 8px 0 6px;
  font-family: var(--rp-serif);
  font-size: 17px;
  line-height: 1.5;
  letter-spacing: 0.5px;
  color: var(--rp-navy);
}
.cover-topic {
  font-size: 12.5px;
  color: var(--el-text-color-regular);
}
.cover-meta {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 11.5px;
  color: var(--el-text-color-secondary);
}
.cover-tags {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.toc-title {
  font-family: var(--rp-serif);
  font-size: 13.5px;
  font-weight: 700;
  color: var(--rp-navy);
  letter-spacing: 1px;
  margin-bottom: 6px;
  padding-bottom: 4px;
  border-bottom: 2px solid var(--rp-navy);
}
.toc-empty {
  font-size: 12px;
}
.toc-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.toc-chapter {
  padding: 6px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}
.toc-chapter:last-child {
  border-bottom: none;
}
.toc-chapter-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.toc-index {
  color: var(--rp-gold);
  font-weight: 700;
}
.toc-summary {
  margin: 3px 0 0 28px;
  font-size: 11.5px;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.toc-sections {
  margin: 3px 0 0 28px;
  padding: 0;
  list-style: none;
}
.toc-section {
  font-size: 11.5px;
  color: var(--el-text-color-secondary);
  line-height: 1.7;
}
</style>
