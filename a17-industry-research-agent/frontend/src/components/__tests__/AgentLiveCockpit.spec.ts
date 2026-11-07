import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { describe, expect, it, vi } from 'vitest'
import AgentLiveCockpit from '../AgentLiveCockpit.vue'
import * as client from '../../api/client'
import type { AgentTraceEvent } from '../../api/types'

const mockEvents: AgentTraceEvent[] = [
  {
    id: 'evt-01',
    timestamp: '2026-09-21T11:15:01.000000',
    stage: 'data_fetch',
    stage_label: '数据采集',
    event_type: 'agent_start',
    message: '启动数据获取智能体，初始化行业投研需求: 白银',
    tool: 'DataFetcherAgent',
    details: { industry: '白银' },
  },
  {
    id: 'evt-02',
    timestamp: '2026-09-21T11:15:05.000000',
    stage: 'data_fetch',
    stage_label: '数据采集',
    event_type: 'tool_call',
    message: '[迭代 #1] 调度问财金融技能 [hithink-query] -> 任务 T-1',
    tool: 'hithink-query',
    details: { query: '白银概念股' },
  },
  {
    id: 'evt-03',
    timestamp: '2026-09-21T11:15:08.000000',
    stage: 'data_fetch',
    stage_label: '数据采集',
    event_type: 'tool_result',
    message: '[迭代 #1] 问财技能 [hithink-query] 执行成功: 入库 15 条实体与指标数据',
    tool: 'hithink-query',
    details: { record_count: 15 },
  },
]

describe('AgentLiveCockpit 智能体实时指挥舱组件', () => {
  it('正确渲染指挥舱标题、当前阶段、活跃工具与最新事件动作', async () => {
    vi.spyOn(client, 'getRunEvents').mockResolvedValue(mockEvents)
    vi.spyOn(client, 'subscribeRunEvents').mockImplementation(() => () => {})

    const wrapper = mount(AgentLiveCockpit, {
      props: {
        runId: 'run-test-cockpit',
        isRunning: true,
        currentStage: 'data_fetch',
        workflow: {
          run_id: 'run-test-cockpit',
          project_id: 'proj-01',
          current_stage: 'data_fetch',
          status: 'running',
          revision: 1,
          created_at: new Date(Date.now() - 35000).toISOString(),
          updated_at: new Date().toISOString(),
          stage_results: {},
        },
      },
      global: { plugins: [ElementPlus, createPinia()] },
    })

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('智能体全链路协同指挥舱')
      expect(wrapper.text()).toContain('数据采集')
      expect(wrapper.text()).toContain('hithink-query')
      expect(wrapper.text()).toContain('入库 15 条实体与指标数据')
      expect(wrapper.text()).toContain('捕获事件')
    })
  })

  it('点击查看动线按钮触发 open-drawer 事件', async () => {
    vi.spyOn(client, 'getRunEvents').mockResolvedValue([])
    vi.spyOn(client, 'subscribeRunEvents').mockImplementation(() => () => {})

    const wrapper = mount(AgentLiveCockpit, {
      props: {
        runId: 'run-test-drawer',
        isRunning: true,
      },
      global: { plugins: [ElementPlus, createPinia()] },
    })

    const drawerBtn = wrapper.find('[data-testid="btn-cockpit-open-drawer"]')
    expect(drawerBtn.exists()).toBe(true)
    await drawerBtn.trigger('click')

    expect(wrapper.emitted('open-drawer')).toBeTruthy()
  })

  it('点击终止执行按钮触发 cancel 事件', async () => {
    vi.spyOn(client, 'getRunEvents').mockResolvedValue([])
    vi.spyOn(client, 'subscribeRunEvents').mockImplementation(() => () => {})

    const wrapper = mount(AgentLiveCockpit, {
      props: {
        runId: 'run-test-cancel',
        isRunning: true,
      },
      global: { plugins: [ElementPlus, createPinia()] },
    })

    const cancelBtn = wrapper.find('[data-testid="btn-cockpit-cancel"]')
    expect(cancelBtn.exists()).toBe(true)
    await cancelBtn.trigger('click')

    expect(wrapper.emitted('cancel')).toBeTruthy()
  })
})
