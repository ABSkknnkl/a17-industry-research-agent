import { mount } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'
import { describe, expect, it } from 'vitest'
import LandingView from '../LandingView.vue'

describe('LandingView 首页', () => {
  it('正确渲染首页大标题与开始制作研究报告按钮', async () => {
    const router = createRouter({
      history: createWebHistory(),
      routes: [
        { path: '/', name: 'home', component: LandingView },
        { path: '/create', name: 'create', component: { template: '<div />' } },
        { path: '/runs', name: 'runs', component: { template: '<div />' } },
      ],
    })
    await router.push('/')
    await router.isReady()

    const wrapper = mount(LandingView, {
      global: {
        plugins: [router],
      },
    })

    expect(wrapper.text()).toContain('把行业研究')
    expect(wrapper.text()).toContain('从资料搜集推进到可审核报告')

    const startBtn = wrapper.find('[data-testid="btn-start-report"]')
    expect(startBtn.exists()).toBe(true)
    expect(startBtn.text()).toContain('开始制作研究报告')
    expect(startBtn.attributes('href')).toBe('/create')

    const historyBtn = wrapper.find('[data-testid="btn-view-history"]')
    expect(historyBtn.exists()).toBe(true)
    expect(historyBtn.attributes('href')).toBe('/runs')
  })
})
