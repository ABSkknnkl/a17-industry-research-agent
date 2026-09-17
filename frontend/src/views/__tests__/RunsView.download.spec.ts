import { flushPromises, mount } from '@vue/test-utils'
import * as Icons from '@element-plus/icons-vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RunsView from '../RunsView.vue'
import type { RunSummary } from '../../api/types'

/**
 * RunsView 的「报告」列入口回归。
 *
 * 关键点有两个：
 * 1) 原来是个静态 <el-tag>可下载</el-tag>（不可点），现在必须是可点按钮；
 * 2) 表格整行有 @row-click 跳工作台，按钮必须 @click.stop 拦住冒泡，
 *    否则点「下载报告」会同时触发行跳转 → 最终落到工作台。
 *    所以「点击后最终路由是 report-download」这一条断言即证明了 @click.stop 生效。
 */
const mocks = vi.hoisted(() => ({
  listRuns: vi.fn(),
}))

vi.mock('../../api/client', () => ({
  listRuns: mocks.listRuns,
}))

function summary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: 'run-1',
    project_id: 'proj-1',
    title: '动力电池行业研究报告',
    current_stage: 'report_fusion',
    status: 'completed',
    revision: 1,
    created_at: '2026-09-16T00:00:00Z',
    updated_at: '2026-09-16T00:00:00Z',
    artifact_count: 3,
    report_available: true,
    ...overrides,
  }
}

async function mountView(items: RunSummary[]) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'home', component: { template: '<div />' } },
      { path: '/runs', name: 'runs', component: RunsView },
      { path: '/runs/:runId', name: 'review', component: { template: '<div />' } },
      { path: '/runs/:runId/download', name: 'report-download', component: { template: '<div />' } },
    ],
  })
  await router.push('/runs')
  await router.isReady()

  mocks.listRuns.mockResolvedValue({ total: items.length, offset: 0, limit: 20, items })
  const wrapper = mount(RunsView, {
    global: {
      plugins: [ElementPlus, createPinia(), router],
      // 真实应用在 main.ts 里全局注册图标，测试环境需要补上，否则报
      // "Failed to resolve component: Refresh"
      components: Icons as unknown as Record<string, never>,
    },
  })
  await flushPromises()
  return { wrapper, router }
}

describe('RunsView 报告下载入口', () => {
  beforeEach(() => {
    mocks.listRuns.mockReset()
  })

  it('report_available 的任务渲染可点按钮（而非静态标签）', async () => {
    const { wrapper } = await mountView([summary()])
    const button = wrapper.find('[data-testid="run-report-download"]')
    expect(button.exists()).toBe(true)
    expect(button.text()).toContain('下载报告')
  })

  it('点击按钮进入下载页，且不被行点击覆盖为工作台（@click.stop 生效）', async () => {
    const { wrapper, router } = await mountView([summary()])
    await wrapper.find('[data-testid="run-report-download"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('report-download')
    expect(router.currentRoute.value.params.runId).toBe('run-1')
  })

  it('无报告的任务不显示下载按钮', async () => {
    const { wrapper } = await mountView([summary({ report_available: false, artifact_count: 0 })])
    expect(wrapper.find('[data-testid="run-report-download"]').exists()).toBe(false)
  })
})
