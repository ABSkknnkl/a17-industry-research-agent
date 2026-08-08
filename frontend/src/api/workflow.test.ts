import { beforeEach, describe, expect, it, vi } from 'vitest'

import api from '@/api'
import { createRun, downloadArtifact, getRun, reviewRun } from '@/api/workflow'
import type { ReviewRequest, RunCreateRequest, WorkflowState } from '@/types/workflow'

vi.mock('@/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

const snapshot: WorkflowState = {
  project_id: 'project-1',
  run_id: 'run-1',
  current_stage: 'data_interpret',
  status: 'waiting_review',
  revision: 1,
  stage_results: {},
  created_at: '2026-07-28T00:00:00Z',
  updated_at: '2026-07-28T00:00:00Z',
}

describe('workflow API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('uses the generic run and review endpoints', async () => {
    vi.mocked(api.post).mockResolvedValue(snapshot)
    vi.mocked(api.get).mockResolvedValue(snapshot)
    const createRequest: RunCreateRequest = {
      project_id: 'project-1',
      input_data: { industry_topic: '中国光伏制造行业' },
      review_stages: ['data_interpret'],
    }
    const reviewRequest: ReviewRequest = {
      run_id: 'run-1',
      stage: 'data_interpret',
      action: 'approve',
      expected_revision: 1,
      comment: '通过',
      edited_data: null,
    }

    await createRun(createRequest)
    await getRun('run-1')
    await reviewRun('run-1', reviewRequest)
    await downloadArtifact('run-1', 'ARTIFACT-REPORT-HTML')

    expect(api.post).toHaveBeenNthCalledWith(1, '/runs', createRequest)
    expect(api.get).toHaveBeenCalledWith('/runs/run-1')
    expect(api.post).toHaveBeenNthCalledWith(2, '/runs/run-1/reviews', reviewRequest)
    expect(api.get).toHaveBeenNthCalledWith(2, '/runs/run-1/artifacts/ARTIFACT-REPORT-HTML', {
      responseType: 'blob',
    })
  })
})
