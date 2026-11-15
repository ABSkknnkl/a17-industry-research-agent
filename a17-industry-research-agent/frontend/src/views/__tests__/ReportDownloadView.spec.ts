import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReportDownloadView from '../ReportDownloadView.vue'
import type { ArtifactRef, StageResult, StageStatus, WorkflowState } from '../../api/types'
import { ApiError } from '../../api/http'

/**
 * 下载页门控 + 顺序下载回归。
 *
 * 所有网络与下载调用都 mock 掉：jsdom 下 URL.createObjectURL 不可靠，
 * 且真实 triggerBlobDownload 会操作 DOM 触发下载。
 */
const mocks = vi.hoisted(() => ({
  getRun: vi.fn(),
  downloadArtifact: vi.fn(),
  downloadCompactReport: vi.fn(),
  triggerBlobDownload: vi.fn(),
}))

vi.mock('../../api/client', () => ({
  getRun: mocks.getRun,
  downloadArtifact: mocks.downloadArtifact,
  downloadCompactReport: mocks.downloadCompactReport,
  triggerBlobDownload: mocks.triggerBlobDownload,
}))

function artifact(id: string, kind: string, filename: string): ArtifactRef {
  return { artifact_id: id, kind, uri: `demo/${filename}`, revision: 1 }
}

const THREE_ARTIFACTS = [
  artifact('a-pdf', 'report_pdf', 'report.pdf'),
  artifact('a-md', 'report_markdown', 'report.md'),
  artifact('a-html', 'report_html', 'report.html'),
]

function stageResult(overrides: Partial<StageResult> = {}): StageResult {
  return {
    stage: 'report_fusion',
    status: 'completed',
    revision: 1,
    data: { title: '动力电池行业研究报告', validation_version: 'report-integrity-1' },
    artifacts: THREE_ARTIFACTS,
    evidence_sources: [],
    error: null,
    ...overrides,
  }
}

function makeRun(status: StageStatus, stageResults: WorkflowState['stage_results']): WorkflowState {
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

async function mountView(run: WorkflowState) {
  mocks.getRun.mockResolvedValue(run)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/runs/:runId', name: 'review', component: { template: '<div />' } },
      { path: '/runs/:runId/download', name: 'report-download', component: ReportDownloadView },
    ],
  })
  await router.push('/runs/run-1/download')
  await router.isReady()
  const wrapper = mount(ReportDownloadView, {
    global: { plugins: [ElementPlus, createPinia(), router] },
  })
  await flushPromises()
  return wrapper
}

async function waitFor(cond: () => boolean, timeoutMs = 4000): Promise<void> {
  const start = Date.now()
  while (!cond() && Date.now() - start < timeoutMs) {
    await new Promise((resolve) => setTimeout(resolve, 25))
  }
}

beforeEach(() => {
  mocks.getRun.mockReset()
  mocks.downloadArtifact.mockReset()
  mocks.downloadCompactReport.mockReset()
  mocks.triggerBlobDownload.mockReset()
  mocks.downloadArtifact.mockImplementation((_runId: string, art: ArtifactRef) =>
    Promise.resolve({ blob: new Blob(['x']), filename: art.uri.split('/').pop() as string })
  )
  mocks.downloadCompactReport.mockImplementation((_runId: string, revision: number) =>
    Promise.resolve({
      blob: new Blob(['zip']),
      filename: `report-compact-r${revision}.zip`,
    })
  )
})

describe('ReportDownloadView', () => {
  it('completed + 有产物：按钮可用，顺序下载全部产物', async () => {
    const wrapper = await mountView(makeRun('completed', { report_fusion: stageResult() }))

    const button = wrapper.find('[data-testid="report-download-all"]')
    expect(button.exists()).toBe(true)
    expect(button.attributes('disabled')).toBeUndefined()
    // 无门控告警
    expect(wrapper.find('[data-testid="report-download-gate"]').exists()).toBe(false)

    await button.trigger('click')
    await waitFor(() => mocks.triggerBlobDownload.mock.calls.length >= 3)

    // 顺序必须是 md → html → pdf（与 KIND_ORDER 一致，而非产物数组原始顺序）
    const filenames = mocks.triggerBlobDownload.mock.calls.map((call) => call[1])
    expect(filenames).toEqual(['report.md', 'report.html', 'report.pdf'])
    expect(mocks.downloadArtifact).toHaveBeenCalledTimes(3)
  })

  it('completed：展示 ArtifactList 表格（文件名/类型/下载）', async () => {
    const wrapper = await mountView(makeRun('completed', { report_fusion: stageResult() }))

    const table = wrapper.find('.el-table')
    expect(table.exists()).toBe(true)
    expect(wrapper.text()).toContain('report.md')
    expect(wrapper.text()).toContain('报告 Markdown')
    expect(wrapper.findAll('.el-table__row')).toHaveLength(3)
    // 门控放行时单项下载可点
    const rowButtons = wrapper.findAll('.el-table .el-button')
    expect(rowButtons.length).toBeGreaterThan(0)
    expect(rowButtons[0].attributes('disabled')).toBeUndefined()
  })

  it('waiting_review 未批准：表格仍在，但单项下载禁用', async () => {
    const wrapper = await mountView(makeRun('waiting_review', { report_fusion: stageResult() }))

    expect(wrapper.find('.el-table').exists()).toBe(true)
    const rowButton = wrapper.find('.el-table .el-button')
    expect(rowButton.exists()).toBe(true)
    expect(rowButton.attributes('disabled')).toBeDefined()
  })

  it('waiting_review 且无阶段错误（尚未人工批准）：按钮禁用并说明原因', async () => {
    const wrapper = await mountView(makeRun('waiting_review', { report_fusion: stageResult() }))

    const button = wrapper.find('[data-testid="report-download-all"]')
    expect(button.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('尚未通过人工审核')
  })

  it('waiting_review 且有阶段错误（fail-closed 异常终态）：放行但强告警', async () => {
    const wrapper = await mountView(
      makeRun('waiting_review', {
        report_fusion: stageResult(),
        data_fetch: stageResult({ stage: 'data_fetch', error: 'upstream_missing', artifacts: [] }),
      })
    )

    const button = wrapper.find('[data-testid="report-download-all"]')
    expect(button.attributes('disabled')).toBeUndefined()

    const gateAlert = wrapper.find('[data-testid="report-download-gate"]')
    expect(gateAlert.exists()).toBe(true)
    expect(wrapper.text()).toContain('异常终态')
    expect(wrapper.text()).toContain('请勿作为正式交付')
  })

  it('running：不可下载', async () => {
    const wrapper = await mountView(makeRun('running', { report_fusion: stageResult() }))
    expect(wrapper.find('[data-testid="report-download-all"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('执行中')
  })
})

describe('ReportDownloadView 四种交付状态', () => {
  it('正式：通过审核且版本一致时可下载全部', async () => {
    const wrapper = await mountView(makeRun('completed', { report_fusion: stageResult() }))
    expect(
      wrapper.find('[data-testid="report-download-all"]').attributes('disabled')
    ).toBeUndefined()
    expect(wrapper.text()).toContain('下载全部报告文件')
  })

  it('受限：质量门未通过时只提供受限草稿下载', async () => {
    const limited = stageResult({
      data: {
        title: '动力电池行业研究报告',
        validation_version: 'report-integrity-1',
        delivery_status: 'ready_with_limits',
        draft_available: true,
        draft_sanitized: true,
        quality: { passed: false },
      },
    })
    const wrapper = await mountView(makeRun('waiting_review', { report_fusion: limited }))
    expect(wrapper.text()).toContain('受限草稿')
    expect(wrapper.text()).toContain('下载全部草稿文件')
    expect(
      wrapper.find('[data-testid="report-download-all"]').attributes('disabled')
    ).toBeUndefined()
  })

  it('重建：编辑后版本不一致时禁止下载并提示重新生成', async () => {
    const rebuilt = stageResult({
      data: {
        title: '动力电池行业研究报告',
        validation_version: 'report-integrity-1',
        built_at_revision: 1,
      },
    })
    const run = makeRun('completed', { report_fusion: rebuilt })
    run.revision = 2
    const wrapper = await mountView(run)
    expect(wrapper.find('[data-testid="report-download-all"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('重新生成')
  })

  it('失败：任务失败时不可下载并说明原因', async () => {
    const wrapper = await mountView(makeRun('failed', { report_fusion: stageResult() }))
    expect(wrapper.find('[data-testid="report-download-all"]').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('任务执行失败')
  })
})

describe('ReportDownloadView 紧凑交付包', () => {
  it('正式：只发一次 POST 并落一个 ZIP', async () => {
    const wrapper = await mountView(makeRun('completed', { report_fusion: stageResult() }))
    const button = wrapper.find('[data-testid="report-download-compact"]')
    expect(button.attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).toContain('下载紧凑交付包')

    await button.trigger('click')
    await waitFor(() => mocks.triggerBlobDownload.mock.calls.length >= 1)

    expect(mocks.downloadCompactReport).toHaveBeenCalledTimes(1)
    expect(mocks.downloadCompactReport).toHaveBeenCalledWith(
      'run-1',
      1,
      'formal',
      expect.anything()
    )
    expect(mocks.triggerBlobDownload.mock.calls[0][1]).toBe('report-compact-r1.zip')
    expect(wrapper.find('[data-testid="report-download-compact-result"]').text()).toContain(
      '已下载'
    )
    // 原「下载全部」流程不受影响
    expect(mocks.downloadArtifact).not.toHaveBeenCalled()
  })

  it('受限草稿：按钮使用草稿文案并传 draft 模式', async () => {
    const limited = stageResult({
      data: {
        title: '动力电池行业研究报告',
        validation_version: 'report-integrity-1',
        delivery_status: 'ready_with_limits',
        draft_available: true,
        draft_sanitized: true,
        quality: { passed: false },
      },
    })
    const wrapper = await mountView(makeRun('waiting_review', { report_fusion: limited }))
    expect(wrapper.text()).toContain('下载紧凑草稿包')
    await wrapper.find('[data-testid="report-download-compact"]').trigger('click')
    await waitFor(() => mocks.downloadCompactReport.mock.calls.length >= 1)
    expect(mocks.downloadCompactReport.mock.calls[0][2]).toBe('draft')
  })

  it('409：提示内容已变并刷新任务状态', async () => {
    mocks.downloadCompactReport.mockRejectedValueOnce(
      new ApiError('报告内容已变更或当前产物失效，请刷新后重新下载。', 409)
    )
    const wrapper = await mountView(makeRun('completed', { report_fusion: stageResult() }))
    await wrapper.find('[data-testid="report-download-compact"]').trigger('click')
    await waitFor(() => wrapper.find('[data-testid="report-download-compact-result"]').exists())
    expect(wrapper.find('[data-testid="report-download-compact-result"]').text()).toContain(
      '报告内容已变更'
    )
    expect(mocks.getRun).toHaveBeenCalledTimes(2)
  })

  it('429：显示忙碌提示且可再次点击', async () => {
    mocks.downloadCompactReport.mockRejectedValueOnce(
      new ApiError('紧凑交付包正在生成，请稍后手动重试。', 429)
    )
    const wrapper = await mountView(makeRun('completed', { report_fusion: stageResult() }))
    await wrapper.find('[data-testid="report-download-compact"]').trigger('click')
    await waitFor(() => wrapper.find('[data-testid="report-download-compact-result"]').exists())
    expect(wrapper.find('[data-testid="report-download-compact-result"]').text()).toContain(
      '正在生成'
    )
    expect(
      wrapper.find('[data-testid="report-download-compact"]').attributes('disabled')
    ).toBeUndefined()
  })

  it('版本不一致：紧凑按钮禁用', async () => {
    const rebuilt = stageResult({ data: { built_at_revision: 1 } })
    const run = makeRun('completed', { report_fusion: rebuilt })
    run.revision = 2
    const wrapper = await mountView(run)
    expect(
      wrapper.find('[data-testid="report-download-compact"]').attributes('disabled')
    ).toBeDefined()
  })

  it('离开页面会取消在途请求', async () => {
    let captured: AbortSignal | undefined
    mocks.downloadCompactReport.mockImplementation(
      (_runId: string, _revision: number, _mode: string, signal?: AbortSignal) => {
        captured = signal
        return new Promise(() => {})
      }
    )
    const wrapper = await mountView(makeRun('completed', { report_fusion: stageResult() }))
    await wrapper.find('[data-testid="report-download-compact"]').trigger('click')
    await flushPromises()
    expect(captured?.aborted).toBe(false)
    wrapper.unmount()
    expect(captured?.aborted).toBe(true)
  })
})
