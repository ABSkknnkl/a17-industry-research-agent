import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it } from 'vitest'
import StageInterventionModal from '../StageInterventionModal.vue'

describe('StageInterventionModal 阶段差异化专业人机协同工作台', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('data_fetch 阶段支持增量数据补采与脏数据清洗', async () => {
    const wrapper = mount(StageInterventionModal, {
      props: {
        visible: true,
        stage: 'data_fetch',
        revision: 2,
        data: {
          source_records: [
            { record_id: 'REC-01', metric: '研发费用', value: 180, unit: '亿元', entity_name: '宁德时代' },
            { record_id: 'REC-02', metric: '脏数据噪声', value: -999, unit: '', entity_name: '未知代码' },
          ],
        },
      },
      attachTo: document.body,
      global: {
        plugins: [ElementPlus],
      },
    })
    await flushPromises()

    const bodyText = document.body.textContent || ''
    expect(bodyText).toContain('数据获取智能体')
    expect(bodyText).toContain('审核确认检索范围与关键词')
    expect(bodyText).toContain('增量数据补采')
    expect(bodyText).toContain('局部子域重采')
    expect(bodyText).toContain('脏数据清洗与剔除')

    // 快捷填入补采
    const buttons = Array.from(document.body.querySelectorAll('button'))
    const quickChip = buttons.find((b) => b.textContent?.includes('补充龙头财务与盈利'))
    expect(quickChip).toBeTruthy()
    quickChip!.click()
    await flushPromises()

    // 提交补采
    const submitBtn = Array.from(document.body.querySelectorAll('button')).find((b) => b.textContent?.includes('启动定向单点补采'))
    expect(submitBtn).toBeTruthy()
    submitBtn!.click()
    await flushPromises()

    const emittedRevise = wrapper.emitted('submitRevise')
    expect(emittedRevise).toBeTruthy()
    const payload = emittedRevise![0]![0] as any
    expect(payload.edited_data.action_type).toBe('replenish')
    expect(payload.edited_data.demand.domain).toBe('financials')
    expect(payload.edited_data.demand.entities).toContain('宁德时代')
  })

  it('data_fetch 阶段增量数据补采默认填入通用的、自适应行业的投研指令与实体', async () => {
    const wrapper = mount(StageInterventionModal, {
      props: {
        visible: true,
        stage: 'data_fetch',
        revision: 1,
        initialTab: 'replenish',
        data: {
          industry_topic: '银行业',
          source_records: [
            { record_id: 'REC-01', metric: '不良贷款率', value: 1.25, unit: '%', entity_name: '工商银行 (601398.SH)' },
            { record_id: 'REC-02', metric: '净息差', value: 1.82, unit: '%', entity_name: '建设银行 (601939.SH)' },
          ],
        },
      },
      attachTo: document.body,
      global: {
        plugins: [ElementPlus],
      },
    })
    await flushPromises()

    // 验证自适应提取出行业与实体，且内容通用化，不含任何写死的电池/储能字样
    const inputs = Array.from(document.body.querySelectorAll('input'))
    const entityInput = inputs.find((i) => i.value.includes('工商银行'))
    expect(entityInput).toBeTruthy()
    expect(entityInput!.value).toContain('建设银行')

    const textarea = document.body.querySelector('textarea')
    expect(textarea).toBeTruthy()
    expect(textarea!.value).toContain('银行业')
    expect(textarea!.value).toContain('核心龙头企业近3年营业收入')
    expect(textarea!.value).not.toContain('储能')
    expect(textarea!.value).not.toContain('宁德时代')
  })

  it('chapter_write 阶段支持提出修改意见与补充要求', async () => {
    const wrapper = mount(StageInterventionModal, {
      props: {
        visible: true,
        stage: 'chapter_write',
        revision: 4,
        data: {
          chapters: [
            { chapter_id: 'CH-01', title: '概述', sections: [] },
            { chapter_id: 'CH-04', title: '竞争格局', sections: [] },
          ],
        },
        initialTab: 'revision_requirements',
      },
      attachTo: document.body,
      global: {
        plugins: [ElementPlus],
      },
    })
    await flushPromises()

    const bodyText = document.body.textContent || ''
    expect(bodyText).toContain('提出修改意见与补充要求')
    expect(bodyText).toContain('正文段落就地精修')

    // 填入单章重写指令
    const textarea = document.body.querySelector('textarea')
    expect(textarea).toBeTruthy()
    textarea!.value = '重点深化宁德时代与比亚迪的储能电池差异化竞争壁垒'
    textarea!.dispatchEvent(new Event('input'))
    await flushPromises()

    const submitBtn = Array.from(document.body.querySelectorAll('button')).find((b) => b.textContent?.includes('提交修改意见与补充要求'))
    expect(submitBtn).toBeTruthy()
    submitBtn!.click()
    await flushPromises()

    const emitted = wrapper.emitted('submitRevise')
    expect(emitted).toBeTruthy()
    const payload = emitted![0]![0] as any
    expect(payload.edited_data.action_type).toBe('single_chapter_rewrite')
    expect(payload.edited_data.instruction).toContain('储能电池差异化竞争壁垒')
  })

  it('report_fusion 阶段支持 8 张核心指标卡定制与评级定稿', async () => {
    const wrapper = mount(StageInterventionModal, {
      props: {
        visible: true,
        stage: 'report_fusion',
        revision: 5,
        data: {
          title: '动力电池深度研报',
          key_metrics: [
            { label: '市场规模', value: '12000', unit: '亿元', change: '+20%', tone: 'up' },
          ],
        },
        initialTab: 'metric_cards',
      },
      attachTo: document.body,
      global: {
        plugins: [ElementPlus],
      },
    })
    await flushPromises()

    const bodyText = document.body.textContent || ''
    expect(bodyText).toContain('8 张核心指标卡定制')
    expect(bodyText).toContain('投资评级与执行摘要定稿')

    const saveBtn = Array.from(document.body.querySelectorAll('button')).find((b) => b.textContent?.includes('保存 8 张核心指标卡定制'))
    expect(saveBtn).toBeTruthy()
    saveBtn!.click()
    await flushPromises()

    const emitted = wrapper.emitted('submitDirectEdit')
    expect(emitted).toBeTruthy()
    const payload = emitted![0]![0] as any
    expect(payload.edited_data.key_metrics).toBeTruthy()
  })

  it('chart_generate 阶段支持图表形态切换并完整保留 option 与字段', async () => {
    const mockSpec = {
      chart_id: 'CHART-TEST-01',
      title: '营业收入横向比较',
      chart_type: 'bar',
      status: 'ready',
      option: {
        xAxis: { type: 'category', data: ['公司A', '公司B'] },
        yAxis: { type: 'value' },
        series: [{ type: 'bar', data: [100, 200] }],
      },
    }

    const wrapper = mount(StageInterventionModal, {
      props: {
        visible: true,
        stage: 'chart_generate',
        revision: 1,
        data: {
          chart_specs: [mockSpec],
        },
        initialTab: 'morph_emphasis',
      },
      attachTo: document.body,
      global: {
        plugins: [ElementPlus],
      },
    })
    await flushPromises()

    const saveBtn = Array.from(document.body.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('保存图表样式与强调重点配置')
    )
    expect(saveBtn).toBeTruthy()
    saveBtn!.click()
    await flushPromises()

    const emitted = wrapper.emitted('submitDirectEdit')
    expect(emitted).toBeTruthy()
    const payload = emitted![0]![0] as any
    expect(payload.edited_data.chart_specs).toHaveLength(1)
    const savedChart = payload.edited_data.chart_specs[0]
    expect(savedChart.chart_id).toBe('CHART-TEST-01')
    expect(savedChart.option).toBeDefined()
    expect(savedChart.option.series).toHaveLength(1)
  })

  it('data_fetch 阶段支持审核确认检索范围与关键词并重新检索', async () => {
    const wrapper = mount(StageInterventionModal, {
      props: {
        visible: true,
        stage: 'data_fetch',
        revision: 1,
        data: {
          keywords: ['800G光模块', 'CPO封装'],
        },
        initialTab: 'scope_keywords',
      },
      attachTo: document.body,
      global: {
        plugins: [ElementPlus],
      },
    })
    await flushPromises()

    const bodyText = document.body.textContent || ''
    expect(bodyText).toContain('审核确认检索范围与关键词')
    expect(bodyText).toContain('800G光模块')

    // 1. 点击就地确认
    const confirmBtn = Array.from(document.body.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('确认审核无误并进入下一步')
    )
    expect(confirmBtn).toBeTruthy()
    confirmBtn!.click()
    await flushPromises()

    const emittedDirect = wrapper.emitted('submitDirectEdit')
    expect(emittedDirect).toBeTruthy()
    const directPayload = emittedDirect![0]![0] as any
    expect(directPayload.edited_data.confirmed_keywords).toContain('800G光模块')
    expect(directPayload.edited_data.confirmed_scope).toBeDefined()

    // 2. 点击重新检索
    const refetchBtn = Array.from(document.body.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('按此范围与关键词重新检索')
    )
    expect(refetchBtn).toBeTruthy()
    refetchBtn!.click()
    await flushPromises()

    const emittedRevise = wrapper.emitted('submitRevise')
    expect(emittedRevise).toBeTruthy()
    const revisePayload = emittedRevise![0]![0] as any
    expect(revisePayload.edited_data.action_type).toBe('scope_keywords_refetch')
    expect(revisePayload.edited_data.confirmed_keywords).toContain('800G光模块')
  })

  it('report_fusion 阶段支持整体审核并提出宏观修订方向', async () => {
    const wrapper = mount(StageInterventionModal, {
      props: {
        visible: true,
        stage: 'report_fusion',
        revision: 5,
        data: {},
        initialTab: 'audit_steering',
      },
      attachTo: document.body,
      global: {
        plugins: [ElementPlus],
      },
    })
    await flushPromises()

    const bodyText = document.body.textContent || ''
    expect(bodyText).toContain('整体审核并提出修订方向')
    expect(bodyText).toContain('机构审慎 / 深度防守')
    expect(bodyText).toContain('积极成长 / 景气驱动')

    const steeringBtn = Array.from(document.body.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('提交全局修订方向')
    )
    expect(steeringBtn).toBeTruthy()
    steeringBtn!.click()
    await flushPromises()

    const emittedRevise = wrapper.emitted('submitRevise')
    expect(emittedRevise).toBeTruthy()
    const payload = emittedRevise![0]![0] as any
    expect(payload.edited_data.action_type).toBe('global_steering')
    expect(payload.edited_data.steering_direction).toBe('机构审慎 / 深度防守')
  })

  it('chart_generate 阶段支持雷达图与环形饼图高级金融图表选型与平滑变形', async () => {
    const mockSpec = {
      chart_id: 'CHART-ADV-01',
      title: '多维综合对标矩阵',
      chart_type: 'radar',
      status: 'ready',
      option: {
        xAxis: { type: 'category', data: ['盈利能力', '成长弹性', '资产质量', '估值吸引力', '研发强度'] },
        yAxis: { type: 'value' },
        series: [{ name: '龙头标的A', data: [80, 85, 75, 90, 95] }],
      },
    }

    const wrapper = mount(StageInterventionModal, {
      props: {
        visible: true,
        stage: 'chart_generate',
        revision: 2,
        data: {
          chart_specs: [mockSpec],
        },
        initialTab: 'morph_emphasis',
      },
      attachTo: document.body,
      global: {
        plugins: [ElementPlus],
      },
    })
    await flushPromises()

    const saveBtn = Array.from(document.body.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('保存图表样式与强调重点配置')
    )
    expect(saveBtn).toBeTruthy()
    saveBtn!.click()
    await flushPromises()

    const emitted = wrapper.emitted('submitDirectEdit')
    expect(emitted).toBeTruthy()
    const payload = emitted![0]![0] as any
    const savedChart = payload.edited_data.chart_specs[0]
    expect(savedChart.chart_type).toBe('radar')
    expect(savedChart.option.radar).toBeDefined()
    expect(savedChart.option.radar.indicator).toHaveLength(5)
    expect(savedChart.option.series[0].type).toBe('radar')
  })
})

