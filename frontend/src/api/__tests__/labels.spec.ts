import { describe, expect, it } from 'vitest'
import { artifactKindLabel, chapterNumber } from '../labels'

/**
 * 章节序号从 chapter_id 反推（3 个弹窗/确认文案共用）。
 * 后端标题是纯文本，编号属于结构信息，因此不依赖标题内容。
 */
describe('chapterNumber', () => {
  it('从 chapter_id 反推序号', () => {
    expect(chapterNumber('CH-01')).toBe('1')
    expect(chapterNumber('CH-07')).toBe('7')
    expect(chapterNumber('CH-12')).toBe('12')
  })

  it('非法或缺失输入返回占位符，不抛错', () => {
    expect(chapterNumber('')).toBe('?')
    expect(chapterNumber(undefined)).toBe('?')
    expect(chapterNumber('SEC-01-01')).toBe('?')
    expect(chapterNumber('chapter-1')).toBe('?')
  })
})

describe('artifactKindLabel', () => {
  it('覆盖四类报告产物', () => {
    expect(artifactKindLabel('report_html')).toBe('报告 HTML')
    expect(artifactKindLabel('report_markdown')).toBe('报告 Markdown')
    expect(artifactKindLabel('report_pdf')).toBe('报告 PDF')
    expect(artifactKindLabel('artifact_manifest')).toBe('产物清单')
  })

  it('未知类型回退原值', () => {
    expect(artifactKindLabel('report_docx')).toBe('report_docx')
    expect(artifactKindLabel(undefined)).toBe('')
  })
})
