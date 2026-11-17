import axios from 'axios'
import { ApiError, http, API_BASE_URL } from './http'
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
  SkillCatalogResponse,
  SkillItem,
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

export async function restoreRevision(runId: string, revision: number): Promise<WorkflowState> {
  const { data } = await http.post<WorkflowState>(`/runs/${runId}/revisions/${revision}/restore`)
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
  action?: string
  changed_fields?: string[]
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
  artifact: DownloadableArtifact,
  mode: 'formal' | 'draft' = 'formal'
): Promise<{ blob: Blob; filename: string }> {
  const { data } = await http.get<Blob>(`/runs/${runId}/artifacts/${artifact.artifact_id}`, {
    params: { mode },
    responseType: 'blob',
    timeout: 300_000,
  })
  const filename = artifact.uri.split(/[\\/]/).pop() || artifact.artifact_id
  return { blob: data, filename: mode === 'draft' ? `draft-${filename}` : filename }
}

export async function downloadEvidenceIndex(
  runId: string,
  revision: number,
  mode: 'formal' | 'draft',
  signal?: AbortSignal
): Promise<{ blob: Blob; filename: string }> {
  const { data } = await http.get<Blob>(`/runs/${runId}/exports/evidence-index`, {
    params: { mode, expected_revision: revision },
    responseType: 'blob',
    signal,
  })
  return { blob: data, filename: `${mode === 'draft' ? 'draft-' : ''}evidence_index.csv` }
}

export async function getReportPreview(runId: string): Promise<Blob> {
  const { data } = await http.get<Blob>(`/runs/${runId}/report-preview`, {
    responseType: 'blob',
  })
  return data
}

/**
 * 工作台紧凑交付包：单次 POST 直接返回内存 ZIP（含 md/html/pdf/完整证据 CSV）。
 * 最终下载资格由服务端按当前版本与草稿/正式门禁确认，前端只做初步判断。
 */
export async function downloadCompactReport(
  runId: string,
  revision: number,
  mode: 'formal' | 'draft',
  signal?: AbortSignal
): Promise<{ blob: Blob; filename: string }> {
  const messages: Record<number, string> = {
    404: '任务不存在，请返回工作台确认。',
    409: '报告内容已变更或当前产物失效，请刷新后重新下载。',
    429: '紧凑交付包正在生成，请稍后手动重试。',
    500: '紧凑交付包生成失败，请稍后重试。',
    504: 'PDF 渲染超时，请稍后重试。',
  }
  try {
    const { data } = await http.post<Blob>(
      `/runs/${runId}/exports/compact`,
      { mode, expected_revision: revision },
      { responseType: 'blob', timeout: 300_000, signal }
    )
    const filename = `${mode === 'draft' ? 'draft-' : ''}report-compact-r${revision}.zip`
    return { blob: data, filename }
  } catch (error) {
    if (error instanceof ApiError) {
      throw new ApiError(messages[error.status ?? 0] ?? error.message, error.status, error.code)
    }
    throw error
  }
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

export async function clearAllRuns(): Promise<{ message: string; deleted_count: number }> {
  const { data } = await http.delete<{ status: string; message: string; deleted_count: number }>(
    '/runs'
  )
  return data
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

export async function getSkillsCatalog(refresh = false): Promise<SkillCatalogResponse> {
  const { data } = await http.get<SkillCatalogResponse>('/skills', {
    params: { refresh },
  })
  return data
}

export async function getSkillDetail(stageId: string, skillId: string): Promise<SkillItem> {
  const { data } = await http.get<SkillItem>(`/skills/${stageId}/${skillId}`)
  return data
}

export async function resumeRun(runId: string, fromStage?: string): Promise<WorkflowState> {
  const { data } = await http.post<WorkflowState>(`/runs/${runId}/resume`, null, {
    params: fromStage ? { from_stage: fromStage } : undefined,
    ...LONG_TIMEOUT,
  })
  return data
}

/** 后端健康状态（`/health`，不在 /api/v1 前缀下） */
export interface HealthStatus {
  status: string
  llm_model?: string
  agents_ready?: boolean
}

/**
 * 健康探测：基址去掉 `/api/v1` 末缀后拼 `/health`。
 * 直接复用外部后端地址（VITE_API_BASE_URL）时也能正确落点。
 */
export async function getHealth(): Promise<HealthStatus> {
  const base = API_BASE_URL.replace(/\/api\/v1\/?$/, '')
  const { data } = await axios.get<HealthStatus>(`${base}/health`, { timeout: 5_000 })
  return data
}
