<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Download, ArrowDown } from '@element-plus/icons-vue'
import { downloadArtifact, triggerBlobDownload } from '../api/client'
import type { ChapterDraftLoose, DownloadableArtifact, ReportFusionData } from '../api/types'

/**
 * 阶段五「最终报告预览」卡片。
 *
 * 设计目标（用户反馈驱动）：
 * 1. 直观呈现报告整体样式 —— 用**缩放 iframe 渲染真实的融合 HTML**，
 *    看到的就是成品本身，而不是文字描述或静态封面示意图；
 * 2. 包含目录结构 —— 右侧列出章节与小节数，点击可直达该章；
 * 3. 明确引导 —— 底部常驻一句「点击即可查看最终成果」+ 主按钮。
 *
 * 数据来源：全部取自 fusion（report_fusion 阶段 data），无需父级另传字段。
 * 缩略图取数：fusion.artifacts 里的 report_html → blob → iframe（sandbox="" 最严格隔离）。
 * 报告为纯静态 HTML（无脚本、无外链），故连 allow-scripts 都不需要。
 */

const props = defineProps<{
  fusion: ReportFusionData | null
  /** 任务 ID：下载产物内容需要（GET /runs/{id}/artifacts/{aid}） */
  runId?: string
}>()

const emit = defineEmits<{ (e: 'preview', anchor?: string): void }>()
let router: ReturnType<typeof useRouter> | null = null
try {
  // 单元测试若未注入 router 则优雅兜底
  router = useRouter()
} catch {
  router = null
}

/** 融合产物清单里的 HTML 产物（清单无 revision，故用 DownloadableArtifact） */
const htmlArtifact = computed<DownloadableArtifact | null>(() => {
  const entry = (props.fusion?.artifacts ?? []).find((item) => item.kind === 'report_html')
  if (entry?.artifact_id && entry.uri) {
    return { artifact_id: entry.artifact_id, uri: entry.uri }
  }
  if (props.runId) {
    return { artifact_id: 'report_html', uri: 'report.html' }
  }
  return null
})

const pdfArtifact = computed<DownloadableArtifact | null>(() => {
  const entry = (props.fusion?.artifacts ?? []).find((item) => item.kind === 'report_pdf')
  if (entry?.artifact_id && entry.uri) {
    return { artifact_id: entry.artifact_id, uri: entry.uri }
  }
  if (props.runId) {
    return { artifact_id: 'report_pdf', uri: 'report.pdf' }
  }
  return null
})

const mdArtifact = computed<DownloadableArtifact | null>(() => {
  const entry = (props.fusion?.artifacts ?? []).find((item) => item.kind === 'report_markdown')
  if (entry?.artifact_id && entry.uri) {
    return { artifact_id: entry.artifact_id, uri: entry.uri }
  }
  if (props.runId) {
    return { artifact_id: 'report_markdown', uri: 'report.md' }
  }
  return null
})

const exportingKind = ref<string | null>(null)

async function handleExport(cmd: string): Promise<void> {
  if (!props.runId) return
  if (cmd === 'all') {
    if (router) {
      void router.push({ name: 'report-download', params: { runId: props.runId } })
    }
    return
  }
  let target: DownloadableArtifact | null = null
  if (cmd === 'pdf') target = pdfArtifact.value
  else if (cmd === 'html') target = htmlArtifact.value
  else if (cmd === 'markdown') target = mdArtifact.value

  if (!target) {
    ElMessage.warning('该格式产物尚未生成')
    return
  }

  exportingKind.value = cmd
  try {
    const { blob, filename } = await downloadArtifact(props.runId, target)
    triggerBlobDownload(blob, filename)
    ElMessage.success(`《${filename}》导出成功`)
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : '导出失败，请重试')
  } finally {
    exportingKind.value = null
  }
}

const hasHtmlReport = computed(() => htmlArtifact.value !== null)

const coverTitle = computed(() => props.fusion?.title ?? '报告尚未生成')
const depthLabel = computed(() => props.fusion?.report_depth ?? '')

const chapterList = computed<ChapterDraftLoose[]>(() => {
  const raw = props.fusion?.chapters
  return Array.isArray(raw) ? raw : []
})

const sectionCount = computed(() =>
  chapterList.value.reduce((n, chapter) => n + (chapter.sections ?? []).length, 0)
)

/**
 * 章节标题：**原样透传后端值**。
 *
 * 这里刻意不做任何改写（曾经用正则剥离「N、」前缀）——
 * 前端只负责显示，命名与编号属于后端；后端把标题改成「原神」也照原样显示。
 * 左侧 `01/02` 是前端按数组下标另加的序号列，与标题内容无关。
 */

// ---------------- 缩略图（缩放 iframe 渲染真实报告） ----------------
const objectUrl = ref('')
const thumbLoading = ref(false)
let disposed = false

function revokeThumb(): void {
  if (objectUrl.value) {
    URL.revokeObjectURL(objectUrl.value)
    objectUrl.value = ''
  }
}

async function loadThumbnail(): Promise<void> {
  const artifact = htmlArtifact.value
  if (!artifact || !props.runId) return
  thumbLoading.value = true
  try {
    const { blob } = await downloadArtifact(props.runId, artifact)
    if (disposed) return
    revokeThumb()
    objectUrl.value = URL.createObjectURL(blob)
  } catch {
    // 缩略图失败不打断主流程：留空态，用户仍可点主按钮进预览页
    revokeThumb()
  } finally {
    thumbLoading.value = false
  }
}

function openPreview(anchor?: string): void {
  emit('preview', anchor)
}

function formatTime(value: string | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN')
}

onMounted(loadThumbnail)
// 产物可能在阶段重跑后变化（artifact_id 变了），重新取缩略图
watch(
  () => htmlArtifact.value?.artifact_id,
  () => {
    revokeThumb()
    void loadThumbnail()
  }
)
onBeforeUnmount(() => {
  disposed = true
  revokeThumb()
})
</script>

<template>
  <div class="report-preview">
    <!-- 报告信息条 -->
    <div class="report-head">
      <div class="head-main">
        <div class="cover-kicker">行业研究报告</div>
        <h3 class="cover-title">{{ coverTitle }}</h3>
        <div class="cover-meta">
          <span v-if="fusion?.industry_topic">研究主题：{{ fusion.industry_topic }}</span>
          <span>研究时点 {{ fusion?.research_as_of ?? '—' }}</span>
          <span v-if="fusion?.generated_at">生成于 {{ formatTime(fusion.generated_at) }}</span>
          <span v-if="depthLabel">深度 {{ depthLabel }}</span>
        </div>
      </div>
      <div class="cover-tags">
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

    <!-- 整体样式缩略图 + 目录结构 -->
    <div class="report-body">
      <div
        class="thumb"
        :class="{ 'thumb-clickable': hasHtmlReport }"
        data-testid="report-thumbnail"
        @click="hasHtmlReport && openPreview()"
      >
        <!--
          sandbox="" 为最严格隔离：报告是纯静态 HTML（无 script、无外链），
          不需要 allow-scripts / allow-same-origin。
          pointer-events:none 让点击穿透到外层容器，避免用户在缩略图内误操作。
        -->
        <iframe
          v-if="objectUrl"
          :src="objectUrl"
          class="thumb-frame"
          sandbox=""
          referrerpolicy="no-referrer"
          tabindex="-1"
          aria-hidden="true"
          title="报告整体样式缩略预览"
          data-testid="report-thumb-frame"
        />
        <div v-else-if="thumbLoading" class="thumb-state">正在生成缩略预览…</div>
        <div v-else class="thumb-state">无可预览的 HTML 报告</div>
        <span v-if="hasHtmlReport" class="thumb-mask">点击查看完整报告</span>
      </div>

      <div class="outline">
        <div class="outline-title">
          目录结构
          <span class="muted outline-count">{{ chapterList.length }} 章 {{ sectionCount }} 节</span>
        </div>
        <div v-if="chapterList.length === 0" class="muted outline-empty">融合结果尚未包含章节</div>
        <ul v-else class="outline-list">
          <li v-for="(chapter, idx) in chapterList" :key="chapter.chapter_id ?? idx">
            <button
              type="button"
              class="outline-item"
              :data-testid="`report-outline-${idx + 1}`"
              :title="`查看第${idx + 1}章 · ${chapter.title ?? '未命名章节'}`"
              @click="openPreview(`chapter-${idx + 1}`)"
            >
              <span class="outline-no">{{ String(idx + 1).padStart(2, '0') }}</span>
              <span class="outline-name">{{ chapter.title ?? '未命名章节' }}</span>
              <span class="outline-sections">{{ (chapter.sections ?? []).length }} 节</span>
            </button>
          </li>
        </ul>
        <div v-if="chapterList.length > 0" class="outline-foot">
          <button type="button" class="outline-item" @click="openPreview('source-index')">
            <span class="outline-no">附</span>
            <span class="outline-name">来源与证据索引</span>
            <span class="outline-sections">完整清单</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 明确引导与导出 -->
    <div class="preview-cta">
      <span class="cta-hint" data-testid="report-preview-hint">
        {{
          hasHtmlReport
            ? '点击即可查看最终成果 —— 阶段五融合完成的 HTML 报告'
            : '完整报告请从下方产物列表下载'
        }}
      </span>
      <div class="cta-actions">
        <el-dropdown
          v-if="props.runId"
          trigger="click"
          @command="handleExport"
        >
          <el-button
            type="success"
            plain
            :loading="exportingKind !== null"
            data-testid="report-preview-export"
          >
            <el-icon style="margin-right: 4px"><Download /></el-icon>
            导出报告
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="pdf" :disabled="!pdfArtifact">
                导出 PDF 格式（出版级排版）
              </el-dropdown-item>
              <el-dropdown-item command="html" :disabled="!htmlArtifact">
                导出 HTML 格式（全交互单页）
              </el-dropdown-item>
              <el-dropdown-item command="markdown" :disabled="!mdArtifact">
                导出 Markdown 格式（结构化文本）
              </el-dropdown-item>
              <el-dropdown-item divided command="all">
                批量交付物打包下载...
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button
          v-if="hasHtmlReport"
          type="primary"
          data-testid="report-preview-open"
          style="margin-left: 8px"
          @click="openPreview()"
        >
          预览完整报告
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.report-preview {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
/* 信息条：纸面底 + 藏青顶条 */
.report-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--rp-line);
  border-top: 3px solid var(--rp-navy);
  border-radius: 4px;
  background: var(--rp-card);
}
.head-main {
  min-width: 0;
}
.cover-kicker {
  font-size: 11px;
  letter-spacing: 5px;
  color: var(--rp-gold);
  font-weight: 700;
}
.cover-title {
  margin: 6px 0;
  font-family: var(--rp-serif);
  font-size: 16px;
  line-height: 1.5;
  color: var(--rp-navy);
}
.cover-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 11.5px;
  color: var(--el-text-color-secondary);
}
.cover-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  flex-shrink: 0;
}

/* 主体：左缩略图 + 右目录 */
.report-body {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}
.thumb {
  position: relative;
  width: 240px;
  height: 323px;
  flex-shrink: 0;
  overflow: hidden;
  border: 1px solid var(--rp-line);
  border-radius: 4px;
  background: #e9eef5;
}
.thumb-clickable {
  cursor: zoom-in;
}
/* 报告 main 宽 1040px，按 240/1040 ≈ 0.2308 缩放，等比例呈现真实排版 */
.thumb-frame {
  width: 1040px;
  height: 1400px;
  border: none;
  transform: scale(0.2308);
  transform-origin: top left;
  pointer-events: none;
}
.thumb-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  padding: 16px;
  text-align: center;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.thumb-mask {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 5px 8px;
  font-size: 11.5px;
  text-align: center;
  color: #fff;
  background: rgba(30, 58, 92, 0.86);
}

/* 目录结构 */
.outline {
  flex: 1;
  min-width: 0;
}
.outline-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-family: var(--rp-serif);
  font-size: 13.5px;
  font-weight: 700;
  color: var(--rp-navy);
  padding-bottom: 5px;
  border-bottom: 2px solid var(--rp-navy);
}
.outline-count {
  font-family: inherit;
  font-weight: 400;
}
.outline-empty {
  padding: 10px 0;
  font-size: 12px;
}
.outline-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
.outline-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  width: 100%;
  padding: 4px 5px;
  border: none;
  border-radius: 3px;
  background: transparent;
  text-align: left;
  font: inherit;
  color: var(--el-text-color-regular);
  cursor: pointer;
}
.outline-item:hover {
  background: var(--el-fill-color-light);
  color: var(--rp-navy);
}
.outline-item:focus-visible {
  outline: 2px solid var(--rp-navy);
  outline-offset: 1px;
}
.outline-no {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  color: var(--rp-gold);
  font-variant-numeric: tabular-nums;
}
.outline-name {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.outline-sections {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.outline-foot {
  margin-top: 5px;
  padding-top: 5px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

/* 引导条 */
.preview-cta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  padding: 10px 14px;
  border: 1px solid var(--rp-line);
  border-left: 3px solid var(--rp-gold);
  border-radius: 4px;
  background: var(--rp-paper);
}
.cta-hint {
  font-size: 12.5px;
  color: var(--rp-ink);
}
.cta-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

@media (max-width: 900px) {
  .report-body {
    flex-direction: column;
  }
  .thumb {
    width: 100%;
    height: 260px;
  }
  .thumb-frame {
    transform: scale(0.33);
  }
}
</style>
