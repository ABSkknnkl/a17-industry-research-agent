// report-page-composer / scripts/export_pdf.js
//
// 正确的 PDF 导出（配合 playwright-cli 的 run-code 使用）。
//
// 为什么必须用它，而不是 `playwright-cli pdf`：
//   1. playwright-cli 的 pdf 命令默认按 US Letter (612×792pt) 出纸，
//      会忽略 CSS 的 `@page { size: A4 }`，把 A4 报告改成 Letter，
//      版心比例与分页位置全部偏移，此前测得的几何结论随之失效。
//   2. 不开启 printBackground 时，封面深色底、表头底色与图表配色会全部丢失。
//
// 用法（输出路径通过 URL 查询参数传入，沙箱内没有 process.env）：
//   playwright-cli goto "http://127.0.0.1:8080/report.html?pdf=/tmp/report.pdf&format=A4"
//   playwright-cli run-code --filename scripts/export_pdf.js --raw
//
// 参数：
//   pdf=<绝对路径>      输出文件；缺省 /tmp/report-page-composer.pdf
//   format=A4|A3|...    纸张；缺省 A4。给 mm=1 时改用 w/h 显式尺寸
//   w=<mm>&h=<mm>       显式纸张尺寸（覆盖 format）

async (page) => {
  // 沙箱内没有 process.env / URL 构造器，只能从当前地址解析查询参数
  const href = page.url();
  const param = (name, fallback) => {
    const m = href.match(new RegExp('[?&]' + name + '=([^&#]+)'));
    return m ? decodeURIComponent(m[1]) : fallback;
  };
  const out = param('pdf', '/tmp/report-page-composer.pdf');
  const format = param('format', 'A4');
  const w = param('w', '');
  const h = param('h', '');

  // 等待字体与布局稳定，避免首页字体替换造成的分页漂移
  await page.evaluate(() => (document.fonts ? document.fonts.ready : null));
  await page.waitForTimeout(500);

  const options = {
    path: out,
    printBackground: true,      // 保留封面底色、表头底色与图表配色
    preferCSSPageSize: true,    // 尊重 @page { size: A4 }
    margin: { top: '0', right: '0', bottom: '0', left: '0' },
    scale: 1,
  };
  if (w && h) {
    options.width = w + 'mm';
    options.height = h + 'mm';
  } else {
    options.format = format;
  }

  await page.pdf(options);

  const containers = await page.locator('.report-page').count();
  return JSON.stringify({
    path: out,
    paper: w && h ? w + 'mm x ' + h + 'mm' : format,
    print_background: true,
    prefer_css_page_size: true,
    page_containers: containers,
  });
}
