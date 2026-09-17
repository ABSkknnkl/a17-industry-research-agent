import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ChartGallery from './ChartGallery.vue'
import { usePrototypeStore } from '../mock/prototypeRun'
import { ensureLocalStorage } from '../mock/testUtils'

vi.mock('../api/client', async () => {
  return {
    isMockDataMode: () => true,
    downloadArtifact: vi.fn(),
    triggerBlobDownload: vi.fn(),
  }
})

const SPECS = [
  {
    chart_id: 'CHART-LI',
    title: '演示折线',
    chart_type: 'line',
    option: {
      xAxis: { type: 'category', data: ['a'] },
      yAxis: {},
      series: [{ type: 'line', data: [1] }],
    },
    render_mode: 'echarts',
    insight_goal: '演示',
  },
  {
    chart_id: 'CHART-003',
    title: '演示产业链',
    chart_type: 'industry_chain',
    render_mode: 'generated_image',
    image_uri: 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg"></svg>',
    insight_goal: '结构',
  },
]

// echarts init 在 jsdom 可能失败，stub 掉
vi.mock('echarts', () => {
  const instance = {
    setOption: vi.fn(),
    resize: vi.fn(),
    dispose: vi.fn(),
    getDom: () => document.createElement('div'),
  }
  return {
    init: () => instance,
  }
})

describe('ChartGallery.prototype', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    ensureLocalStorage().clear()
    usePrototypeStore().resetPrototype()
    // jsdom 无 ResizeObserver
    globalThis.ResizeObserver =
      globalThis.ResizeObserver ??
      (class {
        observe(): void {}
        unobserve(): void {}
        disconnect(): void {}
      } as unknown as typeof ResizeObserver)
  })

  it('现有点击预览仍可用，SVG 与 ECharts 都可渲染', async () => {
    const wrapper = mount(ChartGallery, {
      props: { specs: SPECS as never },
      global: { plugins: [ElementPlus, createPinia()] },
      attachTo: document.body,
    })
    await flushPromises()
    expect(wrapper.find('[data-testid="chart-gallery"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="chart-svg-image"]').exists()).toBe(true)
    // mock 菜单
    expect(wrapper.find('[data-testid="chart-control-menu"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('删除图表菜单改变正确状态', async () => {
    const store = usePrototypeStore()
    const wrapper = mount(ChartGallery, {
      props: { specs: SPECS as never },
      global: { plugins: [ElementPlus, createPinia()] },
      attachTo: document.body,
    })
    await flushPromises()
    const delBtn = wrapper.findAll('[data-testid="chart-delete"]')[0]
    expect(delBtn).toBeTruthy()
    // 直接调用 store 验证状态（跳过 confirm 对话框）
    store.deleteChart('CHART-LI')
    const target = store.getCharts().find((c: { chart_id: string }) => c.chart_id === 'CHART-LI')
    expect(target!.status).toBe('deleted')
    wrapper.unmount()
  })
})
