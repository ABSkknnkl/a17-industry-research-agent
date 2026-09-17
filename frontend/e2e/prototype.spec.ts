import { expect, test } from '@playwright/test'

function isBackendApi(url: string): boolean {
  try {
    const u = new URL(url)
    return u.pathname.startsWith('/api/')
  } catch {
    return false
  }
}

test.describe('原型 Mock 模式', () => {
  test('无后端时打开首页并进入演示工作台，且不发起 /api 请求', async ({ page }) => {
    const apiRequests: string[] = []
    page.on('request', (req) => {
      if (isBackendApi(req.url())) apiRequests.push(req.url())
    })

    await page.goto('/')
    await expect(page.getByTestId('home-demo-tag')).toBeVisible()
    await expect(page.getByTestId('demo-mode-badge')).toBeVisible()

    await page.getByRole('button', { name: /创建任务并启动流水线/ }).click()
    await page.waitForURL(/\/runs\/mock-amd-001/)
    await expect(page.getByTestId('workbench-demo-tag')).toBeVisible()
    await expect(page.getByTestId('btn-approve')).toBeVisible()
    expect(apiRequests).toEqual([])
  })

  test('阶段切换、图表控制与受限对话框', async ({ page }) => {
    const apiRequests: string[] = []
    page.on('request', (req) => {
      if (isBackendApi(req.url())) apiRequests.push(req.url())
    })

    await page.goto('/runs/mock-amd-001')
    await expect(page.getByTestId('review-actions')).toBeVisible()

    // 切换到数据采集
    await page.getByTestId('stage-step-data_fetch').click()
    await expect(page.getByTestId('evidence-review-table')).toBeVisible()

    // 图表页（右栏标签）
    await page.goto('/runs/mock-amd-001')
    await page.getByRole('tab', { name: /图表/ }).click()
    await expect(page.getByTestId('chart-gallery')).toBeVisible()

    // 受限对话框拒绝删除
    await page.getByTestId('btn-revise').click()
    await page.getByTestId('intent-comment').fill('删除这张图')
    await expect(page.getByTestId('intent-reject')).toBeVisible()

    // 关闭后合法意图可预览
    await page.getByTestId('intent-comment').fill('保留封装约束表述')
    await page.getByTestId('intent-preview-btn').click()
    await expect(page.getByTestId('intent-preview')).toBeVisible()

    expect(apiRequests).toEqual([])
  })

  test('重置演示恢复初始状态', async ({ page }) => {
    await page.goto('/runs/mock-amd-001')
    await expect(page.getByTestId('btn-reset-demo')).toBeVisible()
    // Popconfirm 确认
    await page.getByTestId('btn-reset-demo').click()
    await page
      .locator('.el-popconfirm')
      .getByRole('button')
      .filter({ hasText: /确/ })
      .first()
      .click()
    await expect(page.getByTestId('workbench-demo-tag')).toBeVisible()
  })

  test('900px 视口无水平滚动', async ({ page }) => {
    await page.setViewportSize({ width: 900, height: 1000 })
    await page.goto('/runs/mock-amd-001')
    await expect(page.getByTestId('workbench-demo-tag')).toBeVisible()
    const overflow = await page.evaluate(() => {
      return document.documentElement.scrollWidth - document.documentElement.clientWidth
    })
    expect(overflow).toBeLessThanOrEqual(1)
  })
})
