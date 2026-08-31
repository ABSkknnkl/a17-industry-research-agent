import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReviewActions from '../ReviewActions.vue'
import { submitReview } from '../../api/client'
import type { StageName, StageResult } from '../../api/types'

vi.mock('../../api/client', () => ({
  submitReview: vi.fn(),
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
  it('data_fetch 阶段不展示「修订后的研究问题」输入框', async () => {
    const wrapper = mountComponent('data_fetch')
    await openReviseDialog(wrapper)

    // 修复前：data_fetch 也渲染研究问题 textarea，诱导用户填出后端 422 的字段
    const textareas = wrapper.findAll('textarea')
    expect(textareas.length).toBe(1)
    // 唯一的 textarea 是修改备注；研究问题输入框不应出现
    expect(wrapper.text()).toContain('修改备注')
    expect(wrapper.text()).not.toContain('修订后的研究问题')
  })

  it('data_fetch 修订仅提交 comment，edited_data 为 null（回归测试：修复前会带 focus_questions 触发 422）', async () => {
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
    // 后端 DataFetchReviewEdits 白名单只接受 data_fetch_options：
    // 提交 focus_questions 会 422（"edited_data is not allowed for data_fetch"）
    expect(payload.edited_data).toBeNull()
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
