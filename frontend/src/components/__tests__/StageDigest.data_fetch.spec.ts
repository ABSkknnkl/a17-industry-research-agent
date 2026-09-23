import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import StageDigest from '../StageDigest.vue'

import { defineComponent, h, inject, provide } from 'vue'

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

function mountDigest(data: Record<string, unknown>, sourceRecords?: Record<string, unknown>[]) {
  return mount(StageDigest, {
    props: { stage: 'data_fetch', data, sourceRecords },
    global: {
      plugins: [ElementPlus, createPinia()],
      stubs: {
        'el-table': TableStub,
        'el-table-column': ColumnStub,
      },
    },
  })
}

describe('StageDigest · data_fetch 采集来源列表与真实金融指标呈现', () => {
  it('将内部领域名显示为中文，并隐藏重复的采集说明', () => {
    const wrapper = mountDigest({
      intent_routing: {
        plans: {
          'companies 核心数据': {
            requires_clarification: false,
            sub_requirements: [
              {
                description: '采集companies 核心数据相关指标',
                candidate_skills: ['companies'],
              },
            ],
          },
        },
      },
    })

    const text = wrapper.text()

    expect(text).toContain('公司数据')
    expect(text).not.toContain('companies')
    expect(text).not.toContain('采集公司数据相关指标')
  })

  it('正确渲染结构化金融指标明细（公司、指标、数值、单位、中文技能名、报告期）', () => {
    const data = {
      source_records: [
        {
          record_id: 'R-bba9f1ea7e566ec76bda',
          domain: 'industry',
          metric: '指数代码',
          value: '850532.SL',
          unit: null,
          entity_name: null,
          entity_code: null,
          period: null,
          skill_name: 'hithink-industry-query',
        },
        {
          record_id: 'R-6f3e821a1c09dba294fe',
          domain: 'companies',
          metric: '相关产品名称',
          value: ['白银', '铜', '矿产银'],
          unit: null,
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
    }

    const wrapper = mountDigest(data)
    const text = wrapper.text()

    // 标题与条数
    expect(text).toContain('采集来源明细（3 条）')

    // 标的与领域
    expect(text).toContain('紫金矿业')
    expect(text).toContain('601899.SH')
    expect(text).toContain('洛阳钼业')
    expect(text).toContain('行业') // industry tag

    // 采集指标
    expect(text).toContain('指数代码')
    expect(text).toContain('相关产品名称')
    expect(text).toContain('资产负债率')

    // 采集数值与内容格式化
    expect(text).toContain('850532.SL')
    expect(text).toContain('白银、铜、矿产银')
    expect(text).toContain('58.397 %')

    // 技能名称映射为中文规范名称，杜绝英文slug
    expect(text).toContain('行业数据')
    expect(text).toContain('A股选股')
    expect(text).toContain('财务数据')

    // 报告期
    expect(text).toContain('2025-12-31')
    expect(text).toContain('2023-12-31')
    expect(text).toContain('最新')
  })

  it('平滑兼容旧版/轻量协议字段（source_name, as_of_date, row_count）', () => {
    const legacyData = {
      source_records: [
        {
          source_name: '同花顺研报数据库',
          as_of_date: '2024-06-30',
          row_count: 50,
          skill_name: 'report_search',
        },
      ],
    }

    const wrapper = mountDigest(legacyData)
    const text = wrapper.text()

    expect(text).toContain('同花顺研报数据库')
    expect(text).toContain('50 行')
    expect(text).toContain('研报检索')
    expect(text).toContain('2024-06-30')
  })
})
