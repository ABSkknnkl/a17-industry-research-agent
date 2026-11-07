<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { marked } from 'marked'
import { downloadArtifact } from '../api/client'
import type { ArtifactRef } from '../api/types'

const props = defineProps<{
  runId: string
  markdownArtifact: ArtifactRef | null
}>()

const loading = ref(false)
const failed = ref(false)
const markdown = ref('')

/** 来源与证据索引：引用序号 → 来源元信息（解析自报告附录表格，纯前端聚合） */
interface SourceMeta {
  material: string
  publisher: string
  date: string
  locator: string
  method: string
}
const sourceByNumber = ref<Record<number, SourceMeta>>({})

const html = computed(() => {
  if (!markdown.value) return ''
  const raw = marked.parse(markdown.value, { async: false, gfm: true, breaks: false })
  // 引用标记加悬浮壳：〔来源1、来源2〕→ 可悬停的 .ev-ref
  return raw.replace(/来源(\d+)/g, (_m, num: string) => {
    const n = Number(num)
    if (!sourceByNumber.value[n]) return `来源${num}`
    return `<span class="ev-ref" data-cite="${n}">来源${num}</span>`
  })
})

async function loadMarkdown(): Promise<void> {
  const artifact = props.markdownArtifact
  if (!artifact) {
    markdown.value = ''
    return
  }
  loading.value = true
  failed.value = false
  try {
    const { blob } = await downloadArtifact(props.runId, artifact)
    const text = await blob.text()
    markdown.value = text
    sourceByNumber.value = parseSourceTable(text)
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}

/** 解析报告末尾「来源与证据索引」表格（| 序号 | 材料 | 发布主体 | 日期 | 报告期 | 页码/章节 | 获取方式/层级 |） */
function parseSourceTable(md: string): Record<number, SourceMeta> {
  const map: Record<number, SourceMeta> = {}
  const sectionMatch = md.match(/##\s*来源与证据索引[\s\S]*?(?=\n##\s|\s*$)/)
  if (!sectionMatch) return map
  const rows = sectionMatch[0].match(/^\|.*\|$/gm) ?? []
  for (const row of rows) {
    const cells = row.split('|').map((c) => c.trim())
    // cells[0] 为首尾管道间空串：[ '', 序号, 材料, 发布主体, 日期, 报告期, 页码, 获取方式, '' ]
    if (cells.length < 9) continue
    const num = Number(cells[1])
    if (!Number.isInteger(num) || num < 1 || /^[-:]+$/.test(cells[1])) continue
    map[num] = {
      material: cells[2] || '未提供',
      publisher: cells[3] || '未提供',
      date: cells[4] || '未提供',
      locator: [cells[5], cells[6]].filter((v) => v && v !== '未提供').join(' · ') || '未提供',
      method: cells[7] || '未提供',
    }
  }
  return map
}

// ---- 引用悬浮卡（事件委托 + 固定定位，避免逐节点挂 popover） ----
const hoverCard = ref<{ x: number; y: number; source: SourceMeta; anchor: HTMLElement } | null>(
  null
)
const readerBody = ref<HTMLElement | null>(null)

function onMouseOver(event: MouseEvent): void {
  const target = (event.target as HTMLElement).closest?.('.ev-ref')
  if (!target) return
  const num = Number((target as HTMLElement).dataset.cite)
  const source = sourceByNumber.value[num]
  if (!source) return
  const rect = (target as HTMLElement).getBoundingClientRect()
  hoverCard.value = { x: rect.left, y: rect.bottom + 6, source, anchor: target as HTMLElement }
}

function onMouseOut(event: MouseEvent): void {
  if (!hoverCard.value) return
  const related = event.relatedTarget as HTMLElement | null
  if (related && (related === hoverCard.value.anchor || hoverCard.value.anchor.contains(related))) {
    return
  }
  hoverCard.value = null
}

onMounted(loadMarkdown)
watch(
  () => [props.runId, props.markdownArtifact?.artifact_id],
  () => loadMarkdown()
)
onBeforeUnmount(() => {
  hoverCard.value = null
})
</script>

<script lang="ts">
export default { name: 'ReportReader' }
</script>

<template>
  <div class="report-reader">
    <el-empty v-if="!markdownArtifact" description="报告 Markdown 产物尚未生成" :image-size="60" />
    <template v-else>
      <div v-if="failed" class="reader-failed">
        <el-alert type="error" :closable="false" title="报告内容加载失败" />
        <el-button size="small" style="margin-top: 8px" @click="loadMarkdown">重试</el-button>
      </div>
      <div
        v-else
        v-loading="loading"
        class="md-body"
        element-loading-text="加载报告正文…"
        @mouseover="onMouseOver"
        @mouseout="onMouseOut"
      >
        <div v-if="!loading && markdown" ref="readerBody" class="md-content" v-html="html" />
      </div>
    </template>

    <!-- 来源悬浮卡 -->
    <Teleport to="body">
      <div
        v-if="hoverCard"
        class="cite-card"
        :style="{ left: `${hoverCard.x}px`, top: `${hoverCard.y}px` }"
      >
        <div class="cite-title">{{ hoverCard.source.material }}</div>
        <dl>
          <div>
            <dt>发布主体</dt>
            <dd>{{ hoverCard.source.publisher }}</dd>
          </div>
          <div>
            <dt>日期</dt>
            <dd>{{ hoverCard.source.date }}</dd>
          </div>
          <div v-if="hoverCard.source.locator !== '未提供'">
            <dt>定位</dt>
            <dd>{{ hoverCard.source.locator }}</dd>
          </div>
          <div>
            <dt>获取方式</dt>
            <dd>{{ hoverCard.source.method }}</dd>
          </div>
        </dl>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.report-reader {
  position: relative;
}
.reader-failed {
  padding: 8px 0;
}
/* ---- 报告排版（v-html 内容需 :deep） ---- */
.md-body {
  min-height: 120px;
}
.md-content :deep(h1) {
  font-family: var(--rp-serif);
  font-size: 20px;
  color: var(--rp-navy);
  margin: 4px 0 12px;
  padding-bottom: 8px;
  border-bottom: 3px double var(--rp-navy);
}
.md-content :deep(h2) {
  font-family: var(--rp-serif);
  font-size: 15px;
  color: var(--rp-navy);
  margin: 18px 0 8px;
  padding-left: 8px;
  border-left: 3px solid var(--rp-gold);
}
.md-content :deep(h3) {
  font-family: var(--rp-serif);
  font-size: 13.5px;
  color: var(--rp-navy);
  margin: 14px 0 6px;
}
.md-content :deep(p) {
  font-size: 12.5px;
  line-height: 1.9;
  color: var(--el-text-color-primary);
  margin: 6px 0;
}
.md-content :deep(ul),
.md-content :deep(ol) {
  padding-left: 18px;
  margin: 6px 0;
}
.md-content :deep(li) {
  font-size: 12.5px;
  line-height: 1.85;
  color: var(--el-text-color-primary);
}
.md-content :deep(blockquote) {
  margin: 8px 0;
  padding: 6px 10px;
  border-left: 2px solid var(--rp-gold);
  background: var(--rp-paper);
  color: var(--el-text-color-regular);
  font-size: 12px;
  line-height: 1.7;
}
.md-content :deep(code) {
  font-size: 11.5px;
  background: var(--el-fill-color-light);
  padding: 1px 5px;
  border-radius: 2px;
  color: var(--rp-navy);
}
.md-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0;
  font-size: 11.5px;
}
.md-content :deep(th),
.md-content :deep(td) {
  border: 1px solid var(--el-border-color-lighter);
  padding: 4px 6px;
  text-align: left;
  line-height: 1.5;
}
.md-content :deep(th) {
  background: var(--rp-paper);
  color: var(--rp-navy);
  font-weight: 600;
}
.md-content :deep(hr) {
  border: none;
  border-top: 1px solid var(--el-border-color-lighter);
  margin: 12px 0;
}
/* 引用标记 */
.md-content :deep(.ev-ref) {
  color: var(--rp-gold);
  font-weight: 600;
  cursor: help;
  border-bottom: 1px dashed var(--rp-gold);
}
/* ---- 来源悬浮卡（Teleport 到 body，样式不随 scoped 隔离） ---- */
</style>

<style>
.cite-card {
  position: fixed;
  z-index: 3000;
  width: 300px;
  background: var(--el-bg-color-overlay);
  border: 1px solid var(--el-border-color);
  border-top: 2px solid var(--rp-gold);
  border-radius: 3px;
  box-shadow: var(--el-box-shadow-light);
  padding: 10px 12px;
  pointer-events: none;
}
.cite-card .cite-title {
  font-family: var(--rp-serif);
  font-size: 12.5px;
  font-weight: 700;
  color: var(--rp-navy);
  line-height: 1.5;
  margin-bottom: 6px;
}
.cite-card dl {
  margin: 0;
}
.cite-card dl > div {
  display: flex;
  gap: 8px;
  margin-bottom: 3px;
}
.cite-card dt {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.cite-card dd {
  margin: 0;
  font-size: 11px;
  color: var(--el-text-color-primary);
  line-height: 1.5;
}
</style>
