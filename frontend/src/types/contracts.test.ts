import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import {
  chartTypes,
  reportFormats,
  reviewActions,
  stageNames,
  stageStatuses,
} from '@/types/workflow'

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

interface ReportContractSchema {
  $defs: {
    reportFormat: { enum: string[] }
  }
}

interface ChartContractSchema {
  $defs: {
    chartType: { enum: string[] }
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

  it('matches report output formats', () => {
    const schema = loadSchema<ReportContractSchema>('report-fusion-result.schema.json')

    expect(reportFormats).toEqual(schema.$defs.reportFormat.enum)
  })

  it('matches chart types', () => {
    const schema = loadSchema<ChartContractSchema>('chart-generation-result.schema.json')

    expect(chartTypes).toEqual(schema.$defs.chartType.enum)
  })
})
