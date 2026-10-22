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

function mountGallery(specs: Partial<ChartSpec>[] = [spec], extraProps: Record<string, unknown> = {}) {
  const wrapper = mount(ChartGallery, {
    props: { specs, ...extraProps },
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

  it('sanitizes bubble and scatter data where entity names precede coordinates', async () => {
    const rawBubbleSpec = {
      chart_id: 'CHART-BUBBLE-1',
      title: '动态市盈率与资产负债率定位',
      chart_type: 'bubble' as const,
      option: {
        xAxis: { type: 'value', name: '动态市盈率' },
        yAxis: { type: 'value', name: '资产负债率' },
        series: [
          {
            type: 'scatter',
            symbolSize: 'value[3]',
            data: [
              ['五粮液', 15.45, 35.69, 84.6],
              ['贵州茅台', 17.37, 16.42, 91.18],
            ],
          },
        ],
      },
    }
    const wrapper = mountGallery([rawBubbleSpec])
    await flushPromises()

    expect(received.length).toBeGreaterThan(0)
    const passedOpt = received[0] as Record<string, any>
    const seriesData = passedOpt.series[0].data
    expect(seriesData[0].name).toBe('五粮液')
    expect(seriesData[0].value[0]).toBe(15.45)
    expect(seriesData[0].value[1]).toBe(35.69)
    expect(typeof seriesData[0].symbolSize).toBe('number')
    expect(passedOpt.xAxis.scale).toBe(true)
    expect(passedOpt.yAxis.scale).toBe(true)
  })

  it('renders chain-fallback-notice for industry_chain charts using ECharts vector mode', async () => {
    const chainSpec = {
      chart_id: 'CHART-CHAIN-1',
      title: '动力电池产业链拓扑图',
      chart_type: 'industry_chain' as const,
      option: {
        series: [{ type: 'graph', data: [{ name: '上游' }, { name: '中游' }] }],
      },
    }
    const wrapper = mountGallery([chainSpec])
    await flushPromises()

    const notice = wrapper.find('.chain-fallback-notice')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain('已使用 ECharts 矢量拓扑图呈现产业链结构')
  })

  it('automatically adds outlier footnote when series data has values > 5x median', async () => {
    const outlierSpec = {
      chart_id: 'CHART-OUTLIER-1',
      title: '样本市盈率横向对比',
      chart_type: 'bar' as const,
      option: {
        xAxis: { type: 'category', data: ['A', 'B', 'C', 'D'] },
        yAxis: { type: 'value', name: '倍' },
        series: [
          {
            type: 'bar',
            data: [15, 18, 20, 200], // median is 18-20, 200 is > 5x
          },
        ],
      },
    }
    const wrapper = mountGallery([outlierSpec])
    await flushPromises()

    const footnotes = wrapper.findAll('.chart-footnote')
    const hasOutlierNote = footnotes.some((f) => f.text().includes('显著偏离行业中枢'))
    expect(hasOutlierNote).toBe(true)
  })
})


describe('ChartGallery inline SVG (render_mode=svg, 2026-10-07)', () => {
  const CHAIN_SVG =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 300" role="img">' +
    '<title>低空经济产业链结构</title>' +
    '<defs><marker id="chainArrow"><polygon points="0,0 10,4 0,8" fill="#475467"/></marker></defs>' +
    '<rect x="0" y="0" width="800" height="300" fill="#FFFFFF"/>' +
    '<polygon points="10,10 200,10 210,30 200,50 10,50" fill="#0F766E"/>' +
    '<text x="20" y="35" font-size="14" fill="#FFFFFF">上游：基础支撑</text>' +
    '<line x1="220" y1="100" x2="300" y2="100" stroke="#475467" marker-end="url(#chainArrow)"/>' +
    '</svg>'

  const svgSpec = {
    chart_id: 'CHART-CHAIN-SVG',
    title: '低空经济产业链结构',
    chart_type: 'industry_chain' as const,
    option: { series: [{ type: 'graph', data: [] }] },
    evidence_ids: ['E-1'],
    render_mode: 'svg' as const,
    inline_svg: CHAIN_SVG,
  }

  it('renders inline SVG instead of initialising ECharts', async () => {
    const wrapper = mountGallery([svgSpec])
    await flushPromises()
    const host = wrapper.find('.chart-inline-svg')
    expect(host.exists()).toBe(true)
    expect(host.html()).toContain('上游：基础支撑')
    expect(host.find('svg').exists()).toBe(true)
    // ECharts 不应为该图初始化
    expect(vi.mocked(echarts.init).mock.calls.length).toBe(0)
  })

  it('sanitizes event handlers, scripts, hrefs and non-whitelist elements', async () => {
    const evil =
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" onload="alert(1)">' +
      '<script>alert(2)</script>' +
      '<rect x="1" y="1" width="10" height="10" onclick="alert(3)"/>' +
      '<a href="javascript:alert(4)"><text x="5" y="50">安全文本</text></a>' +
      '<foreignObject><div>html</div></foreignObject>' +
      '<text x="5" y="80" style="background:url(http://evil)">保留</text>' +
      '</svg>'
    const wrapper = mountGallery([{ ...svgSpec, inline_svg: evil }])
    await flushPromises()
    const host = wrapper.find('.chart-inline-svg')
    expect(host.exists()).toBe(true)
    const html = host.html()
    expect(html).not.toContain('alert')
    expect(html).not.toContain('script')
    expect(html).not.toContain('onload')
    expect(html).not.toContain('onclick')
    expect(html).not.toContain('href')
    expect(html).not.toContain('foreignObject')
    expect(html).not.toContain('style')
    // <a> 不在白名单 → 整棵子树（含其中文本）一并移除
    expect(html).not.toContain('安全文本')
    expect(html).toContain('保留')
  })

  it('falls back to ECharts branch when inline_svg is missing', async () => {
    const wrapper = mountGallery([{ ...svgSpec, inline_svg: null }])
    await flushPromises()
    expect(wrapper.find('.chart-inline-svg').exists()).toBe(false)
    expect(wrapper.find('.chart-surface').exists()).toBe(true)
  })

  it('shows inline SVG in preview dialog', async () => {
    const wrapper = mountGallery([svgSpec])
    await flushPromises()
    await wrapper.find('.chart-inline-svg').trigger('click')
    await flushPromises()
    const dialog = wrapper.find('.chart-inline-svg-dialog')
    expect(dialog.exists()).toBe(true)
    expect(dialog.html()).toContain('上游：基础支撑')
  })
})

// 2026-10-17：HTML 排版版从「顶替主图」降为「并存补充视图」。
// 主图必须仍是带连线的确定性 SVG —— 用户实测反馈"连线的节点不见了"。
describe('ChartGallery supplement view (2026-10-17)', () => {
  const CHAIN_SVG =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 300" role="img">' +
    '<title>低空经济产业链结构</title>' +
    '<line x1="220" y1="100" x2="300" y2="100" stroke="#475467"/>' +
    '<text x="20" y="35" font-size="14">上游：基础支撑</text>' +
    '</svg>'
  const supplementSpec = {
    chart_id: 'CHART-CHAIN-SUPP',
    title: '低空经济产业链结构',
    chart_type: 'industry_chain' as const,
    option: { series: [{ type: 'graph', data: [] }] },
    evidence_ids: ['E-1'],
    render_mode: 'svg' as const,
    inline_svg: CHAIN_SVG,
    supplement_image_uri:
      '/Users/u/project/data/runs/run-42/artifacts/images/CHART-CHAIN-SUPP_chain.png',
    supplement_html_uri: '/Users/u/project/data/runs/run-42/artifacts/charts/CHART-CHAIN-SUPP.html',
    supplement_note: 'LLM 排版版（卡片信息更细，但不画连线与箭头）',
  }

  it('keeps the connected SVG as the main chart and only adds an entry', async () => {
    const wrapper = mountGallery([supplementSpec], { runId: 'run-42' })
    await flushPromises()
    // 主图仍是内联 SVG（连线在 SVG 里）
    const main = wrapper.find('.chart-inline-svg')
    expect(main.exists()).toBe(true)
    expect(main.html()).toContain('上游：基础支撑')
    // 只多一个切换入口，不改主图、不初始化 ECharts
    expect(wrapper.find('[data-testid="chart-supplement-open"]').exists()).toBe(true)
    expect(vi.mocked(echarts.init).mock.calls.length).toBe(0)
  })

  it('renders the supplementary bitmap through the run artifact endpoint', async () => {
    const wrapper = mountGallery([supplementSpec], { runId: 'run-42' })
    await flushPromises()
    await wrapper.find('[data-testid="chart-supplement-open"]').trigger('click')
    await flushPromises()
    const img = wrapper.find('[data-testid="chart-supplement-image"]')
    expect(img.exists()).toBe(true)
    // 磁盘绝对路径不能直接给浏览器，必须走 run 产物接口（按文件名解析）
    expect(img.attributes('src')).toBe(
      '/api/v1/runs/run-42/artifacts/CHART-CHAIN-SUPP_chain.png'
    )
    expect(wrapper.html()).toContain('LLM 排版版')
  })

  it('hides the supplement entry when no supplement is present', async () => {
    const wrapper = mountGallery([{ ...supplementSpec, supplement_image_uri: null }], {
      runId: 'run-42',
    })
    await flushPromises()
    expect(wrapper.find('[data-testid="chart-supplement-open"]').exists()).toBe(false)
    expect(wrapper.find('.chart-inline-svg').exists()).toBe(true)
  })
})
