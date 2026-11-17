import type { StageResult } from './types'

/** Running and pending stages can retain an error from a previous attempt. */
export function showStageError(result: StageResult): boolean {
  if (['running', 'pending', 'approved', 'completed'].includes(result.status)) return false
  return result.status === 'failed' || Boolean(result.error)
}
