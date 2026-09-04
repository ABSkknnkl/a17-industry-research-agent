<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createRun } from '../api/client'
import { ApiError } from '../api/http'
import { showPipelineOverlay, hidePipelineOverlay } from '../composables/usePipelineOverlay'
import {
  STAGE_LABELS,
  type AnalysisDepth,
  type RiskPreference,
  type RunCreateRequest,
  type StageName,
} from '../api/types'

const router = useRouter()
const submitting = ref(false)

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function randomProjectId(): string {
  return `proj-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

const form = reactive({
  industryTopic: '',
  marketScope: ['中国 A 股'],
  securityTypes: ['股票'],
  reportingCurrency: 'CNY',
  researchAsOf: todayIso(),
  focusQuestionsText: '',
  analysisDepth: 'standard' as AnalysisDepth,
  riskPreference: 'balanced' as RiskPreference,
  keywordsText: '',
  metricsText: '',
  timeRange: '',
  reviewStages: ['data_fetch', 'data_interpret'] as StageName[],
})

const SECURITY_TYPE_OPTIONS = ['股票', '债券', '基金', '期货', '指数']
const REVIEW_STAGE_OPTIONS = Object.entries(STAGE_LABELS).map(([value, label]) => ({
  value: value as StageName,
  label,
}))

/** 快捷模板：一键填充示例（仅前端预填，提交字段不变） */
interface TopicTemplate {
  name: string
  topic: string
  questions: string[]
  keywords: string[]
  metrics: string[]
  timeRange: string
}

const TEMPLATES: TopicTemplate[] = [
  {
    name: '动力电池行业',
    topic: '动力电池行业 2023-2026 发展态势',
    questions: [
      '动力电池行业2023年至2026年装机量及增速变化趋势如何？',
      '宁德时代、比亚迪、中创新航动力电池装机量市场份额对比如何？',
      '碳酸锂价格2023年以来走势及其对电池成本的影响？',
      '动力电池行业主要企业研发投入规模及占营业收入比重变化？',
    ],
    keywords: ['动力电池', '储能电池', '碳酸锂'],
    metrics: ['装机量', '市场占有率', '营业收入', '净利润', '研发费用'],
    timeRange: '2023-2026',
  },
  {
    name: '新能源汽车整车',
    topic: '新能源汽车整车行业竞争格局分析',
    questions: [
      '新能源汽车整车行业2023年至2026年销量及渗透率变化趋势？',
      '比亚迪、特斯拉、理想、蔚来销量及国内市场份额对比？',
      '主要整车企业营业收入、净利润及毛利率变化趋势？',
      '新能源汽车海外出口规模及主要出口区域分布？',
    ],
    keywords: ['新能源汽车', '整车', '出口'],
    metrics: ['销量', '市场占有率', '营业收入', '净利润', '毛利率'],
    timeRange: '2023-2026',
  },
  {
    name: '光伏组件行业',
    topic: '光伏组件行业 2023-2026 供需与盈利分析',
    questions: [
      '光伏组件行业2023年至2026年产能、产量及供需格局变化？',
      '隆基绿能、晶科能源、天合光能组件出货量与市场份额对比？',
      '多晶硅料价格2023年以来走势及其对组件成本的影响？',
      '光伏组件行业主要企业营业收入、净利润及毛利率变化趋势？',
    ],
    keywords: ['光伏组件', '硅料', '装机'],
    metrics: ['出货量', '产能利用率', '营业收入', '净利润', '毛利率'],
    timeRange: '2023-2026',
  },
]

const activeTemplate = ref('')

function applyTemplate(tpl: TopicTemplate): void {
  form.industryTopic = tpl.topic
  form.focusQuestionsText = tpl.questions.join('\n')
  form.keywordsText = tpl.keywords.join('\n')
  form.metricsText = tpl.metrics.join('\n')
  form.timeRange = tpl.timeRange
  activeTemplate.value = tpl.name
  ElMessage.success(`已填充「${tpl.name}」模板，可继续调整`)
}

function splitLines(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

function validate(): string | null {
  const topic = form.industryTopic.trim()
  if (topic.length < 2 || topic.length > 100) {
    return '行业主题长度需在 2-100 个字符之间'
  }
  if (form.marketScope.length < 1) return '请至少填写一个市场范围'
  if (form.securityTypes.length < 1) return '请至少选择一种证券类型'
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.researchAsOf)) return '研究时点格式应为 YYYY-MM-DD'
  const questions = splitLines(form.focusQuestionsText)
  if (questions.length < 1) return '请至少填写一个研究问题'
  if (questions.length > 12) return '研究问题最多 12 个'
  if (questions.some((q) => q.length > 1000)) return '单个研究问题不能超过 1000 字'
  if (form.reviewStages.length === 0) return '请至少选择一个审核门'
  return null
}

async function submit(): Promise<void> {
  const problem = validate()
  if (problem) {
    ElMessage.warning(problem)
    return
  }
  submitting.value = true
  showPipelineOverlay('data_fetch', '创建任务')
  try {
    const payload: RunCreateRequest = {
      project_id: randomProjectId(),
      input_data: {
        industry_topic: form.industryTopic.trim(),
        market_scope: form.marketScope,
        security_types: form.securityTypes,
        reporting_currency: form.reportingCurrency.trim() || undefined,
        research_as_of: form.researchAsOf,
        focus_questions: splitLines(form.focusQuestionsText),
        analysis_depth: form.analysisDepth,
        risk_preference: form.riskPreference,
        data_fetch_options: {
          keywords: splitLines(form.keywordsText),
          metrics: splitLines(form.metricsText),
          time_range: form.timeRange.trim() ? [form.timeRange.trim()] : undefined,
        },
      },
      review_stages: form.reviewStages,
    }
    const state = await createRun(payload)
    ElMessage.success('任务已创建，流水线已启动')
    await router.push({ name: 'review', params: { runId: state.run_id } })
  } catch (e) {
    if (e instanceof ApiError) {
      ElMessage.error(`创建失败：${e.message}${e.code ? `（${e.code}）` : ''}`)
    } else {
      ElMessage.error('创建失败，请稍后重试')
    }
  } finally {
    submitting.value = false
    hidePipelineOverlay()
  }
}
</script>

<template>
  <div class="home-page">
    <!-- 页头：标题 + 一句话说明 -->
    <header class="home-header">
      <div>
        <div class="aside-kicker">INDUSTRY RESEARCH</div>
        <h2 class="page-title home-title">创建行业研究任务</h2>
      </div>
      <p class="home-lead muted">
        填写研究对象与研究问题，智能体自动完成数据采集、分析、图表与报告融合，全程可逐阶段审核。
      </p>
    </header>

    <!-- 快捷模板 -->
    <div class="tpl-bar">
      <span class="tpl-label">快捷模板</span>
      <el-button
        v-for="tpl in TEMPLATES"
        :key="tpl.name"
        size="small"
        :type="activeTemplate === tpl.name ? 'primary' : undefined"
        :plain="activeTemplate === tpl.name"
        @click="applyTemplate(tpl)"
      >
        {{ tpl.name }}
      </el-button>
      <span class="muted">一键填充示例，可修改</span>
    </div>

    <!-- 表单主体 -->
    <el-card class="page-card" shadow="never">
      <el-form label-position="top">
        <!-- 01 研究对象 -->
        <div class="form-section">
          <div class="section-head">
            <span class="section-index">01</span>
            <span class="section-title">研究对象</span>
            <span class="section-line" />
          </div>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="行业主题" required>
                <el-input
                  v-model="form.industryTopic"
                  placeholder="如：新能源汽车 / 动力电池 / 光伏组件（2-100 字）"
                  maxlength="100"
                  show-word-limit
                />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="研究时点" required>
                <el-date-picker
                  v-model="form.researchAsOf"
                  type="date"
                  value-format="YYYY-MM-DD"
                  style="width: 100%"
                />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="报告币种">
                <el-input v-model="form.reportingCurrency" placeholder="CNY / USD" maxlength="20" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="市场范围" required>
                <el-select
                  v-model="form.marketScope"
                  multiple
                  filterable
                  allow-create
                  default-first-option
                  placeholder="输入后回车，如：中国 A 股"
                  style="width: 100%"
                />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="证券类型" required>
                <el-select v-model="form.securityTypes" multiple style="width: 100%">
                  <el-option
                    v-for="opt in SECURITY_TYPE_OPTIONS"
                    :key="opt"
                    :label="opt"
                    :value="opt"
                  />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- 02 研究问题 -->
        <div class="form-section">
          <div class="section-head">
            <span class="section-index">02</span>
            <span class="section-title">研究问题</span>
            <span class="section-line" />
          </div>
          <el-form-item label="每行一个问题（1-12 个）" required>
            <el-input
              v-model="form.focusQuestionsText"
              type="textarea"
              :rows="5"
              maxlength="2000"
              show-word-limit
              placeholder="示例：&#10;锂电池行业2024-2025年营业收入与净利润增速如何？&#10;宁德时代、比亚迪、亿纬锂能2024年市占率与毛利率对比？&#10;碳酸锂价格近一年走势如何？"
            />
          </el-form-item>
          <div class="tip-line muted">
            <el-icon><InfoFilled /></el-icon>
            问题越具体越容易路由到可执行的数据技能；模糊问题（如「今年收益怎么样」）会触发人工澄清。
          </div>
        </div>

        <!-- 03 分析偏好 -->
        <div class="form-section">
          <div class="section-head">
            <span class="section-index">03</span>
            <span class="section-title">分析偏好</span>
            <span class="section-line" />
          </div>
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="分析深度">
                <el-radio-group v-model="form.analysisDepth">
                  <el-radio value="overview">概览</el-radio>
                  <el-radio value="standard">标准</el-radio>
                  <el-radio value="deep">深度</el-radio>
                </el-radio-group>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="风险偏好">
                <el-radio-group v-model="form.riskPreference">
                  <el-radio value="conservative">保守</el-radio>
                  <el-radio value="balanced">均衡</el-radio>
                  <el-radio value="aggressive">进取</el-radio>
                </el-radio-group>
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- 04 高级选项 -->
        <div class="form-section">
          <div class="section-head">
            <span class="section-index">04</span>
            <span class="section-title">数据采集与审核门</span>
            <span class="muted">可选，默认即可</span>
          </div>
          <el-collapse>
            <el-collapse-item title="检索关键词 / 关注指标 / 时间范围" name="fetch">
              <el-row :gutter="16">
                <el-col :span="8">
                  <el-form-item label="检索关键词（每行一个）">
                    <el-input
                      v-model="form.keywordsText"
                      type="textarea"
                      :rows="3"
                      placeholder="如：动力电池&#10;储能"
                    />
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="关注指标（每行一个）">
                    <el-input
                      v-model="form.metricsText"
                      type="textarea"
                      :rows="3"
                      placeholder="如：营业收入&#10;净利润&#10;毛利率"
                    />
                  </el-form-item>
                </el-col>
                <el-col :span="8">
                  <el-form-item label="时间范围">
                    <el-input
                      v-model="form.timeRange"
                      placeholder="如：2023-2026"
                      maxlength="100"
                    />
                  </el-form-item>
                </el-col>
              </el-row>
            </el-collapse-item>
            <el-collapse-item title="人工审核阶段（未勾选的阶段自动通过智能体推荐）" name="gates">
              <el-checkbox-group v-model="form.reviewStages">
                <el-checkbox
                  v-for="opt in REVIEW_STAGE_OPTIONS"
                  :key="opt.value"
                  :value="opt.value"
                  :label="opt.label"
                />
              </el-checkbox-group>
            </el-collapse-item>
          </el-collapse>
        </div>

        <div class="submit-row">
          <el-button type="primary" size="large" :loading="submitting" @click="submit">
            创建任务并启动流水线
          </el-button>
          <span class="muted">创建后自动进入任务工作台，可逐阶段审核。</span>
        </div>
      </el-form>
    </el-card>

    <!-- 底部：参考阅读（指南 / 流程） -->
    <div class="bottom-grid">
      <div class="guide-card">
        <div class="guide-title">研究问题怎么写</div>
        <ol class="guide-list">
          <li><b>具体行业/公司</b>——写「动力电池行业」而非「新能源」</li>
          <li><b>一个问题问一件事</b>——财务、销量份额、价格分开提问</li>
          <li><b>明确指标与时间</b>——如「2024-2025 年毛利率对比」</li>
          <li><b>一次 4-6 个问题</b>——过多易超时，模糊问题会触发澄清</li>
        </ol>
      </div>
      <div class="flow-card">
        <div class="guide-title">任务流程</div>
        <div class="flow-step"><span>1</span>创建任务，智能体开始执行数据采集与分析</div>
        <div class="flow-step"><span>2</span>在工作台逐阶段审核结论、图表与章节</div>
        <div class="flow-step"><span>3</span>融合交付报告（Markdown / HTML / PDF）</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.home-page {
  max-width: 1080px;
}
/* 页头：左标题右说明，双线压底 */
.home-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  border-bottom: 3px double var(--rp-navy);
  padding-bottom: 12px;
  margin-bottom: 14px;
}
.aside-kicker {
  font-size: 10px;
  letter-spacing: 4px;
  color: var(--rp-gold);
  font-weight: 600;
  margin-bottom: 6px;
}
.home-title {
  font-size: 24px;
  margin: 0;
}
.home-lead {
  margin: 0 0 4px;
  font-size: 12.5px;
  max-width: 460px;
  line-height: 1.7;
  text-align: right;
}
.tpl-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.tpl-label {
  font-size: 13px;
  font-weight: 700;
  color: var(--rp-navy);
  font-family: var(--rp-serif);
  letter-spacing: 1px;
}
.form-section {
  margin-bottom: 18px;
}
.section-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 12px;
}
.section-index {
  font-family: var(--rp-serif);
  font-size: 15px;
  font-weight: 700;
  color: var(--rp-gold);
}
.section-title {
  font-family: var(--rp-serif);
  font-size: 15px;
  font-weight: 700;
  color: var(--rp-navy);
  letter-spacing: 1px;
}
.section-line {
  flex: 1;
  height: 1px;
  background: var(--el-border-color-lighter);
  align-self: center;
}
.tip-line {
  display: flex;
  align-items: center;
  gap: 5px;
}
.submit-row {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}
/* 底部参考阅读区 */
.bottom-grid {
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: 12px;
  margin-top: 4px;
}
.guide-card,
.flow-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  background: var(--el-bg-color);
  padding: 12px 14px;
}
.guide-title {
  font-family: var(--rp-serif);
  font-size: 13px;
  font-weight: 700;
  color: var(--rp-navy);
  letter-spacing: 1px;
  margin-bottom: 8px;
  padding-bottom: 5px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.guide-list {
  margin: 0;
  padding: 0;
  list-style: none;
  counter-reset: guide;
}
.guide-list li {
  position: relative;
  padding-left: 22px;
  font-size: 12px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
  margin-bottom: 6px;
}
.guide-list li::before {
  counter-increment: guide;
  content: counter(guide);
  position: absolute;
  left: 0;
  top: 1px;
  width: 15px;
  height: 15px;
  border-radius: 50%;
  background: var(--rp-gold);
  color: #fff;
  font-size: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}
.guide-list b {
  color: var(--rp-navy);
}
.flow-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  line-height: 1.6;
  margin-bottom: 6px;
}
.flow-step:last-child {
  margin-bottom: 0;
}
.flow-step span {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: var(--rp-navy);
  color: #fff;
  font-size: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
@media (max-width: 900px) {
  .home-header {
    flex-direction: column;
    align-items: flex-start;
  }
  .home-lead {
    text-align: left;
  }
  .bottom-grid {
    grid-template-columns: 1fr;
  }
}
</style>
