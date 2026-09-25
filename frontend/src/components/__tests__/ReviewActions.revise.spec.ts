import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus, { ElMessageBox } from 'element-plus'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReviewActions from '../ReviewActions.vue'
import StageInterventionModal from '../StageInterventionModal.vue'
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

beforeEach(() => {
  submitReviewMock.mockReset()
  submitReviewMock.mockResolvedValue({ run_id: 'run-1' } as never)
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('ReviewActions 差异化人机协同控制区（彻底清理旧通用介入）', () => {
  it('不应再渲染旧的千篇一律通用介入按钮', () => {
    const wrapper = mountComponent('data_fetch')
    const buttonTexts = wrapper.findAll('button').map((b) => b.text())
    expect(buttonTexts.some((t) => t.includes('修改条件重跑'))).toBe(false)
    expect(buttonTexts.some((t) => t.includes('原条件重新生成'))).toBe(false)
    expect(wrapper.find('[data-testid="btn-revise"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="btn-direct-edit"]').exists()).toBe(false)
  })

  it('data_fetch 阶段正确渲染数据采集专属的 3 项介入功能', () => {
    const wrapper = mountComponent('data_fetch')
    const text = wrapper.text()
    expect(text).toContain('增量数据补采')
    expect(text).toContain('局部子域重采')
    expect(text).toContain('脏数据清洗与剔除')
  })

  it('chapter_write 阶段正确渲染章节撰写专属的 3 项介入功能', () => {
    const wrapper = mountComponent('chapter_write')
    const text = wrapper.text()
    expect(text).toContain('指定单章定向重写')
    expect(text).toContain('正文段落就地精修')
    expect(text).toContain('研报行文风格引导')
  })

  it('点击阶段专属功能按钮时调起 StageInterventionModal 弹窗', async () => {
    const wrapper = mountComponent('chapter_write')
    const rewriteBtn = wrapper.findAll('button').find((b) => b.text().includes('指定单章定向重写'))
    expect(rewriteBtn).toBeTruthy()
    await rewriteBtn!.trigger('click')
    await flushPromises()

    const modal = wrapper.findComponent(StageInterventionModal)
    expect(modal.exists()).toBe(true)
    expect(modal.props('visible')).toBe(true)
    expect(modal.props('initialTab')).toBe('single_chapter')
  })
})

describe('ReviewActions 提交与事件契约', () => {
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

  it('阶段协同弹窗触发 submit-revise 时向后端提交 revise 请求', async () => {
    const wrapper = mountComponent('data_fetch')
    const modal = wrapper.findComponent(StageInterventionModal)
    expect(modal.exists()).toBe(true)

    // 模拟子组件派发 submit-revise
    modal.vm.$emit('submit-revise', {
      comment: '补充低空经济装机量数据',
      edited_data: { focus_questions: ['测试问题'] },
    })
    await flushPromises()

    expect(submitReviewMock).toHaveBeenCalledTimes(1)
    const payload = submitReviewMock.mock.calls[0][0] as unknown as Record<string, unknown>
    expect(payload.stage).toBe('data_fetch')
    expect(payload.action).toBe('revise')
    expect(payload.run_id).toBe('run-1')
    expect(payload.expected_revision).toBe(3)
    expect(payload.comment).toBe('补充低空经济装机量数据')
    expect(payload.edited_data).toEqual({ focus_questions: ['测试问题'] })
  })

  it('阶段协同弹窗触发 submit-direct-edit 时向后端提交 direct_edit 请求', async () => {
    const wrapper = mountComponent('chapter_write')
    const modal = wrapper.findComponent(StageInterventionModal)
    expect(modal.exists()).toBe(true)

    modal.vm.$emit('submit-direct-edit', {
      comment: '正文段落手工微调',
      edited_data: { chapter_id: 'CH-01', paragraphs: ['新段落内容'] },
    })
    await flushPromises()

    expect(submitReviewMock).toHaveBeenCalledTimes(1)
    const payload = submitReviewMock.mock.calls[0][0] as unknown as Record<string, unknown>
    expect(payload.stage).toBe('chapter_write')
    expect(payload.action).toBe('direct_edit')
    expect(payload.edited_data).toEqual({ chapter_id: 'CH-01', paragraphs: ['新段落内容'] })
  })

  it('右上角取消任务按钮可触发取消操作', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const wrapper = mountComponent('chapter_write')
    const cancelBtn = wrapper.find('[data-testid="btn-cancel"]')
    expect(cancelBtn.exists()).toBe(true)
    await cancelBtn.trigger('click')
    await flushPromises()

    expect(submitReviewMock).toHaveBeenCalledTimes(1)
    const payload = submitReviewMock.mock.calls[0][0] as unknown as Record<string, unknown>
    expect(payload.action).toBe('cancel')
  })
})
