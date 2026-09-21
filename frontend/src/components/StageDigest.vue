<script setup lang="ts">
import { computed } from 'vue'
import {
  type CollaborationRequest,
  type DimensionCoverage,
  type IntentRouting,
  type ReportFusionData,
  type StageName,
} from '../api/types'
import { dimensionLabel, fieldLabel, skillLabel } from '../api/labels'
import ChartGallery from './ChartGallery.vue'
import ReportPreview from './ReportPreview.vue'
import InterpretationDigest from './InterpretationDigest.vue'
import DataFetchDigest from './DataFetchDigest.vue'

const props = defineProps<{
  stage: StageName
  data: Record<string, unknown>
  /** A1 source_records，供结论「查看数据来源」透传 */
  sourceRecords?: Record<string, unknown>[]
  /** 任务 ID：阶段五报告缩略图需要按 artifact 取 HTML 内容 */
  runId?: string
}>()

const emit = defineEmits<{
  /** anchor：点目录结构里某一章时带上锚点，预览页打开后直接跳到该章 */
  (e: 'preview-report', anchor?: string): void
  (e: 'annotate', payload: { stage: StageName; annotations: any[] }): void
}>()

const d = computed(() => props.data as Record<string, unknown>)

/** A1 采集列表：优先用父组件下传的 stage_results.source_records，缺省时回退当前阶段 data */
const sourceList = computed<Record<string, unknown>[]>(
  () => props.sourceRecords ?? asArray<Record<string, unknown>>(d.value.source_records)
)

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : []
}

function formatRecordId(id: unknown, index: number): string {
  if (typeof id === 'string' && id.trim().length > 0) {
    const trimmed = id.trim()
    return trimmed.length > 14 ? `${trimmed.slice(0, 12)}…` : trimmed
  }
  return `#${index + 1}`
}

function formatDomain(domain: unknown): string {
  if (domain === 'industry') return '行业'
  if (domain === 'companies') return '公司'
  if (domain === 'macro') return '宏观'
  if (domain === 'industry_chain') return '产业链'
  if (domain === 'financials') return '财务'
  return String(domain || '—')
}

function formatSourceValue(row: Record<string, unknown>): string {
  const val = row.value
  const unit = row.unit ? ` ${row.unit}` : ''
  if (val === null || val === undefined || val === '') {
    if (typeof row.row_count === 'number') {
      return `${row.row_count} 行`
    }
    return '—'
  }
  if (Array.isArray(val)) {
    return val.map(String).join('、')
  }
  if (typeof val === 'number') {
    return `${val.toLocaleString('zh-CN')}${unit}`
  }
  return `${String(val)}${unit}`
}

/** data_fetch：意图路由计划 */
const intentRouting = computed<IntentRouting | null>(() => {
  const raw = d.value.intent_routing
  return raw && typeof raw === 'object' ? (raw as IntentRouting) : null
})

const intentPlanEntries = computed(() => Object.entries(intentRouting.value?.plans ?? {}))

/** data_fetch：协作请求（澄清问题） */
const collaborationRequests = computed<CollaborationRequest[]>(() =>
  asArray<CollaborationRequest>(d.value.collaboration_requests)
)

const blockingIssues = computed<string[]>(() =>
  asArray<string>(d.value.blocking_issues).map(String)
)

/** data_interpret：维度覆盖 */
const dimensionCoverage = computed<DimensionCoverage[]>(() =>
  asArray<DimensionCoverage>(d.value.dimension_coverage)
)

/** data_interpret：风险 */
const risks = computed<Record<string, unknown>[]>(() => asArray(d.value.risks))

/** chart_specs：交给 ChartGallery 渲染 */
const chartSpecs = computed<Record<string, unknown>[]>(() =>
  asArray<Record<string, unknown>>(d.value.chart_specs)
)

/** chapter_write：章节 */
const chapters = computed<Record<string, unknown>[]>(() => {
  const raw = d.value.chapters ?? d.value.sections
  return asArray<Record<string, unknown>>(raw)
})

/** report_fusion：融合结果（宽松读取，字段与后端 ReportFusionResult 对齐） */
const fusionData = computed<ReportFusionData | null>(() => {
  if (props.stage !== 'report_fusion') return null
  return d.value as unknown as ReportFusionData
})

/**
 * 只有真正产出报告时才走阶段五专属视图。
 *
 * 阶段五有两条 FAILED 路径只返回标量（report_render_failed 的
 * error_type/error_message、report_all_formats_failed 的 export_issues），
 * 它们没有 report_id/title。若不加判据，专属分支会把错误信息整个藏掉。
 * 判据用契约必填字段：真实融合结果必有 report_id 与 title。
 */
const hasFusionReport = computed(() => Boolean(d.value.report_id) || Boolean(d.value.title))
const showFusionReport = computed(() => props.stage === 'report_fusion' && hasFusionReport.value)

/** report_fusion：证据目录条数（= 报告引用的来源数） */
const evidenceCatalogCount = computed(() => asArray<unknown>(d.value.evidence_catalog).length)

export interface ParsedParagraph {
  id: string
  kind?: string
  text: string
  evidenceIds: string[]
  assumptionNote?: string | null
}

function parseParagraph(raw: unknown, fallbackId = ''): ParsedParagraph {
  if (!raw) return { id: fallbackId, text: '', evidenceIds: [] }

  let target: Record<string, unknown> = {}

  if (typeof raw === 'string') {
    const trimmed = raw.trim()
    if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
      try {
        const parsed = JSON.parse(trimmed)
        if (parsed && typeof parsed === 'object') {
          target = parsed as Record<string, unknown>
        } else {
          return { id: fallbackId, text: trimmed, evidenceIds: [] }
        }
      } catch {
        return { id: fallbackId, text: trimmed, evidenceIds: [] }
      }
    } else {
      return { id: fallbackId, text: trimmed, evidenceIds: [] }
    }
  } else if (typeof raw === 'object') {
    target = { ...(raw as Record<string, unknown>) }
  }

  // 解包后端可能出现的嵌套结构：如 { text: { paragraph_id, text, kind, ... } }
  while (target.text && typeof target.text === 'object') {
    const inner = target.text as Record<string, unknown>
    target = { ...target, ...inner }
  }

  // 提取正文文本
  let text = ''
  if (typeof target.text === 'string') {
    text = target.text
  } else if (typeof target.content === 'string') {
    text = target.content
  } else if (typeof target.body === 'string') {
    text = target.body
  }

  // 二次容错：如果 text 碰巧是 JSON 字符串，二次提取其内部纯文本
  if (text.startsWith('{') && text.endsWith('}')) {
    try {
      const parsed = JSON.parse(text)
      if (parsed && typeof parsed === 'object') {
        if (typeof parsed.text === 'string') text = parsed.text
        if (parsed.paragraph_id && !target.paragraph_id) target.paragraph_id = parsed.paragraph_id
        if (parsed.kind && !target.kind) target.kind = parsed.kind
      }
    } catch {
      // 保持原始 text
    }
  }

  const id = String(target.paragraph_id || target.id || fallbackId)
  const kind = typeof target.kind === 'string' ? target.kind : undefined
  const evidenceIds = asArray<unknown>(target.evidence_ids).map(String)
  const assumptionNote = typeof target.assumption_note === 'string' ? target.assumption_note : null

  return { id, kind, text, evidenceIds, assumptionNote }
}

/** chapter_write 文章视图辅助：小节列表 / 字数 / 小节数 / 总字数 */
const chapterSections = (ch: Record<string, unknown>): Record<string, unknown>[] =>
  asArray<Record<string, unknown>>(ch.sections)

const sectionParagraphs = (sec: Record<string, unknown>): ParsedParagraph[] => {
  const rawList = asArray<unknown>(sec.paragraphs)
  return rawList.map((item, idx) => parseParagraph(item, `${sec.section_id || 'sec'}-p${idx + 1}`))
}

const chapterParagraphs = (ch: Record<string, unknown>): ParsedParagraph[] =>
  chapterSections(ch).flatMap(sectionParagraphs)

const chapterWordCount = (ch: Record<string, unknown>): number =>
  chapterParagraphs(ch).reduce((n, p) => n + p.text.length, 0)

const chapterSectionCount = (ch: Record<string, unknown>): number => chapterSections(ch).length

const totalChapterWordCount = computed(() =>
  chapters.value.reduce((n, ch) => n + chapterWordCount(ch), 0)
)

/** 报告融合 / 兜底：展示顶层标量键值 */
const scalarEntries = computed(() => {
  const entries: Array<[string, string]> = []
  for (const [key, value] of Object.entries(d.value)) {
    if (value === null || value === undefined) continue
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      entries.push([key, String(value)])
    }
  }
  return entries.slice(0, 20)
})

const coverageTagType = (status?: string) => {
  switch (status) {
    case 'supported':
    case 'complete':
      return 'success'
    case 'partial':
      return 'warning'
    case 'insufficient':
    case 'missing':
      return 'danger'
    default:
      return 'info'
  }
}

/**
 * 维度覆盖状态：把后端英文枚举翻成用户能看懂的话。
 * 后端现在会下发 status_label，这里只作为老数据/缺字段时的兜底。
 * 取值：supported | partial | insufficient（见 analysis.py 的 DimensionCoverage）
 */
const coverageLabel = (status?: string) => {
  switch (status) {
    case 'supported':
    case 'complete':
      return '数据齐全'
    case 'partial':
      return '数据不全'
    case 'insufficient':
      return '数据不足'
    case 'missing':
      return '缺少数据'
    default:
      return status || '未知'
  }
}

// 维度名 / 技能标识 / 字段名的中文映射统一放在 src/api/labels.ts，
// 避免同一份映射散在多个组件里各自漂移。
// 后端下发 *_label 时优先用后端的，本地映射仅作兜底。
</script>

<template>
  <div class="digest">
    <!-- 所有阶段通用：智能体的协作/澄清请求 -->
    <template v-if="collaborationRequests.length > 0">
      <h4 class="digest-title">待确认问题（AI 需要你补充的信息）</h4>
      <el-alert
        v-for="(req, idx) in collaborationRequests"
        :key="idx"
        type="warning"
        show-icon
        :closable="false"
        class="clarify-item"
      >
        <template #title>{{ req.question || req.reason || '需要人工确认' }}</template>
        <span v-if="req.reason" class="muted">{{ req.reason }}</span>
      </el-alert>
    </template>

    <!-- data_fetch -->
    <template v-if="stage === 'data_fetch'">
      <template v-if="intentPlanEntries.length > 0">
        <h4 class="digest-title">研究问题与数据匹配情况</h4>
        <el-table :data="intentPlanEntries" size="small" border>
          <el-table-column label="研究问题" min-width="220">
            <template #default="{ row }">{{ row[0] }}</template>
          </el-table-column>
          <el-table-column label="处理状态" width="110">
            <template #default="{ row }">
              <el-tag :type="row[1]?.requires_clarification ? 'warning' : 'success'" size="small">
                {{ row[1]?.requires_clarification ? '需你确认' : '已匹配' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="匹配到的数据" min-width="200">
            <template #default="{ row }">
              <template v-if="(row[1]?.sub_requirements ?? []).length > 0">
                <div v-for="(sub, idx) in row[1].sub_requirements" :key="idx" class="skill-line">
                  <span class="muted">{{ sub.description }}</span>
                  <el-tag
                    v-for="skill in sub.candidate_skills ?? []"
                    :key="skill"
                    size="small"
                    effect="plain"
                    style="margin-left: 4px"
                  >
                    {{ skillLabel(skill) }}
                  </el-tag>
                  <el-tag
                    v-if="(sub.candidate_skills ?? []).length === 0"
                    size="small"
                    type="danger"
                    effect="plain"
                  >
                    暂无可用的数据
                  </el-tag>
                </div>
              </template>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-if="sourceList.length > 0 || intentPlanEntries.length > 0">
        <DataFetchDigest
          :data="data"
          :source-records="sourceRecords"
          :run-id="runId"
          @annotate="(annots) => emit('annotate', { stage: 'data_fetch', annotations: annots })"
        />
      </template>

      <template v-else>
        <div class="stage-pending-box">
          <div class="pending-lead">
            <span class="spinner-dot" />
            <span class="pending-title">数据获取智能体正在执行闭环采集</span>
          </div>
          <p class="pending-desc">
            底层智能体正在基于投研需求分解 7 大维度，并并发调度问财金融技能抓取实体与财务指标。采集完成后将自动在此渲染结构化指标列表与意图路由明细。
          </p>
          <div class="pending-steps">
            <div class="pstep is-done">✓ 投研意图分解与 7 大分析领域激活</div>
            <div class="pstep is-active">● 问财金融数据多轮闭环抽取中...</div>
            <div class="pstep">○ 多源数据实体对齐与冲突消解</div>
            <div class="pstep">○ 结构化事实总库入库交付</div>
          </div>
        </div>
      </template>
    </template>

    <!-- data_interpret -->
    <template v-else-if="stage === 'data_interpret'">
      <template
        v-if="
          Boolean(d.executive_summary || d.summary) ||
          asArray(d.insights).length > 0 ||
          asArray(d.knowledge_facts).length > 0 ||
          dimensionCoverage.length > 0
        "
      >
        <InterpretationDigest
          :data="data"
          :run-id="runId"
          @annotate="(annots) => emit('annotate', { stage: 'data_interpret', annotations: annots })"
        />
      </template>
      <template v-else>
        <div class="stage-pending-box">
          <div class="pending-lead">
            <span class="spinner-dot" />
            <span class="pending-title">数据解读智能体正在深入量化推演</span>
          </div>
          <p class="pending-desc">
            正在基于阶段一全量数据集执行确定性复合增速 CAGR 测算、稳健 Z 分数离群异常检测、三表勾稽验证与 6 维投研方法论洞察提炼。
          </p>
          <div class="pending-steps">
            <div class="pstep is-done">✓ 阶段一数据集已成功挂载</div>
            <div class="pstep is-active">● 底层量化计算与同行对标矩阵构建中...</div>
            <div class="pstep">○ 投研方法论自主规划与深度语义洞察</div>
            <div class="pstep">○ 维度覆盖矩阵与风险提示生成</div>
          </div>
        </div>
      </template>
    </template>

    <!-- chart_generate：内嵌图表卡片（替代候选表） -->
    <template v-else-if="stage === 'chart_generate'">
      <template v-if="chartSpecs.length > 0">
        <h4 class="digest-title">生成的图表（{{ chartSpecs.length }} 张）</h4>
        <ChartGallery :specs="chartSpecs" />
      </template>
      <template v-else>
        <div class="stage-pending-box">
          <div class="pending-lead">
            <span class="spinner-dot" />
            <span class="pending-title">出版级图表生成智能体正在规划绘制</span>
          </div>
          <p class="pending-desc">
            正在分析数据形态规划出版级图表矩阵，结合 ECharts 引擎渲染 960x520 矢量图表并进行排版自愈与审美校验。
          </p>
          <div class="pending-steps">
            <div class="pstep is-done">✓ 解读数据特征与量化指标就绪</div>
            <div class="pstep is-active">● 出版级图表选型规划与 ECharts 渲染中...</div>
            <div class="pstep">○ 图表排版自愈与合规审查</div>
            <div class="pstep">○ 960x520 矢量图表交付</div>
          </div>
        </div>
      </template>
    </template>

    <!-- chapter_write -->
    <template v-else-if="stage === 'chapter_write'">
      <template v-if="chapters.length > 0">
        <h4 class="digest-title">
          章节正文（{{ chapters.length }} 篇 · 共 {{ totalChapterWordCount }} 字）
        </h4>
        <!-- 文章流：章节 → 小节 → 连续段落，供完整连贯阅读 -->
        <article
          v-for="(ch, chIdx) in chapters"
          :key="String(ch.chapter_id ?? chIdx)"
          class="article-chapter"
        >
          <header class="article-chapter-head">
            <span class="article-chapter-no">{{ String(chIdx + 1).padStart(2, '0') }}</span>
            <h5 class="article-chapter-title">{{ ch.title ?? '未命名章节' }}</h5>
            <span class="article-chapter-meta muted">
              {{ chapterSectionCount(ch) }} 小节 · {{ chapterWordCount(ch) }} 字
            </span>
          </header>
          <p v-if="ch.summary" class="article-chapter-summary">{{ ch.summary }}</p>
          <section
            v-for="sec in chapterSections(ch)"
            :key="String(sec.section_id)"
            class="article-section"
          >
            <h6 class="article-sec-title">
              <span class="article-sec-name">{{ sec.title ?? '未命名小节' }}</span>
              <span v-if="sec.section_id" class="muted article-sec-id">
                （{{ sec.section_id }}）
              </span>
            </h6>
            <p
              v-for="p in sectionParagraphs(sec)"
              :key="p.id"
              class="article-para"
            >
              {{ p.text }}
            </p>
          </section>
        </article>
      </template>
      <template v-else>
        <div class="stage-pending-box">
          <div class="pending-lead">
            <span class="spinner-dot" />
            <span class="pending-title">章节撰写智能体正在全并发撰写</span>
          </div>
          <p class="pending-desc">
            7 章 21 节券商深度专题骨架已激活，正在并发组织写作方法论技能调度，并穿透关联客观证据与矢量图表。
          </p>
          <div class="pending-steps">
            <div class="pstep is-done">✓ 7 章 21 节大纲与动态证据检索就绪</div>
            <div class="pstep is-active">● 各章节写作方法论技能全并发撰写中...</div>
            <div class="pstep">○ 证据引用与学术规范 Linting 质检</div>
            <div class="pstep">○ 深度连贯研报正文就绪</div>
          </div>
        </div>
      </template>
    </template>

    <!-- report_fusion：最终报告预览（仅真正产出报告时） -->
    <template v-if="showFusionReport">
      <template v-if="fusionData">
        <h4 class="digest-title">
          最终报告预览
          <span v-if="evidenceCatalogCount > 0" class="muted title-note">
            · 引用证据 {{ evidenceCatalogCount }} 条
          </span>
        </h4>
        <ReportPreview
          :fusion="fusionData"
          :run-id="runId"
          @preview="(anchor) => emit('preview-report', anchor)"
        />
      </template>
    </template>
    <template v-else-if="stage === 'report_fusion'">
      <div class="stage-pending-box">
        <div class="pending-lead">
          <span class="spinner-dot" />
          <span class="pending-title">研报融合智能体正在出版级审校与编译</span>
        </div>
        <p class="pending-desc">
          正在组织 4 大总编审校技能协同审计，统合数据口径、编纂证据穿透目录并编译导出 Markdown / HTML / PDF 多格式报告。
        </p>
        <div class="pending-steps">
          <div class="pstep is-done">✓ 汇聚全阶段资产（数据、图表、正文）</div>
          <div class="pstep is-active">● 首席产业研判提炼与 4 维一致性审计中...</div>
          <div class="pstep">○ 100% 证据穿透溯源目录编纂</div>
          <div class="pstep">○ 多格式出版级报告定稿生成</div>
        </div>
      </div>
    </template>

    <!-- 其余情况（含阶段五失败时的标量错误信息）：展示顶层标量键值 -->
    <template v-if="!showFusionReport && scalarEntries.length > 0">
      <h4 class="digest-title">本阶段结果概览</h4>
      <el-descriptions :column="2" size="small" border>
        <el-descriptions-item
          v-for="[key, value] in scalarEntries"
          :key="key"
          :label="fieldLabel(key)"
        >
          {{ value }}
        </el-descriptions-item>
      </el-descriptions>
    </template>

    <template v-if="blockingIssues.length > 0">
      <el-alert
        v-for="(issue, idx) in blockingIssues"
        :key="idx"
        type="error"
        show-icon
        :closable="false"
        :title="`需要先解决的问题：${issue}`"
        style="margin-top: 12px"
      />
    </template>
  </div>
</template>

<style scoped>
.digest-title {
  margin: 16px 0 8px;
  font-size: 14px;
  font-weight: 600;
}
.digest-title:first-child {
  margin-top: 0;
}
.title-note {
  font-size: 12px;
  font-weight: 400;
}
.skill-line {
  line-height: 1.9;
}
.clarify-item {
  margin-bottom: 8px;
}
.coverage-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.risk-list {
  margin: 0;
  padding-left: 18px;
}
.object-area {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
}

/* ---- chapter_write：文章流排版（章节 → 小节 → 连续段落） ---- */
.article-chapter {
  border: 1px solid var(--rp-line);
  border-radius: 8px;
  background: var(--rp-card);
  padding: 12px 16px 14px;
  margin-bottom: 12px;
}
.article-chapter-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding-bottom: 8px;
  border-bottom: 2px double var(--rp-navy);
}
.article-chapter-no {
  font-family: var(--rp-serif);
  font-size: 15px;
  font-weight: 700;
  color: var(--rp-gold);
  flex-shrink: 0;
}
.article-chapter-title {
  margin: 0;
  font-family: var(--rp-serif);
  font-size: 15px;
  font-weight: 700;
  color: var(--rp-navy);
  letter-spacing: 0.3px;
  line-height: 1.5;
}
.article-chapter-meta {
  margin-left: auto;
  font-size: 11.5px;
  flex-shrink: 0;
}
/* 摘要：克制呈现，避免与各小节标题形成重复强调 */
.article-chapter-summary {
  margin: 8px 0 4px;
  padding: 2px 0 2px 10px;
  border-left: 2px solid var(--el-border-color-lighter);
  font-size: 11.5px;
  line-height: 1.7;
  color: var(--el-text-color-secondary);
}
.article-sec-title {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 12px 0 4px;
  font-size: 13px;
  font-weight: 600;
  color: var(--rp-navy);
  padding-left: 8px;
  border-left: 3px solid var(--rp-gold);
}
.article-sec-id {
  margin-left: auto;
  font-weight: 400;
  font-size: 10.5px;
  flex-shrink: 0;
}
.article-para {
  /* 连续阅读：段间距分隔正文，不用逐段卡片框 */
  margin: 6px 0;
  font-size: 12.5px;
  line-height: 1.9;
  color: var(--el-text-color-primary);
  text-align: justify;
}
.source-list-header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-top: 14px;
  margin-bottom: 6px;
}
.source-list-subtitle {
  font-size: 11px;
}
.record-id-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  background: var(--el-fill-color-light);
  padding: 1px 4px;
  border-radius: 4px;
  color: var(--rp-navy);
}
.entity-badge {
  display: inline-flex;
  align-items: baseline;
  gap: 4px;
}
.entity-name {
  color: var(--rp-navy);
}
.entity-code {
  font-size: 10.5px;
}
.metric-name {
  font-weight: 500;
}
.value-highlight {
  color: var(--el-text-color-primary);
}
.table-subtext {
  margin-top: 6px;
  font-size: 11.5px;
}

/* 阶段执行中动态骨架与进度提示 */
.stage-pending-box {
  background: #f8fafc;
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  padding: 16px 20px;
  margin: 10px 0;
}
.pending-lead {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}
.spinner-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--el-color-primary, #409eff);
  box-shadow: 0 0 8px var(--el-color-primary, #409eff);
  animation: spinner-pulse 1.4s infinite ease-in-out;
}
@keyframes spinner-pulse {
  0%, 100% { transform: scale(0.8); opacity: 0.6; }
  50% { transform: scale(1.3); opacity: 1; }
}
.pending-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--rp-navy, #1e3a5c);
}
.pending-desc {
  font-size: 12.5px;
  color: var(--el-text-color-secondary, #64748b);
  line-height: 1.6;
  margin: 4px 0 12px;
}
.pending-steps {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 8px;
  background: #ffffff;
  border: 1px solid var(--el-border-color-lighter, #ebeef5);
  border-radius: 6px;
  padding: 10px 14px;
}
.pstep {
  font-size: 12px;
  color: #94a3b8;
}
.pstep.is-done {
  color: #10b981;
  font-weight: 500;
}
.pstep.is-active {
  color: #1e40af;
  font-weight: 600;
  animation: pstep-glow 1.5s infinite alternate;
}
@keyframes pstep-glow {
  0% { color: #1e40af; }
  100% { color: #2563eb; }
}
</style>
