import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PROTOTYPE_STORAGE_KEY, isMockMode, usePrototypeStore } from '../prototypeRun'
import { DEMO_RUN_ID } from '../fixtures/amdResearchMock'
import { ensureLocalStorage } from '../testUtils'

function store() {
  return usePrototypeStore()
}

describe('prototypeRun store', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    ensureLocalStorage().clear()
    store().resetPrototype()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('fixture 初始化结果固定（真实流水线抽取）', () => {
    const s = store()
    expect(s.state.runId).toBe(DEMO_RUN_ID)
    expect(s.state.evidences.length).toBeGreaterThanOrEqual(8)
    expect(s.state.claims.length).toBeGreaterThanOrEqual(5)
    expect(s.state.charts.length).toBeGreaterThanOrEqual(4)
    expect(s.state.evidences[0]!.evidence_id).toBe('EV-RD-CATL')
    expect(s.getCharts().some((c) => c.chart_id === 'CHART-LI')).toBe(true)
  })

  it('排除和恢复证据', async () => {
    const s = store()
    const p = s.excludeEvidence('EV-RD-CATL', '口径不符')
    await vi.runAllTimersAsync()
    const rec = await p
    expect(rec.ok).toBe(true)
    expect(s.getEvidence().find((e) => e.evidence_id === 'EV-RD-CATL')!.status).toBe('excluded')
    const p2 = s.restoreEvidence('EV-RD-CATL')
    await vi.runAllTimersAsync()
    await p2
    expect(s.getEvidence().find((e) => e.evidence_id === 'EV-RD-CATL')!.status).toBe('active')
  })

  it('排除碳酸锂证据后下游结论 provisional', async () => {
    const s = store()
    const p = s.excludeEvidence('EV-LI-SPOT', '来源可疑')
    await vi.runAllTimersAsync()
    const rec = await p
    expect(rec.affected.length).toBeGreaterThan(0)
    const li = s.getClaims().find((c) => c.claim_id === 'CLM-LI')
    expect(li?.status).toBe('provisional')
  })

  it('驳回和恢复结论', async () => {
    const s = store()
    const id = s.getClaims()[0]!.claim_id
    const p = s.rejectClaim(id, '因果不充分')
    await vi.runAllTimersAsync()
    await p
    expect(s.getClaims().find((c) => c.claim_id === id)!.status).toBe('rejected')
    const p2 = s.restoreClaim(id)
    await vi.runAllTimersAsync()
    await p2
    expect(s.getClaims().find((c) => c.claim_id === id)!.status).toBe('active')
  })

  it('单图重生成只增加目标图版本', async () => {
    const s = store()
    const before = s.getCharts().map((c) => ({ id: c.chart_id, rev: c.unit_revision }))
    const p = s.regenerateChart('CHART-LI')
    await vi.runAllTimersAsync()
    await p
    const after = s.getCharts()
    expect(after.find((c) => c.chart_id === 'CHART-LI')!.unit_revision).toBe(
      before.find((c) => c.id === 'CHART-LI')!.rev + 1
    )
    expect(after.find((c) => c.chart_id === 'CHART-RD')!.unit_revision).toBe(
      before.find((c) => c.id === 'CHART-RD')!.rev
    )
  })

  it('删除图和撤销删除', () => {
    const s = store()
    s.deleteChart('CHART-SHARE')
    expect(s.getCharts().find((c) => c.chart_id === 'CHART-SHARE')!.status).toBe('deleted')
    s.restoreDeletedChart('CHART-SHARE')
    expect(s.getCharts().find((c) => c.chart_id === 'CHART-SHARE')!.status).toBe('active')
  })

  it('段落编辑只改变目标段落', () => {
    const s = store()
    const first = s.getChapters()[0]!.sections[0]!.paragraphs[0]!
    const other = s.getChapters()[0]!.sections[0]!.paragraphs[1]!
    const beforeOther = other.text
    s.updateParagraph(first.paragraph_id, '演示：已修改的段落文本')
    expect(first.version).toBe(2)
    expect(first.text).toBe('演示：已修改的段落文本')
    expect(other.text).toBe(beforeOther)
  })

  it('风险未确认时不能通过阶段（装机缺口）', async () => {
    const s = store()
    const p = s.approveStage('data_fetch')
    await vi.runAllTimersAsync()
    const rec = await p
    expect(rec.ok).toBe(false)
    expect(rec.message).toContain('REQUESTED-DATA-UNAVAILABLE')

    s.acknowledgeRisk('REQUESTED-DATA-UNAVAILABLE')
    const p2 = s.approveStage('data_fetch')
    await vi.runAllTimersAsync()
    const rec2 = await p2
    expect(rec2.ok).toBe(true)
  })

  it('localStorage 持久化和恢复', () => {
    const s = store()
    const pid = s.getChapters()[0]!.sections[0]!.paragraphs[0]!.paragraph_id
    s.updateParagraph(pid, '持久化测试文本')
    s.persist()
    expect(localStorage.getItem(PROTOTYPE_STORAGE_KEY)).toBeTruthy()
    s.raw.chapters[0]!.sections[0]!.paragraphs[0]!.text = '临时'
    s.hydrate()
    expect(s.getChapters()[0]!.sections[0]!.paragraphs[0]!.text).toBe('持久化测试文本')
  })

  it('reset 清除持久化状态', () => {
    const s = store()
    s.persist()
    expect(localStorage.getItem(PROTOTYPE_STORAGE_KEY)).toBeTruthy()
    s.resetPrototype()
    expect(localStorage.getItem(PROTOTYPE_STORAGE_KEY)).toBeNull()
  })

  it('isMockMode 读取环境变量', () => {
    expect(typeof isMockMode()).toBe('boolean')
  })
})

/**
 * 下载 blob 的演示声明注入方式。
 *
 * 曾经的 bug：对 HTML 产物也在 <!doctype> 前拼纯文本声明，
 * 浏览器会把那段文字当正文渲染到报告封面之上（还可能触发怪异模式）。
 */
describe('getDownloadBlob 演示声明注入', () => {
  beforeEach(() => {
    ensureLocalStorage().clear()
    store().resetPrototype()
  })

  function htmlArtifactId(): string {
    const art = store()
      .getArtifacts()
      .find((a) => a.kind === 'report_html')
    expect(art, 'fixture 应含 report_html 产物').toBeTruthy()
    return art!.artifact_id
  }

  /** jsdom 未实现 Blob.prototype.text()，用 FileReader 读内容 */
  function blobText(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result ?? ''))
      reader.onerror = () => reject(reader.error)
      reader.readAsText(blob)
    })
  }

  it('HTML 产物以 <!doctype html> 开头，声明以注释形式注入', async () => {
    const blob = store().getDownloadBlob(htmlArtifactId())
    expect(blob).toBeTruthy()
    expect(blob!.type).toContain('text/html')

    const text = await blobText(blob!)
    expect(text.startsWith('<!doctype html>')).toBe(true)
    expect(text).toContain('<!-- 演示产物')
    expect(text).toContain('不代表真实研究结论')
    // 声明不得以裸文本出现在文档最前面
    expect(text.slice(0, text.indexOf('<!doctype html>'))).toBe('')
  })

  it('HTML 产物是完整报告（不再是 <pre>markdown</pre> 占位）', async () => {
    const text = await blobText(store().getDownloadBlob(htmlArtifactId())!)
    expect(text).toContain('<style>')
    expect(text).toContain('class="cover"')
    expect(text).not.toContain('<pre>')
    expect(text.trimEnd().endsWith('</html>')).toBe(true)
  })

  it('非 HTML 产物保留纯文本声明前缀', async () => {
    const md = store()
      .getArtifacts()
      .find((a) => a.kind === 'report_markdown')
    const text = await blobText(store().getDownloadBlob(md!.artifact_id)!)
    expect(text.startsWith('演示产物 ·')).toBe(true)
    expect(text).toContain('不代表真实研究结论')
  })
})
