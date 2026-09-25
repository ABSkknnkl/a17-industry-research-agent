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
    expect(bodyText).toContain('数据采集智能体')
    expect(bodyText).toContain('增量数据补采')
    expect(bodyText).toContain('局部子域重采')
    expect(bodyText).toContain('脏数据清洗与剔除')

    // 快捷填入补采
    const buttons = Array.from(document.body.querySelectorAll('button'))
    const quickChip = buttons.find((b) => b.textContent?.includes('补充龙头研发与储能财务'))
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

  it('chapter_write 阶段支持指定单章定向重写', async () => {
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
        initialTab: 'single_chapter',
      },
      attachTo: document.body,
      global: {
        plugins: [ElementPlus],
      },
    })
    await flushPromises()

    const bodyText = document.body.textContent || ''
    expect(bodyText).toContain('指定单章定向重写')
    expect(bodyText).toContain('正文段落就地精修')

    // 填入单章重写指令
    const textarea = document.body.querySelector('textarea')
    expect(textarea).toBeTruthy()
    textarea!.value = '重点深化宁德时代与比亚迪的储能电池差异化竞争壁垒'
    textarea!.dispatchEvent(new Event('input'))
    await flushPromises()

    const submitBtn = Array.from(document.body.querySelectorAll('button')).find((b) => b.textContent?.includes('立即定向重写所选单章'))
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
        initialTab: 'morph',
      },
      attachTo: document.body,
      global: {
        plugins: [ElementPlus],
      },
    })
    await flushPromises()

    const saveBtn = Array.from(document.body.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('保存图表形态变更')
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
})
