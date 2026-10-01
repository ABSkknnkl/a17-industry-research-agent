import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it } from 'vitest'
import EvidenceDrawer from '../EvidenceDrawer.vue'

describe('EvidenceDrawer 事实穿透与凭证审计抽屉', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  it('传入 recordIds 时能从 evidenceIndex 精准穿透展示对应证据详情', async () => {
    const mockIndex = {
      'R-001': {
        record_id: 'R-001',
        entity: '中际旭创',
        metric: 'revenue',
        value: 10718000000,
        unit: '元',
        period: '2023-12-31',
        skill_id: 'hithink_finance_query',
        trace_id: 'trace-abc-1234567890abcdef',
      },
      'R-002': {
        record_id: 'R-002',
        entity: '新易盛',
        metric: 'net_margin',
        value: 22.5,
        unit: '%',
        period: '2023-12-31',
        skill_id: 'hithink_finance_query',
        trace_id: 'trace-def-9876543210fedcba',
      },
    }

    const wrapper = mount(EvidenceDrawer, {
      props: {
        visible: true,
        recordIds: ['R-001'],
        evidenceIndex: mockIndex,
      },
      attachTo: document.body,
      global: {
        plugins: [ElementPlus],
      },
    })
    await flushPromises()

    const bodyText = document.body.textContent || ''
    expect(bodyText).toContain('数据事实穿透与凭证审计')
    expect(bodyText).toContain('107.18 亿')
    expect(bodyText).toContain('中际旭创')
    expect(bodyText).toContain('营业收入')
    expect(bodyText).toContain('事实链已对齐')
    expect(bodyText).toContain('trace-abc-123456')

    // 未选中的 R-002 标的不在当前穿透清单中
    expect(bodyText).not.toContain('新易盛')
  })

  it('关闭抽屉触发 close 与 update:visible 事件', async () => {
    const wrapper = mount(EvidenceDrawer, {
      props: {
        visible: true,
        recordIds: [],
        evidenceIndex: {},
      },
      attachTo: document.body,
      global: {
        plugins: [ElementPlus],
      },
    })
    await flushPromises()

    // 触发 close
    wrapper.vm.handleClose?.()
    await flushPromises()

    expect(wrapper.emitted('close')).toBeTruthy()
    expect(wrapper.emitted('update:visible')).toBeTruthy()
  })
})
