/** Runtime-facing types mirrored from /contracts and guarded by contract tests. */

export const stageNames = [
  'data_fetch',
  'data_interpret',
  'chart_generate',
  'chapter_write',
  'report_fusion',
] as const

export const stageStatuses = [
  'pending',
  'running',
  'waiting_review',
  'approved',
  'rejected',
  'completed',
  'failed',
  'cancelled',
] as const

export const reviewActions = [
  'approve',
  'accept_recommendation',
  'accept_with_risks',
  'customize',
  'revise',
  'regenerate',
  'cancel',
] as const

export type StageName = (typeof stageNames)[number]
export type StageStatus = (typeof stageStatuses)[number]
export type ReviewAction = (typeof reviewActions)[number]

export type RiskSeverity = 'info' | 'warning' | 'high' | 'critical'
export type RiskDisposition = 'advisory' | 'acknowledgement_required' | 'hard_block'
export type DecisionStatus =
  | 'not_required'
  | 'awaiting_user'
  | 'accepted_recommendation'
  | 'accepted_with_risks'
  | 'customized'
  | 'cancelled'

export interface RiskNotice {
  risk_code: string
  stage: string
  severity: RiskSeverity
  disposition: RiskDisposition
  title: string
  detail: string
  affected_ids: string[]
  recommendation: string
  consequence: string
  can_override: boolean
}

export interface ChartCandidateResult {
  candidate_id: string
  title: string
  chart_type: string
  status: string
  recommended_chapter_id: string | null
  alternative_chapter_ids: string[]
  priority: number
  evidence_ids: string[]
  risk_notices: RiskNotice[]
  conflict_group_id: string | null
  chart_id: string | null
  suppression_reason: string | null
}

export interface ConflictGroup {
  conflict_group_id: string
  candidate_ids: string[]
  recommended_candidate_id: string
  reason: string
  risk_if_keep_all: string
}

export interface DecisionPackage {
  decision_id: string
  run_id: string
  stage: string
  revision: number
  all_candidates: ChartCandidateResult[]
  recommended_selection: string[]
  conflict_groups: ConflictGroup[]
  risk_notices: RiskNotice[]
  blocking_risk_codes: string[]
  acknowledgement_required_codes: string[]
  decision_status: DecisionStatus
}

export interface UserDecision {
  decision_id: string
  run_id: string
  owner_id: string
  stage: string
  action: ReviewAction
  selected_chart_ids: string[]
  excluded_chart_ids: string[]
  placement_overrides: Record<string, string>
  accepted_risk_codes: string[]
  release_mode: 'formal' | 'draft_with_warnings'
  comment: string | null
  expected_revision: number
  risk_snapshot_sha256: string
}

export interface ArtifactRef {
  artifact_id: string
  kind: string
  uri: string
  checksum: string | null
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

export const p0ChartTypes = ['line', 'bar', 'pie', 'radar', 'industry_chain'] as const
export const p1ChartTypes = [
  'combo',
  'area',
  'scatter',
  'bubble',
  'heatmap',
  'boxplot',
  'treemap',
] as const
export const chartTypes = [...p0ChartTypes, ...p1ChartTypes] as const
export type P0ChartType = (typeof p0ChartTypes)[number]
export type P1ChartType = (typeof p1ChartTypes)[number]
export type ChartType = (typeof chartTypes)[number]
export type ChartVariant =
  | 'line'
  | 'vertical'
  | 'horizontal'
  | 'grouped'
  | 'stacked'
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

export interface ChartReference {
  chart_id: string
  title: string
  chart_type: ChartType
  status: 'planned' | 'ready'
  evidence_ids: string[]
  artifact_id: string | null
  candidate_status?: string | null
}

export interface ChartSpec {
  chart_id: string
  title: string
  chart_type: ChartType
  variant: ChartVariant
  option: Record<string, unknown>
  evidence_ids: string[]
  data_fingerprint: string
  dedupe_key: string
}

export interface ChartGenerationResult {
  charts: ChartReference[]
  chart_specs: ChartSpec[]
  suppressed_candidates: Array<{
    title: string
    reason_code: string
    reason: string
    evidence_ids: string[]
  }>
  quality: {
    passed: boolean
    ready_count: number
    suppressed_count: number
    issues: string[]
  }
}

export const reportFormats = ['markdown', 'html', 'pdf'] as const
export type ReportFormat = (typeof reportFormats)[number]

export interface ReportArtifactManifestEntry {
  artifact_id: string
  kind: 'report_markdown' | 'report_html' | 'report_pdf' | 'artifact_manifest'
  uri: string
  sha256: string
  size_bytes: number
}

export interface ReportFusionResult {
  report_id: string
  title: string
  industry_topic: string
  research_as_of: string
  generated_at: string
  tone: 'professional' | 'plain_language'
  formats: ReportFormat[]
  source_revisions: Array<{
    stage: 'data_interpret' | 'chart_generate' | 'chapter_write'
    revision: number
  }>
  included_chart_ids: string[]
  artifacts: ReportArtifactManifestEntry[]
  quality: {
    passed: boolean
    chapter_count: number
    section_count: number
    included_chart_count: number
    evidence_coverage: number
    issues: string[]
  }
  release_mode: 'formal' | 'draft_with_warnings'
  formal_eligible: boolean
  draft_eligible: boolean
  acknowledged_risks: string[]
  unresolved_risks: string[]
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

export interface RunCreateRequest {
  project_id: string
  run_id?: string | null
  input_data: Record<string, unknown>
  review_stages: StageName[]
}

export interface ReviewRequest {
  run_id: string
  stage: StageName
  action: ReviewAction
  expected_revision: number
  comment: string | null
  edited_data: Record<string, unknown> | null
  accepted_risk_codes?: string[]
  release_mode?: 'formal' | 'draft_with_warnings'
  selected_chart_ids?: string[]
  placement_overrides?: Record<string, string>
}