import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DEMO_RUN_ID } from '../fixtures/amdResearchMock'
import { ensureLocalStorage } from '../testUtils'
import { usePrototypeStore } from '../prototypeRun'

/**
 * Mock 阶段五数据与后端契约（contracts/schemas/report-fusion-result.schema.json）对齐。
 *
 * 背景与两个曾经的偏差：
 * 1. 早期 mock 只有报告元信息，没有 chapters / evidence_catalog —— 目录为空。
 * 2. 更关键的一次误解：曾以为「真实后端 report_view（阶段五 data）带 chapters」。
 *    实际上 `report_view.json` 是 ReportFusionAgent 的**内部产物**（service.py 落盘，
 *    明确不进 manifest / StageResult.artifacts），而 API 返回的
 *    `ReportFusionResult` 当时**根本没有 chapters 字段** —— 于是 mock 有了、真实没有。
 *    现已在后端补齐该字段，本用例锁住两侧一致。
 */
describe('report_fusion 阶段数据字段对齐', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    ensureLocalStorage().clear()
    usePrototypeStore().resetPrototype()
    vi.useRealTimers()
  })

  function fusionData(): Record<string, unknown> {
    const workflow = usePrototypeStore().getWorkflow(DEMO_RUN_ID)
    return workflow.stage_results.report_fusion!.data
  }

  it('带章节，供报告封面目录使用', () => {
    const chapters = fusionData().chapters as Array<Record<string, unknown>>
    expect(Array.isArray(chapters)).toBe(true)
    expect(chapters.length).toBeGreaterThan(0)
    // 目录渲染依赖这三个字段
    expect(chapters[0]).toHaveProperty('chapter_id')
    expect(chapters[0]).toHaveProperty('title')
    expect(chapters[0]).toHaveProperty('summary')
    expect(Array.isArray(chapters[0]!.sections)).toBe(true)
  })

  it('章节标题是纯文本（不带「N、」序号前缀），与真实后端一致', () => {
    const chapters = fusionData().chapters as Array<Record<string, unknown>>
    for (const chapter of chapters) {
      expect(String(chapter.title)).not.toMatch(/^\s*\d+\s*[、.．]/)
    }
  })

  it('带来源清单，条数与采集证据一致', () => {
    const catalog = fusionData().evidence_catalog as Array<Record<string, unknown>>
    const evidenceCount = usePrototypeStore().getEvidence().length
    expect(Array.isArray(catalog)).toBe(true)
    expect(catalog.length).toBe(evidenceCount)
    // 「引用证据」指标与预览页来源清单都读这两项
    expect(catalog[0]).toHaveProperty('citation_number')
    expect(catalog[0]).toHaveProperty('display_label')
    expect(Array.isArray(catalog[0]!.evidence_ids)).toBe(true)
  })

  it('章节数据与 chapter_write 阶段一致（共用同一套映射）', () => {
    const workflow = usePrototypeStore().getWorkflow(DEMO_RUN_ID)
    const fusionChapters = workflow.stage_results.report_fusion!.data.chapters
    const writeChapters = workflow.stage_results.chapter_write!.data.chapters
    expect(JSON.stringify(fusionChapters)).toBe(JSON.stringify(writeChapters))
  })

  it('带契约要求的 outline_version 与 visual_decision', () => {
    const data = fusionData()

    expect(data.outline_version).toBe('2026.1')

    const decision = data.visual_decision as Record<string, unknown>
    expect(decision).toBeTruthy()
    // 契约 required 三项
    for (const key of ['recommended_style', 'effective_style', 'selection_source']) {
      expect(decision, `visual_decision 缺 ${key}`).toHaveProperty(key)
    }
    // 取值对齐真实产物：<body class="visual-data-manual density-balanced">
    expect(decision.effective_style).toBe('data_manual')
    expect(decision.density).toBe('balanced')
    expect(decision.per_chapter_strategy).toBeTruthy()
  })

  it('quality 带评分基准（分母由后端下发，前端不写死 7/21）', () => {
    const quality = fusionData().quality as Record<string, unknown>

    expect(quality.expected_chapter_count).toBe(7)
    expect(quality.expected_section_count).toBe(21)
    expect(quality.chapter_count).toBe(7)
  })

  it('quality 带后端确定性 100 分制字段（total_score / score_breakdown / thresholds）', () => {
    const quality = fusionData().quality as Record<string, unknown>
    const breakdown = quality.score_breakdown as Array<{ score: number; max_score: number }>

    expect(typeof quality.total_score).toBe('number')
    expect(Array.isArray(breakdown)).toBe(true)
    expect(breakdown.length).toBe(5)
    expect(quality.total_score).toBe(
      breakdown.reduce((sum, item) => sum + item.score, 0)
    )
    for (const item of breakdown) {
      expect(item.score).toBeGreaterThanOrEqual(0)
      expect(item.score).toBeLessThanOrEqual(item.max_score)
    }
    expect(quality.thresholds).toEqual({ good: 90, warn: 70 })
  })
})
