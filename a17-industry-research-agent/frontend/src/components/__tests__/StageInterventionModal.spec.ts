import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it } from 'vitest'
import StageInterventionModal from '../StageInterventionModal.vue'

interface ChartEditEvent {
  edited_data: {
    chart_specs: {
      chart_id: string
      chart_type: string
      option: {
        radar?: { indicator: { name: string }[] }
        series: { type?: string }[]
      }
    }[]
  }
}

describe('StageInterventionModal 阶段差异化专业人机协同工作台', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('data_fetch 阶段：定向补采按点提交 partial_refetch', async () => {
    const wrapper = mount(StageInterventionModal, {
      props: {
        visible: true,
        stage: 'data_fetch',
        revision: 2,
        initialTab: 'partial_refetch',
        data: {
          source_records: [
            {
              record_id: 'REC-01',
              metric: '研发费用',
              value: 180,
              unit: '亿元',
              entity_name: '宁德时代',
            },
            {
              record_id: 'REC-02',
              metric: '营业收入',
              value: 1342,
              unit: '亿元',
              entity_name: '比亚迪',
            },
          ],
        },
      },
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    const bodyText = document.body.textContent || ''
    expect(bodyText).toContain('数据获取智能体')
    expect(bodyText).toContain('定向补采')
    // P0-4：清单改为按真实 source_records 的 domain 分组，不再有内置样例分组名
    expect(bodyText).toContain('财务与经营质量')
    expect(bodyText).not.toContain('重点公司财务与盈利指标')
    // 旧「探针补采」页签已合并进点级清单，正常模式下不再单独出现
    expect(bodyText).not.toContain('探针补采')
    expect(bodyText).not.toContain('脏数据清洗与剔除')

    // 两条记录都已采到值，默认不勾选（勾了才会覆盖原值）；显式勾选第一条再提交
    const firstPointCheckbox = document.body.querySelector<HTMLInputElement>(
      '.prp-groups .el-checkbox input'
    )
    expect(firstPointCheckbox).toBeTruthy()
    firstPointCheckbox!.click()
    await flushPromises()

    const submit = Array.from(document.body.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('启动定向补采')
    )
    expect(submit).toBeTruthy()
    submit!.click()
    await flushPromises()

    const emitted = wrapper.emitted('submitRevise')
    expect(emitted).toBeTruthy()
    const payload = emitted![0]![0] as {
      edited_data: {
        action_type: string
        data_point_ids: string[]
        probe_mode: string
        entities: string[]
      }
    }
    expect(payload.edited_data.action_type).toBe('partial_refetch')
    expect(payload.edited_data.probe_mode).toBe('llm_dynamic')
    // 点号必须是后端真实 record_id，而不是内置的 F-01 / C-01 之类样例编号
    expect(payload.edited_data.data_point_ids).toEqual(['REC-01'])
    expect(payload.edited_data.entities).toContain('宁德时代')
  })

  it('演示补采只提交仍缺失且已勾选的真实数据点', async () => {
    const wrapper = mount(StageInterventionModal, {
      props: {
        visible: true,
        stage: 'data_fetch',
        revision: 2,
        initialTab: 'replenish',
        data: {
          nev_probe_demo: true,
          demo_probe_points: [
            {
              id: 'revenue',
              label: '营业收入',
              entity: '长安汽车',
              period: '2025 年度',
              missing: false,
              value: '1,639.998 亿元',
            },
            {
              id: 'cashflow',
              label: '经营现金流',
              entity: '长安汽车',
              period: '2025 年度',
              missing: true,
              value: null,
            },
          ],
        },
      },
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()
    expect(document.body.textContent).toContain('模拟首轮未返回')
    expect(document.body.textContent).toContain('1,639.998 亿元')
    expect(document.body.textContent).not.toContain('常规单次查询')
    const submit = Array.from(document.body.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('补采所选数据点')
    )
    expect(submit).toBeTruthy()
    submit!.click()
    await flushPromises()
    expect(wrapper.emitted('submitRevise')?.[0]?.[0]).toMatchObject({
      edited_data: { action_type: 'partial_refetch', data_point_ids: ['cashflow'] },
    })
  })

  it('定向补采：不勾点、只填清单外诉求时走 replenish 契约', async () => {
    const wrapper = mount(StageInterventionModal, {
      props: {
        visible: true,
        stage: 'data_fetch',
        revision: 1,
        initialTab: 'partial_refetch',
        data: {
          industry_topic: '银行业',
          source_records: [
            {
              record_id: 'REC-01',
              metric: '不良贷款率',
              value: 1.25,
              unit: '%',
              entity_name: '工商银行 (601398.SH)',
            },
            {
              record_id: 'REC-02',
              metric: '净息差',
              value: 1.82,
              unit: '%',
              entity_name: '建设银行 (601939.SH)',
            },
          ],
        },
      },
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    // 清空默认勾选，只保留清单外诉求
    const clearBtn = Array.from(document.body.querySelectorAll('button')).find(
      (b) => b.textContent?.trim() === '清空'
    )
    expect(clearBtn).toBeTruthy()
    clearBtn!.click()
    await flushPromises()

    const adhoc = document.body.querySelector('.prp-adhoc input') as HTMLInputElement | null
    expect(adhoc).toBeTruthy()
    adhoc!.value = '补充 2025 年不良贷款率与净息差'
    adhoc!.dispatchEvent(new Event('input'))
    await flushPromises()

    const submit = Array.from(document.body.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('补采清单外诉求')
    )
    expect(submit).toBeTruthy()
    submit!.click()
    await flushPromises()

    const emitted = wrapper.emitted('submitRevise')
    expect(emitted).toBeTruthy()
    const payload = emitted![0]![0] as {
      edited_data: { action_type: string; demand: { entities: string[]; probe_mode: string } }
    }
    expect(payload.edited_data.action_type).toBe('replenish')
    expect(payload.edited_data.demand.entities).toContain('工商银行')
    expect(payload.edited_data.demand.probe_mode).toBe('llm_dynamic')
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

    const submitBtn = Array.from(document.body.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('提交修改意见与补充要求')
    )
    expect(submitBtn).toBeTruthy()
    submitBtn!.click()
    await flushPromises()

    const emitted = wrapper.emitted('submitRevise')
    expect(emitted).toBeTruthy()
    const payload = emitted![0]![0] as { edited_data: { action_type: string; instruction: string } }
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

    const saveBtn = Array.from(document.body.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('保存 8 张核心指标卡定制')
    )
    expect(saveBtn).toBeTruthy()
    saveBtn!.click()
    await flushPromises()

    const emitted = wrapper.emitted('submitDirectEdit')
    expect(emitted).toBeTruthy()
    const payload = emitted![0]![0] as { edited_data: { key_metrics: unknown[] } }
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
    const payload = emitted![0]![0] as ChartEditEvent
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
    const directPayload = emittedDirect![0]![0] as {
      edited_data: { confirmed_keywords: string[]; confirmed_scope: string[] }
    }
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
    const revisePayload = emittedRevise![0]![0] as {
      edited_data: { action_type: string; confirmed_keywords: string[] }
    }
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
    const payload = emittedRevise![0]![0] as {
      edited_data: { action_type: string; steering_direction: string }
    }
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
        xAxis: {
          type: 'category',
          data: ['盈利能力', '成长弹性', '资产质量', '估值吸引力', '研发强度'],
        },
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
    const payload = emitted![0]![0] as ChartEditEvent
    const savedChart = payload.edited_data.chart_specs[0]
    expect(savedChart.chart_type).toBe('radar')
    expect(savedChart.option.radar).toBeDefined()
    expect(savedChart.option.radar?.indicator).toHaveLength(5)
    expect(savedChart.option.series[0].type).toBe('radar')
  })

  it('定向补采：切到常规单次查询时 probe_mode=static', async () => {
    const wrapper = mount(StageInterventionModal, {
      props: {
        visible: true,
        stage: 'data_fetch',
        revision: 2,
        initialTab: 'partial_refetch',
        data: {
          industry_topic: '白酒行业',
          // P0-4：清单只来自真实记录，空 source_records 会走空态且禁止点级提交
          source_records: [
            {
              record_id: 'REC-BJ-01',
              metric: '营业收入',
              value: 170,
              unit: '亿元',
              entity_name: '贵州茅台',
              domain: 'financials',
            },
          ],
        },
      },
      attachTo: document.body,
      global: { plugins: [ElementPlus] },
    })
    await flushPromises()

    expect(document.body.textContent).toContain('补采执行方式')

    const staticRadio = Array.from(document.body.querySelectorAll('.el-radio-button')).find((el) =>
      el.textContent?.includes('常规单次查询')
    )
    expect(staticRadio).toBeTruthy()
    staticRadio!.querySelector('input')?.click()
    await flushPromises()

    expect(document.body.textContent).toContain('主链路只发一次查询')

    const pointCheckbox = document.body.querySelector<HTMLInputElement>(
      '.prp-groups .el-checkbox input'
    )
    expect(pointCheckbox).toBeTruthy()
    pointCheckbox!.click()
    await flushPromises()

    const submit = Array.from(document.body.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('启动定向补采')
    )
    expect(submit).toBeTruthy()
    submit!.click()
    await flushPromises()

    const emitted = wrapper.emitted('submitRevise')
    expect(emitted).toBeTruthy()
    const payload = emitted![0]![0] as { edited_data: { action_type: string; probe_mode?: string } }
    expect(payload.edited_data.action_type).toBe('partial_refetch')
    expect(payload.edited_data.probe_mode).toBe('static')
    wrapper.unmount()
  })
})
