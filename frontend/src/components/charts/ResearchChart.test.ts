import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { describe, expect, it, vi } from 'vitest'

vi.mock('vue-echarts', () => ({
  default: defineComponent({
    name: 'ECharts',
    props: ['option'],
    template: '<div class="echarts-stub" />',
  }),
}))

import ResearchChart from '@/components/charts/ResearchChart.vue'

describe('ResearchChart', () => {
  it('passes an audited option to the browser renderer', () => {
    const wrapper = mount(ResearchChart, {
      props: {
        spec: {
          chart_id: 'CHART-PIE',
          title: '市场构成',
          chart_type: 'pie',
          variant: 'pie',
          option: { series: [{ type: 'pie', data: [{ name: 'A', value: 60 }] }] },
          evidence_ids: ['E-001'],
          data_fingerprint: 'a'.repeat(64),
          dedupe_key: 'composition:test',
        },
      },
    })

    expect(wrapper.attributes('data-chart-type')).toBe('pie')
    expect(wrapper.find('.echarts-stub').exists()).toBe(true)
    expect(wrapper.text()).toContain('证据：E-001')
  })
})
