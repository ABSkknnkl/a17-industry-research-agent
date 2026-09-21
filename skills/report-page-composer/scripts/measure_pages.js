// report-page-composer / scripts/measure_pages.js
//
// 渲染后几何测量脚本（配合 playwright-cli 的 run-code 使用）。
// 它只负责“测量”，不做裁决；裁决交给 scripts/audit_render.py。
//
// 用法：
//   playwright-cli goto "http://127.0.0.1:<port>/report.html"
//   playwright-cli run-code --filename scripts/measure_pages.js --raw > /tmp/page-metrics.json
//
// 约定：分页容器使用 .report-page，页眉 .pg-head，页脚 .pg-foot。
//       若项目使用其它类名，复制本文件并修改 SELECTORS 即可，不要改测量逻辑。

async (page) => {
  const SELECTORS = {
    page: '.report-page',
    header: '.pg-head',
    footer: '.pg-foot',
    content: '.content',
  };

  await page.setViewportSize({ width: 1000, height: 1400 });
  await page.waitForTimeout(400);

  const metrics = await page.evaluate((SEL) => {
    const R = (v) => Math.round(v * 100) / 100;
    const rel = (el, base) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      const b = base.getBoundingClientRect();
      return { x: R(r.left - b.left), y: R(r.top - b.top), w: R(r.width), h: R(r.height) };
    };
    const abs = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x: R(r.left), y: R(r.top + window.scrollY), w: R(r.width), h: R(r.height) };
    };
    const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const fs = (el) => parseFloat(getComputedStyle(el).fontSize) || 0;
    const lh = (el) => {
      const cs = getComputedStyle(el);
      const v = parseFloat(cs.lineHeight);
      return Number.isFinite(v) ? v : fs(el) * 1.4;
    };
    const visible = (el) => {
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    };
    const cjk = (s) => ((s || '').match(/[\u4e00-\u9fff\u3400-\u4dbf]/g) || []).length;

    const pages = Array.from(document.querySelectorAll(SEL.page)).map((pageEl, i) => {
      const headerEl = pageEl.querySelector(SEL.header);
      const footerEl = pageEl.querySelector(SEL.footer);
      const contentEl = pageEl.querySelector(SEL.content);

      // --- 直接内容块（页级分页单元） ---
      const host = contentEl || pageEl;
      const blocks = Array.from(host.children).map((el, idx) => {
        const r = rel(el, pageEl);
        const text = norm(el.innerText || el.textContent);
        return {
          index: idx,
          tag: el.tagName.toLowerCase(),
          cls: el.className && String(el.className).slice(0, 60),
          block_id: el.getAttribute('data-bid') || null,
          reading_level: el.getAttribute('data-level') || null,
          rect: r,
          font_size: R(fs(el)),
          line_height: R(lh(el)),
          text: text.slice(0, 160),
          text_len: text.length,
          cjk_len: cjk(text),
          scroll_h: R(el.scrollHeight),
          client_h: R(el.clientHeight),
          overflow_y: R(el.scrollHeight - el.clientHeight),
          overflow_x: R(el.scrollWidth - el.clientWidth),
        };
      });

      // --- 文本叶子节点（跨块重叠、窄列折行、字号） ---
      const leaves = [];
      const leafSel = 'p,h1,h2,h3,h4,li,td,th,dt,dd,figcaption,.fig-cap,.fig-src,.tbl-caption,.tbl-source,.note,.chip,.conc,.lead,svg text';
      Array.from(host.querySelectorAll(leafSel)).forEach((el) => {
        if (!visible(el)) return;
        const text = norm(el.innerText || el.textContent);
        if (!text) return;
        const r = rel(el, pageEl);
        const f = fs(el);
        const l = lh(el);
        const cs = getComputedStyle(el);
        // 内容盒尺寸：排除 padding/border，否则窄列会被 padding 撑宽而漏检
        const padX = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0)
                   + (parseFloat(cs.borderLeftWidth) || 0) + (parseFloat(cs.borderRightWidth) || 0);
        const padY = (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0)
                   + (parseFloat(cs.borderTopWidth) || 0) + (parseFloat(cs.borderBottomWidth) || 0);
        const cw = Math.max(r.w - padX, 0);
        const ch = Math.max(r.h - padY, 0);
        leaves.push({
          tag: el.tagName.toLowerCase(),
          cls: el.className && String(el.className).slice(0, 50),
          rect: r,
          in_svg: el.ownerSVGElement ? true : false,
          font_size: R(f),
          line_height: R(l),
          content_w: R(cw),
          content_h: R(ch),
          lines: l > 0 ? R(ch / l) : 0,
          text: text.slice(0, 120),
          text_len: text.length,
          cjk_len: cjk(text),
          max_word_w: R(cw / Math.max(f, 1)),
        });
      });

      // --- 空单元格 / 表格结构 ---
      const tables = Array.from(host.querySelectorAll('table')).map((t) => {
        const rows = Array.from(t.querySelectorAll('tr')).map((tr) =>
          Array.from(tr.children).map((c) => {
            const r = rel(c, pageEl);
            const text = norm(c.innerText || c.textContent);
            return {
              tag: c.tagName.toLowerCase(),
              text: text.slice(0, 60),
              text_len: text.length,
              cjk_len: cjk(text),
              colspan: c.colSpan || 1,
              rect: r,
              lines: c.clientHeight && lh(c) > 0 ? R(c.clientHeight / lh(c)) : 0,
              font_size: R(fs(c)),
            };
          })
        );
        return { rect: rel(t, pageEl), rows };
      });

      // --- SVG 绘图区利用率 + 图内标签碰撞 ---
      const svgs = Array.from(host.querySelectorAll('svg')).map((svg) => {
        const box = rel(svg, pageEl);
        const texts = Array.from(svg.querySelectorAll('text')).map((t) => ({
          text: norm(t.textContent).slice(0, 60),
          rect: rel(t, pageEl),
          font_size: R(fs(t)),
        }));
        const shapes = Array.from(svg.querySelectorAll('rect,line,path,circle,polyline,polygon'))
          .filter((s) => !(s.getAttribute('class') || '').includes('frame'))
          .map((s) => rel(s, pageEl))
          .filter(Boolean);
        let plot = null;
        if (shapes.length) {
          const x0 = Math.min(...shapes.map((s) => s.x));
          const y0 = Math.min(...shapes.map((s) => s.y));
          const x1 = Math.max(...shapes.map((s) => s.x + s.w));
          const y1 = Math.max(...shapes.map((s) => s.y + s.h));
          plot = { x: R(x0), y: R(y0), w: R(x1 - x0), h: R(y1 - y0) };
        }
        return { rect: box, plot, texts, text_count: texts.length };
      });

      return {
        page_number: i + 1,
        page_role: pageEl.getAttribute('data-role') || null,
        chapter_id: pageEl.getAttribute('data-chapter') || null,
        rect: rel(pageEl, pageEl),
        header: rel(headerEl, pageEl),
        footer: rel(footerEl, pageEl),
        header_text: norm(headerEl ? headerEl.innerText || headerEl.textContent : ''),
        footer_text: norm(footerEl ? footerEl.innerText || footerEl.textContent : ''),
        content: rel(contentEl, pageEl),
        content_scroll_h: contentEl ? R(contentEl.scrollHeight) : null,
        content_client_h: contentEl ? R(contentEl.clientHeight) : null,
        page_scroll_h: R(pageEl.scrollHeight),
        page_client_h: R(pageEl.clientHeight),
        page_overflow_y: R(pageEl.scrollHeight - pageEl.clientHeight),
        blocks,
        leaves,
        tables,
        svgs,
      };
    });

    const mmFromPx = 25.4 / 96;
    return {
      generated_at: new Date().toISOString(),
      page_size_px: pages.length
        ? { w: pages[0].rect.w, h: pages[0].rect.h }
        : null,
      page_size_mm: pages.length
        ? { w: Math.round(pages[0].rect.w * mmFromPx * 100) / 100, h: Math.round(pages[0].rect.h * mmFromPx * 100) / 100 }
        : null,
      px_per_mm: 1 / mmFromPx,
      page_count: pages.length,
      pages,
    };
  }, SELECTORS);

  return JSON.stringify(metrics);
}
