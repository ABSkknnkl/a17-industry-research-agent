/**
 * 真实前端全栈自动化运行脚本 (Playwright Live Frontend Runner)
 * 启动真实 Chromium 浏览器，访问 http://127.0.0.1:5173
 * 自动填写“固态电池”研究任务，点击创建并启动流水线，
 * 实时监控 5 大智能体真实执行过程、人机审核阶段放行并留存全程高清界面截图。
 */

const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const SCREENSHOT_DIR = path.resolve(__dirname, '../output/screenshots');
if (!fs.existsSync(SCREENSHOT_DIR)) {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
}

async function run() {
  console.log('================================================================================');
  console.log('🚀 启动前端真实全栈运行自动化器 (Playwright Live Browser Runner)');
  console.log('  目标地址: http://127.0.0.1:5173');
  console.log('  研究主题: 固态电池（典型新能源与电池材料产业链）');
  console.log('  截图保存目录: ' + SCREENSHOT_DIR);
  console.log('================================================================================');

  const browser = await chromium.launch({
    headless: true, // 无头运行，输出高清快照
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  const context = await browser.newContext({
    viewport: { width: 1440, height: 960 },
    deviceScaleFactor: 1.5, // 高清视网膜缩放
  });

  const page = await context.newPage();

  // 1. 打开创建任务页面
  console.log('📍 正在打开真实前端任务创建页面: http://127.0.0.1:5173/create ...');
  await page.goto('http://127.0.0.1:5173/create', { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(1000);

  // 截图：创建页面初始状态
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '01_create_page.png') });
  console.log('📸 [截图 01] 已保存创建页面初始状态: 01_create_page.png');

  // 2. 点击“固态电池”预填预设
  console.log('👉 正在点击预设主题: 固态电池 ...');
  const solidStatePreset = page.locator('[data-testid="preset-固态电池"]');
  if (await solidStatePreset.count() > 0) {
    await solidStatePreset.click();
  } else {
    // 降级选择输入框
    await page.fill('input[placeholder*="商业航天"]', '固态电池');
  }
  await page.waitForTimeout(800);

  // 截图：预填后的表单状态
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '02_form_filled.png') });
  console.log('📸 [截图 02] 已保存表单预填状态: 02_form_filled.png');

  // 3. 点击“创建任务并启动流水线”
  console.log('🚀 正在点击提交按钮: 创建任务并启动流水线 ...');
  const submitBtn = page.locator('button:has-text("创建任务并启动流水线")');
  await submitBtn.click();

  // 等待路由跳转到 /runs/run-...
  console.log('⏳ 等待路由切换至实时任务工作台 (runs/:runId) ...');
  await page.waitForURL(/\/runs\/run-/, { timeout: 30000 });

  const currentUrl = page.url();
  const runIdMatch = currentUrl.match(/runs\/(run-[a-zA-Z0-9-]+)/);
  const runId = runIdMatch ? runIdMatch[1] : 'unknown';
  console.log(`🎉 任务已成功在真实前端中创建并启动！Run ID: ${runId}`);
  console.log(`🔗 任务工作台真实访问地址: ${currentUrl}`);

  await page.waitForTimeout(2000);
  await page.screenshot({ path: path.join(SCREENSHOT_DIR, '03_pipeline_started.png') });
  console.log('📸 [截图 03] 已保存流水线启动就绪状态: 03_pipeline_started.png');

  // 4. 实时观察轮询与人机协同审核处理循环
  const STAGE_NAMES = ['data_fetch', 'data_interpret', 'chart_generate', 'chapter_write', 'report_fusion'];
  const processedReviews = new Set();
  const startTime = Date.now();
  const MAX_WAIT_MS = 12 * 60 * 1000; // 最长等待 12 分钟（真实大模型调用耗时）

  let lastStatus = '';
  let lastStage = '';

  while (Date.now() - startTime < MAX_WAIT_MS) {
    let runData = null;
    try {
      const resp = await page.request.get(`http://127.0.0.1:8000/api/v1/runs/${runId}`);
      if (resp.ok()) {
        runData = await resp.json();
      }
    } catch (e) {
      // 容错忽略
    }

    if (runData) {
      const { status, current_stage, stage_results } = runData;
      if (status !== lastStatus || current_stage !== lastStage) {
        console.log(`⚡ [流水线状态变更] 当前阶段: ${current_stage} | 整体状态: ${status} | 已耗时: ${Math.round((Date.now() - startTime) / 1000)}s`);
        lastStatus = status;
        lastStage = current_stage;
      }

      // 如果当前阶段处于 waiting_review (人机协同审核等待)
      if (status === 'waiting_review' && !processedReviews.has(`${current_stage}_${runData.revision}`)) {
        const reviewKey = `${current_stage}_${runData.revision}`;
        console.log(`🔔 [人机协同审核触发] 阶段 [${current_stage}] 执行完毕，暂停等待人工审核 (Revision ${runData.revision})`);

        await page.waitForTimeout(2000); // 等待前端响应式数据渲染完成
        const ssName = `04_review_${current_stage}.png`;
        await page.screenshot({ path: path.join(SCREENSHOT_DIR, ssName) });
        console.log(`📸 [审核界面截图] 已捕获当前阶段人机审核控制台: ${ssName}`);

        // 执行真实前端按钮交互：通过审核
        console.log(`👉 [人机交互] 模拟分析师在真实前端中确认数据与产物，点击审核通过...`);

        // 检查是否有风险弹窗按钮
        const riskNoticeBtn = page.locator('[data-testid="btn-risk-notice"]');
        if (await riskNoticeBtn.isVisible()) {
          console.log('⚠️ 检测到需要确认的风险项，点击打开风险提示对话框...');
          await riskNoticeBtn.click();
          await page.waitForTimeout(800);
          const riskAgreeBtn = page.locator('[data-testid="risk-agree"]');
          if (await riskAgreeBtn.isVisible()) {
            await riskAgreeBtn.click();
            console.log('✅ 已同意风险说明并继续推进！');
          }
        } else {
          // 直接点击主通过按钮
          const approveBtn = page.locator('[data-testid="btn-approve"]');
          if (await approveBtn.isVisible()) {
            await approveBtn.click();
            console.log(`✅ 已点击【通过审核】，流水线将继续向下推进！`);
          } else {
            console.log('⚠️ 未找到主通过按钮，尝试备用按钮...');
            const fallbackBtn = page.locator('.intervention-actions button.el-button--primary');
            if (await fallbackBtn.count() > 0) {
              await fallbackBtn.first().click();
            }
          }
        }

        processedReviews.add(reviewKey);
        await page.waitForTimeout(3000);
        continue;
      }

      // 如果整体流程已完成
      if (status === 'completed') {
        console.log('================================================================================');
        console.log(`🎉🎉🎉 [真实全流程执行圆满完成] 研报全链路生成与出版级交付就绪！`);
        console.log(`  总耗时: ${Math.round((Date.now() - startTime) / 1000)} 秒`);
        console.log('================================================================================');

        await page.waitForTimeout(3000);
        // 截取最终交付报告预览界面
        await page.screenshot({ path: path.join(SCREENSHOT_DIR, '05_final_report_completed.png') });
        console.log('📸 [最终截图] 已保存完整交付报告工作台快照: 05_final_report_completed.png');

        // 滚动页面查看生成的报告正文
        await page.evaluate(() => window.scrollTo(0, 1200));
        await page.waitForTimeout(1500);
        await page.screenshot({ path: path.join(SCREENSHOT_DIR, '06_final_report_preview_scroll.png') });
        console.log('📸 [最终截图] 已保存报告正文与图表嵌入预览快照: 06_final_report_preview_scroll.png');
        break;
      }

      // 如果任务失败
      if (status === 'failed') {
        console.error(`❌ [任务失败] 阶段: ${current_stage}`);
        await page.screenshot({ path: path.join(SCREENSHOT_DIR, 'error_failed_state.png') });
        break;
      }
    }

    await page.waitForTimeout(4000);
  }

  await browser.close();
  console.log('🏁 真实前端运行脚本执行结束。');
}

run().catch((err) => {
  console.error('❌ 执行异常:', err);
  process.exit(1);
});
