<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { StageName } from '../api/types'
import { STAGE_LABELS } from '../api/types'

const props = defineProps<{
  visible: boolean
  stage: StageName
  revision: number
  data: Record<string, unknown>
  submitting?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', val: boolean): void
  (e: 'submit', payload: { edited_data: Record<string, unknown>; comment?: string }): void
}>()

// -------------------------------------------------------------
// 1. chapter_write: 章节段落就地编辑
// -------------------------------------------------------------
interface ParagraphItem {
  paragraph_id: string
  kind?: string
  text: string
  evidence_ids?: string[]
  assumption_note?: string | null
}

interface SectionItem {
  section_id: string
  title: string
  paragraphs: ParagraphItem[]
}

interface ChapterItem {
  chapter_id: string
  title: string
  summary?: string
  sections: SectionItem[]
}

const localChapters = ref<ChapterItem[]>([])
const selectedChapterId = ref<string>('')
const selectedSectionId = ref<string>('')

function initChapterData() {
  const rawChapters = (props.data?.chapters || props.data?.sections || []) as any[]
  localChapters.value = JSON.parse(JSON.stringify(rawChapters))
  if (localChapters.value.length > 0) {
    selectedChapterId.value = localChapters.value[0].chapter_id
    if (localChapters.value[0].sections?.length > 0) {
      selectedSectionId.value = localChapters.value[0].sections[0].section_id
    }
  }
}

const currentChapter = computed(() =>
  localChapters.value.find((c) => c.chapter_id === selectedChapterId.value)
)

const currentSection = computed(() =>
  currentChapter.value?.sections?.find((s) => s.section_id === selectedSectionId.value)
)

watch(selectedChapterId, (newChId) => {
  const ch = localChapters.value.find((c) => c.chapter_id === newChId)
  if (ch && ch.sections?.length > 0) {
    selectedSectionId.value = ch.sections[0].section_id
  } else {
    selectedSectionId.value = ''
  }
})

// -------------------------------------------------------------
// 2. chart_generate: 图表配置/标题/显隐就地调整
// -------------------------------------------------------------
interface LocalChartSpec {
  chart_id: string
  title: string
  chart_type: string
  status?: string
  excluded?: boolean
  footnotes?: string[]
}

const localChartSpecs = ref<LocalChartSpec[]>([])

function initChartData() {
  const rawSpecs = (props.data?.chart_specs || []) as any[]
  localChartSpecs.value = rawSpecs.map((c) => ({
    chart_id: c.chart_id || '',
    title: c.title || '',
    chart_type: c.chart_type || '',
    status: c.status || 'ready',
    excluded: c.status === 'excluded',
    footnotes: c.footnotes || [],
  }))
}

// -------------------------------------------------------------
// 3. data_interpret: 核心研判结论微调
// -------------------------------------------------------------
const localFindings = ref<Array<{ id: string; title: string; text: string }>>([])

function initInterpretData() {
  const rawFindings = (props.data?.findings || props.data?.key_findings || []) as any[]
  if (Array.isArray(rawFindings)) {
    localFindings.value = rawFindings.map((f, i) => ({
      id: f.id || `F-${i + 1}`,
      title: f.title || f.claim || `研判 #${i + 1}`,
      text: typeof f === 'string' ? f : f.text || f.content || f.description || '',
    }))
  }
}

// -------------------------------------------------------------
// 4. report_fusion: 报告标题与执行摘要微调
// -------------------------------------------------------------
const localReportTitle = ref('')
const localExecutiveSummary = ref('')

function initFusionData() {
  localReportTitle.value = String(props.data?.title || '')
  const es = props.data?.executive_summary
  if (typeof es === 'string') {
    localExecutiveSummary.value = es
  } else if (Array.isArray(es)) {
    localExecutiveSummary.value = es.join('\n\n')
  } else if (es && typeof es === 'object') {
    localExecutiveSummary.value = (es as any).text || (es as any).content || JSON.stringify(es)
  }
}

// 弹窗打开时加载各阶段对应数据快照
watch(
  () => props.visible,
  (val) => {
    if (val) {
      if (props.stage === 'chapter_write') {
        initChapterData()
      } else if (props.stage === 'chart_generate') {
        initChartData()
      } else if (props.stage === 'data_interpret') {
        initInterpretData()
      } else if (props.stage === 'report_fusion') {
        initFusionData()
      }
    }
  },
  { immediate: true }
)

function handleSave() {
  const edited_data: Record<string, unknown> = {}
  let comment = '用户就地微调'

  if (props.stage === 'chapter_write') {
    edited_data.chapters = localChapters.value
    comment = `用户就地微调章节正文（已更新 ${localChapters.value.length} 个章节）`
  } else if (props.stage === 'chart_generate') {
    // 同步 chart status
    const updated = localChartSpecs.value.map((c) => ({
      ...c,
      status: c.excluded ? 'excluded' : 'ready',
    }))
    edited_data.chart_specs = updated
    comment = `用户就地调整图表标题与可见性（共 ${updated.length} 张图表）`
  } else if (props.stage === 'data_interpret') {
    edited_data.findings = localFindings.value
    comment = `用户就地微调定性研判结论（共 ${localFindings.value.length} 条）`
  } else if (props.stage === 'report_fusion') {
    if (localReportTitle.value) edited_data.title = localReportTitle.value
    if (localExecutiveSummary.value) edited_data.executive_summary = localExecutiveSummary.value
    comment = '用户就地微调研报总标题与执行摘要'
  }

  emit('submit', { edited_data, comment })
}

function handleClose() {
  emit('update:visible', false)
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="`就地局部微调：【${STAGE_LABELS[stage] || stage}】`"
    width="860px"
    class="direct-edit-dialog"
    destroy-on-close
    @close="handleClose"
  >
    <div class="direct-edit-body">
      <!-- 提示横幅 -->
      <div class="tip-banner">
        <div class="tip-title">
          <span class="tip-badge">LIVE</span>
          <strong>毫秒级就地生效（无需重跑大模型，零算力开销）</strong>
        </div>
        <div class="tip-desc">
          当前处于 <b>r{{ revision }}</b> 版本。在此处修改的文案与参数将直接更新系统结构化数据与交付物（<b>r{{ revision + 1 }}</b>），不会触发耗时的全量重算。保存后可直接点击「审核通过」推进下一阶段或「重新融合」导出定稿。
        </div>
      </div>

      <!-- A. chapter_write: 章节正文精修 -->
      <div v-if="stage === 'chapter_write'" class="edit-section">
        <div class="selector-row">
          <div class="select-item">
            <span class="select-label">选择章节：</span>
            <el-select v-model="selectedChapterId" style="width: 280px" size="default">
              <el-option
                v-for="ch in localChapters"
                :key="ch.chapter_id"
                :label="`${ch.chapter_id} ${ch.title}`"
                :value="ch.chapter_id"
              />
            </el-select>
          </div>
          <div v-if="currentChapter?.sections?.length" class="select-item">
            <span class="select-label">选择小节：</span>
            <el-select v-model="selectedSectionId" style="width: 320px" size="default">
              <el-option
                v-for="sec in currentChapter.sections"
                :key="sec.section_id"
                :label="`${sec.section_id} ${sec.title}`"
                :value="sec.section_id"
              />
            </el-select>
          </div>
        </div>

        <div v-if="currentSection" class="paragraphs-list">
          <div class="section-badge-bar">
            <span class="sec-title">{{ currentSection.title }}</span>
            <span class="sec-id">（{{ currentSection.section_id }}）</span>
            <span class="para-count">共 {{ currentSection.paragraphs?.length || 0 }} 段</span>
          </div>

          <div
            v-for="(p, idx) in currentSection.paragraphs"
            :key="p.paragraph_id || idx"
            class="para-edit-card"
          >
            <div class="para-meta">
              <el-tag size="small" type="info" effect="plain">{{ p.paragraph_id || `P-${idx + 1}` }}</el-tag>
              <el-tag v-if="p.kind" size="small" type="success" effect="light" style="margin-left: 6px">
                {{ p.kind }}
              </el-tag>
              <span v-if="p.evidence_ids?.length" class="evidence-tag">
                关联证据: {{ p.evidence_ids.join(', ') }}
              </span>
            </div>
            <el-input
              v-model="p.text"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 8 }"
              placeholder="请输入或精修本段研报正文..."
              style="margin-top: 8px"
            />
          </div>
        </div>
        <el-empty v-else description="暂无章节或小节可编辑" />
      </div>

      <!-- B. chart_generate: 图表控制与标题微调 -->
      <div v-else-if="stage === 'chart_generate'" class="edit-section">
        <p class="section-hint">您可在此直接修改图表呈现标题，或开关排除不理想的图表：</p>
        <div class="charts-edit-list">
          <div
            v-for="c in localChartSpecs"
            :key="c.chart_id"
            class="chart-edit-card"
            :class="{ 'is-excluded': c.excluded }"
          >
            <div class="chart-card-head">
              <div class="head-left">
                <el-tag size="small" effect="dark" type="primary">{{ c.chart_type }}</el-tag>
                <span class="chart-id-muted">{{ c.chart_id }}</span>
              </div>
              <div class="head-right">
                <el-switch
                  v-model="c.excluded"
                  active-text="排除此图"
                  inactive-text="纳入报告"
                  active-color="#ef4444"
                  inactive-color="#10b981"
                />
              </div>
            </div>
            <div class="chart-input-row">
              <span class="input-lbl">图表标题：</span>
              <el-input
                v-model="c.title"
                size="default"
                :disabled="c.excluded"
                placeholder="图表标题..."
              />
            </div>
          </div>
        </div>
      </div>

      <!-- C. data_interpret: 核心研判微调 -->
      <div v-else-if="stage === 'data_interpret'" class="edit-section">
        <p class="section-hint">您可在此直接精修核心研判结论文本：</p>
        <div v-if="localFindings.length > 0" class="findings-edit-list">
          <div v-for="f in localFindings" :key="f.id" class="finding-edit-card">
            <div class="finding-title">
              <el-tag size="small" type="warning" effect="plain">{{ f.id }}</el-tag>
              <strong>{{ f.title }}</strong>
            </div>
            <el-input
              v-model="f.text"
              type="textarea"
              :autosize="{ minRows: 2, maxRows: 6 }"
              placeholder="研判正文..."
              style="margin-top: 6px"
            />
          </div>
        </div>
        <el-empty v-else description="暂无结构化研判项，可直接修改条件重跑" />
      </div>

      <!-- D. report_fusion: 报告标题与执行摘要微调 -->
      <div v-else-if="stage === 'report_fusion'" class="edit-section">
        <div class="fusion-field">
          <span class="field-lbl">报告总标题：</span>
          <el-input v-model="localReportTitle" placeholder="研报主标题..." size="default" />
        </div>
        <div class="fusion-field" style="margin-top: 14px">
          <span class="field-lbl">首席执行摘要 / 核心研判：</span>
          <el-input
            v-model="localExecutiveSummary"
            type="textarea"
            :autosize="{ minRows: 6, maxRows: 14 }"
            placeholder="输入或修改开篇执行摘要..."
          />
        </div>
      </div>

      <!-- 兜底提示 -->
      <div v-else class="edit-section">
        <el-empty description="当前阶段暂无专属局部编辑面板，请使用「修改条件重跑」" />
      </div>
    </div>

    <template #footer>
      <div class="dialog-foot">
        <el-button @click="handleClose">取消</el-button>
        <el-button
          type="primary"
          :loading="submitting"
          class="btn-save-direct"
          @click="handleSave"
        >
          保存局部修改（即刻生效）
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.direct-edit-dialog :deep(.el-dialog__body) {
  padding: 16px 20px;
  max-height: 72vh;
  overflow-y: auto;
}
.direct-edit-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.tip-banner {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  border-radius: 6px;
  padding: 10px 14px;
}
.tip-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #166534;
  font-size: 13.5px;
  margin-bottom: 4px;
}
.tip-badge {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 3px;
  background: #166534;
  color: #ffffff;
  letter-spacing: 0.05em;
  font-family: ui-monospace, SFMono-Regular, monospace;
}
.tip-desc {
  font-size: 12px;
  color: #15803d;
  line-height: 1.6;
}
.selector-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 14px;
  background: #f8fafc;
  padding: 10px 12px;
  border-radius: 6px;
  border: 1px solid #e2e8f0;
}
.select-item {
  display: flex;
  align-items: center;
  gap: 8px;
}
.select-label {
  font-size: 13px;
  font-weight: 500;
  color: #334155;
}
.section-badge-bar {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid #e2e8f0;
}
.sec-title {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
}
.sec-id,
.para-count {
  font-size: 12px;
  color: #64748b;
}
.paragraphs-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.para-edit-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
}
.para-meta {
  display: flex;
  align-items: center;
  font-size: 12px;
}
.evidence-tag {
  margin-left: auto;
  color: #94a3b8;
  font-size: 11px;
}

/* 图表列表编辑 */
.section-hint {
  font-size: 12.5px;
  color: #64748b;
  margin: 0 0 10px;
}
.charts-edit-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.chart-edit-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 14px;
  transition: all 0.2s ease;
}
.chart-edit-card.is-excluded {
  background: #fef2f2;
  border-color: #fecaca;
  opacity: 0.75;
}
.chart-card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.head-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chart-id-muted {
  font-size: 12px;
  color: #94a3b8;
}
.chart-input-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.input-lbl {
  font-size: 13px;
  color: #334155;
  white-space: nowrap;
}

/* 研判编辑 */
.findings-edit-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.finding-edit-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
}
.finding-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #1e293b;
}

/* 报告融合编辑 */
.fusion-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field-lbl {
  font-size: 13px;
  font-weight: 500;
  color: #1e293b;
}

.dialog-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.btn-save-direct {
  background: #16a34a;
  border-color: #16a34a;
  font-weight: 600;
}
.btn-save-direct:hover {
  background: #15803d;
  border-color: #15803d;
}
</style>
