/**
 * 后端契约类型定义（镜像 backend/app/schemas/*.py，extra=forbid）。
 * 字段名与后端完全一致，勿自创字段。
 */

// ---------- 枚举（backend/app/schemas/workflow.py L14-40） ----------

export type StageName =
  'data_fetch' | 'data_interpret' | 'chart_generate' | 'chapter_write' | 'report_fusion'

export const STAGE_ORDER: StageName[] = [
  'data_fetch',
  'data_interpret',
  'chart_generate',
  'chapter_write',
  'report_fusion',
]

export const STAGE_LABELS: Record<StageName, string> = {
  data_fetch: '数据采集',
  data_interpret: '数据解读',
  chart_generate: '图表生成',
  chapter_write: '章节撰写',
  report_fusion: '报告融合',
}

export type StageStatus =
  | 'pending'
  | 'running'
  | 'waiting_review'
  | 'approved'
  | 'rejected'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type ReviewAction =
  | 'approve'
  | 'accept_recommendation'
  | 'accept_with_risks'
  | 'customize'
  | 'revise'
  | 'regenerate'
  | 'cancel'

// ---------- 运行时状态（workflow.py L47-110） ----------

export interface ArtifactRef {
  artifact_id: string
  kind: string
  uri: string
  checksum?: string | null
  revision: number
}

/**
 * 产物下载只需的字段子集。
 * 融合产物清单（ReportArtifactManifestEntry）没有 revision，
 * 用这个类型可直接复用下载链路，不必伪造 revision。
 */
export type DownloadableArtifact = Pick<ArtifactRef, 'artifact_id' | 'uri'>

export interface StageResult {
  stage: StageName
  status: StageStatus
  revision: number
  data: Record<string, unknown>
  artifacts: ArtifactRef[]
  evidence_sources: string[]
  error: string | null
}

export interface WorkflowState {
  project_id: string
  run_id: string
  current_stage: StageName
  status: StageStatus
  revision: number
  stage_results: Partial<Record<StageName, StageResult>>
  created_at: string
  updated_at: string
}

export interface RunSummary {
  run_id: string
  project_id: string
  title: string
  current_stage: StageName
  status: StageStatus
  revision: number
  created_at: string
  updated_at: string
  artifact_count: number
  report_available: boolean
}

export interface RunListResponse {
  total: number
  offset: number
  limit: number
  items: RunSummary[]
}

export interface RevisionSummary {
  revision: number
  status: StageStatus
  current_stage: StageName
  updated_at: string
}

export interface RevisionListResponse {
  run_id: string
  current_revision: number
  revisions: RevisionSummary[]
}

// ---------- 创建任务（run.py） ----------

export type AnalysisDepth = 'overview' | 'standard' | 'deep'
export type RiskPreference = 'conservative' | 'balanced' | 'aggressive'

/** DataFetchOptions（workflow.py L132-137），全部字段可选 */
export interface DataFetchOptions {
  keywords?: string[]
  industry_scope?: string[]
  time_range?: string[]
  data_sources?: string[]
  metrics?: string[]
}

/** ResearchBrief（analysis.py L46-56），全部字段可选 */
export interface ResearchBrief {
  geography?: string
  time_range?: string
  included_topics?: string[]
  excluded_topics?: string[]
  focus_companies?: string[]
  report_depth?: 'brief' | 'standard' | 'deep'
}

export type ChartTypeName =
  | 'line'
  | 'bar'
  | 'comparison_bar'
  | 'pie'
  | 'radar'
  | 'industry_chain'
  | 'combo'
  | 'area'
  | 'scatter'
  | 'bubble'
  | 'heatmap'
  | 'boxplot'
  | 'treemap'

/** Agent 3 目前允许新生成的六种图表风格。 */
export type ActiveChartTypeName = 'line' | 'bar' | 'combo' | 'area' | 'pie' | 'radar'

// ---------- 图表公开契约（contracts/schemas/chart-generation-result.schema.json） ----------

export type ChartVariant =
  | 'line'
  | 'vertical'
  | 'horizontal'
  | 'grouped'
  | 'stacked'
  | 'comparison_bar'
  | 'pie'
  | 'radar'
  | 'graph'
  | 'combo'
  | 'area'
  | 'scatter'
  | 'bubble'
  | 'heatmap'
  | 'boxplot'
  | 'treemap'
  | 'dual_panel'

export interface ChartPanel {
  panel_id: string
  position: 'left' | 'right'
  series: string[]
  axis_name?: string | null
}

export interface ChartAnnotation {
  annotation_type: 'reference_line' | 'shaded_region' | 'callout'
  label: string
  value?: number | null
  start?: string | null
  end?: string | null
  series?: string | null
}

/** 完整 ECharts 配置直接透传；footnotes 为后端附加的原文说明。 */
export interface ChartOption extends Record<string, unknown> {
  footnotes?: string[]
}

interface ChartMetadata {
  chart_id: string
  title: string
  chart_type: ChartTypeName
  user_requested?: boolean
  requested_chart_type?: ChartTypeName | null
  resolution_reason?: string | null
  evidence_ids: string[]
  insight_goal?: string | null
  quality_issue_ids?: string[]
  footnotes?: string[]
}

interface ChartSpecBase extends ChartMetadata {
  variant: ChartVariant
  /** 布局分类（后端 chart_generate 按数据量下发）：full 长图表独占一行，half 小图表每行两个。缺省时前端按数据量兜底估算。 */
  display_size?: 'full' | 'half'
  option: ChartOption
  panels?: ChartPanel[] | null
  annotations?: ChartAnnotation[] | null
  data_fingerprint: string
  dedupe_key: string
  /** 卡片展示字段：真实后端 Phase2 前可能缺失，UI 须降级不显示 */
  unit_revision?: number
  source_name?: string | null
  updated_at?: string | null
}

interface ChartImageMetadata {
  image_uri?: string | null
  image_mime_type?: 'image/png' | 'image/webp' | 'image/jpeg' | null
  generation_prompt?: string | null
  generation_prompt_model?: string | null
  generation_image_model?: string | null
  chain_template?: 'product_decomposition' | 'horizontal_flow' | null
  chain_graph?: Record<string, unknown> | null
}

export type ChartSpec = ChartSpecBase &
  (
    | ({ render_mode?: 'echarts' } & ChartImageMetadata)
    | ({ render_mode: 'generated_image'; chart_type: 'industry_chain' } & {
        [K in keyof ChartImageMetadata]-?: NonNullable<ChartImageMetadata[K]>
      })
  )

interface ChartReferenceBase extends ChartMetadata {
  recommended_chapter_id?: string | null
  candidate_status?:
    | 'valid'
    | 'recommended'
    | 'not_recommended'
    | 'selected'
    | 'excluded_by_user'
    | 'hard_blocked'
    | 'needs_reassignment'
    | null
}

export type ChartReference = ChartReferenceBase &
  ({ status: 'planned'; artifact_id?: string | null } | { status: 'ready'; artifact_id: string })

/** 确定性机器检查提示，不代表人工视觉审核，也不改变 passed 发布门槛。 */
export interface ChartReviewChecklist {
  five_second_readable?: boolean
  axis_not_misleading?: boolean
  key_point_highlighted?: boolean
}

export interface ChartQualityReport {
  passed: boolean
  ready_count: number
  suppressed_count: number
  issues: string[]
  review_checklist?: ChartReviewChecklist
}

export interface ChartGenerationResult {
  charts: ChartReference[]
  chart_specs: ChartSpec[]
  suppressed_candidates: {
    title: string
    reason_code: string
    reason: string
    evidence_ids: string[]
  }[]
  quality: ChartQualityReport
  decision_package?: Record<string, unknown> | null
  /** 审核反馈路径在模型序列化后附加的审计字段。 */
  feedback_interpretation?: ChartFeedbackInterpretation
  applied_feedback_edits?: { op: string; value: string; resolved_value: string | null }[]
}

export interface ChartFeedbackInterpretation {
  stage: string
  original_feedback: string
  outcomes?: {
    op: string
    value: string
    resolved_value?: string | null
    confidence: number
    reason?: string
    status: 'applied' | 'pending_review' | 'rejected'
    reject_reason?: string | null
  }[]
  unparsed_text?: string | null
  clarification_question?: string | null
  parser_mode?: 'llm' | 'fallback'
  warnings?: string[]
}

/** ChartGenerationOptions（workflow.py L158-169），全部字段可选 */
export interface ChartGenerationOptions {
  chart_type?: ActiveChartTypeName
  requested_chart_count?: number
  requested_chart_types?: ActiveChartTypeName[]
  user_priority?: boolean
  allow_multiple_charts_per_dataset?: boolean
  bar_variant?: 'vertical' | 'horizontal' | 'grouped' | 'stacked'
  metric_ids?: string[]
  title?: string
  color_theme?: string
  emphasis?: string
}

export interface ResearchInput {
  industry_topic: string
  market_scope: string[]
  security_types: string[]
  reporting_currency?: string
  /** ISO 日期：YYYY-MM-DD */
  research_as_of: string
  focus_questions: string[]
  data_fetch_options?: DataFetchOptions
  /** 后端默认 standard，可不传 */
  analysis_depth?: AnalysisDepth
  /** 后端默认 balanced，可不传（首页已改用「图表选择」，不再提供风险偏好 UI） */
  risk_preference?: RiskPreference
  research_brief?: ResearchBrief
  chart_generate_options?: ChartGenerationOptions
}

export interface RunCreateRequest {
  project_id: string
  input_data: ResearchInput
  review_stages: StageName[]
}

// ---------- 审核请求（workflow.py L202-214） ----------

export type ReleaseMode = 'formal' | 'draft_with_warnings'

/** 各阶段 data.decision_package 的形状（agent service 填充） */
export interface DecisionPackage {
  decision_id: string
  run_id: string
  revision: number
  stage: string
  risk_notices?: Array<Record<string, unknown>>
  blocking_risk_codes?: string[]
  acknowledgement_required_codes?: string[]
  risk_snapshot_sha256?: string
}

export interface ReviewRequest {
  run_id: string
  stage: StageName
  action: ReviewAction
  expected_revision: number
  comment?: string | null
  /** 必须符合该阶段的 ReviewEdits 白名单，否则 422 */
  edited_data?: Record<string, unknown> | null
  accepted_risk_codes?: string[]
  release_mode?: ReleaseMode
  selected_chart_ids?: string[] | null
  decision_id?: string | null
  risk_snapshot_sha256?: string | null
}

// ---------- 阶段产出 digest 中的常用结构（宽松读取） ----------

export interface IntentSubRequirement {
  description?: string
  candidate_skills?: string[]
  confidence?: number
}

export interface IntentPlan {
  requires_clarification?: boolean
  confidence?: number
  clarification_questions?: string[]
  sub_requirements?: IntentSubRequirement[]
}

export interface IntentRouting {
  strategy?: string
  enabled?: boolean
  clarification_required?: boolean
  plans?: Record<string, IntentPlan>
}

export interface CollaborationRequest {
  request_id?: string
  question?: string
  reason?: string
  affected_dimensions?: string[]
}

export interface Claim {
  claim_id?: string
  statement?: string
  evidence_ids?: string[]
  dimension?: string
  confidence?: number
}

export interface DimensionCoverage {
  dimension?: string
  status?: string
  reason?: string
  /** 后端下发的中文维度名（contracts/display-labels.json），缺省时前端用本地映射兜底 */
  dimension_label?: string
  /** 后端下发的中文状态（contracts/display-labels.json），缺省时前端用本地映射兜底 */
  status_label?: string
}

export interface ChartCandidate {
  chart_id: string
  chart_type: ChartTypeName
  title?: string
  rationale?: string
}

// ---------- 阶段产出宽松读取（镜像 backend/app/schemas/report.py、chapter.py） ----------

/** 单维度评分明细（backend ScoreBreakdownItem） */
export interface ScoreBreakdownItem {
  /** 稳定英文标识：structure/evidence_coverage/citation_consistency/dimension_coverage/risk_disclosure */
  dimension?: string
  score?: number
  weight?: number
  max_score?: number
  reason?: string
}

/** 分数档阈值（backend QualityThresholds）：total_score ≥ good 优、≥ warn 警示 */
export interface QualityThresholds {
  good?: number
  warn?: number
}

/** report_fusion data.quality（backend ReportQualityReport） */
export interface ReportQualityReport {
  passed?: boolean
  chapter_count?: number
  section_count?: number
  included_chart_count?: number
  /** 0-1 */
  evidence_coverage?: number
  issues?: string[]
  /**
   * 评分基准（分母），由后端下发。前端不得写死 7 / 21 —— 后端改大纲时前端自动跟随。
   * 历史 run 无此字段时前端兜底（见 QualityPanel）。
   */
  expected_chapter_count?: number
  expected_section_count?: number
  /**
   * 总分 100 评分模型（2026-09-19 方案）：后端确定性产出，前端只渲染、不再自行平均。
   * 历史 run 无这些字段时前端兜底（见 QualityPanel）。
   */
  total_score?: number
  score_breakdown?: ScoreBreakdownItem[]
  thresholds?: QualityThresholds
}

/** report_fusion data.artifacts 条目（backend ReportArtifactManifestEntry L154-159） */
export interface ReportArtifactManifestEntry {
  artifact_id?: string
  kind?: ReportArtifactKind
  uri?: string
  size_bytes?: number
}

export type ReportArtifactKind =
  'report_markdown' | 'report_html' | 'report_pdf' | 'artifact_manifest'

export type DeliveryStatus = 'ready' | 'ready_with_limits' | 'blocked'

export type VisualStyle = 'data_manual' | 'analysis_note' | 'deep_research'

/** report_fusion data.visual_decision.per_chapter_strategy 条目 */
export interface ChapterVisualStrategyLoose {
  chart_count?: number
  table_candidate_count?: number
  dominant_content?:
    | 'narrative'
    | 'time_series'
    | 'comparison'
    | 'financial_detail'
    | 'industry_chain'
    | 'risk'
    | 'scenario'
    | 'summary'
}

/**
 * report_fusion data.visual_decision（backend VisualDecision）。
 * 契约要求「后端 Pydantic 模型、前端 TS 类型、Mock 数据保持一致」，故此处完整镜像；
 * 当前前端不消费该字段（仅报告 HTML 的 body class 体现），保留类型以备后续使用。
 */
export interface VisualDecisionLoose {
  recommended_style?: VisualStyle
  requested_style?: 'auto' | VisualStyle
  effective_style?: VisualStyle
  selection_source?: 'user' | 'agent_recommendation' | 'default'
  density?: 'compact' | 'balanced' | 'detailed'
  chart_density?: 'low' | 'medium' | 'high'
  table_priority?: 'low' | 'medium' | 'high'
  recommendation_reasons?: string[]
  override_warnings?: string[]
  per_chapter_strategy?: Record<string, ChapterVisualStrategyLoose>
}

/** report_fusion data.source_revisions 条目（backend SourceRevision L149-153） */
export interface SourceRevision {
  stage?: 'data_interpret' | 'chart_generate' | 'chapter_write'
  revision?: number
}

/** report_fusion data.evidence_catalog 条目（报告末尾来源清单，实测字段） */
export interface EvidenceCatalogEntry {
  citation_number?: number
  display_label?: string
  material_title?: string
  publishers?: string[]
  source_levels?: string[]
  audit_labels?: string[]
  locators?: string[]
  metric_names?: string[]
  reporting_periods?: string[]
  retrieval_methods?: string[]
  available_dates?: string[]
  scopes?: string[]
  evidence_ids?: string[]
}

/** report_fusion data.charts 条目：已嵌入报告的图表，svg 为内联矢量图 */
export interface FusionChartLoose {
  chart_id?: string
  title?: string
  chart_type?: string
  svg?: string
  evidence_ids?: string[]
  footnotes?: string[]
  insight_goal?: string
  placement_section_id?: string
  quality_issue_ids?: string[]
}

/** report_fusion data.quality_appendix（数据质量 / 维度覆盖 / 财务一致性 / 跳过图表） */
export interface ReportQualityAppendix {
  data_quality_issues?: Array<{
    issue_id?: string
    issue_type?: string
    metric?: string
    description?: string
    impact_level?: string
    suggested_handling?: string
    affected_dimensions?: string[]
    evidence_ids?: string[]
  }>
  dimension_coverage?: DimensionCoverage[]
  financial_consistency_checks?: Array<Record<string, unknown>>
  skipped_chart_notes?: Array<Record<string, unknown> | string>
}

/** report_fusion data 顶层（backend ReportFusionResult，宽松读取） */
export interface ReportFusionData {
  report_id?: string
  title?: string
  industry_topic?: string
  research_as_of?: string
  generated_at?: string
  tone?: 'professional' | 'plain_language'
  report_depth?: 'brief' | 'standard' | 'deep'
  delivery_status?: DeliveryStatus
  formats?: Array<'markdown' | 'html' | 'pdf'>
  included_chart_ids?: string[]
  artifacts?: ReportArtifactManifestEntry[]
  quality?: ReportQualityReport
  release_mode?: 'formal' | 'draft_with_warnings'
  unresolved_risks?: string[]
  source_revisions?: SourceRevision[]
  /**
   * 融合后的章节结构（后端 FusionChapterOutline：仅 id/title + 小节 id/title）。
   * 前端目录按此**原样**渲染，不做任何标题改写 —— 后端给什么就显示什么。
   */
  chapters?: ChapterDraftLoose[]
  /** 大纲版本（chapter_writer 的 OUTLINE_VERSION），溯源用 */
  outline_version?: string
  /** 视觉编排决策（后端实际下发；前端当前不消费，契约要求类型保持一致） */
  visual_decision?: VisualDecisionLoose
  /** 研究意图（后端 ReportDecisionBrief：focus_questions/聚焦公司等） */
  decision_brief?: {
    focus_questions?: string[]
    included_topics?: string[]
    excluded_topics?: string[]
    focus_companies?: string[]
    editorial_instruction?: string | null
  }
  /** 编辑计划（Agent5 可选编辑模型输出；关闭时为 null/缺省） */
  editorial_plan?: unknown
  /** 页面组合计划（确定性派生，缺省为 null） */
  page_composition_plan?: unknown
  /** 视觉复检摘要（Agent5 可选视觉模型/确定性检查输出） */
  visual_review?: {
    passed?: boolean
    score?: number
    critical_count?: number
    major_count?: number
    minor_count?: number
    review_rounds?: number
    degraded?: boolean
  } | null
  /** 报告蓝图（编辑→渲染交接对象，缺省为 null） */
  report_blueprint?: unknown
  /** 已嵌入报告的图表清单 */
  charts?: FusionChartLoose[]
  /** 报告末尾的来源清单：条数即「引用证据」数 */
  evidence_catalog?: EvidenceCatalogEntry[]
  /** 质量附录 */
  quality_appendix?: ReportQualityAppendix
  /** 免责声明与融合方法说明 */
  disclaimer?: string
  methodology_note?: string
}

/** chapter_write data.chapters 条目（backend ChapterDraft L152-161，宽松读取） */
export interface ChapterDraftLoose {
  chapter_id?: string
  title?: string
  summary?: string
  sections?: Array<{
    section_id?: string
    title?: string
    paragraphs?: Array<{ text?: string }>
  }>
}

// ---------- 原型对象级类型（仅 Mock 演示使用） ----------

export type EvidenceStatus = 'active' | 'excluded' | 'provisional'
export type EvidenceCategory = 'company' | 'industry' | 'tech' | 'opinion'
export type ClaimStatus = 'active' | 'provisional' | 'rejected' | 'evidence_insufficient'
export type ChartStatus = 'active' | 'provisional' | 'deleted' | 'running'
export type ParagraphStatus = 'active' | 'provisional'

export interface EvidenceItem {
  evidence_id: string
  title: string
  source_type: EvidenceCategory
  publisher: string
  as_of_date: string
  summary: string
  url_hint: string
  status: EvidenceStatus
  exclude_reason?: string | null
}

export interface ClaimItem {
  claim_id: string
  statement: string
  dimension: string
  evidence_ids: string[]
  counter_condition: string
  status: ClaimStatus
  reject_reason?: string | null
}

export interface ChartItem {
  chart_id: string
  title: string
  chart_type: ChartTypeName
  template: string
  color_theme: string
  unit_revision: number
  in_report: boolean
  status: ChartStatus
  render_mode: 'echarts' | 'svg'
  option?: Record<string, unknown>
  svg?: string
  compatible_templates: string[]
  insight_goal: string
}

export interface ParagraphItem {
  paragraph_id: string
  section_id: string
  text: string
  version: number
  status: ParagraphStatus
  history: Array<{ version: number; text: string }>
  diff?: { before: string; after: string; lines: string[] } | null
}

export interface SectionItem {
  section_id: string
  title: string
  paragraphs: ParagraphItem[]
}

export interface ChapterItem {
  chapter_id: string
  title: string
  order: number
  upstream_hint?: string | null
  sections: SectionItem[]
}

export interface ArtifactItem {
  artifact_id: string
  kind: ReportArtifactKind
  uri: string
  revision: number
  format_label: string
  generated_at_label: string
  content: string
}

export interface RiskItem {
  risk_code: string
  title: string
  description: string
  requires_ack: boolean
  stage: StageName
  acknowledged: boolean
}

export interface PrototypeOperation {
  id: string
  action: string
  object_id: string
  summary: string
  at: string
}

export interface PrototypeRevision {
  revision: number
  status: StageStatus
  current_stage: StageName
  updated_at: string
  note: string
}

export interface ActionReceipt {
  action: string
  object_id: string | null
  before_revision: number
  after_revision: number
  ok: boolean
  message: string
  affected: string[]
}

export type QueueFilter = 'all' | 'pending' | 'done'

export interface PrototypeStage {
  status: StageStatus
  revision: number
  produced: boolean
}

export type ReportSettings = {
  tone: 'professional' | 'plain'
  depth: 'brief' | 'standard' | 'deep'
  chart_density: 'compact' | 'balanced' | 'rich'
  formats: Array<'markdown' | 'html' | 'pdf'>
  summary_length: 'short' | 'standard' | 'long'
}
