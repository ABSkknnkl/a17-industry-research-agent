/**
 * Mock 数据适配器：导出与真实 client.ts 同形的 API。
 * VITE_DATA_MODE=mock 时由 client.ts 委托到此文件，不发起任何网络请求。
 */
import type {
  DownloadableArtifact,
  RevisionListResponse,
  ReviewRequest,
  RunCreateRequest,
  RunListResponse,
  WorkflowState,
} from '../api/types'
import { DEMO_RUN_ID } from './fixtures/amdResearchMock'
import { ensurePrototypeHydrated, usePrototypeStore } from './prototypeRun'

ensurePrototypeHydrated()

function store() {
  return usePrototypeStore()
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

const SYNC_DELAY = 350

export async function createRun(payload: RunCreateRequest): Promise<WorkflowState> {
  void payload
  await sleep(SYNC_DELAY)
  const s = store()
  s.persist()
  return s.getWorkflow(DEMO_RUN_ID)
}

export async function listRuns(offset = 0, limit = 20): Promise<RunListResponse> {
  await sleep(80)
  return store().listRuns(offset, limit)
}

export async function getRun(runId: string): Promise<WorkflowState> {
  await sleep(50)
  return store().getWorkflow(runId || DEMO_RUN_ID)
}

export async function listRevisions(runId: string): Promise<RevisionListResponse> {
  await sleep(50)
  const s = store()
  void runId
  return s.listRevisions()
}

export async function getRevision(runId: string, revision: number): Promise<WorkflowState> {
  await sleep(50)
  return store().getRevision(runId, revision)
}

export async function submitReview(payload: ReviewRequest): Promise<WorkflowState> {
  const s = store()
  if (payload.action === 'approve' || payload.action === 'accept_with_risks') {
    const ack = s.acknowledgeRisk.bind(s)
    // 自动确认阶段内未确认的必须风险，便于演示通过路径
    const risks = s.getRiskItems().filter((r) => r.stage === payload.stage)
    for (const r of risks) {
      if (r.requires_ack) ack(r.risk_code)
    }
    const rec = await s.approveStage(payload.stage)
    if (!rec.ok) {
      throw new Error(rec.message)
    }
  } else if (payload.action === 'revise' || payload.action === 'regenerate') {
    await s.returnStage(payload.stage, payload.comment || payload.action)
  } else if (payload.action === 'cancel') {
    s.raw.workflowStatus = 'cancelled'
    s.raw.stages[payload.stage] = {
      ...(s.raw.stages[payload.stage] as {
        status: WorkflowState['status']
        revision: number
        produced: boolean
      }),
      status: 'cancelled',
    }
    s.persist()
  }
  return s.getWorkflow(payload.run_id || DEMO_RUN_ID)
}

export async function downloadArtifact(
  _runId: string,
  artifact: DownloadableArtifact
): Promise<{ blob: Blob; filename: string }> {
  await sleep(80)
  const blob = store().getDownloadBlob(artifact.artifact_id)
  if (!blob) throw new Error('演示产物不存在')
  const filename = artifact.uri.split(/[\\/]/).pop() || artifact.artifact_id
  return { blob, filename }
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
