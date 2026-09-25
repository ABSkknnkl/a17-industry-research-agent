<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createRun } from '../api/client'
import { ApiError } from '../api/http'
import { showPipelineOverlay, hidePipelineOverlay } from '../composables/usePipelineOverlay'
import {
  STAGE_LABELS,
  type AnalysisDepth,
  type RunCreateRequest,
  type StageName,
} from '../api/types'
import ProjectTree from '../components/ProjectTree.vue'

const route = useRoute()
const router = useRouter()
const submitting = ref(false)

function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

function randomProjectId(): string {
  return `proj-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** 配图密度（standard=标准精选(12~15张) / rich=详尽全景(18~22张) / minimal=极简摘要(4~6张) / none=纯文与表格(0张)） */
type ChartMode = 'standard' | 'rich' | 'minimal' | 'none' | 'auto'

const SECURITY_TYPE_OPTIONS = ['股票', '债券', '基金', '期货', '指数']

/** 市场范围选项（value 为提交给后端的纯市场名；label 带可达性备注）。
 * 可达性依据当前接线（问财 hithink_* + L3 博查联网）实测：
 * full=结构化完整；partial=部分数据（联网定性/缺口披露补充）；unavailable=暂无结构化数据。
 */
interface MarketOption {
  value: string
  label: string
  availability: 'full' | 'partial' | 'unavailable'
}

const MARKET_OPTIONS: MarketOption[] = [
  { value: '中国 A 股', label: '中国 A 股（沪深北·人民币）', availability: 'full' },
  { value: '港股', label: '港股（港交所）', availability: 'partial' },
  { value: '美股', label: '美股（纽交所/纳斯达克，含中概 ADR）', availability: 'partial' },
  { value: '中国 B 股', label: '中国 B 股（深港币/沪美元）', availability: 'partial' },
  { value: '中国台湾', label: '中国台湾（暂无可获取的结构化数据）', availability: 'unavailable' },
  { value: '日本', label: '日本（暂无可获取的结构化数据）', availability: 'unavailable' },
  { value: '欧洲', label: '欧洲（暂无可获取的结构化数据）', availability: 'unavailable' },
]

/** 默认可用市场：中国 A 股 + 港股 + 美股 + 中国 B 股（排除暂无结构化数据的台湾/日本/欧洲） */
const AVAILABLE_MARKET_OPTIONS = MARKET_OPTIONS.filter((opt) => opt.availability !== 'unavailable').map((opt) => opt.value)
const AVAILABLE_SECURITY_TYPES = [...SECURITY_TYPE_OPTIONS]

export interface PresetTopic {
  topic: string
  badge: string
  questions: string[]
}

const PRESET_TOPICS: PresetTopic[] = [
  {
    topic: '商业航天',
    badge: '硬科技',
    questions: [
      '商业航天产业链各环节（上游核心元器件与特种材料、中游卫星总装与地面测控、下游卫星运营与终端应用）竞争格局与主要壁垒如何？',
      '核心上市公司（中兴通讯、铖昌科技、中国卫星、海格通信等）近三年营收增速、研发费用率与净资产收益率ROE对比情况如何？',
      '低轨卫星互联网星座建设节奏、牌照发放与商业航天产业政策催化带来的中长期市场空间与潜在风险点有哪些？',
    ],
  },
  {
    topic: '低空经济',
    badge: '新兴产业',
    questions: [
      'eVTOL飞行器产业化商业化落地节奏、适航取证进展与核心技术路线演进如何？',
      '低空基础设施（通信、导航、监视、空域管控系统）与整机制造供应链关键企业竞争优势对比？',
      '空域管理政策开放节奏与低空应用场景（城市空中交通、物流配送、应急救援）的市场容量与商业模式？',
    ],
  },
  {
    topic: '固态电池',
    badge: '新能源',
    questions: [
      '全固态与半固态电池关键材料（固态电解质、高镍三元正极、硅碳负极）的技术瓶颈与量产装车时间表？',
      '宁德时代、亿纬锂能、国轩高科、当升科技等主要企业的研发开支、专利布局与量产产线规划对比？',
      '固态电池相较于传统液态锂电在能量密度、安全性与循环寿命上的综合性价比曲线测算？',
    ],
  },
  {
    topic: '光模块',
    badge: '算力基建',
    questions: [
      '800G与1.6T高速光模块在国内外AI云服务商数据中心集群的渗透率与未来两年的出货预期？',
      '中际旭创、天孚通信、新易盛等龙头企业的海外收入占比、销售毛利率与前瞻市盈率估值对比？',
      '硅光集成方案与CPO光电共封装架构对传统可插拔光模块产业链竞争壁垒的长期影响？',
    ],
  },
  {
    topic: '白酒行业',
    badge: '大消费',
    questions: [
      '高端白酒与次高端白酒价格带分化、批价走势及渠道社会库存周期如何？',
      '贵州茅台、五粮液、泸州老窖的合同负债、应收账款周转率与经营活动现金流质量对比？',
      '商务宴席与大众消费场景动销变化对白酒板块估值中枢与中长期盈利稳定性的影响？',
    ],
  },
]

const form = reactive({
  industryTopic: '',
  marketScope: [...AVAILABLE_MARKET_OPTIONS],
  securityTypes: [...AVAILABLE_SECURITY_TYPES],
  reportingCurrency: 'CNY',
  researchAsOf: todayIso(),
  focusQuestionsText: '',
  analysisDepth: 'standard' as AnalysisDepth,
  chartMode: 'standard' as ChartMode,
  reviewStages: [
    'data_fetch',
    'data_interpret',
    'chart_generate',
    'chapter_write',
  ] as StageName[],
})

const REVIEW_STAGE_OPTIONS = Object.entries(STAGE_LABELS).map(([value, label]) => ({
  value: value as StageName,
  label,
}))

function applyPreset(preset: PresetTopic): void {
  form.industryTopic = preset.topic
  form.focusQuestionsText = preset.questions.join('\n')
  ElMessage.success(`已应用【${preset.topic}】研究范例与 3 个专业问题`)
}

onMounted(() => {
  const qTopic = route.query.topic
  if (typeof qTopic === 'string' && qTopic.trim()) {
    const target = qTopic.trim()
    const match = PRESET_TOPICS.find(
      (p) => p.topic === target || p.topic.includes(target) || target.includes(p.topic)
    )
    if (match) {
      applyPreset(match)
    } else {
      form.industryTopic = target
    }
  }
})

function selectAllAvailableMarkets(): void {
  form.marketScope = [...AVAILABLE_MARKET_OPTIONS]
}

function selectAllSecurityTypes(): void {
  form.securityTypes = [...AVAILABLE_SECURITY_TYPES]
}

/** 市场 → 建议报告币种（与 A2 框架「按上市地记账币种」口径一致；仅提示，不自动改值）。 */
const CURRENCY_BY_MARKET: Record<string, string> = { 港股: 'HKD', 美股: 'USD', '中国 B 股': 'HKD' }

const currencyHints = computed(() =>
  form.marketScope
    .filter((market) => CURRENCY_BY_MARKET[market] != null)
    .map((market) => ({ market, currency: CURRENCY_BY_MARKET[market] }))
)

function applySuggestedCurrency(): void {
  const target = [...new Set(currencyHints.value.map((hint) => hint.currency))]
  if (target.length > 0) {
    form.reportingCurrency = target[0]
    ElMessage.success(`已填入报告币种 ${target[0]}`)
  }
}

/** 一键通过（全自动）：取消全部人工审核门，流程结束后自动跳转下载页。 */
async function automateGates(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      '将取消全部人工审核门：数据采集、数据解读、图表生成、章节撰写、报告融合均自动通过，无需逐个点击。中、低风险（如数据缺口、质量降级等需确认项）会一并自动放行并写入报告披露；检测到红色高风险会暂停等待人工处理。流程结束后自动跳转到报告下载页。',
      '一键通过（全自动）',
      {
        confirmButtonText: '确认开启全自动',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
  } catch {
    return
  }
  form.reviewStages = []
  ElMessage.success('已开启全自动：所有阶段自动通过，完成后自动进入下载页')
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
  return null
}

async function submit(): Promise<void> {
  const problem = validate()
  if (problem) {
    ElMessage.warning(problem)
    return
  }
  const limited = form.marketScope.filter((market) => {
    const opt = MARKET_OPTIONS.find((item) => item.value === market)
    return opt != null && opt.availability !== 'full'
  })
  if (limited.length > 0) {
    ElMessage.warning(
      `以下市场数据获取能力有限，报告将以缺口披露或联网定性补充：${limited.join('、')}`
    )
  }
  submitting.value = true
  showPipelineOverlay('data_fetch', '创建任务')
  try {
    const chartCount =
      form.chartMode === 'none'
        ? 0
        : form.chartMode === 'minimal'
          ? 6
          : form.chartMode === 'rich'
            ? 22
            : 15

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
        chart_generate_options: {
          requested_chart_count: chartCount,
          allow_multiple_charts_per_dataset: form.chartMode === 'rich',
        },
      },
      review_stages: form.reviewStages,
    }
    const state = await createRun(payload)
    // 全自动任务（未勾选任何审核门）：打标记，工作台据此在完成后自动跳转下载页
    if (form.reviewStages.length === 0) {
      try {
        localStorage.setItem(`autojump:${state.run_id}`, '1')
      } catch {
        /* localStorage 不可用时退回手动跳转 */
      }
    }
    ElMessage.success('任务已创建，流水线已启动')
    await router.push({
      name: 'review',
      params: { runId: state.run_id },
    })
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
  <div class="home-layout">
    <!-- 左栏：研究报告列表 -->
    <aside class="home-left">
      <el-card class="page-card" shadow="never">
        <ProjectTree active-run-id="" />
      </el-card>
    </aside>

    <!-- 右栏：创建任务表单 -->
    <div class="home-page">
      <!-- 页头：标题 + 一句话说明 -->
      <header class="home-header">
        <div>
          <div class="aside-kicker">INDUSTRY RESEARCH</div>
          <div class="title-row">
            <h2 class="page-title home-title">创建行业研究任务</h2>
          </div>
        </div>
        <p class="home-lead muted">
          填写研究对象与研究问题，智能体自动完成数据采集、分析、图表与报告融合，全程可逐阶段审核。
        </p>
      </header>

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
                    placeholder="如：商业航天 / 低空经济 / 固态电池（2-100 字）"
                    maxlength="100"
                    show-word-limit
                  />
                  <div class="topic-presets">
                    <span class="presets-label">热门范例（点击一键预填主题与3个专业问题）：</span>
                    <div class="preset-chips">
                      <button
                        v-for="p in PRESET_TOPICS"
                        :key="p.topic"
                        type="button"
                        class="preset-chip"
                        :class="{ active: form.industryTopic === p.topic }"
                        :data-testid="`preset-${p.topic}`"
                        @click="applyPreset(p)"
                      >
                        <span class="chip-title">{{ p.topic }}</span>
                        <span v-if="p.badge" class="chip-badge">{{ p.badge }}</span>
                      </button>
                    </div>
                  </div>
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
                  <el-input
                    v-model="form.reportingCurrency"
                    placeholder="CNY / USD"
                    maxlength="20"
                  />
                  <div v-if="currencyHints.length" class="tip-line muted">
                    <el-icon><InfoFilled /></el-icon>
                    <template
                      v-if="
                        currencyHints.some(
                          (hint) => hint.currency === form.reportingCurrency.trim().toUpperCase()
                        )
                      "
                    >
                      当前币种与所选市场建议一致（{{
                        currencyHints.map((hint) => `${hint.market}→${hint.currency}`).join('，')
                      }}）
                    </template>
                    <template v-else>
                      已选 {{ currencyHints.map((hint) => hint.market).join('、') }}，建议币种
                      {{ [...new Set(currencyHints.map((hint) => hint.currency))].join('/') }}
                      <el-link type="primary" :underline="false" @click="applySuggestedCurrency"
                        >一键填入</el-link
                      >
                    </template>
                  </div>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item required>
                  <template #label>
                    <div class="field-label-row">
                      <span>市场范围</span>
                      <span class="field-actions">
                        <el-link type="primary" :underline="false" @click="selectAllAvailableMarkets">全选可用</el-link>
                        <span class="divider">/</span>
                        <el-link type="info" :underline="false" @click="form.marketScope = ['中国 A 股']">仅A股</el-link>
                      </span>
                    </div>
                  </template>
                  <el-select
                    v-model="form.marketScope"
                    multiple
                    filterable
                    allow-create
                    default-first-option
                    placeholder="选择或输入市场，如：中国 A 股"
                    style="width: 100%"
                  >
                    <el-option
                      v-for="opt in MARKET_OPTIONS"
                      :key="opt.value"
                      :value="opt.value"
                      :label="opt.label"
                    />
                  </el-select>
                  <div class="tip-line muted">
                    <el-icon><InfoFilled /></el-icon>
                    数据可达性：中国 A 股完整；港股/美股/中国 B
                    股为部分数据（联网补充+缺口披露）；中国台湾/日本/欧洲暂无结构化数据，也可输入自定义市场。
                  </div>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item required>
                  <template #label>
                    <div class="field-label-row">
                      <span>证券类型</span>
                      <span class="field-actions">
                        <el-link type="primary" :underline="false" @click="selectAllSecurityTypes">全选</el-link>
                        <span class="divider">/</span>
                        <el-link type="info" :underline="false" @click="form.securityTypes = ['股票']">仅股票</el-link>
                      </span>
                    </div>
                  </template>
                  <el-select
                    v-model="form.securityTypes"
                    multiple
                    placeholder="选择证券类型"
                    style="width: 100%"
                  >
                    <el-option
                      v-for="st in SECURITY_TYPE_OPTIONS"
                      :key="st"
                      :value="st"
                      :label="st"
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
                    <el-tooltip
                      content="常规篇幅报告，覆盖核心研究维度，生成速度更快"
                      placement="top"
                    >
                      <el-radio value="standard">标准</el-radio>
                    </el-tooltip>
                    <el-tooltip
                      content="全面展开的多章节详析，证据与附录更完整，耗时更长"
                      placement="top"
                    >
                      <el-radio value="deep">深度</el-radio>
                    </el-tooltip>
                  </el-radio-group>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="配图密度">
                  <el-radio-group v-model="form.chartMode">
                    <el-tooltip
                      content="标准精选（12~15张）：核心章节精选关键图表，每章2~3张，图文平衡（推荐）"
                      placement="top"
                    >
                      <el-radio value="standard">标准精选</el-radio>
                    </el-tooltip>
                    <el-tooltip
                      content="详尽全景（18~22张）：多维覆盖全产业链环节与重点龙头横向对标"
                      placement="top"
                    >
                      <el-radio value="rich">详尽全景</el-radio>
                    </el-tooltip>
                    <el-tooltip
                      content="极简摘要（4~6张）：仅保留行业大盘、产业链及核心龙头关键图表，其余表格呈现"
                      placement="top"
                    >
                      <el-radio value="minimal">极简摘要</el-radio>
                    </el-tooltip>
                    <el-tooltip
                      content="纯文与表格（无图表）：跳过图表生成，报告侧重结构化深度表格与文本研报交付"
                      placement="top"
                    >
                      <el-radio value="none">无图表</el-radio>
                    </el-tooltip>
                  </el-radio-group>
                </el-form-item>
              </el-col>
            </el-row>
          </div>

          <!-- 04 高级选项 -->
          <div class="form-section">
            <div class="section-head">
              <span class="section-index">04</span>
              <span class="section-title">审核门</span>
              <span class="muted">可选，默认即可</span>
            </div>
            <el-collapse>
              <el-collapse-item title="人工审核阶段（未勾选的阶段自动通过智能体推荐）" name="gates">
                <el-checkbox-group v-model="form.reviewStages">
                  <el-checkbox
                    v-for="opt in REVIEW_STAGE_OPTIONS"
                    :key="opt.value"
                    :value="opt.value"
                    :label="opt.label"
                  />
                </el-checkbox-group>
                <div class="gate-quick-bar">
                  <el-button
                    size="small"
                    type="primary"
                    plain
                    data-testid="btn-automate-gates"
                    @click="automateGates"
                  >
                    <el-icon style="margin-right: 4px"><Select /></el-icon>
                    一键通过（全自动）
                  </el-button>
                  <span class="muted"
                    >取消全部审核门：各阶段自动通过，中/低风险一并放行并披露，完成后自动进入下载页</span
                  >
                </div>
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
    <!-- /.home-page -->
  </div>
  <!-- /.home-layout -->
</template>

<style scoped>
.home-layout {
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}
.home-left {
  position: sticky;
  top: 16px;
}
.home-page {
  max-width: none;
  min-width: 0;
}
@media (max-width: 1100px) {
  .home-layout {
    grid-template-columns: 1fr;
  }
  .home-left {
    position: static;
  }
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
.title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.home-lead {
  margin: 0 0 4px;
  font-size: 12.5px;
  max-width: 460px;
  line-height: 1.7;
  text-align: right;
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
.gate-quick-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
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
.field-label-row {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
.field-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: normal;
}
.field-actions .divider {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.topic-presets {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.presets-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.preset-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.preset-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 4px;
  border: 1px solid #dcdfe6;
  background: #fdfdfd;
  color: #303133;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s ease-in-out;
}
.preset-chip:hover {
  border-color: #b7791f;
  color: #1e3a5c;
  background: #fffdf9;
  transform: translateY(-1px);
}
.preset-chip.active {
  border-color: #1e3a5c;
  background: #f0f4f8;
  color: #1e3a5c;
  font-weight: 600;
}
.chip-badge {
  font-size: 10px;
  background: #eef2f6;
  color: #4b5563;
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: normal;
}
.preset-chip.active .chip-badge {
  background: #1e3a5c;
  color: #fff;
}
</style>
