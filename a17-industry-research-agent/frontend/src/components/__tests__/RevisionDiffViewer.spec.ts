import { flushPromises, shallowMount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import { getFeedbackHistory, getRevision } from '../../api/client'
import RevisionDiffViewer from '../RevisionDiffViewer.vue'

vi.mock('../../api/client', () => ({
  getFeedbackHistory: vi.fn(),
  getRevision: vi.fn(),
  restoreRevision: vi.fn(),
}))

function mountViewer() {
  return shallowMount(RevisionDiffViewer, {
    props: { runId: 'run-1', currentRevision: 2 },
    global: {
      stubs: ['el-button', 'el-icon'],
      directives: { loading: () => undefined },
    },
  })
}

it('shows a recoverable error when history cannot load', async () => {
  vi.mocked(getFeedbackHistory).mockRejectedValueOnce(new Error('network failed'))
  const wrapper = mountViewer()
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('修订历史加载失败')
  expect(wrapper.text()).not.toContain('当前为初始生成版本')
})

it('shows a comparison error when only one of the snapshots is available', async () => {
  vi.mocked(getFeedbackHistory).mockResolvedValueOnce([
    {
      stage: 'data_fetch',
      from_revision: 1,
      to_revision: 2,
      comment: null,
      edited_data: null,
      combined_feedback: '',
      timestamp: '2026-11-13T10:00:00Z',
    },
  ])
  vi.mocked(getRevision).mockResolvedValueOnce({} as never)
  vi.mocked(getRevision).mockRejectedValueOnce(new Error('missing snapshot'))
  const wrapper = mountViewer()
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('无法读取版本快照')
  expect(wrapper.find('.diff-lines').exists()).toBe(false)
})
