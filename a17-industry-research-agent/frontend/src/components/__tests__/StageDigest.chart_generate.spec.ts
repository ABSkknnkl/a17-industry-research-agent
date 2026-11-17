import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { expect, it, vi } from 'vitest'
import StageDigest from '../StageDigest.vue'

it('按题面展示发布图表与缺口，并能跳到对应卡片', async () => {
  const wrapper = mount(StageDigest, {
    attachTo: document.body,
    props: {
      stage: 'chart_generate',
      data: {
        chart_specs: [{ chart_id: 'CHART-01', figure_number: '图 1' }],
        question_chart_titles: { 'Q-1': '销量如何变化？', 'Q-2': '毛利率如何比较？' },
        question_plan: {
          mode: 'apply',
          coverage: [
            { question_id: 'Q-1', status: 'published', chart_ids: ['CHART-01'], uncovered: [] },
            {
              question_id: 'Q-2',
              status: 'evidence_gap',
              chart_ids: [],
              uncovered: ['毛利率'],
            },
          ],
        },
      },
    },
    global: {
      plugins: [ElementPlus],
      stubs: { ChartGallery: { template: '<div id="workbench-chart-CHART-01" />' } },
    },
  })
  const card = wrapper.get<HTMLElement>('#workbench-chart-CHART-01').element
  const scroll = vi.fn()
  card.scrollIntoView = scroll
  const coverage = wrapper.get('[aria-label="按研究问题核对图表"]')
  expect(coverage.text()).toContain('Q-1 销量如何变化？')
  expect(coverage.text()).toContain('图表缺口：毛利率')
  await coverage.get('button').trigger('click')
  expect(scroll).toHaveBeenCalledWith({ block: 'center' })
  wrapper.unmount()
})
