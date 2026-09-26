import { mount } from '@vue/test-utils'
import * as Icons from '@element-plus/icons-vue'
import { createPinia } from 'pinia'
import ElementPlus, { ElTooltip } from 'element-plus'
import { describe, expect, it } from 'vitest'
import QualityPanel from '../QualityPanel.vue'

/**
 * 评分基准回归：完整度分母**必须来自后端**（quality.expected_*），不得写死 7 / 21。
 *
 * 关键用例是「后端下发非 7/21 基准时前端跟着变」——
 * 如果分母是写死的，那条会失败。
 */

function mountPanel(quality: Record<string, unknown>) {
  return mount(QualityPanel, {
    props: { fusion: { quality } as never },
    global: {
      plugins: [ElementPlus, createPinia()],
      // 真实应用在 main.ts 全局注册图标，测试环境需补上
      components: Icons as unknown as Record<string, never>,
    },
  })
}

/** 各子项分值（章节完整度 / 结构完整度 / 证据覆盖率） */
function subScoreValues(wrapper: ReturnType<typeof mountPanel>): number[] {
  return wrapper.findAll('.bar-value').map((node) => Number(node.text().replace('%', '')))
}

/** hint 在 el-tooltip 的 content prop 里，不在 text() 里 */
function hints(wrapper: ReturnType<typeof mountPanel>): string[] {
  return wrapper.findAllComponents(ElTooltip).map((node) => String(node.props('content')))
}

describe('QualityPanel 评分基准由后端下发', () => {
  it('基准 7/21 且实际 7/21 → 章节与结构均为 100，hint 显示标准值', () => {
    const wrapper = mountPanel({
      chapter_count: 7,
      section_count: 21,
      evidence_coverage: 1,
      expected_chapter_count: 7,
      expected_section_count: 21,
    })

    expect(hints(wrapper)).toContain('章节数 / 标准 7 章')
    expect(hints(wrapper)).toContain('小节数 / 标准 21 节')
    expect(subScoreValues(wrapper).slice(0, 2)).toEqual([100, 100])
  })

  it('实际少于基准 → 按后端基准折算（5/7≈71、15/21≈71）', () => {
    const wrapper = mountPanel({
      chapter_count: 5,
      section_count: 15,
      expected_chapter_count: 7,
      expected_section_count: 21,
    })

    expect(subScoreValues(wrapper).slice(0, 2)).toEqual([71, 71])
  })

  it('后端下发非 7/21 基准时，前端跟随变化（证明分母未写死）', () => {
    const wrapper = mountPanel({
      chapter_count: 10,
      section_count: 30,
      expected_chapter_count: 10,
      expected_section_count: 30,
    })

    expect(hints(wrapper)).toContain('章节数 / 标准 10 章')
    expect(hints(wrapper)).toContain('小节数 / 标准 30 节')
    expect(subScoreValues(wrapper).slice(0, 2)).toEqual([100, 100])

    // 反向关键用例：实际 = 旧写死基准 7/21，而后端基准是 10/30 → 应为 70。
    // 分母若写死 7/21 这里会得 100，从而暴露回归。
    const shifted = mountPanel({
      chapter_count: 7,
      section_count: 21,
      expected_chapter_count: 10,
      expected_section_count: 30,
    })
    expect(subScoreValues(shifted).slice(0, 2)).toEqual([70, 70])
  })

  it('历史 run 无基准字段 → 兜底 7/21，不回归', () => {
    const wrapper = mountPanel({ chapter_count: 7, section_count: 21 })

    expect(hints(wrapper)).toContain('章节数 / 标准 7 章')
    expect(hints(wrapper)).toContain('小节数 / 标准 21 节')
    expect(subScoreValues(wrapper).slice(0, 2)).toEqual([100, 100])
  })

  it('含质检冲突与警告时，动态计算数据合规分并执行加权评分', () => {
    const wrapper = mountPanel({
      chapter_count: 7,
      section_count: 21,
      expected_chapter_count: 7,
      expected_section_count: 21,
      evidence_coverage: 0.97,
      passed: true,
      issues: [
        '检测到跨章节总市值数量级冲突，总编辑已启用事实基准自动对齐',
        '趋势分析多数样本仅3-5个观测，统计功效有限',
        '部分公司财务数据缺失，可比性受限',
        '五粮液毛利率数据在不同来源中存在冲突（5.52% vs 77.54%）',
        '样本中部分公司出现亏损，普通PE排名不适用',
      ],
    })

    const values = subScoreValues(wrapper)
    expect(values).toHaveLength(4)
    expect(values[0]).toBe(100) // 章节完整度
    expect(values[1]).toBe(100) // 结构完整度
    expect(values[2]).toBe(97)  // 证据覆盖率
    expect(values[3]).toBe(86)  // 数据一致与合规 (100 - 14)
    // 综合加权得分：100*0.1 + 100*0.1 + 97*0.4 + 86*0.4 = 93.2 -> 93
    expect(wrapper.find('.score-value').text()).toBe('93')
  })
})

