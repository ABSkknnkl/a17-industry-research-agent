import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, nextTick, watch } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as echarts from 'echarts'
import ChartGallery from '../ChartGallery.vue'
import type { ChartReference, ChartSpec } from '../../api/types'

// Canvas rendering belongs to ECharts; record the options crossing that boundary.
vi.mock('echarts', () => ({ init: vi.fn() }))

const option = {
  grid: [
    { left: '8%', width: '35%' },
    { left: '58%', width: '35%' },
  ],
  xAxis: [{ data: ['2024', '2025'] }, { gridIndex: 1, data: ['2024', '2025'] }],
  yAxis: [{ name: '万吨' }, { gridIndex: 1, name: '%' }],
  footnotes: ['纵轴未从 0 开始', '[需核实:货币单位]'],
  series: [
    {
      name: '销量',
      type: 'bar',
      xAxisIndex: 0,
      yAxisIndex: 0,
      data: [100, 120],
      markLine: { data: [{ yAxis: 110, name: '目标' }] },
    },
    {
      name: '增速',
      type: 'line',
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: [10, 20],
      markArea: { data: [[{ xAxis: '2024' }, { xAxis: '2025' }]] },
      markPoint: { data: [{ coord: ['2025', 20], name: '回升' }] },
    },
  ],
}

const spec: ChartSpec = {
  chart_id: 'CHART-PANEL',
  title: '销量增长20%且增速回升',
  chart_type: 'combo',
  variant: 'dual_panel',
  option,
  evidence_ids: ['E-1'],
  data_fingerprint: 'a'.repeat(64),
  dedupe_key: 'combo:test',
  panels: [
    { panel_id: 'volume', position: 'left', series: ['销量'], axis_name: '万吨' },
    { panel_id: 'rate', position: 'right', series: ['增速'], axis_name: '%' },
  ],
  annotations: [{ annotation_type: 'reference_line', label: '目标', value: 110 }],
  footnotes: ['[需核实:货币单位]', '<b>原始数据说明</b>'],
}

// Compile-time regressions for producer model-validator rules (checked by vue-tsc).
function acceptSpec(value: ChartSpec) {
  return value
}
function acceptReference(value: ChartReference) {
  return value
}
// @ts-expect-error Generated images cannot omit their required generation metadata.
acceptSpec({ ...spec, chart_type: 'industry_chain', render_mode: 'generated_image' })
// @ts-expect-error Generated images are restricted to industry_chain.
acceptSpec({
  ...spec,
  chart_type: 'line',
  render_mode: 'generated_image',
  image_uri: 'image.png',
  image_mime_type: 'image/png',
  generation_prompt: '绘图',
  generation_prompt_model: 'prompt',
  generation_image_model: 'image',
  chain_template: 'horizontal_flow',
  chain_graph: {},
})
// @ts-expect-error Ready references must carry a non-null artifact_id.
acceptReference({
  chart_id: 'CHART-1',
  title: '收入增长',
  chart_type: 'line',
  evidence_ids: ['E-1'],
  status: 'ready',
  artifact_id: null,
})
acceptReference({
  chart_id: 'CHART-1',
  title: '收入增长',
  chart_type: 'line',
  evidence_ids: ['E-1'],
  status: 'planned',
})
acceptSpec({ ...spec, render_mode: 'echarts', image_uri: null, chain_graph: null })
acceptSpec({
  ...spec,
  chart_type: 'industry_chain',
  render_mode: 'generated_image',
  image_uri: 'image.png',
  image_mime_type: 'image/png',
  generation_prompt: '绘图',
  generation_prompt_model: 'prompt',
  generation_image_model: 'image',
  chain_template: 'horizontal_flow',
  chain_graph: {},
})

const Dialog = defineComponent({
  props: { modelValue: Boolean },
  emits: ['opened', 'update:modelValue'],
  setup(props, { emit }) {
    watch(
      () => props.modelValue,
      async (visible) => {
        if (visible) {
          await nextTick()
          emit('opened')
        }
      }
    )
  },
  template: '<section v-if="modelValue" class="preview"><slot /></section>',
})

const received: unknown[] = []
const wrappers: ReturnType<typeof mount>[] = []

beforeEach(() => {
  received.length = 0
  vi.mocked(echarts.init).mockImplementation(
    (el) =>
      ({
        setOption: (value: unknown) => received.push(value),
        getDom: () => el,
        resize: vi.fn(),
        dispose: vi.fn(),
      }) as unknown as echarts.ECharts
  )
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    queueMicrotask(() => callback(0))
    return 0
  })
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    }
  )
})

afterEach(() => {
  wrappers.forEach((wrapper) => wrapper.unmount())
  wrappers.length = 0
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

function mountGallery(specs: Partial<ChartSpec>[] = [spec]) {
  const wrapper = mount(ChartGallery, {
    props: { specs },
    global: {
      stubs: {
        'el-dialog': Dialog,
        'el-tag': { template: '<span><slot /></span>' },
        'el-empty': true,
      },
    },
  })
  wrappers.push(wrapper)
  return wrapper
}

describe('ChartGallery contract consumption', () => {
  it('passes the entire producer option unchanged in thumbnails', async () => {
    mountGallery()
    await flushPromises()
    expect(received).toEqual([option])
  })

  it('displays both producer footnote locations as literal text', async () => {
    const wrapper = mountGallery()
    await flushPromises()
    const expected = ['[需核实:货币单位]', '<b>原始数据说明</b>', '纵轴未从 0 开始']
    expect(
      wrapper
        .find('.chart-card')
        .findAll('.chart-footnote')
        .map((el) => el.text())
    ).toEqual(expected)
    expect(wrapper.find('.chart-card b').exists()).toBe(false)
  })

  it('renders legacy specs with no panel, annotation, or footnote metadata', async () => {
    const wrapper = mountGallery([
      { chart_id: 'CHART-LEGACY', option: { series: [{ type: 'line', data: [1, 2] }] } },
    ])
    await flushPromises()
    expect(wrapper.find('.chart-card').exists()).toBe(true)
    expect(wrapper.findAll('.chart-footnote')).toHaveLength(0)
    expect(received).toEqual([{ series: [{ type: 'line', data: [1, 2] }] }])
  })

  it('renders the comparison bar type label through the shared ECharts path', async () => {
    const comparisonOption = {
      xAxis: { data: ['公司A', '公司B'] },
      yAxis: { min: -20, max: 30 },
      series: [{ type: 'bar', data: [20, -10] }],
    }
    const wrapper = mountGallery([
      {
        ...spec,
        chart_id: 'CHART-COMPARISON',
        chart_type: 'comparison_bar',
        variant: 'comparison_bar',
        option: comparisonOption,
      },
    ])
    await flushPromises()

    expect(wrapper.text()).toContain('涨跌幅对比图')
    expect(received).toEqual([comparisonOption])
  })

  it('renders a labelled article with a keyboard-openable chart surface', async () => {
    const wrapper = mountGallery([{ ...spec, insight_goal: '比较销量与增速的联动关系' }])
    await flushPromises()

    const article = wrapper.find('article.chart-card')
    const title = article.find('h3.chart-title')
    const surface = article.find('.chart-surface')
    expect(article.attributes('aria-labelledby')).toBe(title.attributes('id'))
    expect(title.text()).toBe(spec.title)
    expect(surface.attributes('role')).toBe('button')
    expect(surface.attributes('tabindex')).toBe('0')
    expect(surface.attributes('aria-label')).toBe(`查看“${spec.title}”大图`)
    expect(article.find('.chart-insight').text()).toContain('比较销量与增速的联动关系')

    await surface.trigger('keydown.enter')
    await flushPromises()
    expect(wrapper.find('.preview').exists()).toBe(true)
    expect(received).toEqual([option, option])
  })
})
