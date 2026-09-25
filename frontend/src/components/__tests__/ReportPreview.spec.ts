import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import ReportPreview from '../ReportPreview.vue'

/**
 * 核心需求回归：**前端按后端数据原样渲染章节名，不做任何改写。**
 *
 * 用户原话：「比如目录第一章叫『原神』，名称也能显示就行」。
 * 因此本文件断言的是「显示值 === 后端给的值」，而不是「显示得像不像标准报告」。
 */

function fusionWith(chapterTitles: string[]) {
  return {
    title: '动力电池行业研究报告',
    industry_topic: '动力电池行业',
    research_as_of: '2026-01-15',
    chapters: chapterTitles.map((title, idx) => ({
      chapter_id: `CH-0${idx + 1}`,
      title,
      sections: [{ section_id: `SEC-0${idx + 1}-01`, title: '第一节' }],
    })),
  }
}

function mountPreview(chapterTitles: string[]) {
  return mount(ReportPreview, {
    props: { fusion: fusionWith(chapterTitles) as never },
    global: { plugins: [ElementPlus, createPinia()] },
  })
}

/** 只取章节列表里的名称（排除附录「来源与证据索引」项） */
function outlineNames(wrapper: ReturnType<typeof mountPreview>): string[] {
  return wrapper.findAll('.outline-list .outline-name').map((node) => node.text())
}

function outlineItems(wrapper: ReturnType<typeof mountPreview>) {
  return wrapper.findAll('.outline-list .outline-item')
}

describe('ReportPreview 按后端数据原样渲染', () => {
  it('后端把第一章命名为「原神」，前端原样显示', () => {
    const wrapper = mountPreview(['原神', '市场规模与成长性'])

    expect(outlineNames(wrapper)).toEqual(['原神', '市场规模与成长性'])
    expect(wrapper.text()).toContain('原神')
  })

  it('不做任何标题改写：带序号的标题也原样显示（不剥离「1、」）', () => {
    const wrapper = mountPreview(['1、原神', '2、行业定义'])

    expect(outlineNames(wrapper)).toEqual(['1、原神', '2、行业定义'])
  })

  it('章节序号来自数组下标，与标题内容无关', () => {
    const wrapper = mountPreview(['原神', '第二回 · 提瓦特', '任意名字'])

    const numbers = wrapper.findAll('.outline-list .outline-no').map((node) => node.text())
    expect(numbers).toEqual(['01', '02', '03'])
    expect(outlineNames(wrapper)).toEqual(['原神', '第二回 · 提瓦特', '任意名字'])
  })

  it('章节数量随后端变化（不写死 7 章）', () => {
    const wrapper = mountPreview(['一', '二', '三'])
    expect(outlineItems(wrapper)).toHaveLength(3)
    expect(wrapper.text()).toContain('3 章')
  })

  it('后端未给章节时显示空态，不报错', () => {
    const wrapper = mount(ReportPreview, {
      props: { fusion: { title: '空报告' } as never },
      global: { plugins: [ElementPlus, createPinia()] },
    })

    expect(wrapper.text()).toContain('融合结果尚未包含章节')
    expect(outlineNames(wrapper)).toEqual([])
  })

  it('封面字段原样取后端值', () => {
    const wrapper = mount(ReportPreview, {
      props: {
        fusion: {
          title: '自定义标题',
          industry_topic: '自定义行业',
          research_as_of: '2026-09-17',
          report_depth: 'deep',
        } as never,
      },
      global: { plugins: [ElementPlus, createPinia()] },
    })

    const text = wrapper.text()
    expect(text).toContain('自定义标题')
    expect(text).toContain('自定义行业')
    expect(text).toContain('2026-09-17')
    expect(text).toContain('深度 deep')
  })
})
