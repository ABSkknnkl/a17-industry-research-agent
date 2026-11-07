import { mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { describe, expect, it } from 'vitest'
import StageDigest from '../StageDigest.vue'

/**
 * 阶段五（report_fusion）专属分支回归。
 *
 * 此前 report_fusion 落到通用兜底（顶层标量键值对列表），
 * 用户看不到报告封面/目录/产物；本用例锁住"走专属分支、不走兜底"。
 */

const FUSION_DATA = {
  report_id: 'REPORT-TEST-R1',
  title: '动力电池行业研究报告',
  industry_topic: '动力电池',
  research_as_of: '2026-08-11',
  generated_at: '2026-09-05T11:39:10Z',
  delivery_status: 'ready_with_limits',
  release_mode: 'draft_with_warnings',
  report_depth: 'standard',
  formats: ['markdown', 'html', 'pdf'],
  chapters: [
    {
      chapter_id: 'CH-01',
      title: '行业概述',
      summary: '政策环境与产业发展阶段',
      sections: [{ section_id: 'SEC-01-01', title: '政策环境' }],
    },
  ],
  evidence_catalog: [{ citation_number: 1, display_label: '来源1：中汽协' }],
  artifacts: [
    {
      artifact_id: 'ART-HTML',
      kind: 'report_html',
      uri: 'run-test/reports/r1/report.html',
      size_bytes: 84_283,
    },
  ],
}

function mountDigest(data: Record<string, unknown>) {
  return mount(StageDigest, {
    props: { stage: 'report_fusion', data },
    global: { plugins: [ElementPlus, createPinia()] },
  })
}

describe('StageDigest · report_fusion 分支', () => {
  it('展示报告预览，且不再回退到通用键值对兜底', () => {
    const wrapper = mountDigest(FUSION_DATA)
    const text = wrapper.text()

    expect(text).toContain('最终报告预览')
    // 交付产物表格已移至独立下载页，阶段五不再展示
    expect(text).not.toContain('交付产物')
    // 引用证据条数来自 evidence_catalog
    expect(text).toContain('引用证据 1 条')
    // 有 HTML 产物时可在线预览
    expect(wrapper.find('[data-testid="report-preview-open"]').exists()).toBe(true)
    // 兜底区块必须消失，否则阶段五又会退化成键值对列表
    expect(text).not.toContain('本阶段结果概览')
  })

  it('只有 Markdown/PDF 产物时，不提供在线预览入口', () => {
    const wrapper = mountDigest({
      ...FUSION_DATA,
      artifacts: [
        { artifact_id: 'ART-MD', kind: 'report_markdown', uri: 'r/report.md', size_bytes: 100 },
      ],
    })

    expect(wrapper.find('[data-testid="report-preview-open"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('最终报告预览')
  })

  it('缺少 quality / 章节为空时不报错', () => {
    const wrapper = mountDigest({ title: '空报告' })

    expect(wrapper.text()).toContain('最终报告预览')
    expect(wrapper.find('[data-testid="report-preview-open"]').exists()).toBe(false)
  })

  it('融合失败（只有标量错误信息）时，必须回退兜底，不能把错误藏掉', () => {
    // 后端 report_render_failed 的真实 data 形状（service.py:252-256）
    const wrapper = mountDigest({
      error_type: 'RenderError',
      error_message: '模板渲染失败',
      error_traceback: 'Traceback ...',
    })

    expect(wrapper.text()).not.toContain('最终报告预览')
    expect(wrapper.text()).toContain('本阶段结果概览')
    expect(wrapper.text()).toContain('模板渲染失败')
  })
})
