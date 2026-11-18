import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import StageDigest from '../StageDigest.vue'

function render(data: Record<string, unknown>) {
  return mount(StageDigest, {
    props: { stage: 'data_fetch', data },
    global: {
      plugins: [ElementPlus],
      stubs: {
        ChartGallery: true,
        ReportPreview: true,
        InterpretationDigest: true,
        DataFetchDigest: true,
      },
    },
  })
}

describe('StageDigest 补采与动态探针状态可见性', () => {
  it('自动补采预算耗尽后展示剩余缺口和手动入口提示', () => {
    const wrapper = render({
      auto_probe: {
        status: 'budget_exhausted',
        calls_used: 12,
        max_calls: 12,
        remaining_requirements: 2,
      },
    })
    expect(wrapper.text()).toContain('12/12 次')
    expect(wrapper.text()).toContain('剩余 2 项需求待补')
    expect(wrapper.text()).toContain('定向补采')
    wrapper.unmount()
  })

  it('取数中：显示进行中状态与说明', () => {
    const wrapper = render({
      probe_mode: 'llm_dynamic',
      probe_status: 'running',
      probe_message: '正在选择技能并改写查询',
    })
    expect(wrapper.text()).toContain('取数中')
    expect(wrapper.text()).toContain('正在选择技能并改写查询')
    wrapper.unmount()
  })

  it('取数成功：显示新增记录数与尝试次数', () => {
    const wrapper = render({
      probe_mode: 'llm_dynamic',
      probe_status: 'success',
      probe_records: 12,
      probe_attempts: [{ attempt: 1 }, { attempt: 2 }],
    })
    expect(wrapper.text()).toContain('取数成功')
    expect(wrapper.text()).toContain('新增 12 条记录')
    expect(wrapper.text()).toContain('2 次尝试')
    wrapper.unmount()
  })

  it('取数失败 / 无数据：显示原因，不伪装成功', () => {
    const wrapper = render({
      probe_mode: 'llm_dynamic',
      probe_status: 'no_data',
      probe_message: '返回指标与缺口不匹配，未写入数据集',
    })
    expect(wrapper.text()).toContain('取数失败 / 无数据')
    expect(wrapper.text()).toContain('返回指标与缺口不匹配')
    wrapper.unmount()
  })

  it('主链路取数不完整时给出用户可见提示并引导补采', () => {
    const wrapper = render({
      data_gap_notice: '主链路取数不完整：status=partial',
      probe_hint: '可在增量数据补采中选择大模型动态探针',
    })
    expect(wrapper.text()).toContain('主链路取数不完整')
    expect(wrapper.text()).toContain('可在增量数据补采中选择大模型动态探针')
    wrapper.unmount()
  })
})
