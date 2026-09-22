import { defineComponent, h, inject, provide } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import StageDigest from '../StageDigest.vue'

const TableStub = defineComponent({
  name: 'ElTable',
  props: ['data'],
  setup(props, { slots }) {
    provide('tableProps', props)
    return () => h('div', { class: 'el-table' }, slots.default?.())
  },
})

const ColumnStub = defineComponent({
  name: 'ElTableColumn',
  props: ['label', 'prop'],
  setup(props, { slots }) {
    const tableProps = inject<{ data?: unknown[] }>('tableProps', {})
    return () => {
      const data = (tableProps.data ?? []) as Record<string, unknown>[]
      return h('div', { class: 'el-table-column' }, [
        h('span', { class: 'col-label' }, props.label),
        data.map((row, $index) =>
          slots.default
            ? slots.default({ row, $index })
            : h('span', String(row[props.prop as string] ?? ''))
        ),
      ])
    }
  },
})

function mountDigest(data: Record<string, unknown>) {
  return mount(StageDigest, {
    props: { stage: 'data_fetch', data },
    global: {
      plugins: [ElementPlus, createPinia()],
      stubs: { 'el-table': TableStub, 'el-table-column': ColumnStub },
    },
  })
}

describe('StageDigest · data_fetch real agent records', () => {
  it('renders structured financial records from the real data-fetch agent', () => {
    const wrapper = mountDigest({
      source_records: [
        {
          record_id: 'R-bba9f1ea7e566ec76bda',
          domain: 'industry',
          metric: '指数代码',
          value: '850532.SL',
          skill_name: 'hithink-industry-query',
        },
        {
          record_id: 'R-6f3e821a1c09dba294fe',
          domain: 'companies',
          metric: '相关产品名称',
          value: ['白银', '铜', '矿产银'],
          entity_name: '紫金矿业',
          entity_code: '601899.SH',
          period: '2025-12-31',
          skill_name: 'hithink-astock-selector',
        },
        {
          record_id: 'R-a154676337e9a8a18958',
          domain: 'financials',
          metric: '资产负债率',
          value: 58.3972,
          unit: '%',
          entity_name: '洛阳钼业',
          entity_code: '603993.SH',
          period: '2023-12-31',
          skill_name: 'hithink-finance-query',
        },
      ],
    })

    const text = wrapper.text()
    expect(text).toContain('采集来源明细（3 条）')
    expect(text).toContain('紫金矿业')
    expect(text).toContain('601899.SH')
    expect(text).toContain('洛阳钼业')
    expect(text).toContain('行业')
    expect(text).toContain('指数代码')
    expect(text).toContain('相关产品名称')
    expect(text).toContain('资产负债率')
    expect(text).toContain('850532.SL')
    expect(text).toContain('白银、铜、矿产银')
    expect(text).toContain('58.397 %')
    expect(text).toContain('行业数据')
    expect(text).toContain('A股选股')
    expect(text).toContain('财务数据')
    expect(text).toContain('2025-12-31')
    expect(text).toContain('2023-12-31')
    expect(text).toContain('最新')
  })

  it('keeps the legacy lightweight source protocol working', () => {
    const wrapper = mountDigest({
      source_records: [
        {
          source_name: '同花顺研报数据库',
          as_of_date: '2024-06-30',
          row_count: 50,
          skill_name: 'report_search',
        },
      ],
    })

    const text = wrapper.text()
    expect(text).toContain('同花顺研报数据库')
    expect(text).toContain('50 行')
    expect(text).toContain('研报检索')
    expect(text).toContain('2024-06-30')
  })
})
