import api from '@/api'
import type {
  ReviewRequest,
  RevisionListResponse,
  RunCreateRequest,
  RunListResponse,
  WorkflowState,
} from '@/types/workflow'

export function createRun(request: RunCreateRequest): Promise<WorkflowState> {
  return api.post<WorkflowState, WorkflowState, RunCreateRequest>('/runs', request)
}

export function getRun(runId: string): Promise<WorkflowState> {
  return api.get<WorkflowState, WorkflowState>(`/runs/${runId}`)
}

export function listRuns(params: { offset: number; limit: number }): Promise<RunListResponse> {
  return api.get<RunListResponse, RunListResponse>('/runs', { params })
}

export function listRunRevisions(runId: string): Promise<RevisionListResponse> {
  return api.get<RevisionListResponse, RevisionListResponse>(`/runs/${runId}/revisions`)
}

export function getRunRevision(runId: string, revision: number): Promise<WorkflowState> {
  return api.get<WorkflowState, WorkflowState>(`/runs/${runId}/revisions/${revision}`)
}

export function reviewRun(runId: string, request: ReviewRequest): Promise<WorkflowState> {
  return api.post<WorkflowState, WorkflowState, ReviewRequest>(`/runs/${runId}/reviews`, request)
}

export function downloadArtifact(runId: string, artifactId: string): Promise<Blob> {
  return api.get<Blob, Blob>(`/runs/${runId}/artifacts/${artifactId}`, {
    responseType: 'blob',
  })
}
