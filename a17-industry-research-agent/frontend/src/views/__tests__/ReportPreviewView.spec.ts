import { flushPromises, mount } from '@vue/test-utils'
import * as Icons from '@element-plus/icons-vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReportPreviewView from '../ReportPreviewView.vue'
import type { WorkflowState } from '../../api/types'

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

function makeState(): WorkflowState {
  return {
    project_id: 'proj-1',
    run_id: 'run-1',
    current_stage: 'report_fusion',
    status: 'completed',
    revision: 1,
    stage_results: {
      report_fusion: {
        stage: 'report_fusion',
        status: 'completed',
        revision: 1,
        data: {
          title: '低空经济行业研究报告',
          industry_topic: '低空经济',
        },
        artifacts: [
          { artifact_id: 'a-html', kind: 'report_html', uri: 'report.html', revision: 1 },
          { artifact_id: 'a-pdf', kind: 'report_pdf', uri: 'report.pdf', revision: 1 },
          { artifact_id: 'a-md', kind: 'report_markdown', uri: 'report.md', revision: 1 },
        ],
        evidence_sources: [],
        error: null,
      },
    },
    created_at: '2026-09-24T00:00:00Z',
    updated_at: '2026-09-24T00:00:00Z',
  }
}

describe('ReportPreviewView 报告导出功能', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.getRun.mockResolvedValue(makeState())
    mocks.downloadArtifact.mockResolvedValue({
      blob: new Blob(['fake content']),
      filename: 'report.pdf',
    })
  })

  async function mountView() {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/runs/:runId/preview', name: 'report-preview', component: ReportPreviewView },
        {
          path: '/runs/:runId/download',
          name: 'report-download',
          component: { template: '<div />' },
        },
        { path: '/runs/:runId', name: 'review', component: { template: '<div />' } },
      ],
    })
    await router.push('/runs/run-1/preview')
    await router.isReady()

    const wrapper = mount(ReportPreviewView, {
      global: {
        plugins: [createPinia(), router, ElementPlus],
        components: { ...Icons },
      },
    })
    await flushPromises()
    return { wrapper, router }
  }

  it('渲染 PDF / HTML / Markdown 导出按钮与批量下载入口', async () => {
    const { wrapper } = await mountView()
    expect(wrapper.find('[data-testid="btn-preview-export-pdf"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="btn-preview-export-html"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="btn-preview-export-md"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="btn-preview-export-all"]').exists()).toBe(true)
  })

  it('点击导出 PDF 按钮成功调用 downloadArtifact 与 triggerBlobDownload', async () => {
    const { wrapper } = await mountView()
    const pdfBtn = wrapper.find('[data-testid="btn-preview-export-pdf"]')
    await pdfBtn.trigger('click')
    await flushPromises()

    expect(mocks.downloadArtifact).toHaveBeenCalledWith(
      'run-1',
      expect.objectContaining({ artifact_id: 'a-pdf' }),
      'formal'
    )
    expect(mocks.triggerBlobDownload).toHaveBeenCalledWith(expect.any(Blob), 'report.pdf')
  })

  it('点击批量交付物下载跳转至 report-download 路由', async () => {
    const { wrapper, router } = await mountView()
    const allBtn = wrapper.find('[data-testid="btn-preview-export-all"]')
    await allBtn.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('report-download')
  })
})

describe('ReportPreviewView 受限交付状态', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.downloadArtifact.mockResolvedValue({
      blob: new Blob(['fake content']),
      filename: 'report.html',
    })
  })

  function limitedState(): WorkflowState {
    const state = makeState()
    state.stage_results.report_fusion!.data = {
      title: '低空经济行业研究报告',
      industry_topic: '低空经济',
      delivery_status: 'ready_with_limits',
      draft_available: true,
      draft_sanitized: true,
      quality: { passed: false, issues: ['审校防幻觉拦截 2 处未获授权的编辑'] },
      quality_issues: [
        { code: 'unsupported_quantity', claim: '9150亿元' },
        { code: 'unsupported_direction_claim', claim: '行业未来将持续增长' },
      ],
    }
    return state
  }

  async function mountWith(state: WorkflowState) {
    mocks.getRun.mockResolvedValue(state)
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/runs/:runId/preview', name: 'report-preview', component: ReportPreviewView },
        {
          path: '/runs/:runId/download',
          name: 'report-download',
          component: { template: '<div />' },
        },
        { path: '/runs/:runId', name: 'review', component: { template: '<div />' } },
      ],
    })
    await router.push('/runs/run-1/preview')
    await router.isReady()
    const wrapper = mount(ReportPreviewView, {
      global: { plugins: [createPinia(), router, ElementPlus], components: { ...Icons } },
    })
    await flushPromises()
    return wrapper
  }

  it('shows the audit details for limited delivery', async () => {
    const wrapper = await mountWith(limitedState())

    const banner = wrapper.find('[data-testid="limited-delivery-banner"]')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain('受限')

    const toggle = wrapper.find('[data-testid="audit-details-toggle"]')
    expect(toggle.exists()).toBe(true)
    expect(wrapper.find('[data-testid="audit-details"]').exists()).toBe(false)

    await toggle.trigger('click')
    await flushPromises()

    const details = wrapper.find('[data-testid="audit-details"]')
    expect(details.exists()).toBe(true)
    expect(details.text()).toContain('2')
    expect(details.text()).toContain('行业未来将持续增长')
  })

  it('hides the limited banner once the report is ready', async () => {
    const wrapper = await mountWith(makeState())
    expect(wrapper.find('[data-testid="limited-delivery-banner"]').exists()).toBe(false)
  })
})
