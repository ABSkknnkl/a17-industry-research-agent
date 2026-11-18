import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CreateRunView from '../CreateRunView.vue'

/**
 * A1：问题驱动选图选项（question_planner_mode）端到端透传。
 *
 * 后端 workflow.py 的 ChartGenerationOptions 早在 2026-11-15 就收了该字段
 * （Literal off/observe/apply | None），state_machine 在创建时解析进执行快照。
 * 前端此前没有入口——本组用例锁定：表单选项必须出现在 payload 里。
 */
const mocks = vi.hoisted(() => ({
  createRun: vi.fn(),
  showPipelineOverlay: vi.fn(),
  hidePipelineOverlay: vi.fn(),
}))

vi.mock('../../api/client', () => ({
  createRun: mocks.createRun,
}))

vi.mock('../../composables/usePipelineOverlay', () => ({
  showPipelineOverlay: mocks.showPipelineOverlay,
  hidePipelineOverlay: mocks.hidePipelineOverlay,
}))

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/create', name: 'create', component: CreateRunView },
    { path: '/runs/:runId', name: 'review', component: { template: '<div />' } },
    { path: '/', redirect: { name: 'create' } },
  ],
})

const originalTimezone = process.env.TZ

afterEach(() => {
  vi.useRealTimers()
  if (originalTimezone === undefined) delete process.env.TZ
  else process.env.TZ = originalTimezone
})

beforeEach(() => {
  mocks.createRun.mockReset()
  mocks.createRun.mockResolvedValue({ run_id: 'run-test-1', status: 'running' })
})

async function mountView(): Promise<ReturnType<typeof mount>> {
  await router.push('/create')
  await router.isReady()
  const wrapper = mount(CreateRunView, {
    global: { plugins: [ElementPlus, createPinia(), router] },
    attachTo: document.body,
  })
  await flushPromises()
  return wrapper
}

/** 填最小合法表单（行业主题 + 1 个研究问题）并提交 */
async function submitForm(wrapper: ReturnType<typeof mount>): Promise<void> {
  const topicInput = wrapper.find('input[type="text"]')
  await topicInput.setValue('新能源汽车')
  const textareas = wrapper.findAll('textarea')
  await textareas[0].setValue('2023-2025 年国内新能源汽车零售渗透率如何变化？')
  const submitBtn = wrapper.findAll('button').find((b) => b.text().includes('创建并启动任务'))
  if (!submitBtn) throw new Error('未找到提交按钮')
  await submitBtn.trigger('click')
  await flushPromises()
}

function payloadChartOptions(): Record<string, unknown> {
  const payload = mocks.createRun.mock.calls[0]?.[0] as
    { input_data: { chart_generate_options?: Record<string, unknown> } } | undefined
  return payload?.input_data?.chart_generate_options ?? {}
}

describe('CreateRunView question_planner_mode', () => {
  it('default payload sends question_planner_mode off', async () => {
    const wrapper = await mountView()
    await submitForm(wrapper)
    expect(mocks.createRun).toHaveBeenCalledTimes(1)
    expect(payloadChartOptions().question_planner_mode).toBe('off')
    wrapper.unmount()
  })

  it('apply mode is forwarded in payload', async () => {
    const wrapper = await mountView()
    // 找到「问题驱动选图」radio 组并勾选 apply
    const applyRadio = wrapper
      .findAll('input[type="radio"]')
      .find((input) => input.element.closest('label')?.textContent?.includes('应用模式'))
    if (!applyRadio) throw new Error('未找到应用模式选项')
    await applyRadio.setValue(true)
    await submitForm(wrapper)
    expect(mocks.createRun).toHaveBeenCalledTimes(1)
    expect(payloadChartOptions().question_planner_mode).toBe('apply')
    wrapper.unmount()
  })

  it('关键数据自动补采默认开启，关闭后随任务保存', async () => {
    const wrapper = await mountView()
    await submitForm(wrapper)
    expect(mocks.createRun.mock.calls[0]?.[0]).toMatchObject({
      input_data: { data_fetch_options: { auto_probe_enabled: true } },
    })
    mocks.createRun.mockClear()
    await wrapper.get('[data-testid="auto-probe-switch"] input').setValue(false)
    await submitForm(wrapper)
    expect(mocks.createRun.mock.calls[0]?.[0]).toMatchObject({
      input_data: { data_fetch_options: { auto_probe_enabled: false } },
    })
    wrapper.unmount()
  })

  it('uses the browser local calendar date instead of the previous UTC day', async () => {
    process.env.TZ = 'Asia/Shanghai'
    vi.useFakeTimers({ toFake: ['Date'] })
    // 中国本地 2026-11-16 00:30，但 UTC 仍为 2026-11-15。
    vi.setSystemTime(new Date('2026-11-15T16:30:00.000Z'))
    const wrapper = await mountView()
    await submitForm(wrapper)
    const payload = mocks.createRun.mock.calls[0]?.[0] as
      { input_data: { research_as_of: string } } | undefined
    expect(payload?.input_data.research_as_of).toBe('2026-11-16')
    wrapper.unmount()
  })
})

it('比赛交付模式只保留报告终审', async () => {
  const wrapper = await mountView()
  await wrapper.get('[data-testid="competition-delivery"] input').setValue(true)
  await submitForm(wrapper)
  expect(mocks.createRun.mock.calls[0]?.[0]).toMatchObject({
    delivery_profile: 'competition',
    review_stages: ['report_fusion'],
  })
  wrapper.unmount()
})
