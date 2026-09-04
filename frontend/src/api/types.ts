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

/** ChartGenerationOptions（workflow.py L158-169），全部字段可选 */
export interface ChartGenerationOptions {
  chart_type?: ChartTypeName
  requested_chart_count?: number
  requested_chart_types?: ChartTypeName[]
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
  analysis_depth: AnalysisDepth
  risk_preference: RiskPreference
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
}

export interface ChartCandidate {
  chart_id: string
  chart_type: ChartTypeName
  title?: string
  rationale?: string
}

// ---------- 阶段产出宽松读取（镜像 backend/app/schemas/report.py、chapter.py） ----------

/** report_fusion data.quality（backend ReportQualityReport L162-168） */
export interface ReportQualityReport {
  passed?: boolean
  chapter_count?: number
  section_count?: number
  included_chart_count?: number
  /** 0-1 */
  evidence_coverage?: number
  issues?: string[]
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

/** report_fusion data.source_revisions 条目（backend SourceRevision L149-153） */
export interface SourceRevision {
  stage?: 'data_interpret' | 'chart_generate' | 'chapter_write'
  revision?: number
}

/** report_fusion data 顶层（backend ReportFusionResult L171-191，宽松读取） */
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
