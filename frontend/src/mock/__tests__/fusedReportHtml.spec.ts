import { describe, expect, it } from 'vitest'
import { cloneArtifacts } from '../fixtures/realBatteryData'

/**
 * mock 的 report_html 产物必须是一份结构完整、引用自洽的报告 HTML。
 *
 * 背景：它原先只是把 markdown 塞进 <pre>，报告预览页打开后看不到成品样子。
 * 现在由 fusedReportHtml.ts 按真实后端模板结构生成，本用例锁住结构完整性，
 * 重点是「引用编号不能悬空」——正文里链到的 #source-N 必须真实存在。
 */

function reportHtml(): string {
  const artifact = cloneArtifacts().find((item) => item.kind === 'report_html')
  expect(artifact, 'report_html 产物应存在').toBeTruthy()
  return artifact!.content
}

/** 从 HTML 里抽出某属性/文本的匹配集合 */
function matchAll(html: string, pattern: RegExp): string[] {
  return [...html.matchAll(pattern)].map((m) => m[1]!)
}

describe('mock report_html 产物结构', () => {
  it('是完整的 HTML 文档并内联样式', () => {
    const html = reportHtml()
    expect(html.startsWith('<!doctype html>')).toBe(true)
    expect(html).toContain('<html lang="zh-CN">')
    expect(html).toContain('<style>')
    // 样式来自真实产物捕获，至少有封面与章节规则
    expect(html).toContain('.cover')
    expect(html).toContain('.chapter')
  })

  it('包含封面、草稿横幅、目录、执行摘要四个开篇区块', () => {
    const html = reportHtml()
    expect(html).toContain('class="cover"')
    expect(html).toContain('class="draft-banner"')
    expect(html).toContain('<h2>目录</h2>')
    expect(html).toContain('<ol class="toc">')
    expect(html).toContain('<h2>执行摘要</h2>')
    expect(html).toContain('class="summary"')
  })

  it('七章齐全，且目录锚点与正文锚点一一对应', () => {
    const html = reportHtml()

    const chapterIds = matchAll(html, /id="(chapter-\d+)"/g)
    expect(chapterIds).toEqual([
      'chapter-1',
      'chapter-2',
      'chapter-3',
      'chapter-4',
      'chapter-5',
      'chapter-6',
      'chapter-7',
    ])

    const tocTargets = matchAll(html, /<a href="#(chapter-\d+)">/g)
    expect(tocTargets).toEqual(chapterIds)

    // 章节标题按中文序号命名
    expect(html).toContain('第一章 ·')
    expect(html).toContain('第七章 ·')
  })

  it('章节标题不出现重复编号（fixture 的「N、」前缀需被剥离）', () => {
    const html = reportHtml()
    const chapterHeadings = matchAll(html, /<h2>(第[一二三四五六七八九十]+章 · [^<]+)<\/h2>/g)
    expect(chapterHeadings.length).toBe(7)
    for (const heading of chapterHeadings) {
      // 形如「第一章 · 1、行业定义…」即为重复编号
      expect(heading, `章节标题不应重复编号：${heading}`).not.toMatch(/第[一二三四五六七八九十]+章 · \d+[、.．]/)
    }
    const tocLabels = matchAll(html, /<a href="#chapter-\d+">([^<]+)<\/a>/g)
    for (const label of tocLabels) {
      expect(label, `目录项不应重复编号：${label}`).not.toMatch(/第[一二三四五六七八九十]+章 · \d+[、.．]/)
    }
  })

  it('来源索引存在，且正文/摘要中的引用编号全部可解析（无悬空引用）', () => {
    const html = reportHtml()

    const sourceIds = new Set(matchAll(html, /<tr id="(source-\d+)">/g))
    expect(sourceIds.size).toBeGreaterThan(0)
    expect(html).toContain('id="source-index"')

    const cited = matchAll(html, /href="#(source-\d+)"/g)
    expect(cited.length).toBeGreaterThan(0)
    for (const target of cited) {
      expect(sourceIds.has(target), `引用 ${target} 应有对应来源行`).toBe(true)
    }
  })

  it('正文包含全部小节标题与段落文本', () => {
    const html = reportHtml()
    // 章节标题形如「第1章第1节 · …」，七章各 2 节
    const sectionHeadings = matchAll(html, /<h3>(第\d+章第\d+节 · [^<]+)<\/h3>/g)
    expect(sectionHeadings.length).toBe(14)
    // 段落非空
    expect(html).toContain('<p>')
  })

  it('内联图表 SVG 且带图号与数据来源说明', () => {
    const html = reportHtml()
    if (!html.includes('class="chart')) {
      // fixture 若无带 svg 的图表，则不生成图表块（不是失败）
      expect(html).not.toContain('<figure')
      return
    }
    expect(html).toContain('<figure class="chart')
    expect(html).toContain('class="chart-number"')
    expect(html).toContain('<svg')
  })

  it('以真实报告免责声明收尾，且不再是把 markdown 塞进 pre 的占位', () => {
    const html = reportHtml()
    expect(html).toContain('免责声明')
    expect(html).toContain('不构成证券投资建议')
    expect(html).not.toContain('<pre>')
    expect(html.trimEnd().endsWith('</html>')).toBe(true)
  })
})
