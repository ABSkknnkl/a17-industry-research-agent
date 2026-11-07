import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import StageInterventionModal from '../StageInterventionModal.vue'
import ReviewActions from '../ReviewActions.vue'
import { submitReview } from '../../api/client'
import type { WorkflowState } from '../../api/types'

vi.mock('../../api/client', () => ({ submitReview: vi.fn() }))
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => {
  wrappers.forEach((wrapper) => wrapper.unmount())
  wrappers.length = 0
  document.body.innerHTML = ''
})

async function clickButton(label: string) {
  const button = Array.from(document.querySelectorAll('button')).find((item) =>
    item.textContent?.includes(label)
  )
  expect(button).toBeDefined()
  button!.click()
  await flushPromises()
}

describe('report editing truthful defaults and export status', () => {
  it('preserves production metric identity, evidence and extension fields on save', async () => {
    const source = {
      metric_id: 'metric-prod-1',
      name: '营业收入',
      value: 100,
      unit: '亿元',
      entity: '公司甲',
      period: '2025-12-31',
      evidence_record_ids: ['R-prod'],
      importance_score: 1,
      extension: { retain: true },
    }
    const wrapper = mount(StageInterventionModal, {
      props: {
        visible: true,
        stage: 'report_fusion',
        revision: 1,
        data: { key_metrics: [source] },
        initialTab: 'metric_cards',
      },
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    wrappers.push(wrapper)
    await flushPromises()
    await clickButton('保存 8 张核心指标卡定制')
    expect(wrapper.emitted('submitDirectEdit')?.[0]?.[0]).toMatchObject({
      edited_data: {
        key_metrics: [
          {
            metric_id: source.metric_id,
            evidence_record_ids: source.evidence_record_ids,
            entity: source.entity,
            period: source.period,
            extension: source.extension,
          },
        ],
      },
    })
    expect(source.value).toBe(100)
  })

  it('does not manufacture metric values from an empty report', async () => {
    const wrapper = mount(StageInterventionModal, {
      props: {
        visible: true,
        stage: 'report_fusion',
        revision: 1,
        data: {},
        initialTab: 'metric_cards',
      },
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    wrappers.push(wrapper)
    await flushPromises()
    await clickButton('保存 8 张核心指标卡定制')
    expect(wrapper.emitted('submitDirectEdit')?.[0]?.[0]).toMatchObject({
      edited_data: { key_metrics: [] },
    })
  })

  it('does not assign a buy rating to a report without an investment rating', async () => {
    const wrapper = mount(StageInterventionModal, {
      props: {
        visible: true,
        stage: 'report_fusion',
        revision: 1,
        data: {},
        initialTab: 'summary_rating',
      },
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    wrappers.push(wrapper)
    await flushPromises()
    await clickButton('保存评级与执行摘要定稿')
    expect(wrapper.emitted('submitDirectEdit')?.[0]?.[0]).toMatchObject({
      edited_data: { investment_rating: '' },
    })
  })

  it.each([
    [
      { exports_stale: true, formats: [], export_notice: '需重新融合以生成当前导出文件' },
      '需重新融合以生成当前导出文件',
    ],
    [{ exports_stale: false, formats: ['markdown', 'html'] }, 'PDF 需重新融合后生成'],
  ])('reports actual export availability after saving (%j)', async (data, notice) => {
    const result = {
      stage: 'report_fusion' as const,
      status: 'waiting_review' as const,
      revision: 1,
      data: {},
      artifacts: [],
      evidence_sources: [],
      error: null,
    }
    const state: WorkflowState = {
      project_id: 'test',
      run_id: 'run-export',
      current_stage: 'report_fusion',
      status: 'waiting_review',
      revision: 2,
      stage_results: { report_fusion: { ...result, revision: 2, data } },
      created_at: '2026-10-30T00:00:00Z',
      updated_at: '2026-10-30T00:00:00Z',
    }
    vi.mocked(submitReview).mockResolvedValue(state)
    const wrapper = mount(ReviewActions, {
      props: { runId: 'run-export', stage: 'report_fusion', result, revision: 1 },
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    wrappers.push(wrapper)
    await clickButton('8 张核心指标卡定制')
    await clickButton('保存 8 张核心指标卡定制')
    expect(document.body.textContent).toContain(notice)
  })
})
