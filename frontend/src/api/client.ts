import type {
  DownloadableArtifact,
  RevisionListResponse,
  ReviewRequest,
  RunCreateRequest,
  RunListResponse,
  WorkflowState,
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
 *
 * VITE_DATA_MODE=mock 时全部委托到 mock/client.ts，真实模式保持原实现不变。
 */

export function isMockDataMode(): boolean {
  return import.meta.env.VITE_DATA_MODE === 'mock'
}

type MockClient = typeof import('../mock/client')

let mockClientPromise: Promise<MockClient> | null = null

async function mock(): Promise<MockClient> {
  if (!mockClientPromise) {
    mockClientPromise = import('../mock/client')
  }
  return mockClientPromise
}

/** 创建与审核是同步执行阶段的接口，放宽超时到 5 分钟 */
const LONG_TIMEOUT = { timeout: 300_000 }

async function realHttp() {
  // 惰性加载 axios 封装，避免 mock 模式初始化真实 http 拦截器依赖
  return import('./http')
}

export async function createRun(payload: RunCreateRequest): Promise<WorkflowState> {
  if (isMockDataMode()) return (await mock()).createRun(payload)
  const { http } = await realHttp()
  const { data } = await http.post<WorkflowState>('/runs', payload, LONG_TIMEOUT)
  return data
}

export async function listRuns(offset = 0, limit = 20): Promise<RunListResponse> {
  if (isMockDataMode()) return (await mock()).listRuns(offset, limit)
  const { http } = await realHttp()
  const { data } = await http.get<RunListResponse>('/runs', {
    params: { offset, limit },
  })
  return data
}

export async function getRun(runId: string): Promise<WorkflowState> {
  if (isMockDataMode()) return (await mock()).getRun(runId)
  const { http } = await realHttp()
  const { data } = await http.get<WorkflowState>(`/runs/${runId}`)
  return data
}

export async function listRevisions(runId: string): Promise<RevisionListResponse> {
  if (isMockDataMode()) return (await mock()).listRevisions(runId)
  const { http } = await realHttp()
  const { data } = await http.get<RevisionListResponse>(`/runs/${runId}/revisions`)
  return data
}

export async function getRevision(runId: string, revision: number): Promise<WorkflowState> {
  if (isMockDataMode()) return (await mock()).getRevision(runId, revision)
  const { http } = await realHttp()
  const { data } = await http.get<WorkflowState>(`/runs/${runId}/revisions/${revision}`)
  return data
}

export async function submitReview(payload: ReviewRequest): Promise<WorkflowState> {
  if (isMockDataMode()) return (await mock()).submitReview(payload)
  const { http } = await realHttp()
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
  if (isMockDataMode()) return (await mock()).downloadArtifact(runId, artifact)
  const { http } = await realHttp()
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
