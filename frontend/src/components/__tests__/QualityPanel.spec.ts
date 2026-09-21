import { mount } from '@vue/test-utils'
import * as Icons from '@element-plus/icons-vue'
import { createPinia } from 'pinia'
import ElementPlus, { ElTooltip } from 'element-plus'
import { describe, expect, it } from 'vitest'
import QualityPanel from '../QualityPanel.vue'

/**
 * QualityPanel 评分口径：
 * 1) 有后端 total_score / score_breakdown → 界面展示后端确定性分数
 * 2) 历史 run 缺这些字段 → 兜底前端聚合（章节/结构/覆盖率）
 * 3) 分母 expected_* 必须来自后端，不得写死
 */

function mountPanel(fusion: Record<string, unknown>) {
  return mount(QualityPanel, {
    props: { fusion: fusion as never },
    global: {
      plugins: [ElementPlus, createPinia()],
      components: Icons as unknown as Record<string, never>,
    },
  })
}

function qualityPanel(quality: Record<string, unknown>) {
  return mountPanel({ quality })
}

function ringScore(wrapper: ReturnType<typeof mountPanel>): string {
  return wrapper.find('.score-value').text()
}

function barLabels(wrapper: ReturnType<typeof mountPanel>): string[] {
  return wrapper.findAll('.bar-label').map((n) => n.text())
}

function barDisplays(wrapper: ReturnType<typeof mountPanel>): string[] {
  return wrapper.findAll('.bar-value').map((n) => n.text().trim())
}

function hints(wrapper: ReturnType<typeof mountPanel>): string[] {
  return wrapper.findAllComponents(ElTooltip).map((node) => String(node.props('content')))
}

function note(wrapper: ReturnType<typeof mountPanel>): string {
  return wrapper.find('.score-note').text()
}

const backendBreakdown = [
  {
    dimension: 'structure',
    score: 25,
    weight: 25,
    max_score: 25,
    reason: '章节 7/7，小节 21/21',
  },
  {
    dimension: 'evidence_coverage',
    score: 22,
    weight: 30,
    max_score: 30,
    reason: '证据覆盖率 72%',
  },
  {
    dimension: 'citation_consistency',
    score: 15,
    weight: 15,
    max_score: 15,
    reason: '引用全部可追溯',
  },
  {
    dimension: 'dimension_coverage',
    score: 12,
    weight: 20,
    max_score: 20,
    reason: '维度覆盖均值 0.60',
  },
  {
    dimension: 'risk_disclosure',
    score: 10,
    weight: 10,
    max_score: 10,
    reason: '风险全部披露',
  },
]
const backendTotal = backendBreakdown.reduce((s, i) => s + i.score, 0)

describe('QualityPanel 渲染后端确定性评分', () => {
  it('有 total_score 时环上与分项均来自后端，不再前端均值', () => {
    const wrapper = qualityPanel({
      chapter_count: 7,
      section_count: 21,
      evidence_coverage: 1,
      expected_chapter_count: 7,
      expected_section_count: 21,
      total_score: backendTotal,
      score_breakdown: backendBreakdown,
      thresholds: { good: 90, warn: 70 },
    })

    expect(ringScore(wrapper)).toBe(String(backendTotal))
    expect(note(wrapper)).toContain('后端确定性评分')
    expect(barLabels(wrapper)).toEqual([
      '结构完整度',
      '证据覆盖率',
      '引用一致性',
      '维度覆盖',
      '风险披露',
    ])
    // 展示「分数/满分」，与后端 score_breakdown 一致
    expect(barDisplays(wrapper)).toEqual([
      '25/25',
      '22/30',
      '15/15',
      '12/20',
      '10/10',
    ])
    expect(hints(wrapper)).toContain('证据覆盖率 72%')
  })

  it('total_score 与分项之和不一致时，环上仍以 total_score 为准（后端字段权威）', () => {
    const wrapper = qualityPanel({
      total_score: 86,
      score_breakdown: backendBreakdown,
      thresholds: { good: 90, warn: 70 },
    })
    expect(ringScore(wrapper)).toBe('86')
  })

  it('阈值颜色说明使用后端 thresholds', () => {
    const wrapper = qualityPanel({
      total_score: 95,
      score_breakdown: [],
      thresholds: { good: 90, warn: 70 },
    })
    expect(note(wrapper)).toContain('优≥90')
    expect(note(wrapper)).toContain('警≥70')
  })
})

describe('QualityPanel 历史 run 兜底（无后端总分）', () => {
  it('基准 7/21 且实际 7/21 → 章节与结构均为 100%', () => {
    const wrapper = qualityPanel({
      chapter_count: 7,
      section_count: 21,
      evidence_coverage: 1,
      expected_chapter_count: 7,
      expected_section_count: 21,
    })

    expect(note(wrapper)).toContain('历史数据前端聚合')
    expect(hints(wrapper)).toContain('章节数 / 标准 7 章')
    expect(hints(wrapper)).toContain('小节数 / 标准 21 节')
    expect(barDisplays(wrapper).slice(0, 2)).toEqual(['100%', '100%'])
  })

  it('实际少于基准 → 按后端基准折算（5/7≈71、15/21≈71）', () => {
    const wrapper = qualityPanel({
      chapter_count: 5,
      section_count: 15,
      expected_chapter_count: 7,
      expected_section_count: 21,
    })

    expect(barDisplays(wrapper).slice(0, 2)).toEqual(['71%', '71%'])
  })

  it('后端下发非 7/21 基准时，前端跟随变化（分母未写死）', () => {
    const wrapper = qualityPanel({
      chapter_count: 10,
      section_count: 30,
      expected_chapter_count: 10,
      expected_section_count: 30,
    })

    expect(hints(wrapper)).toContain('章节数 / 标准 10 章')
    expect(hints(wrapper)).toContain('小节数 / 标准 30 节')
    expect(barDisplays(wrapper).slice(0, 2)).toEqual(['100%', '100%'])

    const shifted = qualityPanel({
      chapter_count: 7,
      section_count: 21,
      expected_chapter_count: 10,
      expected_section_count: 30,
    })
    expect(barDisplays(shifted).slice(0, 2)).toEqual(['70%', '70%'])
  })

  it('历史 run 无基准字段 → 兜底 7/21，不回归', () => {
    const wrapper = qualityPanel({ chapter_count: 7, section_count: 21 })

    expect(hints(wrapper)).toContain('章节数 / 标准 7 章')
    expect(hints(wrapper)).toContain('小节数 / 标准 21 节')
    expect(barDisplays(wrapper).slice(0, 2)).toEqual(['100%', '100%'])
  })
})
