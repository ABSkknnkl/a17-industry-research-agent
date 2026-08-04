import api from '@/api'
import type { ReviewRequest, RunCreateRequest, WorkflowState } from '@/types/workflow'

export function createRun(request: RunCreateRequest): Promise<WorkflowState> {
  return api.post<WorkflowState, WorkflowState, RunCreateRequest>('/runs', request)
}

export function getRun(runId: string): Promise<WorkflowState> {
  return api.get<WorkflowState, WorkflowState>(`/runs/${runId}`)
}

export function reviewRun(runId: string, request: ReviewRequest): Promise<WorkflowState> {
  return api.post<WorkflowState, WorkflowState, ReviewRequest>(`/runs/${runId}/reviews`, request)
}
