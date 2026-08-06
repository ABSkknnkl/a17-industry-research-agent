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

export const reviewActions = ['approve', 'revise', 'regenerate', 'cancel'] as const

export type StageName = (typeof stageNames)[number]
export type StageStatus = (typeof stageStatuses)[number]
export type ReviewAction = (typeof reviewActions)[number]

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

export type P0ChartType = 'line' | 'bar' | 'industry_chain'
export type ChartVariant = 'line' | 'vertical' | 'horizontal' | 'grouped' | 'stacked' | 'graph'

export interface ChartReference {
  chart_id: string
  title: string
  chart_type: P0ChartType
  status: 'planned' | 'ready'
  evidence_ids: string[]
  artifact_id: string | null
}

export interface ChartSpec {
  chart_id: string
  title: string
  chart_type: P0ChartType
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
}
