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

describe('StageDigest · chapter_write 阶段正文排版与防代码泄露', () => {
  it('标准格式段落渲染纯正文，正确统计字数', () => {
    const data = {
      chapters: [
        {
          chapter_id: 'CH-01',
          title: '行业定义与研究基础',
          summary: '这是章节摘要',
          sections: [
            {
              section_id: 'SEC-01-01',
              title: '行业定义、研究边界与证券范围',
              paragraphs: [
                {
                  paragraph_id: 'P-01-01-01',
                  kind: 'thesis',
                  text: '本研究以白银产业为核心，覆盖上游矿产资源开采与冶炼。',
                },
                {
                  paragraph_id: 'P-01-01-02',
                  kind: 'evidence',
                  text: '样本中紫金矿业规模绝对领先。',
                },
              ],
            },
          ],
        },
      ],
    }

    const wrapper = mountDigest(data)
    const text = wrapper.text()

    expect(text).toContain('行业定义与研究基础')
    expect(text).toContain('本研究以白银产业为核心，覆盖上游矿产资源开采与冶炼。')
    expect(text).toContain('样本中紫金矿业规模绝对领先。')
    expect(text).not.toContain('paragraph_id')
    expect(text).not.toContain('[object Object]')
    // 检查正文字数统计：26 + 14 = 40 字
    expect(text).toContain('40 字')
  })

  it('防御性兼容后端嵌套格式 { text: { paragraph_id, text, ... } }，绝不泄露 JSON 代码', () => {
    const nestedData = {
      chapters: [
        {
          chapter_id: 'CH-01',
          title: '行业定义与研究基础',
          sections: [
            {
              section_id: 'SEC-01-01',
              title: '行业定义、研究边界与证券范围',
              paragraphs: [
                {
                  text: {
                    paragraph_id: 'P-01-01-01',
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
    }

    const wrapper = mountDigest(nestedData)
    const text = wrapper.text()

    // 应该展示提取后的纯文本
    expect(text).toContain('嵌套结构下的白银研究核心段落文本。')
    // 绝不应该把整个 JSON 字典代码暴露到页面上
    expect(text).not.toContain('paragraph_id')
    expect(text).not.toContain('evidence_ids')
    expect(text).not.toContain('R-001')
    expect(text).not.toContain('[object Object]')
    expect(text).toContain('17 字')
  })

  it('容错兼容 JSON 字符串化的段落', () => {
    const stringifiedData = {
      chapters: [
        {
          chapter_id: 'CH-01',
          title: '行业定义与研究基础',
          sections: [
            {
              section_id: 'SEC-01-01',
              title: '行业定义、研究边界与证券范围',
              paragraphs: [
                JSON.stringify({
                  paragraph_id: 'P-01-01-01',
                  kind: 'thesis',
                  text: '字符串化后成功解析的段落。',
                }),
              ],
            },
          ],
        },
      ],
    }

    const wrapper = mountDigest(stringifiedData)
    const text = wrapper.text()

    expect(text).toContain('字符串化后成功解析的段落。')
    expect(text).not.toContain('{"paragraph_id"')
  })
})
