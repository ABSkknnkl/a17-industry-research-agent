<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createRun } from '../api/client'
import { ApiError } from '../api/http'
import { showPipelineOverlay, hidePipelineOverlay } from '../composables/usePipelineOverlay'
import {
  STAGE_LABELS,
  type AnalysisDepth,
  type ChartMode,
  type RunCreateRequest,
  type StageName,
} from '../api/types'

const route = useRoute()
const router = useRouter()
const submitting = ref(false)
const researchOptions = ref<HTMLDetailsElement | null>(null)

function todayIso(): string {
  const now = new Date()
  // 研究截止日是用户所在地的日历日期，不能用 UTC ISO 截断（可能落到前一天）。
  return [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0'),
  ].join('-')
}

function randomProjectId(): string {
  return `proj-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

const SECURITY_TYPE_OPTIONS = ['股票', '基金', '期货', '指数']

/** 市场范围选项（value 为提交给后端的纯市场名；label 带可达性备注）。
 * 可达性依据当前接线（问财 hithink_* + L3 博查联网）实测：
 * full=结构化完整；partial=部分数据（联网定性/缺口披露补充）。
 */
interface MarketOption {
  value: string
  label: string
  availability: 'full' | 'partial'
}

const MARKET_OPTIONS: MarketOption[] = [
  { value: '中国 A 股', label: '中国 A 股（沪深北·人民币）', availability: 'full' },
  { value: '港股', label: '港股（港交所）', availability: 'partial' },
  { value: '美股', label: '美股（纽交所/纳斯达克，含中概 ADR）', availability: 'partial' },
  { value: '中国 B 股', label: '中国 B 股（深港币/沪美元）', availability: 'partial' },
]

/** 默认可用市场：中国 A 股 + 港股 + 美股 + 中国 B 股 */
const AVAILABLE_MARKET_OPTIONS = MARKET_OPTIONS.map((opt) => opt.value)
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

export interface SkillOption {
  name: string
  label: string
  desc: string
  category: '产业格局' | '深度财务' | '策略与事件'
}

const SKILL_HUB_OPTIONS: SkillOption[] = [
  {
    name: '竞争格局分析',
    label: '竞争格局分析',
    desc: 'CR4/CR8行业集中度测算、梯队对标矩阵',
    category: '产业格局',
  },
  {
    name: '产业链全景拆解',
    label: '产业链全景拆解',
    desc: '上中下游全环节拆解与价值链利润池流动',
    category: '产业格局',
  },
  {
    name: '财务报表与杜邦分析',
    label: '财务报表与杜邦分析',
    desc: 'ROE杜邦拆解、三表勾稽与盈利质量体检',
    category: '深度财务',
  },
  {
    name: '科技炒作与基本面',
    label: '科技炒作与基本面',
    desc: 'Gartner技术成熟度、泡沫甄别与量产商业化',
    category: '策略与事件',
  },
  {
    name: '估值环境与可比分析',
    label: '估值环境与可比',
    desc: '历史PE/PB分位数、可比公司相对估值',
    category: '深度财务',
  },
  {
    name: '宏观周期与政策研判',
    label: '宏观周期与政策',
    desc: '宏观流动性环境、产业政策支持与周期位置',
    category: '产业格局',
  },
  {
    name: '公司事件与催化剂',
    label: '公司事件与催化剂',
    desc: '重大产业会议、新品发布与关键业绩窗口',
    category: '策略与事件',
  },
  {
    name: '风险分析与压力测试',
    label: '风险分析与压力测试',
    desc: '关税汇率波动、原材料成本与需求下行测算',
    category: '深度财务',
  },
]

const DEFAULT_SELECTED_SKILLS = [
  '竞争格局分析',
  '产业链全景拆解',
  '财务报表与杜邦分析',
  '科技炒作与基本面',
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
  // A3 用户问题驱动选图：默认 off 与后端全局默认一致。
  // observe 档（2026-11-16 删）：产物与 off 逐字节一致且无展示入口，前端只暴露两档；
  // 后端 API 契约仍接受 observe（高级场景可直连）。
  questionPlannerMode: 'off' as 'off' | 'apply',
  selectedSkills: [...DEFAULT_SELECTED_SKILLS] as string[],
  competitionDelivery: false,
  reviewStages: [
    'data_fetch',
    'data_interpret',
    'chart_generate',
    'chapter_write',
    'report_fusion',
  ] as StageName[],
})

function toggleSkill(name: string, checked: boolean): void {
  if (checked) {
    if (!form.selectedSkills.includes(name)) form.selectedSkills.push(name)
  } else {
    form.selectedSkills = form.selectedSkills.filter((s) => s !== name)
  }
}

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

function validate(): { message: string; openResearchOptions?: true } | null {
  const topic = form.industryTopic.trim()
  if (topic.length < 2 || topic.length > 100) {
    return { message: '行业主题长度需在 2-100 个字符之间' }
  }
  const questions = splitLines(form.focusQuestionsText)
  if (questions.length < 1) return { message: '请至少填写一个研究问题' }
  if (questions.length > 12) return { message: '研究问题最多 12 个' }
  if (questions.some((q) => q.length > 1000)) return { message: '单个研究问题不能超过 1000 字' }
  if (form.marketScope.length < 1) {
    return { message: '请至少填写一个市场范围', openResearchOptions: true }
  }
  if (form.securityTypes.length < 1) {
    return { message: '请至少选择一种证券类型', openResearchOptions: true }
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(form.researchAsOf)) {
    return { message: '研究时点格式应为 YYYY-MM-DD', openResearchOptions: true }
  }
  return null
}

async function submit(): Promise<void> {
  const problem = validate()
  if (problem) {
    if (problem.openResearchOptions && researchOptions.value) {
      researchOptions.value.open = true
    }
    ElMessage.warning(problem.message)
    return
  }
  const limited = form.marketScope.filter((market) => {
    const opt = MARKET_OPTIONS.find((item) => item.value === market)
    return opt != null && opt.availability !== 'full'
  })
  if (limited.length > 0) {
    ElMessage.info(
      `已选境外市场（${limited.join('、')}），系统将重点对标核心龙头行情与中概对标标的`
    )
  }
  submitting.value = true
  showPipelineOverlay('data_fetch', '创建任务')
  try {
    const payload: RunCreateRequest = {
      project_id: randomProjectId(),
      ...(form.competitionDelivery ? { delivery_profile: 'competition' } : {}),
      input_data: {
        industry_topic: form.industryTopic.trim(),
        market_scope: form.marketScope,
        security_types: form.securityTypes,
        reporting_currency: 'CNY',
        research_as_of: form.researchAsOf,
        focus_questions: splitLines(form.focusQuestionsText),
        analysis_depth: form.analysisDepth,
        chart_generate_options: {
          chart_mode: form.chartMode,
          allow_multiple_charts_per_dataset: form.chartMode === 'rich',
          question_planner_mode: form.competitionDelivery ? 'apply' : form.questionPlannerMode,
        },
        selected_skills: form.selectedSkills,
      },
      review_stages: form.competitionDelivery ? ['report_fusion'] : form.reviewStages,
    }
    const state = await createRun(payload)
    // 全自动任务（未勾选任何审核门）：打标记，工作台据此在完成后自动跳转下载页
    if (payload.review_stages.length === 0) {
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
  <div class="home-page">
    <header class="home-header">
      <h1 class="page-title home-title">创建行业研究任务</h1>
      <p class="home-lead muted">填写行业主题与研究问题，启动研报生成流程。</p>
    </header>

    <!-- 表单主体 -->
    <el-card class="page-card" shadow="never">
      <el-form label-position="top">
        <section class="form-section" aria-labelledby="research-brief">
          <div class="section-head">
            <h2 id="research-brief" class="section-title">研究主题与问题</h2>
            <span class="section-line" />
          </div>
          <el-form-item label="行业主题" required>
            <el-input
              v-model="form.industryTopic"
              placeholder="如：商业航天、低空经济"
              maxlength="100"
              show-word-limit
            />
            <div class="topic-presets">
              <span class="presets-label">热门范例 · 预填主题和研究问题</span>
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
          <el-form-item label="每行一个问题（1-12 个）" required>
            <el-input
              v-model="form.focusQuestionsText"
              type="textarea"
              :rows="5"
              maxlength="2000"
              show-word-limit
              placeholder="如：2024—2025 年动力电池行业营收增速如何？"
            />
          </el-form-item>
          <div class="tip-line muted">
            <el-icon><InfoFilled /></el-icon>
            建议每个问题写明研究对象、时间范围和指标。
          </div>
        </section>

        <details ref="researchOptions" class="research-options">
          <summary>
            研究范围与分析偏好
            <span class="muted options-summary">
              {{ form.marketScope.length }} 个市场 ·
              {{ form.analysisDepth === 'deep' ? '深度分析' : '标准分析' }}
            </span>
          </summary>
          <div class="options-body">
            <section class="form-section" aria-labelledby="research-scope">
              <div class="section-head">
                <h2 id="research-scope" class="section-title">研究范围</h2>
                <span class="section-line" />
              </div>
              <el-row :gutter="16">
                <el-col :xs="24" :sm="12" :md="10">
                  <el-form-item required>
                    <template #label>
                      <div class="field-label-row">
                        <span>市场范围</span>
                        <span class="field-actions">
                          <el-link
                            type="primary"
                            :underline="false"
                            @click="selectAllAvailableMarkets"
                            >全选可用</el-link
                          >
                          <span class="divider">/</span>
                          <el-link
                            type="info"
                            :underline="false"
                            @click="form.marketScope = ['中国 A 股']"
                            >仅A股</el-link
                          >
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
                      数据可达性：中国 A 股提供全套三表与行情；港股/美股/中国 B
                      股提供代表性标的行情与对标数据。
                    </div>
                  </el-form-item>
                </el-col>
                <el-col :xs="24" :sm="12" :md="8">
                  <el-form-item required>
                    <template #label>
                      <div class="field-label-row">
                        <span>证券类型</span>
                        <span class="field-actions">
                          <el-link type="primary" :underline="false" @click="selectAllSecurityTypes"
                            >全选</el-link
                          >
                          <span class="divider">/</span>
                          <el-link
                            type="info"
                            :underline="false"
                            @click="form.securityTypes = ['股票']"
                            >仅股票</el-link
                          >
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
                <el-col :xs="24" :sm="12" :md="6">
                  <el-form-item label="研究时点" required>
                    <el-date-picker
                      v-model="form.researchAsOf"
                      type="date"
                      value-format="YYYY-MM-DD"
                      style="width: 100%"
                    />
                    <div class="tip-line muted">
                      <el-icon><InfoFilled /></el-icon>
                      报告基准币种为人民币（CNY）。
                    </div>
                  </el-form-item>
                </el-col>
              </el-row>
            </section>

            <div class="form-section">
              <div class="section-head">
                <h2 class="section-title">分析偏好</h2>
                <span class="section-line" />
              </div>
              <el-row :gutter="16">
                <el-col :xs="24" :sm="12">
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
                <el-col :xs="24" :sm="12">
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
                  <el-form-item label="问题驱动选图">
                    <el-radio-group v-model="form.questionPlannerMode">
                      <el-tooltip
                        content="关闭（默认）：按行业通用选图策略，行为与历史版本一致"
                        placement="top"
                      >
                        <el-radio value="off">关闭</el-radio>
                      </el-tooltip>
                      <el-tooltip
                        content="应用模式：按研究问题驱动选图与排序，报告末尾附「研究问题与结论索引」（需至少 1 个研究问题）"
                        placement="top"
                      >
                        <el-radio value="apply">应用模式</el-radio>
                      </el-tooltip>
                    </el-radio-group>
                  </el-form-item>
                </el-col>
              </el-row>

              <!-- 问财 SkillHub 投研技能挂载 -->
              <div class="skillhub-mount-box">
                <div class="skillhub-mount-title">
                  <span class="skillhub-tag">问财 SkillHub</span>
                  <span>投研分析技能挂载（已选 {{ form.selectedSkills.length }} 项）：</span>
                  <span class="muted skillhub-hint"
                    >智能体将优先调用所选技能专属方法论推演事实与研报章节</span
                  >
                </div>
                <div class="skillhub-chips">
                  <el-check-tag
                    v-for="skill in SKILL_HUB_OPTIONS"
                    :key="skill.name"
                    :checked="form.selectedSkills.includes(skill.name)"
                    class="skill-chip"
                    @change="(val: boolean) => toggleSkill(skill.name, val)"
                  >
                    <span class="skill-name">{{ skill.label }}</span>
                    <span class="skill-cat">[{{ skill.category }}]</span>
                  </el-check-tag>
                </div>
              </div>
            </div>
          </div>
        </details>

        <div class="form-section">
          <div class="section-head">
            <h2 class="section-title">审核设置</h2>
            <span class="section-line" />
            <span class="muted"
              >已选
              {{ form.competitionDelivery ? 1 : form.reviewStages.length }} 个人工审核阶段</span
            >
          </div>
          <el-checkbox v-model="form.competitionDelivery" data-testid="competition-delivery">
            比赛交付模式
          </el-checkbox>
          <p v-if="form.competitionDelivery" class="gate-hint muted">
            只保留报告终审。图数允许少于目标，核心数据、引用和导出仍须核验。
          </p>
          <el-collapse v-else>
            <el-collapse-item title="选择人工审核阶段" name="gates">
              <p class="gate-hint muted">未勾选的阶段按自动审核规则推进。</p>
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
            创建并启动任务
          </el-button>
          <span class="muted">创建后进入任务工作台查看进度。</span>
        </div>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.home-page {
  max-width: 1000px;
  margin: 0 auto;
}
.home-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 6px 16px;
  border-bottom: 3px double var(--rp-navy);
  padding-bottom: 12px;
  margin-bottom: 14px;
}
.home-title {
  font-size: 24px;
  margin: 0;
}
.home-lead {
  margin: 0;
  font-size: 13px;
  line-height: 1.7;
}
.form-section {
  margin-bottom: 18px;
}
.research-options {
  margin-bottom: 18px;
  border-top: 1px solid var(--el-border-color-light);
  border-bottom: 1px solid var(--el-border-color-light);
}
.research-options > summary {
  cursor: pointer;
  padding: 10px 0;
  color: var(--rp-navy);
  font-weight: 600;
  font-size: 14px;
}
.options-summary {
  margin-left: 10px;
  font-weight: 400;
}
.options-body {
  padding-top: 8px;
}
.section-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 12px;
}
.section-title {
  margin: 0;
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
  align-items: baseline;
  gap: 5px;
  margin-top: 4px;
  line-height: 1.6;
}
.tip-line :deep(.el-icon) {
  flex-shrink: 0;
}
.gate-quick-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}
.gate-hint {
  margin: 0 0 4px;
}
.submit-row {
  margin-top: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}
@media (max-width: 680px) {
  .submit-row {
    flex-direction: column;
    align-items: stretch;
    text-align: center;
  }
  .home-page :deep(.el-radio),
  .home-page :deep(.el-checkbox) {
    margin-right: 16px;
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

.skillhub-mount-box {
  margin-top: 14px;
  padding: 10px 14px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}
.skillhub-mount-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--rp-navy, #1e3a5c);
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.skillhub-tag {
  font-size: 10px;
  font-weight: 700;
  background: #e0f2fe;
  color: #0369a1;
  padding: 1px 6px;
  border-radius: 4px;
}
.skillhub-hint {
  font-size: 11px;
  font-weight: normal;
  color: #64748b;
}
.skillhub-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.skill-chip {
  cursor: pointer;
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: 4px;
}
.skill-cat {
  font-size: 10px;
  opacity: 0.75;
}
</style>
