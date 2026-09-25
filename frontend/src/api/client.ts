import { http, API_BASE_URL } from './http'
import type {
  AgentTraceEvent,
  DownloadableArtifact,
  RevisionListResponse,
  ReviewRequest,
  RunCreateRequest,
  RunListResponse,
  WorkflowState,
  SystemSettingsConfig,
  TestConnectivityResult,
} from './types'

/**
 * 后端端点封装（backend/app/api/routes.py）：
 * - POST   /api/v1/runs                          创建任务 → WorkflowState
 * - GET    /api/v1/runs?offset&limit             任务列表 → RunListResponse
 * - GET    /api/v1/runs/{run_id}                 任务详情 → WorkflowState
 * - GET    /api/v1/runs/{run_id}/revisions       历史版本 → RevisionListResponse
 * - GET    /api/v1/runs/{run_id}/revisions/{r}   指定版本 → WorkflowState
 * - POST   /api/v1/runs/{run_id}/reviews         提交审核（同步执行下一阶段，可能耗时数分钟）
 * - GET    /api/v1/runs/{run_id}/artifacts/{aid} 下载产物文件
 */

/** 创建与审核是同步执行阶段的接口，放宽超时到 5 分钟 */
const LONG_TIMEOUT = { timeout: 300_000 }

export async function createRun(payload: RunCreateRequest): Promise<WorkflowState> {
  const { data } = await http.post<WorkflowState>('/runs', payload, LONG_TIMEOUT)
  return data
}

export async function listRuns(offset = 0, limit = 20): Promise<RunListResponse> {
  const { data } = await http.get<RunListResponse>('/runs', {
    params: { offset, limit },
  })
  return data
}

export async function getRun(runId: string): Promise<WorkflowState> {
  const { data } = await http.get<WorkflowState>(`/runs/${runId}`)
  return data
}

export async function listRevisions(runId: string): Promise<RevisionListResponse> {
  const { data } = await http.get<RevisionListResponse>(`/runs/${runId}/revisions`)
  return data
}

export async function getRevision(runId: string, revision: number): Promise<WorkflowState> {
  const { data } = await http.get<WorkflowState>(`/runs/${runId}/revisions/${revision}`)
  return data
}

export interface FeedbackHistoryItem {
  from_revision: number
  to_revision: number
  stage: string
  comment: string | null
  edited_data: Record<string, unknown> | null
  combined_feedback: string
  timestamp: string
}

export async function getFeedbackHistory(runId: string): Promise<FeedbackHistoryItem[]> {
  const { data } = await http.get<FeedbackHistoryItem[]>(`/runs/${runId}/feedback-history`)
  return data
}

export async function submitReview(payload: ReviewRequest): Promise<WorkflowState> {
  const { data } = await http.post<WorkflowState>(
    `/runs/${payload.run_id}/reviews`,
    payload,
    LONG_TIMEOUT
  )
  return data
}

/**
 * 下载只依赖 artifact_id（取数）与 uri（推断文件名）。
 * 入参用 DownloadableArtifact 而非完整 ArtifactRef：
 * 融合产物清单缺 revision，放宽后可直接复用，无需伪造字段。
 */
export async function downloadArtifact(
  runId: string,
  artifact: DownloadableArtifact
): Promise<{ blob: Blob; filename: string }> {
  const { data } = await http.get<Blob>(`/runs/${runId}/artifacts/${artifact.artifact_id}`, {
    responseType: 'blob',
    timeout: 300_000,
  })
  const filename = artifact.uri.split(/[\\/]/).pop() || artifact.artifact_id
  return { blob: data, filename }
}

export function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

export async function deleteRun(runId: string): Promise<void> {
  await http.delete(`/runs/${runId}`)
}

export async function cancelRun(runId: string): Promise<WorkflowState> {
  const { data } = await http.post<WorkflowState>(`/runs/${runId}/cancel`)
  return data
}

export async function getRunEvents(runId: string, limit = 500): Promise<AgentTraceEvent[]> {
  const { data } = await http.get<AgentTraceEvent[]>(`/runs/${runId}/events`, {
    params: { limit },
  })
  return data
}

export function subscribeRunEvents(
  runId: string,
  onEvent: (event: AgentTraceEvent) => void,
  onError?: (err: Event) => void
): () => void {
  const url = `${API_BASE_URL}/runs/${runId}/events/stream`
  const es = new EventSource(url)

  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data) as AgentTraceEvent
      onEvent(data)
    } catch {
      // ignore JSON parse error
    }
  }

  if (onError) {
    es.onerror = onError
  }

  return () => {
    es.close()
  }
}

// ---------- 系统配置（Settings）端点 ----------

export async function getSettingsConfig(): Promise<SystemSettingsConfig> {
  const { data } = await http.get<SystemSettingsConfig>('/settings/config')
  return data
}

export async function updateSettingsConfig(
  payload: Partial<SystemSettingsConfig>
): Promise<{ status: string; message: string; data: SystemSettingsConfig }> {
  const { data } = await http.post<{ status: string; message: string; data: SystemSettingsConfig }>(
    '/settings/config',
    payload
  )
  return data
}

export async function resetSettingsConfig(): Promise<{
  status: string
  message: string
  data: SystemSettingsConfig
}> {
  const { data } = await http.post<{
    status: string
    message: string
    data: SystemSettingsConfig
  }>('/settings/reset')
  return data
}

export async function testLlmConnectivity(payload: {
  llm_api_key?: string
  llm_base_url?: string
  llm_model?: string
}): Promise<TestConnectivityResult> {
  const { data } = await http.post<TestConnectivityResult>('/settings/test-llm', payload, {
    timeout: 15_000,
  })
  return data
}

export async function testIwencaiConnectivity(payload: {
  iwencai_api_key?: string
}): Promise<TestConnectivityResult> {
  const { data } = await http.post<TestConnectivityResult>('/settings/test-iwencai', payload, {
    timeout: 15_000,
  })
  return data
}


