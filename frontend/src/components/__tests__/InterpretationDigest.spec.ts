import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import InterpretationDigest from '../InterpretationDigest.vue'

function mountDigest(data: Record<string, unknown>, sourceRecords?: Record<string, unknown>[]) {
  return mount(InterpretationDigest, {
    props: { data, sourceRecords },
    global: { plugins: [ElementPlus] },
  })
}

describe('InterpretationDigest 可读凭证与差异化异常信息', () => {
  it('用实体、指标和值展示洞察凭证，不暴露内部编号', () => {
    const wrapper = mountDigest({
      insights: [
        {
          insight_id: 'INS-1',
          title: '龙头收入领先',
          conclusion: '宁德时代收入规模领先。',
          confidence: 'high',
          evidence_record_ids: ['R-secret-1'],
        },
      ],
      evidence_digest: {
        'R-secret-1': {
          label: '宁德时代 · 营业收入 2769.17亿元',
        },
      },
    })

    expect(wrapper.text()).toContain('宁德时代 · 营业收入 2769.17亿元')
    expect(wrapper.text()).not.toContain('R-secret-1')
  })

  it('旧任务缺少凭证摘要时从阶段一来源记录生成标签', () => {
    const wrapper = mountDigest(
      {
        insights: [
          {
            insight_id: 'INS-OLD',
            title: '利润率变化',
            conclusion: '毛利率发生变化。',
            confidence: 'high',
            evidence_record_ids: ['R-old-1'],
          },
        ],
      },
      [
        {
          record_id: 'R-old-1',
          entity_name: '比亚迪',
          metric: 'gross_margin',
          value: 18.8473,
          period: '2026-06-30',
        },
      ]
    )

    expect(wrapper.text()).toContain('比亚迪 · 毛利率 18.8473')
    expect(wrapper.text()).not.toContain('R-old-1')
  })

  it('展示异常类型、具体数据点和参考区间', async () => {
    const wrapper = mountDigest({
      risks: [
        {
          risk_code: 'ANO-1',
          kind: 'cross_sectional_outlier',
          severity: 'high',
          entity: '宁德时代',
          metric: '营业收入',
          observed_value: 92.12,
          expected_range: '40–60',
          description: '该值的稳健 Z 分数超过阈值。',
        },
      ],
    })

    await wrapper.find('input[value="coverage"]').setValue()

    const text = wrapper.text()
    expect(text).toContain('投研风险警示（1 条）')
    expect(text).toContain('同业离群')
    expect(text).toContain('宁德时代 · 营业收入')
    expect(text).toContain('观测值 92.12')
    expect(text).toContain('参考区间 40–60')
    expect(text).not.toContain('稳健 Z 分数')
  })
})
