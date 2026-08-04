import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useWorkflowStore } from '@/stores/workflow'
import type { WorkflowState } from '@/types/workflow'

const waitingState: WorkflowState = {
  project_id: 'project-1',
  run_id: 'run-1',
  current_stage: 'data_fetch',
  status: 'waiting_review',
  revision: 1,
  stage_results: {},
  created_at: '2026-07-22T00:00:00Z',
  updated_at: '2026-07-22T00:00:00Z',
}

describe('workflow store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('tracks a server snapshot waiting for review', () => {
    const store = useWorkflowStore()

    store.applySnapshot(waitingState)

    expect(store.isWaitingForReview).toBe(true)
    expect(store.workflow?.run_id).toBe('run-1')
  })

  it('resets transient and server state', () => {
    const store = useWorkflowStore()
    store.applySnapshot(waitingState)
    store.setLoading(true)

    store.reset()

    expect(store.workflow).toBeNull()
    expect(store.loading).toBe(false)
  })
})
