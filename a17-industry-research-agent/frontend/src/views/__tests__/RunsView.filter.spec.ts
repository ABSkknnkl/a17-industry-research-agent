import { flushPromises, mount } from '@vue/test-utils'
import * as Icons from '@element-plus/icons-vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import RunsView from '../RunsView.vue'
import type { RunSummary } from '../../api/types'

/**
 * B43（前端 B5）：任务列表的状态筛选与搜索。
 *
 * 此前列表只能一页页翻：3 个任务停在 waiting_review 也要逐个点开才发现。
 * 这里补「待审阅」等状态筛选 chip 和主题/ID 搜索（当前页内筛选，接口无查询参数）。
 */
const mocks = vi.hoisted(() => ({
  listRuns: vi.fn(),
}))

vi.mock('../../api/client', () => ({
  listRuns: mocks.listRuns,
  deleteRun: vi.fn(),
  clearAllRuns: vi.fn(),
}))

function summary(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: 'run-1',
    project_id: 'proj-1',
    title: '《半导体设备》行业研究报告',
    current_stage: 'report_fusion',
    status: 'waiting_review',
    revision: 1,
    created_at: '2026-11-11T10:00:00Z',
    updated_at: '2026-11-11T10:00:00Z',
    artifact_count: 3,
    report_available: false,
    draft_available: true,
    ...overrides,
  }
}

const ITEMS: RunSummary[] = [
  summary({ run_id: 'run-aaa', title: '《半导体设备》行业研究报告', status: 'waiting_review' }),
  summary({ run_id: 'run-bbb', title: '《低空经济》行业研究报告', status: 'completed' }),
  summary({ run_id: 'run-ccc', title: '《白酒》行业研究报告', status: 'failed' }),
]

async function mountView() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'runs', component: RunsView },
      { path: '/runs/:runId', name: 'review', component: { template: '<div />' } },
      {
        path: '/runs/:runId/download',
        name: 'report-download',
        component: { template: '<div />' },
      },
    ],
  })
  await router.push('/')
  await router.isReady()

  mocks.listRuns.mockResolvedValue({ total: ITEMS.length, offset: 0, limit: 20, items: ITEMS })
  const wrapper = mount(RunsView, {
    global: {
      plugins: [ElementPlus, createPinia(), router],
      components: Icons as unknown as Record<string, never>,
    },
  })
  await flushPromises()
  return { wrapper, router }
}

async function chooseFilter(
  wrapper: Awaited<ReturnType<typeof mountView>>['wrapper'],
  key: string
): Promise<void> {
  // Element Plus 的 radio-button 在 jsdom 里点 label 不会联动 input，直接切 input
  await wrapper.find(`[data-testid="filter-${key}"] input`).setValue(true)
  await flushPromises()
}

function visibleRunIds(wrapper: Awaited<ReturnType<typeof mountView>>['wrapper']): string[] {
  return wrapper
    .findAll('[data-testid="run-row-id"]')
    .map((node) => node.text())
    .filter(Boolean)
}

describe('RunsView 筛选与搜索', () => {
  beforeEach(() => mocks.listRuns.mockReset())

  it('默认展示当前页全部任务', async () => {
    const { wrapper } = await mountView()
    expect(visibleRunIds(wrapper)).toHaveLength(3)
    wrapper.unmount()
  })

  it('选择「待审阅」后只保留 waiting_review 任务', async () => {
    const { wrapper } = await mountView()
    await chooseFilter(wrapper, 'waiting_review')

    const ids = visibleRunIds(wrapper)
    expect(ids).toHaveLength(1)
    expect(ids[0]).toContain('run-aaa')
    wrapper.unmount()
  })

  it('搜索框按主题或任务 ID 过滤', async () => {
    const { wrapper } = await mountView()
    const input = wrapper.find('[data-testid="runs-search"]')
    await input.setValue('低空')
    await flushPromises()

    const ids = visibleRunIds(wrapper)
    expect(ids).toHaveLength(1)
    expect(ids[0]).toContain('run-bbb')
    wrapper.unmount()
  })

  it('筛选与搜索可组合，且清空后恢复全部', async () => {
    const { wrapper } = await mountView()
    await chooseFilter(wrapper, 'failed')
    expect(visibleRunIds(wrapper)).toHaveLength(1)

    const input = wrapper.find('[data-testid="runs-search"]')
    await input.setValue('半导体')
    await flushPromises()
    expect(visibleRunIds(wrapper)).toHaveLength(0)

    await input.setValue('')
    await chooseFilter(wrapper, 'all')
    expect(visibleRunIds(wrapper)).toHaveLength(3)
    wrapper.unmount()
  })

  it('筛选无结果时可一次清空状态和关键词', async () => {
    const { wrapper } = await mountView()
    await chooseFilter(wrapper, 'failed')
    await wrapper.get('[data-testid="runs-search"]').setValue('半导体')
    expect(visibleRunIds(wrapper)).toHaveLength(0)

    await wrapper.get('[data-testid="reset-runs-filters"]').trigger('click')
    expect(visibleRunIds(wrapper)).toHaveLength(3)
    wrapper.unmount()
  })
})
