import { describe, expect, it } from 'vitest'
import { classifyReportDownload, isDecisionAction, shouldAutoJumpToDownload } from '../reportGate'
import type { ArtifactRef, StageResult, StageStatus, WorkflowState } from '../types'

/**
 * 门控是「未批准报告不得当交付」的唯一防线（后端下载接口不看 status），
 * 本文件锁住三态分类与自动跳转判定，防止回归。
 */

function artifact(id: string, kind: string): ArtifactRef {
  return { artifact_id: id, kind, uri: `demo/${id}`, revision: 1 }
}

function stageResult(overrides: Partial<StageResult> = {}): StageResult {
  return {
    stage: 'report_fusion',
    status: 'completed',
    revision: 1,
    data: {},
    artifacts: [],
    evidence_sources: [],
    error: null,
    ...overrides,
  }
}

function makeRun(
  status: StageStatus,
  stageResults: WorkflowState['stage_results'] = {}
): WorkflowState {
  return {
    project_id: 'proj-1',
    run_id: 'run-1',
    current_stage: 'report_fusion',
    status,
    revision: 1,
    stage_results: stageResults,
    created_at: '2026-09-16T00:00:00Z',
    updated_at: '2026-09-16T00:00:00Z',
  }
}

const FUSION_WITH_ARTIFACTS = {
  report_fusion: stageResult({
    artifacts: [
      artifact('a-md', 'report_markdown'),
      artifact('a-html', 'report_html'),
      artifact('a-pdf', 'report_pdf'),
    ],
  }),
}

/** 无任何阶段结果（产物缺失） */
const FUSION_WITHOUT_ARTIFACTS = {}

describe('classifyReportDownload', () => {
  it('completed + 有产物 → normal 可下载', () => {
    const gate = classifyReportDownload(makeRun('completed', FUSION_WITH_ARTIFACTS))
    expect(gate.level).toBe('normal')
    expect(gate.downloadable).toBe(true)
    expect(gate.artifactCount).toBe(3)
  })

  it('approved + 有产物 → normal（approved 是 run 的合法中间态）', () => {
    const gate = classifyReportDownload(makeRun('approved', FUSION_WITH_ARTIFACTS))
    expect(gate.level).toBe('normal')
    expect(gate.downloadable).toBe(true)
  })

  it('completed 但无产物 → blocked', () => {
    const gate = classifyReportDownload(makeRun('completed', FUSION_WITHOUT_ARTIFACTS))
    expect(gate.level).toBe('blocked')
    expect(gate.downloadable).toBe(false)
    expect(gate.reason).toContain('尚未生成')
  })

  it('waiting_review + 存在阶段 error → exception，放行但强告警', () => {
    const run = makeRun('waiting_review', {
      report_fusion: stageResult({
        artifacts: [artifact('a-html', 'report_html')],
      }),
      data_fetch: stageResult({ stage: 'data_fetch', error: 'upstream_missing' }),
    })
    const gate = classifyReportDownload(run)
    expect(gate.level).toBe('exception')
    expect(gate.downloadable).toBe(true)
    expect(gate.alertType).toBe('error')
    expect(gate.reason).toContain('异常终态')
    expect(gate.reason).toContain('请勿作为正式交付')
  })

  it('waiting_review 但无 error（产物已出、尚未人工批准）→ blocked', () => {
    const gate = classifyReportDownload(makeRun('waiting_review', FUSION_WITH_ARTIFACTS))
    expect(gate.level).toBe('blocked')
    expect(gate.downloadable).toBe(false)
    expect(gate.reason).toContain('尚未通过人工审核')
  })

  it('running / pending → blocked，提示执行中', () => {
    for (const status of ['running', 'pending'] as StageStatus[]) {
      const gate = classifyReportDownload(makeRun(status))
      expect(gate.level).toBe('blocked')
      expect(gate.reason).toContain('执行中')
    }
  })

  it('rejected / failed / cancelled → blocked', () => {
    for (const status of ['rejected', 'failed', 'cancelled'] as StageStatus[]) {
      const gate = classifyReportDownload(makeRun(status, FUSION_WITH_ARTIFACTS))
      expect(gate.level).toBe('blocked')
      expect(gate.downloadable).toBe(false)
    }
  })

  it('阶段结果为空时不抛错', () => {
    const gate = classifyReportDownload(makeRun('completed'))
    expect(gate.level).toBe('blocked')
    expect(gate.artifactCount).toBe(0)
  })
})

describe('isDecisionAction / shouldAutoJumpToDownload', () => {
  it('决策类动作判定正确', () => {
    for (const action of ['approve', 'accept_recommendation', 'accept_with_risks', 'customize']) {
      expect(isDecisionAction(action)).toBe(true)
    }
    for (const action of ['revise', 'regenerate', 'cancel']) {
      expect(isDecisionAction(action)).toBe(false)
    }
    expect(isDecisionAction(null)).toBe(false)
    expect(isDecisionAction(undefined)).toBe(false)
  })

  it('最终阶段 + 决策类动作 → 跳转', () => {
    expect(shouldAutoJumpToDownload('report_fusion', 'approve')).toBe(true)
    expect(shouldAutoJumpToDownload('report_fusion', 'accept_with_risks')).toBe(true)
    expect(shouldAutoJumpToDownload('report_fusion', 'customize')).toBe(true)
  })

  it('最终阶段 + 非决策类动作 → 不跳转', () => {
    expect(shouldAutoJumpToDownload('report_fusion', 'revise')).toBe(false)
    expect(shouldAutoJumpToDownload('report_fusion', 'regenerate')).toBe(false)
    expect(shouldAutoJumpToDownload('report_fusion', 'cancel')).toBe(false)
  })

  it('非最终阶段 → 不跳转', () => {
    expect(shouldAutoJumpToDownload('chapter_write', 'approve')).toBe(false)
    expect(shouldAutoJumpToDownload(null, 'approve')).toBe(false)
  })
})
