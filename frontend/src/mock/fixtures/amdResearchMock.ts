/**
 * 动力电池行业演示入口：聚合后端真实流水线抽取数据 + Workflow 映射。
 * 真实序列见 ./realBatteryData.ts（run b3f5732f-e86a-4a7e-a5a5-fede9c3af8f3）。
 */
import type {
  ArtifactItem,
  ChapterItem,
  ChartItem,
  ClaimItem,
  EvidenceItem,
  PrototypeRevision,
  ReportSettings,
  RiskItem,
  RunSummary,
  StageName,
  StageResult,
  StageStatus,
  WorkflowState,
} from '../../api/types'

export {
  CHART_REGEN_MS,
  DEMO_BANNER,
  DEMO_PROJECT_ID,
  DEMO_QUESTIONS,
  DEMO_RUN_ID,
  DEMO_TITLE,
  FIXED_CREATED_AT,
  FIXED_NOW,
  FIXTURE_VERSION,
  MOCK_DELAY_MS,
  REAL_RUN_ID,
  cloneArtifacts,
  cloneCharts,
  cloneChapters,
  cloneClaims,
  cloneEvidence,
  cloneRisks,
  defaultReportSettings,
} from './realBatteryData'

import {
  DEMO_BANNER,
  DEMO_PROJECT_ID,
  DEMO_RUN_ID,
  DEMO_TITLE,
  FIXED_CREATED_AT,
  FIXED_NOW,
} from './realBatteryData'

export function cloneHistory(): PrototypeRevision[] {
  return [
    {
      revision: 1,
      status: 'waiting_review',
      current_stage: 'data_fetch',
      updated_at: FIXED_CREATED_AT,
      note: '真实流水线：动力电池行业任务创建',
    },
    {
      revision: 2,
      status: 'waiting_review',
      current_stage: 'data_interpret',
      updated_at: '2026-01-15T09:40:00.000Z',
      note: '数据采集通过（接受装机/份额缺口）',
    },
    {
      revision: 3,
      status: 'waiting_review',
      current_stage: 'chart_generate',
      updated_at: FIXED_NOW,
      note: 'LLM 分析完成，进入图表/融合演示',
    },
  ]
}

/** 初始全局状态：全部 5 阶段已产出，停在 chart_generate 等待审核 */
export function initialStageMap(): Record<
  StageName,
  { status: StageStatus; revision: number; produced: boolean }
> {
  return {
    data_fetch: { status: 'approved', revision: 1, produced: true },
    data_interpret: { status: 'approved', revision: 2, produced: true },
    chart_generate: { status: 'waiting_review', revision: 3, produced: true },
    chapter_write: { status: 'waiting_review', revision: 3, produced: true },
    report_fusion: { status: 'waiting_review', revision: 3, produced: true },
  }
}

export function buildDemoRunSummary(): RunSummary {
  return {
    run_id: DEMO_RUN_ID,
    project_id: DEMO_PROJECT_ID,
    title: DEMO_TITLE,
    current_stage: 'chart_generate',
    status: 'waiting_review',
    revision: 3,
    created_at: FIXED_CREATED_AT,
    updated_at: FIXED_NOW,
    artifact_count: 3,
    report_available: true,
  }
}

export function buildExtraDemoRuns(): RunSummary[] {
  return [
    {
      run_id: 'mock-amd-002',
      project_id: DEMO_PROJECT_ID,
      title: '演示：储能电池配套材料研究',
      current_stage: 'data_fetch',
      status: 'completed',
      revision: 5,
      created_at: '2026-01-10T08:00:00.000Z',
      updated_at: '2026-01-12T08:00:00.000Z',
      artifact_count: 2,
      report_available: true,
    },
    {
      run_id: 'mock-amd-003',
      project_id: 'proj-ev-demo',
      title: '演示：新能源汽车整车竞争格局',
      current_stage: 'report_fusion',
      status: 'running',
      revision: 1,
      created_at: '2026-01-14T08:00:00.000Z',
      updated_at: FIXED_NOW,
      artifact_count: 0,
      report_available: false,
    },
  ]
}

/**
 * 模拟后端 chart_generate 的 display_size 布局分类（与 backend/service.py 规则一致）：
 * 数据点 >= 10 或 industry_chain 视为长图表 full（独占一行），否则 half（每行 2 个）。
 */
const DISPLAY_FULL_MIN_POINTS = 10

function mockDisplaySize(option?: Record<string, unknown>, chartType?: string): 'full' | 'half' {
  if (chartType === 'industry_chain') return 'full'
  const lengths: number[] = []
  const rawXAxis = option?.xAxis
  if (Array.isArray(rawXAxis)) {
    for (const axis of rawXAxis) {
      if (axis && Array.isArray((axis as { data?: unknown[] }).data)) {
        lengths.push((axis as { data: unknown[] }).data.length)
      }
    }
  } else if (rawXAxis && Array.isArray((rawXAxis as { data?: unknown[] }).data)) {
    lengths.push((rawXAxis as { data: unknown[] }).data.length)
  }
  for (const series of Array.isArray(option?.series)
    ? (option.series as Array<Record<string, unknown>>)
    : []) {
    if (series && Array.isArray(series.data)) lengths.push((series.data as unknown[]).length)
  }
  return Math.max(0, ...lengths) >= DISPLAY_FULL_MIN_POINTS ? 'full' : 'half'
}

/**
 * 章节 → 阶段数据形状。
 *
 * chapter_write 与 report_fusion 共用同一套映射，避免两处漂移：
 * 真实后端的 report_view（阶段五 data）同样带 chapters，供独立报告预览页的目录使用。
 * summary 由小节标题拼接，不编造正文内容。
 */
function toStageChapter(ch: ChapterItem) {
  return {
    chapter_id: ch.chapter_id,
    title: ch.title,
    summary: ch.sections.map((s) => s.title).join('；'),
    sections: ch.sections.map((s) => ({
      section_id: s.section_id,
      title: s.title,
      paragraphs: s.paragraphs.map((p) => ({
        text: p.text,
        paragraph_id: p.paragraph_id,
        version: p.version,
        status: p.status,
      })),
    })),
  }
}

export function buildWorkflowState(input: {
  runId: string
  currentStage: StageName
  status: StageStatus
  revision: number
  stages: Record<StageName, { status: StageStatus; revision: number; produced: boolean }>
  evidences: EvidenceItem[]
  claims: ClaimItem[]
  charts: ChartItem[]
  chapters: ChapterItem[]
  artifacts: ArtifactItem[]
  risks: RiskItem[]
  settings: ReportSettings
  createdAt?: string
  updatedAt?: string
}): WorkflowState {
  const { stages, evidences, claims, charts, chapters, artifacts, risks, settings } = input
  const stageResults: Partial<Record<StageName, StageResult>> = {}
  const evidenceSources = evidences.map((e) => e.evidence_id)

  stageResults.data_fetch = {
    stage: 'data_fetch',
    status: stages.data_fetch.status,
    revision: stages.data_fetch.revision,
    data: {
      source_records: evidences.map((e) => ({
        source_name: e.title,
        skill_name: e.source_type,
        as_of_date: e.as_of_date,
        row_count: 12 + e.evidence_id.charCodeAt(e.evidence_id.length - 1),
      })),
      intent_routing: {
        plans: {
          '装机量与增速趋势？': { requires_clarification: false, confidence: 0.72 },
          '三家市场份额对比？': { requires_clarification: false, confidence: 0.68 },
          '碳酸锂价格与成本影响？': { requires_clarification: false, confidence: 0.86 },
          '研发投入规模与费用率？': { requires_clarification: false, confidence: 0.84 },
        },
      },
      collaboration_requests: [],
      data_gaps: [
        {
          gap_id: 'GAP-INSTALL',
          description: '权威装机量序列未返回，以电池产量作代理并披露公开口径',
        },
      ],
      decision_package: {
        decision_id: 'DEC-FETCH-REAL-001',
        run_id: input.runId,
        revision: stages.data_fetch.revision,
        stage: 'data_fetch',
        risk_notices: risks
          .filter((r) => r.stage === 'data_fetch')
          .map((r) => ({ title: r.title, description: r.description })),
        acknowledgement_required_codes: risks
          .filter((r) => r.stage === 'data_fetch' && r.requires_ack && !r.acknowledged)
          .map((r) => r.risk_code),
      },
    },
    artifacts: [],
    evidence_sources: evidenceSources,
    error: null,
  }

  stageResults.data_interpret = {
    stage: 'data_interpret',
    status: stages.data_interpret.status,
    revision: stages.data_interpret.revision,
    data: {
      claims: claims.map((c) => ({
        claim_id: c.claim_id,
        statement: c.statement,
        evidence_ids: c.evidence_ids,
        dimension: c.dimension,
        confidence: 0.8,
      })),
      dimension_coverage: [
        { dimension: 'competition', status: 'partial' },
        { dimension: 'growth', status: 'partial' },
        { dimension: 'cost', status: 'supported' },
        { dimension: 'rd', status: 'supported' },
      ],
      risks: risks
        .filter((r) => r.stage === 'data_interpret')
        .map((r) => ({ risk_code: r.risk_code, description: r.description })),
      decision_package: {
        decision_id: 'DEC-INT-REAL-001',
        run_id: input.runId,
        revision: stages.data_interpret.revision,
        stage: 'data_interpret',
        risk_notices: risks
          .filter((r) => r.stage === 'data_interpret')
          .map((r) => ({ title: r.title, description: r.description })),
        acknowledgement_required_codes: risks
          .filter((r) => r.stage === 'data_interpret' && r.requires_ack && !r.acknowledged)
          .map((r) => r.risk_code),
      },
    },
    artifacts: [],
    evidence_sources: evidenceSources,
    error: null,
  }

  const activeCharts = charts.filter((c) => c.status !== 'deleted')
  stageResults.chart_generate = {
    stage: 'chart_generate',
    status: stages.chart_generate.status,
    revision: stages.chart_generate.revision,
    data: {
      charts: activeCharts.map((c) => ({
        chart_id: c.chart_id,
        chart_type: c.chart_type,
        title: c.title,
        rationale: c.insight_goal,
        status: c.status === 'running' ? 'running' : 'ready',
      })),
      chart_specs: activeCharts.map((c) => ({
        chart_id: c.chart_id,
        title: c.title,
        chart_type: c.chart_type,
        display_size: mockDisplaySize(c.option, c.chart_type),
        option: c.render_mode === 'echarts' ? c.option : undefined,
        render_mode: c.render_mode === 'svg' ? 'generated_image' : 'echarts',
        image_uri:
          c.render_mode === 'svg'
            ? `data:image/svg+xml;utf8,${encodeURIComponent(c.svg ?? '')}`
            : null,
        insight_goal: c.insight_goal,
        footnotes: [`${DEMO_BANNER} · unitRevision ${c.unit_revision}`],
        unit_revision: c.unit_revision,
        source_name: '演示证据源',
        updated_at: FIXED_NOW,
      })),
      decision_package: {
        decision_id: 'DEC-CHART-REAL-001',
        run_id: input.runId,
        revision: stages.chart_generate.revision,
        stage: 'chart_generate',
        risk_notices: risks
          .filter((r) => r.stage === 'chart_generate')
          .map((r) => ({ title: r.title, description: r.description })),
        acknowledgement_required_codes: risks
          .filter((r) => r.stage === 'chart_generate' && r.requires_ack && !r.acknowledged)
          .map((r) => r.risk_code),
      },
    },
    artifacts: activeCharts.map((c) => ({
      artifact_id: `ART-CHART-${c.chart_id}`,
      kind: 'chart',
      uri: `demo/charts/${c.chart_id}.json`,
      revision: c.unit_revision,
    })),
    evidence_sources: evidenceSources,
    error: null,
  }

  stageResults.chapter_write = {
    stage: 'chapter_write',
    status: stages.chapter_write.status,
    revision: stages.chapter_write.revision,
    data: {
      chapters: chapters.map(toStageChapter),
    },
    artifacts: [],
    evidence_sources: evidenceSources,
    error: null,
  }

  const included = charts.filter((c) => c.in_report && c.status !== 'deleted')
  stageResults.report_fusion = {
    stage: 'report_fusion',
    status: stages.report_fusion.status,
    revision: stages.report_fusion.revision,
    data: {
      report_id: 'RPT-REAL-001',
      title: DEMO_TITLE,
      industry_topic: '动力电池行业',
      research_as_of: '2026-01-15',
      generated_at: input.updatedAt ?? FIXED_NOW,
      tone: settings.tone === 'professional' ? 'professional' : 'plain_language',
      report_depth:
        settings.depth === 'brief' ? 'brief' : settings.depth === 'deep' ? 'deep' : 'standard',
      delivery_status: 'ready_with_limits',
      formats: settings.formats,
      included_chart_ids: included.map((c) => c.chart_id),
      artifacts: artifacts.map((a) => ({
        artifact_id: a.artifact_id,
        kind: a.kind,
        uri: a.uri,
        size_bytes: a.content.length,
      })),
      quality: {
        passed: true,
        chapter_count: chapters.length,
        section_count: chapters.reduce((n, c) => n + c.sections.length, 0),
        included_chart_count: included.length,
        evidence_coverage: 0.72,
        issues: ['装机量结构化序列缺口（REQUESTED-DATA-UNAVAILABLE）', DEMO_BANNER],
        // 评分基准（分母）由后端下发，前端不写死 7 / 21（与 REPORT_OUTLINE 对齐）
        expected_chapter_count: 7,
        expected_section_count: 21,
      },
      release_mode: 'draft_with_warnings',
      /*
       * 对齐真实后端 ReportFusionResult：
       * - chapters：前端目录按此**原样**渲染后端命名（FusionChapterOutline）
       * - outline_version：大纲版本，溯源用
       * - evidence_catalog：报告末尾来源清单，条数即「引用证据」指标
       */
      chapters: chapters.map(toStageChapter),
      outline_version: '2026.1',
      /*
       * 视觉编排决策：真实后端必填且实际下发，契约曾漏收该字段（已修）。
       * 取值对齐真实产物 report.html 的 <body class="visual-data-manual density-balanced">。
       */
      visual_decision: {
        recommended_style: 'data_manual',
        requested_style: 'auto',
        effective_style: 'data_manual',
        selection_source: 'agent_recommendation',
        density: 'balanced',
        chart_density: 'medium',
        table_priority: 'medium',
        recommendation_reasons: ['行业数据密集、图表与表格并重', '用户未指定视觉风格'],
        override_warnings: [],
        per_chapter_strategy: Object.fromEntries(
          chapters.map((c) => [
            c.chapter_id,
            {
              chart_count: 0,
              table_candidate_count: 0,
              dominant_content: 'narrative',
            },
          ])
        ),
      },
      evidence_catalog: evidences.map((e, idx) => ({
        citation_number: idx + 1,
        display_label: `来源${idx + 1}：${e.title}`,
        material_title: e.title,
        publishers: e.publisher ? [e.publisher] : [],
        evidence_ids: [e.evidence_id],
        available_dates: [e.as_of_date],
      })),
      disclaimer: '本报告仅用于行业研究与信息交流，不构成证券投资建议、收益保证或交易邀约。',
      methodology_note:
        '报告由数据解读智能体的结构化结论、图表智能体的已校验图表与章节撰写智能体的正文确定性组装；报告融合智能体不新增事实、不改写数据结论。',
      unresolved_risks: risks
        .filter((r) => r.requires_ack && !r.acknowledged)
        .map((r) => r.risk_code),
      source_revisions: [
        { stage: 'data_interpret', revision: stages.data_interpret.revision },
        { stage: 'chart_generate', revision: stages.chart_generate.revision },
        { stage: 'chapter_write', revision: stages.chapter_write.revision },
      ],
    },
    artifacts: artifacts.map((a) => ({
      artifact_id: a.artifact_id,
      kind: a.kind,
      uri: a.uri,
      revision: a.revision,
    })),
    evidence_sources: evidenceSources,
    error: null,
  }

  return {
    project_id: DEMO_PROJECT_ID,
    run_id: input.runId,
    current_stage: input.currentStage,
    status: input.status,
    revision: input.revision,
    stage_results: stageResults,
    created_at: input.createdAt ?? FIXED_CREATED_AT,
    updated_at: input.updatedAt ?? FIXED_NOW,
  }
}

export function buildStageResultPayload(
  stage: StageName,
  workflow: WorkflowState
): StageResult | null {
  return workflow.stage_results[stage] ?? null
}
