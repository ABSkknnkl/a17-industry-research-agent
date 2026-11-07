import { expect, test } from '@playwright/test'
import type { ReviewRequest, WorkflowState } from '../src/api/types'

// Only the HTTP boundary is replaced: the route, review view, dialog, controls,
// request construction, response handling, and reopened editor are real.
test('company edits retain production financial fields and evidence through save and reopen', async ({
  page,
}) => {
  let submitted: ReviewRequest | undefined
  const unexpectedRequests: string[] = []
  let workflow: WorkflowState = {
    project_id: 'browser-contract',
    run_id: 'browser-comps',
    current_stage: 'data_interpret',
    status: 'waiting_review',
    revision: 2,
    created_at: '2026-10-30T00:00:00Z',
    updated_at: '2026-10-30T00:00:00Z',
    stage_results: {
      data_interpret: {
        stage: 'data_interpret',
        status: 'waiting_review',
        revision: 2,
        artifacts: [],
        evidence_sources: ['R-browser'],
        error: null,
        data: {
          comps_matrix: {
            entries: [
              {
                company_name: '浏览器测试科技',
                company_code: '600001.SH',
                market_cap: 12,
                pe_ttm: 0,
                pb: 0,
                revenue: 150,
                net_profit: 0,
                evidence_record_ids: ['R-browser'],
                valuation_tier: 'loss_or_high_multiple',
                custom_note: '保留扩展字段',
              },
            ],
            currency: 'CNY',
            total_market_cap: 12,
            median_pe: 18,
          },
        },
      },
    },
  }
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path.endsWith('/runs/browser-comps/reviews') && route.request().method() === 'POST') {
      submitted = route.request().postDataJSON() as ReviewRequest
      workflow = {
        ...workflow,
        revision: 3,
        stage_results: {
          data_interpret: {
            ...workflow.stage_results.data_interpret!,
            revision: 3,
            data: { ...workflow.stage_results.data_interpret!.data, ...submitted.edited_data },
          },
        },
      }
      await route.fulfill({ json: workflow })
    } else if (path.endsWith('/runs/browser-comps')) {
      await route.fulfill({ json: workflow })
    } else if (path.endsWith('/revisions')) {
      await route.fulfill({
        json: { run_id: 'browser-comps', current_revision: workflow.revision, revisions: [] },
      })
    } else if (path.endsWith('/events') || path.endsWith('/feedback-history')) {
      await route.fulfill({ json: [] })
    } else if (path.endsWith('/runs')) {
      await route.fulfill({ json: { items: [], total: 0, offset: 0, limit: 100 } })
    } else {
      unexpectedRequests.push(`${route.request().method()} ${path}`)
      await route.abort()
    }
  })
  await page.goto('/runs/browser-comps')
  await page.getByRole('button', { name: '标的池与可比公司调整' }).click()
  const dialog = page.getByRole('dialog')
  const inputs = dialog.locator('.el-table input')
  await expect(inputs.nth(0)).toHaveValue('浏览器测试科技')
  await expect(inputs.nth(1)).toHaveValue('600001.SH')
  await expect(inputs.nth(3)).toHaveValue('0')
  await inputs.nth(0).fill('修订测试科技')
  await inputs.nth(2).fill('0')
  await dialog.getByRole('button', { name: '保存标的池调整', exact: false }).click()
  await expect(dialog).toBeHidden()
  expect(submitted).toMatchObject({
    run_id: 'browser-comps',
    stage: 'data_interpret',
    action: 'direct_edit',
    expected_revision: 2,
    edited_data: {
      comps_matrix: {
        entries: [
          {
            company_name: '修订测试科技',
            company_code: '600001.SH',
            market_cap: 0,
            pe_ttm: 0,
            pb: 0,
            revenue: 150,
            net_profit: 0,
            evidence_record_ids: ['R-browser'],
            valuation_tier: 'loss_or_high_multiple',
            custom_note: '保留扩展字段',
          },
        ],
        currency: 'CNY',
        total_market_cap: 0,
        median_pe: 18,
      },
    },
  })
  await page.getByRole('button', { name: '标的池与可比公司调整' }).click()
  await expect(dialog.locator('.el-table input').nth(0)).toHaveValue('修订测试科技')
  await expect(dialog.locator('.el-table input').nth(2)).toHaveValue('0')
  expect(unexpectedRequests).toEqual([])
})
