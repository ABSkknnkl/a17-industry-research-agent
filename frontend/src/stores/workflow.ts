import { defineStore } from 'pinia'

import type { WorkflowState } from '@/types/workflow'

interface WorkflowStoreState {
  workflow: WorkflowState | null
  loading: boolean
  error: string | null
}

export const useWorkflowStore = defineStore('workflow', {
  state: (): WorkflowStoreState => ({
    workflow: null,
    loading: false,
    error: null,
  }),
  getters: {
    isWaitingForReview: (state): boolean => state.workflow?.status === 'waiting_review',
  },
  actions: {
    applySnapshot(snapshot: WorkflowState): void {
      this.workflow = snapshot
      this.error = null
    },
    setLoading(loading: boolean): void {
      this.loading = loading
    },
    setError(message: string): void {
      this.error = message
      this.loading = false
    },
    reset(): void {
      this.workflow = null
      this.loading = false
      this.error = null
    },
  },
})
