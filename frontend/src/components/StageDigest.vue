<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  type CollaborationRequest,
  type DimensionCoverage,
  type IntentRouting,
  type ReportFusionData,
  type StageName,
} from '../api/types'
import { isMockDataMode } from '../api/client'
import { chapterNumber, dimensionLabel, fieldLabel, skillLabel } from '../api/labels'
import { usePrototypeStore } from '../mock/prototypeRun'
import EvidenceReviewTable from './review/EvidenceReviewTable.vue'
import ClaimReviewList from './review/ClaimReviewList.vue'
import ChartGallery from './ChartGallery.vue'
import ReportPreview from './ReportPreview.vue'

const props = defineProps<{
  stage: StageName
  data: Record<string, unknown>
  /** A1 source_records，供结论「查看数据来源」透传 */
  sourceRecords?: Record<string, unknown>[]
  /** 任务 ID：阶段五报告缩略图需要按 artifact 取 HTML 内容 */
  runId?: string
}>()

const emit = defineEmits<{
  (e: 'inspect', objectId: string, focus?: 'sources' | 'citations' | null): void
  (e: 'object-receipt', action: string, objectIds: string[]): void
  /** anchor：点目录结构里某一章时带上锚点，预览页打开后直接跳到该章 */
  (e: 'preview-report', anchor?: string): void
}>()

const mockMode = isMockDataMode()

const d = computed(() => props.data as Record<string, unknown>)

/** A1 采集列表：优先用父组件下传的 stage_results.source_records，缺省时回退当前阶段 data */
const sourceList = computed<Record<string, unknown>[]>(
  () => props.sourceRecords ?? asArray<Record<string, unknown>>(d.value.source_records)
)

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : []
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

/** chart_specs：交给 ChartGallery 渲染（真实与 mock 同源） */
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
const hasFusionReport = computed(
  () => Boolean(d.value.report_id) || Boolean(d.value.title)
)
const showFusionReport = computed(() => props.stage === 'report_fusion' && hasFusionReport.value)

/** report_fusion：证据目录条数（= 报告引用的来源数） */
const evidenceCatalogCount = computed(() => asArray<unknown>(d.value.evidence_catalog).length)

/** chapter_write 文章视图辅助：小节列表 / 字数 / 小节数 / 总字数 */
const chapterSections = (ch: Record<string, unknown>): Record<string, unknown>[] =>
  asArray<Record<string, unknown>>(ch.sections)

const chapterParagraphs = (ch: Record<string, unknown>): Record<string, unknown>[] =>
  chapterSections(ch).flatMap((s) => asArray<Record<string, unknown>>(s.paragraphs))

const sectionParagraphs = (sec: Record<string, unknown>): Record<string, unknown>[] =>
  asArray<Record<string, unknown>>(sec.paragraphs)

const chapterWordCount = (ch: Record<string, unknown>): number =>
  chapterParagraphs(ch).reduce((n, p) => n + String(p.text ?? '').length, 0)

const chapterSectionCount = (ch: Record<string, unknown>): number => chapterSections(ch).length

const totalChapterWordCount = computed(() =>
  chapters.value.reduce((n, ch) => n + chapterWordCount(ch), 0)
)

// ---- 章节级操作（重新生成需先询问修改诉求 / 删除）----
const regenDialog = ref<{
  visible: boolean
  chapterId: string
  title: string
  instruction: string
}>({ visible: false, chapterId: '', title: '', instruction: '' })
const regenSubmitting = ref(false)

function openRegenChapter(ch: Record<string, unknown>): void {
  const chapterId = String(ch.chapter_id ?? '')
  regenDialog.value = {
    visible: true,
    chapterId,
    // 编号从 chapter_id 反推（后端标题是纯文本，不含序号）
    title: `第${chapterNumber(chapterId)}章 · ${ch.title ?? ''}`,
    instruction: '',
  }
}

async function confirmRegenChapter(): Promise<void> {
  const { chapterId, instruction } = regenDialog.value
  regenDialog.value.visible = false
  if (!mockMode) {
    ElMessage.info('演示环境可用单章重新生成；真实 API 将在后续版本接入')
    return
  }
  const store = usePrototypeStore()
  regenSubmitting.value = true
  const rec = await store.regenerateChapter(chapterId, instruction)
  regenSubmitting.value = false
  if (!rec.ok) {
    ElMessage.error(rec.message)
    return
  }
  ElMessage.success(rec.message)
  emit('object-receipt', rec.action, [chapterId])
}

function onDeleteChapter(ch: Record<string, unknown>): void {
  const chapterId = String(ch.chapter_id ?? '')
  if (!mockMode) {
    ElMessage.info('演示环境可用单章删除；真实 API 将在后续版本接入')
    return
  }
  const rec = usePrototypeStore().deleteChapter(chapterId)
  if (!rec.ok) {
    ElMessage.error(rec.message)
    return
  }
  ElMessage.success(rec.message)
  emit('object-receipt', rec.action, [chapterId])
}

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

      <template v-if="sourceList.length > 0">
        <h4 class="digest-title">采集来源（{{ sourceList.length }} 条）</h4>
        <el-table :data="sourceList.slice(0, 10)" size="small" border>
          <el-table-column prop="source_name" label="来源" min-width="200" show-overflow-tooltip />
          <el-table-column label="数据来源" width="200" show-overflow-tooltip>
            <template #default="{ row }">{{
              row.skill_label || skillLabel(String(row.skill_name ?? ''))
            }}</template>
          </el-table-column>
          <el-table-column prop="as_of_date" label="数据日期" width="110" />
          <el-table-column prop="row_count" label="行数" width="80" />
        </el-table>
        <p v-if="sourceList.length > 10" class="muted">
          仅显示前 10 条，共 {{ sourceList.length }} 条
        </p>
      </template>

      <!-- Mock：对象级证据审核 -->
      <EvidenceReviewTable
        v-if="mockMode"
        class="object-area"
        @inspect="emit('inspect', $event)"
        @receipt="(a, ids) => emit('object-receipt', a, ids)"
      />
    </template>

    <!-- data_interpret -->
    <template v-else-if="stage === 'data_interpret'">
      <template v-if="dimensionCoverage.length > 0">
        <h4 class="digest-title">各维度数据覆盖情况</h4>
        <div class="coverage-row">
          <el-tooltip
            v-for="(cov, idx) in dimensionCoverage"
            :key="idx"
            :content="cov.reason || cov.dimension || ''"
            placement="top"
          >
            <el-tag :type="coverageTagType(cov.status)" effect="plain">
              {{ cov.dimension_label || dimensionLabel(cov.dimension) }}：{{
                cov.status_label || coverageLabel(cov.status)
              }}
            </el-tag>
          </el-tooltip>
        </div>
      </template>
      <template v-if="risks.length > 0">
        <h4 class="digest-title">风险提示（{{ risks.length }} 条）</h4>
        <ul class="risk-list">
          <li v-for="(risk, idx) in risks.slice(0, 10)" :key="idx" class="muted">
            {{
              risk.description ||
              risk.message ||
              risk.risk_code ||
              JSON.stringify(risk).slice(0, 120)
            }}
          </li>
        </ul>
      </template>
      <ClaimReviewList
        v-if="mockMode"
        class="object-area"
        @inspect="(id, focus) => emit('inspect', id, focus)"
        @receipt="(a, ids) => emit('object-receipt', a, ids)"
      />
    </template>

    <!-- chart_generate：内嵌图表卡片（替代候选表） -->
    <template v-else-if="stage === 'chart_generate'">
      <h4 class="digest-title">生成的图表（{{ chartSpecs.length }} 张）</h4>
      <ChartGallery
        :specs="chartSpecs"
        @inspect="(id) => emit('inspect', id)"
        @object-receipt="(a, ids) => emit('object-receipt', a, ids)"
      />
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
              :key="String(p.paragraph_id)"
              class="article-para"
            >
              {{ p.text }}
            </p>
          </section>
          <div class="article-ops">
            <el-tooltip
              :disabled="mockMode"
              content="演示环境可用；真实单章重生成 API 将在后续版本接入"
              placement="top"
            >
              <span>
                <el-button
                  size="small"
                  round
                  plain
                  type="primary"
                  data-testid="chapter-regen"
                  @click="openRegenChapter(ch)"
                >
                  重新生成
                </el-button>
              </span>
            </el-tooltip>
            <el-tooltip
              :disabled="mockMode"
              content="演示环境可用；真实单章删除 API 将在后续版本接入"
              placement="top"
            >
              <span>
                <el-popconfirm
                  :title="`确认删除「第${chapterNumber(String(ch.chapter_id ?? ''))}章 · ${ch.title ?? ''}」？删除后将移出报告。`"
                  width="280"
                  @confirm="onDeleteChapter(ch)"
                >
                  <template #reference>
                    <el-button
                      size="small"
                      round
                      plain
                      type="danger"
                      data-testid="chapter-delete"
                      :disabled="!mockMode"
                    >
                      删除
                    </el-button>
                  </template>
                </el-popconfirm>
              </span>
            </el-tooltip>
          </div>
        </article>
      </template>
      <template v-else>
        <p class="muted" style="margin: 0">章节撰写完成后展示正文。</p>
      </template>
    </template>

    <!-- 章节重新生成：先询问用户具体要修改什么东西 -->
    <el-dialog
      v-model="regenDialog.visible"
      :title="`重新生成章节：${regenDialog.title}`"
      width="480px"
      data-testid="chapter-regen-dialog"
    >
      <p class="muted" style="margin: 0 0 8px">
        请描述希望如何修改这个章节（例如：补充 XX 数据、调整结论表述、精简本节篇幅…）：
      </p>
      <el-input
        v-model="regenDialog.instruction"
        type="textarea"
        :rows="4"
        placeholder="填写具体的修改诉求…"
        data-testid="chapter-regen-instruction"
      />
      <p class="muted" style="margin: 8px 0 0; font-size: 11.5px">
        该指令将作为本章节重新生成的条件提交。
      </p>
      <template #footer>
        <el-button @click="regenDialog.visible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="regenSubmitting"
          data-testid="chapter-regen-confirm"
          @click="confirmRegenChapter"
        >
          确认重新生成
        </el-button>
      </template>
    </el-dialog>

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
.article-ops {
  display: flex;
  justify-content: flex-start;
  gap: 8px;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px dashed var(--el-border-color-lighter);
  flex-wrap: wrap;
}
</style>
