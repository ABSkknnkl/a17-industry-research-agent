import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import StageDigest from '../StageDigest.vue'

function mountDigest(data: Record<string, unknown>) {
  return mount(StageDigest, {
    props: { stage: 'chapter_write', data },
    global: { plugins: [ElementPlus, createPinia()] },
  })
}

describe('StageDigest · chapter_write real agent paragraphs', () => {
  it('renders normal paragraphs and counts their text', () => {
    const wrapper = mountDigest({
      chapters: [
        {
          chapter_id: 'CH-01',
          title: '行业定义与研究基础',
          sections: [
            {
              section_id: 'SEC-01-01',
              title: '研究范围',
              paragraphs: [
                { paragraph_id: 'P-1', text: '本研究以白银产业为核心，覆盖上游矿产资源开采与冶炼。' },
                { paragraph_id: 'P-2', text: '样本中紫金矿业规模绝对领先。' },
              ],
            },
          ],
        },
      ],
    })

    expect(wrapper.text()).toContain('40 字')
    expect(wrapper.text()).not.toContain('paragraph_id')
  })

  it('unwraps nested paragraph objects without leaking JSON', () => {
    const wrapper = mountDigest({
      chapters: [
        {
          chapter_id: 'CH-01',
          title: '行业定义与研究基础',
          sections: [
            {
              section_id: 'SEC-01-01',
              title: '研究范围',
              paragraphs: [
                {
                  text: {
                    paragraph_id: 'P-1',
                    kind: 'thesis',
                    text: '嵌套结构下的白银研究核心段落文本。',
                    evidence_ids: ['R-001'],
                  },
                },
              ],
            },
          ],
        },
      ],
    })

    const text = wrapper.text()
    expect(text).toContain('嵌套结构下的白银研究核心段落文本。')
    expect(text).toContain('17 字')
    expect(text).not.toContain('paragraph_id')
    expect(text).not.toContain('evidence_ids')
    expect(text).not.toContain('R-001')
    expect(text).not.toContain('[object Object]')
  })

  it('parses stringified paragraphs', () => {
    const wrapper = mountDigest({
      chapters: [
        {
          chapter_id: 'CH-01',
          title: '行业定义与研究基础',
          sections: [
            {
              section_id: 'SEC-01-01',
              title: '研究范围',
              paragraphs: [
                JSON.stringify({ paragraph_id: 'P-1', text: '字符串化后成功解析的段落。' }),
              ],
            },
          ],
        },
      ],
    })

    expect(wrapper.text()).toContain('字符串化后成功解析的段落。')
    expect(wrapper.text()).not.toContain('{"paragraph_id"')
  })
})
