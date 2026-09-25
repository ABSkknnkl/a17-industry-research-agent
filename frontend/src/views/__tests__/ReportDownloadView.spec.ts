import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReportDownloadView from '../ReportDownloadView.vue'
import type { ArtifactRef, StageResult, StageStatus, WorkflowState } from '../../api/types'

/**
 * 下载页门控 + 顺序下载回归。
 *
 * 所有网络与下载调用都 mock 掉：jsdom 下 URL.createObjectURL 不可靠，
 * 且真实 triggerBlobDownload 会操作 DOM 触发下载。
 */
const mocks = vi.hoisted(() => ({
  getRun: vi.fn(),
  downloadArtifact: vi.fn(),
  triggerBlobDownload: vi.fn(),
}))

vi.mock('../../api/client', () => ({
  getRun: mocks.getRun,
  downloadArtifact: mocks.downloadArtifact,
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
    data: { title: '动力电池行业研究报告' },
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

describe('ReportDownloadView', () => {
  beforeEach(() => {
    mocks.getRun.mockReset()
    mocks.downloadArtifact.mockReset()
    mocks.triggerBlobDownload.mockReset()
    mocks.downloadArtifact.mockImplementation((_runId: string, art: ArtifactRef) =>
      Promise.resolve({ blob: new Blob(['x']), filename: art.uri.split('/').pop() as string })
    )
  })

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
