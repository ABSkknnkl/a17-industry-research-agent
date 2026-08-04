import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { reviewActions, stageNames, stageStatuses } from '@/types/workflow'

interface WorkflowContractSchema {
  $defs: {
    stageName: { enum: string[] }
    stageStatus: { enum: string[] }
  }
}

interface ReviewContractSchema {
  properties: {
    action: { enum: string[] }
  }
}

function loadSchema<T>(name: string): T {
  const path = resolve(process.cwd(), '..', 'contracts', 'schemas', name)
  return JSON.parse(readFileSync(path, 'utf-8')) as T
}

describe('public contract mirrors', () => {
  it('matches workflow stage and status enums', () => {
    const schema = loadSchema<WorkflowContractSchema>('workflow-state.schema.json')

    expect(stageNames).toEqual(schema.$defs.stageName.enum)
    expect(stageStatuses).toEqual(schema.$defs.stageStatus.enum)
  })

  it('matches review actions', () => {
    const schema = loadSchema<ReviewContractSchema>('review-action.schema.json')

    expect(reviewActions).toEqual(schema.properties.action.enum)
  })
})
