import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import MetricCards from '../MetricCards.vue'

/**
 * 「章节 / 小节」卡片的 hint 必须跟随后端下发的基准，不得写死 7 / 21。
 */

function mountCards(quality: Record<string, unknown>) {
  return mount(MetricCards, {
    props: {
      stage: 'report_fusion',
      data: { quality } as never,
    },
    global: { plugins: [ElementPlus, createPinia()] },
  })
}

describe('MetricCards 结构 hint 由后端基准驱动', () => {
  it('使用后端下发的基准', () => {
    const wrapper = mountCards({
      chapter_count: 7,
      section_count: 21,
      expected_chapter_count: 7,
      expected_section_count: 21,
    })

    expect(wrapper.text()).toContain('报告结构（标准 7 章 21 节）')
    expect(wrapper.text()).toContain('7 / 21')
  })

  it('后端基准变化时 hint 跟随', () => {
    const wrapper = mountCards({
      chapter_count: 10,
      section_count: 30,
      expected_chapter_count: 10,
      expected_section_count: 30,
    })

    expect(wrapper.text()).toContain('报告结构（标准 10 章 30 节）')
  })

  it('历史 run 无基准字段时不显示「标准 N 章」，避免误导', () => {
    const wrapper = mountCards({ chapter_count: 7, section_count: 21 })

    expect(wrapper.text()).not.toContain('标准')
    expect(wrapper.text()).toContain('报告结构')
  })
})
