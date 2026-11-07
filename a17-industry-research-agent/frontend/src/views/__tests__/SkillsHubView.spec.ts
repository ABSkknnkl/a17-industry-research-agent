import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ElementPlus from 'element-plus'
import SkillsHubView from '../SkillsHubView.vue'
import * as client from '../../api/client'
import type { SkillCatalogResponse } from '../../api/types'

const mockCatalog: SkillCatalogResponse = {
  total: 66,
  agents: [
    {
      stage_id: 'data_fetch',
      stage_num: 1,
      agent_name: '数据获取智能体',
      agent_role: 'Data Fetcher',
      badge_text: '25 项专业技能',
      description: '负责问财金融自然语言查询与结构化取数',
      skills_count: 25,
      skills: [
        {
          id: 'stock_search',
          name: '全量A股股票检索与筛选',
          description: '通过问财自然语言指令筛选符合条件股票',
          domains: ['股票', '选股'],
          keywords: ['市盈率', '净利润'],
          source: '问财自然语言接口',
          category: '股票行情与筛选',
          full_doc: '# 股票检索规范\n\n使用标准问财语法进行股票筛选。',
        },
        {
          id: 'macro_economy',
          name: '宏观经济与产业统计指标查询',
          description: '查询GDP、PMI、PPI等宏观产业统计数据',
          domains: ['宏观', '统计'],
          keywords: ['GDP', 'PMI'],
          source: '问财自然语言接口',
          category: '宏观与产业数据',
          full_doc: '# 宏观经济规范\n\n查询最新宏观指标。',
        },
      ],
    },
    {
      stage_id: 'data_interpret',
      stage_num: 2,
      agent_name: '数据解读智能体',
      agent_role: 'Data Interpreter',
      badge_text: '20 项专业技能',
      description: '负责量化分析、行业竞争格局识别与杜邦分析',
      skills_count: 20,
      skills: [
        {
          id: 'dupont_analysis',
          name: '杜邦分析与ROE三因子拆解',
          description: '净利率、资产周转率与权益乘数归因',
          domains: ['财务', '杜邦'],
          category: '量化与财务分析',
          full_doc: '# 杜邦分析规范\n\n拆解ROE核心驱动力。',
        },
      ],
    },
  ],
}

describe('SkillsHubView 问财Skill知识库', () => {
  it('正确渲染页面标题、英雄横幅、统计指标与各智能体独立分区', async () => {
    vi.spyOn(client, 'getSkillsCatalog').mockResolvedValue(mockCatalog)

    const wrapper = mount(SkillsHubView, {
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    // 标题与横幅
    expect(wrapper.text()).toContain('同花顺问财金融 Skill 知识库')
    expect(wrapper.text()).toContain('全量A股股票检索与筛选')
    expect(wrapper.text()).toContain('数据获取智能体')
    expect(wrapper.text()).toContain('数据解读智能体')

    // 智能体分开展示：存在独立的分组头部
    const headers = wrapper.findAll('.agent-section-card')
    expect(headers.length).toBe(2)

    // 检查是否有 emoji
    const emojiRegex = /[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}]/u
    expect(emojiRegex.test(wrapper.text())).toBe(false)
  })

  it('支持输入关键词实时筛选技能', async () => {
    vi.spyOn(client, 'getSkillsCatalog').mockResolvedValue(mockCatalog)

    const wrapper = mount(SkillsHubView, {
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    const searchInput = wrapper.find('input')
    expect(searchInput.exists()).toBe(true)
    await searchInput.setValue('杜邦')
    await flushPromises()

    // 只有数据解读的杜邦技能显示，股票技能被过滤
    expect(wrapper.text()).toContain('杜邦分析与ROE三因子拆解')
    expect(wrapper.text()).not.toContain('全量A股股票检索与筛选')
  })

  it('支持点击阶段标签仅展示特定智能体', async () => {
    vi.spyOn(client, 'getSkillsCatalog').mockResolvedValue(mockCatalog)

    const wrapper = mount(SkillsHubView, {
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    // 点击 Stage 2 标签
    const stageBtns = wrapper.findAll('.stage-tab-btn')
    const stage2Btn = stageBtns.find((b) => b.text().includes('Stage 2'))
    expect(stage2Btn).toBeDefined()
    await stage2Btn!.trigger('click')
    await flushPromises()

    // 仅显示 Stage 2 智能体
    expect(wrapper.text()).toContain('数据解读智能体')
    expect(wrapper.text()).not.toContain('全量A股股票检索与筛选')
  })

  it('点击技能卡片可打开抽屉查看技能规范与Markdown文档', async () => {
    vi.spyOn(client, 'getSkillsCatalog').mockResolvedValue(mockCatalog)

    const wrapper = mount(SkillsHubView, {
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    const skillCard = wrapper.find('.skill-card')
    expect(skillCard.exists()).toBe(true)
    await skillCard.trigger('click')
    await flushPromises()

    // 抽屉被激活
    expect(wrapper.find('.skill-detail-drawer').exists()).toBe(true)
  })
})
