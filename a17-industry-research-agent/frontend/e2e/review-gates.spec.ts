import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'
import type { ReviewRequest, WorkflowState } from '../src/api/types'

/**
 * 人机审核门禁回归（方案 §6.4）
 *
 * 只替换 HTTP 边界：路由、审核视图、弹窗、控件、请求构造与响应处理全部是真实实现。
 * 状态由 e2e/fixtures/review-cases/*.json 的问题数据注入，与 mock 服务器同一套用例，
 * 保证「字段缺失 / 格式错误 / 数据冲突 / 审核状态异常」四类问题在 CI 里可重复验证。
 */

const CASE_DIR = resolve(dirname(fileURLToPath(import.meta.url)), 'fixtures/review-cases')

type Case = {
  case_id: string
  mock_review_stage: string
  state_patch: Record<string, unknown>
}

function loadCase(prefix: string): Case {
  const files = readFileSync(resolve(CASE_DIR, `${prefix}.json`), 'utf-8')
  return JSON.parse(files) as Case
}

/** RFC 7386 JSON Merge Patch：null 表示删键，与 mock 服务器 review_gates.merge_patch 一致 */
function mergePatch(target: unknown, patch: unknown): unknown {
  if (patch === null || typeof patch !== 'object' || Array.isArray(patch)) {
    return patch === null ? undefined : structuredClone(patch)
  }
  const base =
    target && typeof target === 'object' && !Array.isArray(target)
      ? (structuredClone(target) as Record<string, unknown>)
      : {}
  for (const [key, value] of Object.entries(patch as Record<string, unknown>)) {
    if (value === null) delete base[key]
    else base[key] = mergePatch(base[key], value)
  }
  return base
}

/** 新能源汽车真实产出的字段形状（英文名 + 元 + 小数增速 + insight_id） */
function baseState(stage: string): WorkflowState {
  const stageResults: WorkflowState['stage_results'] = {}
  const order = ['data_fetch', 'data_interpret', 'chart_generate', 'chapter_write', 'report_fusion']
  for (const name of order) {
    const index = order.indexOf(name)
    const target = order.indexOf(stage)
    stageResults[name] = {
      stage: name,
      status: index < target ? 'approved' : index === target ? 'waiting_review' : 'pending',
      revision: 1,
      artifacts: [],
      evidence_sources: [],
      error: null,
      data: {},
    }
  }
  stageResults.data_fetch!.data = {
    total_records: 373,
    keywords: ['新能源汽车'],
    source_records: [
      {
        record_id: 'R-nev-01',
        entity: '比亚迪',
        metric: '营业收入',
        value: 803964958000,
        unit: '元',
        period: '2025-12-31',
        skill_name: '财务数据',
      },
    ],
    metric_requirements: [],
  }
  stageResults.data_interpret!.data = {
    insights: [
      {
        insight_id: 'I-NEV-01',
        title: '2021—2025 年全国新能源汽车销量增长',
        conclusion: '中国新能源汽车销量 2025 年为 1649.00 万辆。',
        significance: '年度数量与同比增速分别解读。',
        confidence: 'high',
        evidence_record_ids: ['R-nev-01', 'R-nev-02'],
      },
    ],
    key_metrics: [
      {
        metric_id: 'K-nev-01',
        name: 'revenue',
        entity: '比亚迪',
        value: 803964958000,
        unit: '元',
        change_pct: 0.03456,
        evidence_record_ids: ['R-nev-01'],
      },
    ],
    comps_matrix: {
      entries: [
        {
          company_name: '比亚迪',
          company_code: '002594',
          valuation_tier: 'profitable',
          market_cap: null,
          pe_ttm: null,
          evidence_record_ids: [],
        },
      ],
      currency: 'CNY',
    },
  }
  stageResults.report_fusion!.data = {
    title: '新能源汽车行业研究报告',
    exports_stale: false,
    built_at_revision: 1,
    key_metrics: stageResults.data_interpret!.data.key_metrics,
    data_interpret: {
      executive_summary: '本报告按五道研究问题比较新能源汽车销量、出口与零售渗透率。',
    },
  }
  return {
    project_id: 'review-gates',
    run_id: 'gate-run',
    current_stage: stage,
    status: 'waiting_review',
    revision: 1,
    created_at: '2026-11-18T00:00:00Z',
    updated_at: '2026-11-18T00:00:00Z',
    stage_results: stageResults,
  } as WorkflowState
}

type Harness = {
  submitted: ReviewRequest[]
  unexpected: string[]
}

/**
 * 决策包在生产由 expose_current_review 读时注入、mock 由 review_gates 注入，
 * 归档 state 里没有。这里镜像同一口径，否则硬阻塞门禁在测试里不会生效。
 */
function exposeDecisionPackage(state: WorkflowState) {
  if (state.status !== 'waiting_review') return
  const result = state.stage_results[state.current_stage]
  if (!result || result.status !== 'waiting_review') return
  const risks = ((result.data?.risks as Array<Record<string, unknown>>) ?? []).filter(Boolean)
  const blocking = risks.filter((r) => r.blocking === true).map((r) => String(r.code))
  const ack = risks.filter((r) => r.blocking !== true).map((r) => String(r.code))
  result.data = {
    ...result.data,
    decision_package: {
      run_id: state.run_id,
      stage: state.current_stage,
      revision: state.revision,
      risks,
      blocking_risk_codes: blocking.sort(),
      acknowledgement_required_codes: ack.sort(),
      recommended_action: blocking.length
        ? 'blocked'
        : ack.length
          ? 'accept_with_risks'
          : 'approve',
      decision_id: `dec_${state.current_stage}_${state.revision}`,
      risk_snapshot_sha256: `sha_${state.current_stage}_${state.revision}`,
    },
  }
}

/** 装载路由：注入问题数据、按需返回 409、记录所有提交 */
async function mount(
  page: import('@playwright/test').Page,
  caseId: string,
  options: { rejectWith?: { status: number; detail: string } } = {}
): Promise<Harness> {
  const fixture = loadCase(caseId)
  const stage = fixture.mock_review_stage
  let workflow = mergePatch(baseState(stage), fixture.state_patch) as WorkflowState
  exposeDecisionPackage(workflow)
  const harness: Harness = { submitted: [], unexpected: [] }

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/reviews') && route.request().method() === 'POST') {
      const body = route.request().postDataJSON() as ReviewRequest
      harness.submitted.push(body)
      if (options.rejectWith) {
        await route.fulfill({
          status: options.rejectWith.status,
          json: { detail: options.rejectWith.detail },
        })
        return
      }
      const current = workflow.stage_results[workflow.current_stage]!
      workflow = {
        ...workflow,
        revision: workflow.revision + 1,
        stage_results: {
          ...workflow.stage_results,
          [workflow.current_stage]: {
            ...current,
            revision: workflow.revision + 1,
            data: { ...current.data, ...(body.edited_data ?? {}) },
          },
        },
      }
      await route.fulfill({ json: workflow })
    } else if (path.endsWith('/runs/gate-run')) {
      await route.fulfill({ json: workflow })
    } else if (path.endsWith('/revisions')) {
      await route.fulfill({
        json: { run_id: 'gate-run', current_revision: workflow.revision, revisions: [] },
      })
    } else if (
      path.endsWith('/events') ||
      path.endsWith('/events/summary') ||
      path.endsWith('/feedback-history')
    ) {
      await route.fulfill({ json: path.endsWith('/summary') ? { total: 0 } : [] })
    } else if (path.endsWith('/runs')) {
      await route.fulfill({ json: { items: [], total: 0, offset: 0, limit: 100 } })
    } else {
      harness.unexpected.push(`${route.request().method()} ${path}`)
      await route.fulfill({ json: {} })
    }
  })
  await page.goto('/runs/gate-run')
  return harness
}

/** 弹窗内切换 tab：Element Plus 渲染成 role=tab，不是 button */
async function switchTab(dialog: import('@playwright/test').Locator, label: string) {
  await dialog.locator('.el-tabs__item').filter({ hasText: label }).first().click()
}

test('T01 字段缺失：研判区空态、保存禁用且零请求，不得回落内置样例', async ({ page }) => {
  const harness = await mount(page, 'T01-interpret-fields-missing')
  await page.getByRole('button', { name: '补充背景知识与修正判断' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByTestId('judgments-empty')).toBeVisible()
  await expect(dialog.getByTestId('save-judgments')).toBeDisabled()
  await expect(dialog).not.toContainText('产业处于高景气周期与出海放量红利期')
  await expect(dialog).not.toContainText('J-1')
  await dialog.getByTestId('save-judgments').click({ force: true })
  expect(harness.submitted).toEqual([])
})

test('T02 证据缺失：补采清单空态、启动按钮禁用，不得出现硬编码假点', async ({ page }) => {
  const harness = await mount(page, 'T02-source-records-missing')
  await page.getByRole('button', { name: '定向补采' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByTestId('refetch-empty')).toBeVisible()
  await expect(dialog.getByRole('button', { name: '启动定向补采' })).toBeDisabled()
  for (const fake of ['F-01', '样本龙头甲', '1,342', '21.4%']) {
    await expect(dialog).not.toContainText(fake)
  }
  expect(harness.submitted).toEqual([])
})

test('T04 格式错误：非法估值禁用保存并提示，清空后归一为 null 而非 0', async ({ page }) => {
  const harness = await mount(page, 'T04-comps-format-error')
  await page.getByRole('button', { name: '补充背景知识与修正判断' }).click()
  const dialog = page.getByRole('dialog')
  await switchTab(dialog, '可比公司标的池调整')
  const save = dialog.getByTestId('save-comps')
  await expect(save).toBeDisabled()
  await expect(dialog).toContainText('公司名称不能为空')
  await save.click({ force: true })
  expect(harness.submitted).toEqual([])

  // 修正为合法：补公司名、把非法文本清空（留空表示缺失）
  const rows = dialog.locator('.el-table__body tbody tr')
  for (const [index, name] of ['比亚迪', '赛力斯'].entries()) {
    const cells = rows.nth(index).locator('input')
    await cells.nth(0).fill(name)
    await cells.nth(2).fill('')
    await cells.nth(3).fill('')
  }
  await expect(save).toBeEnabled()
  await save.click()
  const entries = harness.submitted.at(-1)?.edited_data?.comps_matrix?.entries as Array<
    Record<string, unknown>
  >
  expect(entries).toHaveLength(2)
  for (const entry of entries) {
    expect(entry.market_cap).toBeNull()
    expect(entry.pe_ttm).toBeNull()
  }
})

test('T07 硬阻塞：不渲染通过入口，展示阻断项明细', async ({ page }) => {
  await mount(page, 'T07-blocking-risk')
  const main = page.locator('main')
  await expect(main).toContainText('待处理的阻断项')
  await expect(main).toContainText('核心营收证据缺少可核验来源')
  await expect(page.getByRole('button', { name: '确认数据完备，进入解读分析' })).toHaveCount(0)
})

test('T05 版本冲突：409 后弹窗保留、表单不丢、给出可读提示', async ({ page }) => {
  const harness = await mount(page, 'T05-revision-conflict', {
    rejectWith: { status: 409, detail: 'Revision conflict: expected 1, current 5' },
  })
  await page.getByRole('button', { name: '补充背景知识与修正判断' }).click()
  const dialog = page.getByRole('dialog')
  await switchTab(dialog, '可比公司标的池调整')
  const firstRow = dialog.locator('.el-table__body tbody tr').first()
  await firstRow.locator('input').nth(0).fill('冲突保留验证')
  await dialog.getByTestId('save-comps').click()
  await expect(page.locator('.el-message').first()).toContainText('Revision conflict')
  await expect(dialog).toBeVisible()
  await expect(
    dialog.locator('.el-table__body tbody tr').first().locator('input').nth(0)
  ).toHaveValue('冲突保留验证')
  expect(harness.submitted).toHaveLength(1)
})

test('T10 摘要防覆盖：只改评级时不得下发 executive_summary', async ({ page }) => {
  const harness = await mount(page, 'T10-empty-summary-overwrite')
  await page.getByRole('button', { name: '投资评级与执行摘要定稿' }).click()
  const dialog = page.getByRole('dialog')
  // 取不到任何摘要来源时必须只读，且提交不得携带该键（否则后端会写成 headline:''）
  await expect(dialog.getByTestId('summary-readonly-hint')).toBeVisible()
  await expect(dialog.getByTestId('summary-text')).toHaveAttribute('readonly', '')
  await dialog.getByTestId('save-summary-rating').click()
  expect(harness.submitted.length).toBeGreaterThan(0)
  const edited = harness.submitted.at(-1)?.edited_data ?? {}
  expect(Object.keys(edited)).not.toContain('executive_summary')
  expect(Object.keys(edited)).toContain('investment_rating')
})
