import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import AgentLiveTrace from '../AgentLiveTrace.vue'
import * as client from '../../api/client'
import type { AgentTraceEvent } from '../../api/types'

const mockEvents: AgentTraceEvent[] = [
  {
    id: 'evt-01',
    timestamp: '2026-09-20T22:42:12.100000',
    stage: 'data_fetch',
    stage_label: '数据采集',
    event_type: 'agent_start',
    message: '启动数据获取智能体，规划问财查询...',
    tool: 'DataFetcherAgent',
    details: { industry: '白银' },
  },
  {
    id: 'evt-02',
    timestamp: '2026-09-20T22:42:15.300000',
    stage: 'data_fetch',
    stage_label: '数据采集',
    event_type: 'tool_call',
    message: '调度技能 hithink-astock-selector 执行产业链选股查询',
    tool: 'hithink-astock-selector',
    details: { query: '白银概念股' },
  },
  {
    id: 'evt-03',
    timestamp: '2026-09-20T22:42:25.000000',
    stage: 'chart_generate',
    stage_label: '图表生成',
    event_type: 'tool_call',
    message: '调用 EChartsEngine 渲染对比图表',
    tool: 'EChartsEngine',
    details: { chart_type: 'bar' },
  },
]

describe('AgentLiveTrace 智能体执行动线组件', () => {
  it('正确渲染事件列表与调用记录条数', async () => {
    vi.spyOn(client, 'getRunEvents').mockResolvedValue(mockEvents)

    const wrapper = mount(AgentLiveTrace, {
      props: {
        runId: 'test-run-123',
        isRunning: false,
      },
      global: { plugins: [ElementPlus, createPinia()] },
    })

    // 等待异步加载完成
    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('智能体微观执行动线与工具调用')
      expect(wrapper.text()).toContain('已归档调用记录 (3 条)')
      expect(wrapper.text()).toContain('hithink-astock-selector')
      expect(wrapper.text()).toContain('EChartsEngine')
    })
  })

  it('正在执行时显示实时推流标签与高亮状态', async () => {
    vi.spyOn(client, 'getRunEvents').mockResolvedValue(mockEvents)
    vi.spyOn(client, 'subscribeRunEvents').mockImplementation(() => () => {})

    const wrapper = mount(AgentLiveTrace, {
      props: {
        runId: 'test-run-123',
        isRunning: true,
      },
      global: { plugins: [ElementPlus, createPinia()] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('实时推流中 (Live Stream)')
      expect(wrapper.text()).toContain('当前智能体正在工作')
    })
  })

  it('点击参数明细可展开查看 JSON 详情', async () => {
    vi.spyOn(client, 'getRunEvents').mockResolvedValue(mockEvents)

    const wrapper = mount(AgentLiveTrace, {
      props: {
        runId: 'test-run-123',
        isRunning: false,
      },
      global: { plugins: [ElementPlus, createPinia()] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('参数明细')
    })

    const detailBtn = wrapper.find('.msg-actions button')
    expect(detailBtn.exists()).toBe(true)
    await detailBtn.trigger('click')

    expect(wrapper.html()).toContain('白银')
  })
})
