/**
 * 原型运行时状态：固定 fixture + localStorage 持久化。
 * 所有异步动作使用固定延迟；ID 与演示时间不随机。
 */
import { reactive, readonly } from 'vue'
import type {
  ActionReceipt,
  ArtifactItem,
  ChartItem,
  ChapterItem,
  ClaimItem,
  EvidenceItem,
  ParagraphItem,
  PrototypeRevision,
  ReportSettings,
  RiskItem,
  RunListResponse,
  RunSummary,
  StageName,
  StageStatus,
  WorkflowState,
} from '../api/types'
import {
  CHART_REGEN_MS,
  DEMO_PROJECT_ID,
  DEMO_RUN_ID,
  DEMO_TITLE,
  FIXED_NOW,
  FIXTURE_VERSION,
  MOCK_DELAY_MS,
  buildDemoRunSummary,
  buildExtraDemoRuns,
  buildWorkflowState,
  cloneArtifacts,
  cloneCharts,
  cloneChapters,
  cloneClaims,
  cloneEvidence,
  cloneHistory,
  cloneRisks,
  defaultReportSettings,
  initialStageMap,
} from './fixtures/amdResearchMock'

export const PROTOTYPE_STORAGE_KEY = 'trc:prototype:v1'

export interface PrototypeState {
  runId: string
  globalRevision: number
  selectedStage: StageName
  selectedObjectId: string | null
  queueFilter: 'all' | 'pending' | 'done'
  stages: Record<StageName, { status: StageStatus; revision: number; produced: boolean }>
  evidences: EvidenceItem[]
  claims: ClaimItem[]
  charts: ChartItem[]
  chapters: ChapterItem[]
  artifacts: ArtifactItem[]
  risks: RiskItem[]
  operations: Array<{ id: string; action: string; object_id: string; summary: string; at: string }>
  history: PrototypeRevision[]
  lastAction: ActionReceipt | null
  reportSettings: ReportSettings
  workflowStatus: StageStatus
  simulationRunning: boolean
  simulationPhase: number
  fixtureVersion: string
}

function initialState(): PrototypeState {
  return {
    runId: DEMO_RUN_ID,
    globalRevision: 3,
    selectedStage: 'chart_generate',
    selectedObjectId: null,
    queueFilter: 'all',
    stages: initialStageMap(),
    evidences: cloneEvidence(),
    claims: cloneClaims(),
    charts: cloneCharts(),
    chapters: cloneChapters(),
    artifacts: cloneArtifacts(defaultReportSettings),
    risks: cloneRisks(),
    operations: [
      {
        id: 'OP-INIT',
        action: 'init',
        object_id: DEMO_RUN_ID,
        summary: '演示 fixture 初始化',
        at: FIXED_NOW,
      },
    ],
    history: cloneHistory(),
    lastAction: null,
    reportSettings: { ...defaultReportSettings },
    workflowStatus: 'waiting_review',
    simulationRunning: false,
    simulationPhase: 0,
    fixtureVersion: FIXTURE_VERSION,
  }
}

const state = reactive<PrototypeState>(initialState())

let opSeq = 1

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

function receipt(
  action: string,
  objectId: string | null,
  ok: boolean,
  message: string,
  affected: string[] = [],
  bumpGlobal = false
): ActionReceipt {
  const before = state.globalRevision
  if (bumpGlobal) state.globalRevision += 1
  const after = state.globalRevision
  const rec: ActionReceipt = {
    action,
    object_id: objectId,
    before_revision: before,
    after_revision: after,
    ok,
    message,
    affected,
  }
  state.lastAction = rec
  state.operations = [
    ...state.operations,
    {
      id: `OP-${String(opSeq++).padStart(3, '0')}`,
      action,
      object_id: objectId ?? '',
      summary: message,
      at: FIXED_NOW,
    },
  ].slice(-50)
  return rec
}

function pushHistory(note: string): void {
  state.history = [
    ...state.history,
    {
      revision: state.globalRevision,
      status: state.workflowStatus,
      current_stage: state.selectedStage,
      updated_at: FIXED_NOW,
      note,
    },
  ]
}

function findEvidence(id: string): EvidenceItem | undefined {
  return state.evidences.find((e) => e.evidence_id === id)
}

function findClaim(id: string): ClaimItem | undefined {
  return state.claims.find((c) => c.claim_id === id)
}

function findChart(id: string): ChartItem | undefined {
  return state.charts.find((c) => c.chart_id === id)
}

function findChapter(id: string): ChapterItem | undefined {
  return state.chapters.find((c) => c.chapter_id === id)
}

function findParagraph(id: string): { paragraph: ParagraphItem; sectionId: string } | null {
  for (const chapter of state.chapters) {
    for (const section of chapter.sections) {
      const paragraph = section.paragraphs.find((p) => p.paragraph_id === id)
      if (paragraph) return { paragraph, sectionId: section.section_id }
    }
  }
  return null
}

/** 排除 EV-003（碳酸锂价格）后的下游影响：CLM-003 / SEC-03-01 */
function propagateEvidenceExclusion(evidenceId: string): string[] {
  const affected: string[] = []
  if (evidenceId !== 'EV-003') {
    // 通用：引用该证据的结论变为 provisional
    for (const claim of state.claims) {
      if (claim.evidence_ids.includes(evidenceId) && claim.status === 'active') {
        claim.status = 'provisional'
        affected.push(claim.claim_id)
      }
    }
    return affected
  }

  for (const claim of state.claims) {
    if (claim.claim_id === 'CLM-003' && claim.status === 'active') {
      claim.status = 'provisional'
      affected.push(claim.claim_id)
    }
  }
  for (const chapter of state.chapters) {
    for (const section of chapter.sections) {
      if (section.section_id === 'SEC-03-01') {
        chapter.upstream_hint = '上游证据 EV-003（碳酸锂价格）已排除，成本结论待复核'
        affected.push(section.section_id)
      }
    }
  }
  return affected
}

function restoreEvidencePropagation(evidenceId: string): string[] {
  const affected: string[] = []
  for (const claim of state.claims) {
    if (claim.evidence_ids.includes(evidenceId) && claim.status === 'provisional') {
      const others = claim.evidence_ids.filter((id) => id !== evidenceId)
      const stillMissing = others.some((id) => findEvidence(id)?.status === 'excluded')
      if (!stillMissing) {
        claim.status = 'active'
        affected.push(claim.claim_id)
      }
    }
  }
  if (evidenceId === 'EV-003') {
    for (const chapter of state.chapters) {
      if (chapter.upstream_hint) {
        chapter.upstream_hint = null
        affected.push('SEC-02-01')
      }
    }
  }
  return affected
}

export function usePrototypeStore() {
  return {
    state: readonly(state),
    raw: state,

    persist(): void {
      const payload: PrototypeState = JSON.parse(JSON.stringify(state))
      localStorage.setItem(PROTOTYPE_STORAGE_KEY, JSON.stringify(payload))
    },

    hydrate(): boolean {
      const raw = localStorage.getItem(PROTOTYPE_STORAGE_KEY)
      if (!raw) return false
      try {
        const parsed = JSON.parse(raw) as PrototypeState
        // fixture 版本不一致：丢弃旧演示进度（例如从 AMD 演示切到动力电池）
        if (parsed.fixtureVersion !== FIXTURE_VERSION) {
          localStorage.removeItem(PROTOTYPE_STORAGE_KEY)
          return false
        }
        Object.assign(state, parsed)
        return true
      } catch {
        return false
      }
    },

    resetPrototype(): ActionReceipt {
      Object.assign(state, initialState())
      localStorage.removeItem(PROTOTYPE_STORAGE_KEY)
      return receipt('resetPrototype', null, true, '已恢复演示初始状态')
    },

    getWorkflow(runId: string): WorkflowState {
      return buildWorkflowState({
        runId: runId || state.runId,
        currentStage: state.selectedStage,
        status: state.workflowStatus,
        revision: state.globalRevision,
        stages: state.stages,
        evidences: state.evidences,
        claims: state.claims,
        charts: state.charts,
        chapters: state.chapters,
        artifacts: state.artifacts,
        risks: state.risks,
        settings: state.reportSettings,
      })
    },

    listRuns(offset = 0, limit = 20): RunListResponse {
      const primary: RunSummary = {
        ...buildDemoRunSummary(),
        run_id: state.runId,
        project_id: DEMO_PROJECT_ID,
        title: DEMO_TITLE,
        current_stage: state.selectedStage,
        status: state.workflowStatus,
        revision: state.globalRevision,
        artifact_count: state.artifacts.length,
        report_available: state.artifacts.length > 0,
      }
      const items = [primary, ...buildExtraDemoRuns()]
      return {
        total: items.length,
        offset,
        limit,
        items: items.slice(offset, offset + limit),
      }
    },

    listRevisions() {
      return {
        run_id: state.runId,
        current_revision: state.globalRevision,
        revisions: state.history.map((h) => ({
          revision: h.revision,
          status: h.status,
          current_stage: h.current_stage,
          updated_at: h.updated_at,
        })),
      }
    },

    getRevision(_runId: string, revision: number): WorkflowState {
      const wf = this.getWorkflow(state.runId)
      return { ...wf, revision }
    },

    async startSimulation(): Promise<ActionReceipt> {
      if (state.simulationRunning) {
        return receipt('startSimulation', null, false, '模拟执行已在进行中')
      }
      state.simulationRunning = true
      state.workflowStatus = 'running'
      state.stages = {
        data_fetch: { status: 'running', revision: 1, produced: false },
        data_interpret: { status: 'pending', revision: 1, produced: false },
        chart_generate: { status: 'pending', revision: 1, produced: false },
        chapter_write: { status: 'pending', revision: 1, produced: false },
        report_fusion: { status: 'pending', revision: 1, produced: false },
      }
      const order: StageName[] = [
        'data_fetch',
        'data_interpret',
        'chart_generate',
        'chapter_write',
        'report_fusion',
      ]
      for (let i = 0; i < order.length; i += 1) {
        const stage = order[i]!
        state.simulationPhase = i + 1
        state.stages[stage] = {
          status: 'running',
          revision: state.globalRevision,
          produced: false,
        }
        await delay(MOCK_DELAY_MS)
        state.stages[stage] = {
          status: 'waiting_review',
          revision: state.globalRevision,
          produced: true,
        }
        state.selectedStage = stage
      }
      // 演示：从可审核的完整状态重新装入对象（模拟生成后回到可操作 fixture）
      state.evidences = cloneEvidence()
      state.claims = cloneClaims()
      state.charts = cloneCharts()
      state.chapters = cloneChapters()
      state.artifacts = cloneArtifacts(state.reportSettings)
      state.risks = cloneRisks()
      state.workflowStatus = 'waiting_review'
      state.selectedStage = 'chart_generate'
      state.simulationRunning = false
      state.simulationPhase = 0
      const rec = receipt(
        'startSimulation',
        state.runId,
        true,
        '模拟生成完成，五个阶段进入可审核状态',
        [],
        true
      )
      pushHistory('模拟生成完成')
      this.persist()
      return rec
    },

    selectStage(stage: StageName): ActionReceipt {
      const s = state.stages[stage]
      if (!s?.produced) {
        return receipt('selectStage', stage, false, '该阶段尚未产出，无法切换查看')
      }
      state.selectedStage = stage
      state.selectedObjectId = null
      return receipt('selectStage', stage, true, `已切换到 ${stage}`)
    },

    selectObject(objectId: string | null): ActionReceipt {
      state.selectedObjectId = objectId
      return receipt(
        'selectObject',
        objectId,
        true,
        objectId ? `已选中 ${objectId}` : '已取消选中对象'
      )
    },

    async excludeEvidence(evidenceId: string, reason: string): Promise<ActionReceipt> {
      await delay(MOCK_DELAY_MS)
      const ev = findEvidence(evidenceId)
      if (!ev) return receipt('excludeEvidence', evidenceId, false, '证据不存在')
      if (ev.status === 'excluded')
        return receipt('excludeEvidence', evidenceId, false, '证据已是排除状态')
      ev.status = 'excluded'
      ev.exclude_reason = reason
      const affected = propagateEvidenceExclusion(evidenceId)
      const rec = receipt(
        'excludeEvidence',
        evidenceId,
        true,
        `已排除 ${evidenceId}（${reason}）`,
        affected,
        true
      )
      this.persist()
      return rec
    },

    async restoreEvidence(evidenceId: string): Promise<ActionReceipt> {
      await delay(MOCK_DELAY_MS)
      const ev = findEvidence(evidenceId)
      if (!ev) return receipt('restoreEvidence', evidenceId, false, '证据不存在')
      if (ev.status === 'active')
        return receipt('restoreEvidence', evidenceId, false, '证据已是启用状态')
      ev.status = 'active'
      ev.exclude_reason = null
      const affected = restoreEvidencePropagation(evidenceId)
      const rec = receipt(
        'restoreEvidence',
        evidenceId,
        true,
        `已恢复 ${evidenceId}`,
        affected,
        true
      )
      this.persist()
      return rec
    },

    async rejectClaim(claimId: string, reason: string): Promise<ActionReceipt> {
      await delay(MOCK_DELAY_MS)
      const claim = findClaim(claimId)
      if (!claim) return receipt('rejectClaim', claimId, false, '结论不存在')
      claim.status = 'rejected'
      claim.reject_reason = reason
      const rec = receipt('rejectClaim', claimId, true, `已驳回 ${claimId}（${reason}）`, [], true)
      this.persist()
      return rec
    },

    async restoreClaim(claimId: string): Promise<ActionReceipt> {
      await delay(MOCK_DELAY_MS)
      const claim = findClaim(claimId)
      if (!claim) return receipt('restoreClaim', claimId, false, '结论不存在')
      claim.status = 'active'
      claim.reject_reason = null
      const rec = receipt('restoreClaim', claimId, true, `已恢复 ${claimId}`, [], true)
      this.persist()
      return rec
    },

    /** 演示：按用户指令重新生成本条结论（固定延迟后恢复为有效，版本号+1 体现在 globalRevision） */
    async regenerateClaim(claimId: string, instruction = ''): Promise<ActionReceipt> {
      await delay(MOCK_DELAY_MS)
      const claim = findClaim(claimId)
      if (!claim) return receipt('regenerateClaim', claimId, false, '结论不存在')
      claim.status = 'provisional'
      await delay(MOCK_DELAY_MS)
      claim.status = 'active'
      claim.reject_reason = null
      const hint = instruction.trim()
      const rec = receipt(
        'regenerateClaim',
        claimId,
        true,
        hint
          ? `已按指令重新生成结论 ${claimId}：${hint.slice(0, 40)}${hint.length > 40 ? '…' : ''}`
          : `已重新生成结论 ${claimId}`,
        [claimId],
        true
      )
      this.persist()
      return rec
    },

    async markClaimEvidenceInsufficient(claimId: string): Promise<ActionReceipt> {
      await delay(MOCK_DELAY_MS)
      const claim = findClaim(claimId)
      if (!claim) return receipt('markClaimEvidenceInsufficient', claimId, false, '结论不存在')
      claim.status = 'evidence_insufficient'
      const rec = receipt(
        'markClaimEvidenceInsufficient',
        claimId,
        true,
        `已标记证据不足 ${claimId}`,
        [],
        true
      )
      this.persist()
      return rec
    },

    async updateChartTitle(chartId: string, title: string): Promise<ActionReceipt> {
      const chart = findChart(chartId)
      if (!chart) return receipt('updateChartTitle', chartId, false, '图表不存在')
      chart.title = title
      chart.unit_revision += 1
      const rec = receipt(
        'updateChartTitle',
        chartId,
        true,
        `已更新标题 ${chartId}`,
        [chartId],
        true
      )
      this.persist()
      return rec
    },

    async changeChartTemplate(chartId: string, template: string): Promise<ActionReceipt> {
      const chart = findChart(chartId)
      if (!chart) return receipt('changeChartTemplate', chartId, false, '图表不存在')
      if (!chart.compatible_templates.includes(template)) {
        return receipt('changeChartTemplate', chartId, false, '模板与该图数据不兼容')
      }
      chart.template = template
      if (chart.render_mode === 'echarts' && chart.option) {
        // 模板切换：仅调整标题区示意，数据固定
        const opt = { ...chart.option } as Record<string, unknown>
        opt.title = {
          text: `${chart.title} · ${template}`,
          left: 4,
          textStyle: { fontSize: 13 },
        }
        chart.option = opt
      }
      chart.unit_revision += 1
      const rec = receipt(
        'changeChartTemplate',
        chartId,
        true,
        `已切换模板 ${chartId} → ${template}`,
        [chartId],
        true
      )
      this.persist()
      return rec
    },

    async changeChartColor(chartId: string, theme: string): Promise<ActionReceipt> {
      const chart = findChart(chartId)
      if (!chart) return receipt('changeChartColor', chartId, false, '图表不存在')
      chart.color_theme = theme
      chart.unit_revision += 1
      const rec = receipt(
        'changeChartColor',
        chartId,
        true,
        `已切换配色 ${chartId} → ${theme}`,
        [chartId],
        true
      )
      this.persist()
      return rec
    },

    async regenerateChart(chartId: string): Promise<ActionReceipt> {
      const chart = findChart(chartId)
      if (!chart) return receipt('regenerateChart', chartId, false, '图表不存在')
      if (chart.status === 'deleted')
        return receipt('regenerateChart', chartId, false, '已删除图表不可重生成')
      chart.status = 'running'
      await delay(CHART_REGEN_MS)
      chart.unit_revision += 1
      chart.status = 'active'
      const rec = receipt(
        'regenerateChart',
        chartId,
        true,
        `已重新生成 ${chartId}（unitRevision=${chart.unit_revision}）`,
        [chartId],
        true
      )
      this.persist()
      return rec
    },

    toggleChartInReport(chartId: string): ActionReceipt {
      const chart = findChart(chartId)
      if (!chart || chart.status === 'deleted') {
        return receipt('toggleChartInReport', chartId, false, '图表不可用')
      }
      chart.in_report = !chart.in_report
      const rec = receipt(
        'toggleChartInReport',
        chartId,
        true,
        chart.in_report ? `已纳入报告 ${chartId}` : `已移出报告 ${chartId}`,
        [chartId],
        true
      )
      this.persist()
      return rec
    },

    deleteChart(chartId: string): ActionReceipt {
      const chart = findChart(chartId)
      if (!chart) return receipt('deleteChart', chartId, false, '图表不存在')
      chart.status = 'deleted'
      chart.in_report = false
      const rec = receipt(
        'deleteChart',
        chartId,
        true,
        `已删除 ${chartId}，可撤销`,
        [chartId],
        true
      )
      this.persist()
      return rec
    },

    /** 章节级重新生成：模拟按用户指令重写章节，段落进入待复核状态。 */
    async regenerateChapter(chapterId: string, instruction: string): Promise<ActionReceipt> {
      const chapter = findChapter(chapterId)
      if (!chapter) return receipt('regenerateChapter', chapterId, false, '章节不存在')
      for (const section of chapter.sections) {
        for (const paragraph of section.paragraphs) {
          paragraph.version += 1
          paragraph.status = 'provisional'
        }
      }
      const hint = instruction.trim()
      chapter.upstream_hint = hint
        ? `重生成指令：${hint.slice(0, 60)}${hint.length > 60 ? '…' : ''}`
        : '已按默认条件重新生成'
      const rec = receipt(
        'regenerateChapter',
        chapterId,
        true,
        hint ? `已按指令重新生成章节 ${chapterId}` : `已重新生成章节 ${chapterId}`,
        [chapterId],
        true
      )
      this.persist()
      return rec
    },

    deleteChapter(chapterId: string): ActionReceipt {
      const index = state.chapters.findIndex((c) => c.chapter_id === chapterId)
      if (index < 0) return receipt('deleteChapter', chapterId, false, '章节不存在')
      state.chapters.splice(index, 1)
      const rec = receipt(
        'deleteChapter',
        chapterId,
        true,
        `已删除章节并移出报告 ${chapterId}`,
        [chapterId],
        true
      )
      this.persist()
      return rec
    },

    restoreDeletedChart(chartId: string): ActionReceipt {
      const chart = findChart(chartId)
      if (!chart) return receipt('restoreDeletedChart', chartId, false, '图表不存在')
      chart.status = 'active'
      chart.in_report = true
      const rec = receipt(
        'restoreDeletedChart',
        chartId,
        true,
        `已撤销删除 ${chartId}`,
        [chartId],
        true
      )
      this.persist()
      return rec
    },

    updateParagraph(paragraphId: string, text: string): ActionReceipt {
      const found = findParagraph(paragraphId)
      if (!found) return receipt('updateParagraph', paragraphId, false, '段落不存在')
      const p = found.paragraph
      p.history = [...p.history, { version: p.version, text: p.text }]
      const before = p.text
      p.text = text
      p.version += 1
      p.diff = buildDiff(before, text)
      const rec = receipt(
        'updateParagraph',
        paragraphId,
        true,
        `已保存段落 ${paragraphId}`,
        [paragraphId],
        true
      )
      this.persist()
      return rec
    },

    restoreParagraph(paragraphId: string): ActionReceipt {
      const found = findParagraph(paragraphId)
      if (!found) return receipt('restoreParagraph', paragraphId, false, '段落不存在')
      const p = found.paragraph
      if (p.history.length === 0)
        return receipt('restoreParagraph', paragraphId, false, '没有可恢复的历史版本')
      const prev = p.history[p.history.length - 1]!
      const before = p.text
      p.text = prev.text
      p.version += 1
      p.history = p.history.slice(0, -1)
      p.diff = buildDiff(before, p.text)
      const rec = receipt(
        'restoreParagraph',
        paragraphId,
        true,
        `已恢复段落 ${paragraphId}`,
        [paragraphId],
        true
      )
      this.persist()
      return rec
    },

    updateReportSettings(patch: Partial<ReportSettings>): ActionReceipt {
      state.reportSettings = { ...state.reportSettings, ...patch }
      const rec = receipt(
        'updateReportSettings',
        null,
        true,
        `已更新报告设置：${JSON.stringify(patch)}`,
        [],
        true
      )
      this.persist()
      return rec
    },

    generateArtifacts(): ActionReceipt {
      state.artifacts = cloneArtifacts(state.reportSettings).map((a, idx) => ({
        ...a,
        revision: state.globalRevision,
        artifact_id: a.artifact_id,
        content:
          a.kind === 'report_markdown'
            ? cloneArtifacts(state.reportSettings)[0]!.content
            : a.content + `\n演示生成标记 ${state.globalRevision}-${idx + 1}\n`,
        generated_at_label: FIXED_NOW,
      }))
      // 按设置过滤格式
      const wanted = new Set(state.reportSettings.formats)
      state.artifacts = state.artifacts.filter((a) => {
        if (a.kind === 'report_markdown') return wanted.has('markdown')
        if (a.kind === 'report_html') return wanted.has('html')
        if (a.kind === 'report_pdf') return wanted.has('pdf')
        return true
      })
      const rec = receipt(
        'generateArtifacts',
        null,
        true,
        `已生成模拟产物：${state.reportSettings.formats.join(', ')}`,
        state.artifacts.map((a) => a.artifact_id),
        true
      )
      this.persist()
      return rec
    },

    async approveStage(stage: StageName): Promise<ActionReceipt> {
      await delay(MOCK_DELAY_MS)
      const unacked = state.risks.filter(
        (r) => r.stage === stage && r.requires_ack && !r.acknowledged
      )
      if (unacked.length > 0) {
        return receipt(
          'approveStage',
          stage,
          false,
          `风险未确认：${unacked.map((r) => r.risk_code).join(', ')}`,
          unacked.map((r) => r.risk_code)
        )
      }
      const stages = [
        'data_fetch',
        'data_interpret',
        'chart_generate',
        'chapter_write',
        'report_fusion',
      ] as StageName[]
      const idx = stages.indexOf(stage)
      state.stages[stage] = { ...state.stages[stage]!, status: 'approved', produced: true }
      const next = stages[idx + 1]
      if (next) {
        state.stages[next] = { ...state.stages[next]!, status: 'waiting_review', produced: true }
        state.selectedStage = next
      } else {
        state.workflowStatus = 'completed'
        state.stages.report_fusion = {
          status: 'completed',
          revision: state.globalRevision,
          produced: true,
        }
      }
      const rec = receipt(
        'approveStage',
        stage,
        true,
        `已通过阶段 ${stage}`,
        next ? [next] : [],
        true
      )
      pushHistory(`通过 ${stage}`)
      this.persist()
      return rec
    },

    async returnStage(stage: StageName, note: string): Promise<ActionReceipt> {
      await delay(MOCK_DELAY_MS)
      state.stages[stage] = {
        ...state.stages[stage]!,
        status: 'waiting_review',
        produced: true,
      }
      state.workflowStatus = 'waiting_review'
      const rec = receipt('returnStage', stage, true, `已退回阶段 ${stage}：${note}`, [stage], true)
      this.persist()
      return rec
    },

    acknowledgeRisk(riskCode: string): ActionReceipt {
      const risk = state.risks.find((r) => r.risk_code === riskCode)
      if (!risk) return receipt('acknowledgeRisk', riskCode, false, '风险项不存在')
      risk.acknowledged = true
      const rec = receipt(
        'acknowledgeRisk',
        riskCode,
        true,
        `已确认风险 ${riskCode}`,
        [riskCode],
        true
      )
      this.persist()
      return rec
    },

    getRiskItems(): RiskItem[] {
      return state.risks
    },

    getEvidence(): EvidenceItem[] {
      return state.evidences
    },

    getClaims(): ClaimItem[] {
      return state.claims
    },

    getCharts(): ChartItem[] {
      return state.charts
    },

    getChapters(): ChapterItem[] {
      return state.chapters
    },

    getArtifacts(): ArtifactItem[] {
      return state.artifacts
    },

    getDownloadBlob(artifactId: string): Blob | null {
      const art = state.artifacts.find((a) => a.artifact_id === artifactId)
      if (!art) return null
      const notice = `演示产物 · ${DEMO_TITLE} · ${DEMO_RUN_ID}｜演示数据，不代表真实研究结论`
      if (art.kind === 'report_html') {
        /*
         * HTML 不能在 <!doctype> 之前拼纯文本：
         * 浏览器会把这段文字当成正文渲染到页面最上方（报告封面之上多出一行），
         * 且前置文本还可能触发怪异模式。改成注入 HTML 注释——文档结构合法，
         * 演示声明仍在源码里可见。
         */
        const html = /<!doctype html>/i.test(art.content)
          ? art.content.replace(/<!doctype html>/i, `<!doctype html>\n<!-- ${notice} -->`)
          : `<!-- ${notice} -->\n${art.content}`
        return new Blob([html], { type: 'text/html;charset=utf-8' })
      }
      return new Blob([`${notice}\n\n${art.content}`], {
        type: 'text/plain;charset=utf-8',
      })
    },
  }
}

function buildDiff(
  before: string,
  after: string
): { before: string; after: string; lines: string[] } {
  const beforeLines = before.split(/\n/)
  const afterLines = after.split(/\n/)
  const lines: string[] = []
  const max = Math.max(beforeLines.length, afterLines.length)
  for (let i = 0; i < max; i += 1) {
    const b = beforeLines[i]
    const a = afterLines[i]
    if (b === a) {
      if (a !== undefined) lines.push(`  ${a}`)
    } else {
      if (b !== undefined) lines.push(`- ${b}`)
      if (a !== undefined) lines.push(`+ ${a}`)
    }
  }
  return { before, after, lines }
}

export function isMockMode(): boolean {
  return import.meta.env.VITE_DATA_MODE === 'mock'
}

/** 模块加载时自动 hydrate（真实模式下不调用） */
export function ensurePrototypeHydrated(): void {
  const store = usePrototypeStore()
  store.hydrate()
}
