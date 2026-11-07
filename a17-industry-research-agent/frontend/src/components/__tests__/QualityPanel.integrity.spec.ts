import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import QualityPanel from '../QualityPanel.vue'

it('门禁失败时不把结构和引用率合成事实准确性评分', () => {
  const wrapper = mount(QualityPanel, {
    props: {
      fusion: {
        title: '受限草稿',
        quality: {
          passed: false,
          chapter_count: 7,
          section_count: 21,
          evidence_coverage: 0.97,
          issues: ['审校防幻觉拦截2处未获授权的编辑'],
        },
      },
    },
    global: { stubs: ['el-progress', 'el-tag', 'el-tooltip', 'el-icon'] },
  })
  expect(wrapper.find('.score-ring').exists()).toBe(false)
  expect(wrapper.text()).toContain('核心论据引用率')
  expect(wrapper.text()).not.toContain('100% 捍卫正文事实准确性')
})
