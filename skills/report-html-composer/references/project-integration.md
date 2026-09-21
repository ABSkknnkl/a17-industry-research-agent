# Agent 5 接入说明

## 唯一规范源

- 编辑设计简报：`skills/report-html-composer/references/design-brief.json`
- 可执行布局目录：`skills/report-html-composer/references/layout-catalog.json`
- 运行时加载器：`backend/app/reporting/html_composer_loader.py`
- 模型上下文与事实锁：`backend/app/agents/report_fusion/editorial.py`
- 模型决策校验与确定性降级：`backend/app/agents/report_fusion/html_composition.py`
- 运行时 HTML 结构质量门：`backend/app/reporting/html_quality.py`
- HTML 渲染器：`backend/app/reporting/html.py`
- 模板：`backend/app/reporting/templates/report.html.j2`

编辑模型收到的是 `design-brief.json`、实际章节/小节/图表/证据信号和严格 JSON Schema；它不直接改写正文或输出任意 HTML。后端不得复制这两份规范。加载失败时报告继续生成，但只采用安全单栏，并把 `report_html_composer_missing` 或 `report_html_composer_unusable` 写入 readiness issues。

## 与现有 Agent 5 的边界

- `visual.py`：决定报告级视觉预设和章级语义。
- `composition.py`：决定 PDF/分页相关的章级页面计划。
- `html_composition.py`：决定屏幕阅读的小节级图文关系。
- `report-page-composer`：负责 A4 分页、续表、PDF 几何和出版体裁检查。
- `report-html-composer`：负责连续 HTML 阅读、响应式布局、导航和证据中心。

两个 composer 共享同一 `ReportViewModel`，但互不覆盖。屏幕布局只写入 `@media screen`，不得改变打印基线。

当 `beautify_mode=on` 且编辑模型可用时，`EditorialPlan.section_decisions` 为每个小节提供 `composition`、`reading_order`、`content_width` 和主图 ID。运行时逐项核对真实图表数量、语义和 ID；不合法决策回退确定性布局并标记原因。模型不可用时不冒充已调用，`source` 保持 `fallback` 或 `deterministic`。

模板采用“小节构图优先”：`table_led`、`risk_matrix` 等章级语义只能增加章节装饰，不能把小节改渲染成 `<tr>` 或缺少内部容器的特殊分支。除 `coverage_summary` 外，每个小节必须是带 `data-layout-structure="section-body-copy-v1"` 的 `<article>`，并包含统一的正文、图表和证据容器。这样计划里的 `layout_id` 在所有章节都具有同一执行含义。

`report_mode` 必须经过内容守卫：10 张及以上图表强制归入 `chart_led`，避免模型返回文字型方向而实际输入是数据密集报告；其余情况在内容允许时尊重模型选择。最终模式、来源和校正理由写入公开计划。`design_direction` 在桌面阅读导航中作为阅读提示显示，不能成为未消费的说明字段。

## 可审计性

模板必须输出：

```html
<script type="application/json" id="html-composition-plan">…</script>
```

同时在每个小节写入 `data-html-layout`、`data-layout-source` 与不含原始编号的 `data-section-key`。计划 JSON 使用同一个 `section_key`，另一个 AI 或浏览器测试器可以按键比较计划与真实 DOM，检查“计划说双栏但页面没有双栏”之类的失效接入。压缩进研究覆盖表的小节也必须保留这些属性。`section_key` 只是稳定连接键，不提供匿名化或安全保证。

公开计划还必须含 7 条 `chapter_decisions`，只使用 `chapter_key` / `chapter_number`，不得暴露内部章节 ID。
