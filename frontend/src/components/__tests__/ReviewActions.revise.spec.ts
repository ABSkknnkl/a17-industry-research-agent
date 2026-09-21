import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReviewActions from '../ReviewActions.vue'
import { submitReview } from '../../api/client'
import type { StageName, StageResult } from '../../api/types'

vi.mock('../../api/client', () => ({
  submitReview: vi.fn(),
  downloadArtifact: vi.fn(),
  triggerBlobDownload: vi.fn(),
}))

const submitReviewMock = vi.mocked(submitReview)

function makeResult(stage: StageName): StageResult {
  return {
    stage,
    status: 'waiting_review',
    revision: 1,
    data: {},
    artifacts: [],
    evidence_sources: [],
    error: null,
  }
}

function mountComponent(stage: StageName) {
  return mount(ReviewActions, {
    props: {
      runId: 'run-1',
      stage,
      result: makeResult(stage),
      revision: 3,
    },
    global: {
      plugins: [ElementPlus],
    },
  })
}

async function openReviseDialog(wrapper: ReturnType<typeof mountComponent>) {
  const trigger = wrapper.findAll('button').find((b) => b.text().includes('修改条件重跑'))
  expect(trigger, '应存在「修改条件重跑」按钮').toBeTruthy()
  await trigger!.trigger('click')
  await flushPromises()
}

async function clickSubmit(wrapper: ReturnType<typeof mountComponent>) {
  const submit = wrapper.findAll('button').find((b) => b.text().includes('提交修订并重跑'))
  expect(submit, '修订对话框应存在提交按钮').toBeTruthy()
  await submit!.trigger('click')
  await flushPromises()
}

beforeEach(() => {
  submitReviewMock.mockReset()
  submitReviewMock.mockResolvedValue({ run_id: 'run-1' } as never)
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('ReviewActions revise payload 契约（后端 ReviewEdits 白名单）', () => {
  // 2026-09-01 契约变更：DataFetchReviewEdits 白名单已纳入 focus_questions
  // （advisory 升级门下用户「删除某个研究问题」的修订诉求需要合法通道），
  // 因此 data_fetch 与 data_interpret 两个阶段都展示研究问题输入框。
  it('data_fetch 阶段展示「修订后的研究问题」输入框', async () => {
    const wrapper = mountComponent('data_fetch')
    await openReviseDialog(wrapper)

    const textareas = wrapper.findAll('textarea')
    expect(textareas.length).toBe(2)
    expect(wrapper.text()).toContain('修改备注')
    expect(wrapper.text()).toContain('修订后的研究问题')
  })

  it('data_fetch 修订仅填备注时，edited_data 为 null', async () => {
    const wrapper = mountComponent('data_fetch')
    await openReviseDialog(wrapper)

    await wrapper.findAll('textarea')[0].setValue('请补充动力电池装机量数据，时间扩大到近5年')
    await clickSubmit(wrapper)

    expect(submitReviewMock).toHaveBeenCalledTimes(1)
    const payload = submitReviewMock.mock.calls[0][0] as unknown as Record<string, unknown>
    expect(payload.stage).toBe('data_fetch')
    expect(payload.action).toBe('revise')
    expect(payload.run_id).toBe('run-1')
    expect(payload.expected_revision).toBe(3)
    expect(payload.comment).toBe('请补充动力电池装机量数据，时间扩大到近5年')
    expect(payload.edited_data).toBeNull()
  })

  it('data_fetch 修订提交研究问题时按白名单契约携带 focus_questions', async () => {
    const wrapper = mountComponent('data_fetch')
    await openReviseDialog(wrapper)

    const textareas = wrapper.findAll('textarea')
    await textareas[0].setValue('删除第三个问题')
    await textareas[1].setValue('锂电池行业2024-2025年出货量如何？')
    await clickSubmit(wrapper)

    expect(submitReviewMock).toHaveBeenCalledTimes(1)
    const payload = submitReviewMock.mock.calls[0][0] as unknown as Record<string, unknown>
    expect(payload.stage).toBe('data_fetch')
    expect(payload.edited_data).toEqual({
      focus_questions: ['锂电池行业2024-2025年出货量如何？'],
    })
  })

  it('data_interpret 修订仍按契约提交 focus_questions', async () => {
    const wrapper = mountComponent('data_interpret')
    await openReviseDialog(wrapper)

    // data_interpret 白名单允许 focus_questions，应渲染两个输入框
    const textareas = wrapper.findAll('textarea')
    expect(textareas.length).toBe(2)

    await textareas[0].setValue('请补充估值维度的分析')
    await textareas[1].setValue('锂电池行业2024-2025年营收增速如何？\n宁德时代2024年毛利率？')
    await clickSubmit(wrapper)

    expect(submitReviewMock).toHaveBeenCalledTimes(1)
    const payload = submitReviewMock.mock.calls[0][0] as unknown as Record<string, unknown>
    expect(payload.stage).toBe('data_interpret')
    expect(payload.action).toBe('revise')
    expect(payload.comment).toBe('请补充估值维度的分析')
    expect(payload.edited_data).toEqual({
      focus_questions: ['锂电池行业2024-2025年营收增速如何？', '宁德时代2024年毛利率？'],
    })
  })

  it('两个输入框都为空时阻止提交且不调用接口', async () => {
    const wrapper = mountComponent('data_fetch')
    await openReviseDialog(wrapper)
    await clickSubmit(wrapper)

    expect(submitReviewMock).not.toHaveBeenCalled()
  })
})

/**
 * submitted 事件契约：第二阶段参数 { stage, action } 供 ReviewView 判断
 * 「本次通过的是否为最后一个阶段」——只看返回的 run.status 在 mock 下会误判
 * （mock returnStage 会把 workflowStatus 置为 waiting_review，与未批准同态）。
 */
describe('ReviewActions submitted 事件契约', () => {
  it('通过阶段时 emit 的 meta 携带被审阶段与动作类型', async () => {
    const wrapper = mountComponent('report_fusion')

    const approve = wrapper.find('[data-testid="btn-approve"]')
    expect(approve.exists()).toBe(true)
    await approve.trigger('click')
    await flushPromises()

    const emitted = wrapper.emitted('submitted') as unknown[][] | undefined
    expect(emitted).toBeTruthy()
    expect(emitted![0]![1]).toEqual({ stage: 'report_fusion', action: 'approve' })
  })

  it('修订动作的 meta 里 action 为 revise（不应触发自动跳转）', async () => {
    const wrapper = mountComponent('data_interpret')
    await openReviseDialog(wrapper)

    await wrapper.findAll('textarea')[0].setValue('请补充估值维度')
    await clickSubmit(wrapper)

    const emitted = wrapper.emitted('submitted') as unknown[][] | undefined
    expect(emitted).toBeTruthy()
    expect(emitted![0]![1]).toEqual({ stage: 'data_interpret', action: 'revise' })
  })
})
