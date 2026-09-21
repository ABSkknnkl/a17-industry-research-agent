# 本工程接入位置

本参考仅适用于 `a17-industry-research-agent-agent-chart-mvp-sync`。

## 当前结构限制

- `backend/app/agents/report_fusion/visual.py` 只选择章级 `layout_pattern`，没有逐页内容槽位。
- `backend/app/agents/report_fusion/editorial.py` 约束编辑模型不得修改 HTML、CSS 和分页规则。
- `backend/app/reporting/templates/report.html.j2` 使用浏览器自然流分页，并对结论卡、图表、章节导语、证据块等大量元素设置不可拆分。
- 普通柱图、折线图、面积图、组合图等在模板中默认为全宽，无法根据同页关系自动组成双图或 2×2。
- 质量附录、来源索引和未解决问题依次自动输出，缺少对外版与内部审计版的分层。

## 推荐职责拆分

### Agent 3：图表语义

继续负责事实安全的图表规格，同时补充仅与展示有关的字段：

- `visual_task`：trend、ranking、comparison、composition、distribution、relationship、single_metric；
- `label_profile`：中文标签数量、最长标签字符数、预计换行数；
- `size_class`：small、medium、hero；
- `group_key`：允许同页比较的图表组；
- `preferred_arrangements`：two_up、two_by_two、hero_plus_two 等；
- `orientation_preference`：horizontal、vertical、auto。

不得让 Agent 3 决定最终页码。

### Agent 5：页级编辑

在 `EditorialPlan` 与 HTML 渲染之间增加 `PageCompositionPlan`：

1. 冻结原始内容块 ID 与顺序约束；
2. 估算文字、图表和表格高度；
3. 为每页选择 `page_role` 和 `grid`；
4. 将内容块放入页槽，并记录允许的跨页关系；
5. 输出结构化蓝图并校验；
6. 模板严格消费蓝图，不再完全依赖浏览器自由流动。

同时增加 `EditorialDensityPlan`：将内容标记为 `headline/lead/support/detail/audit`，只允许去除重复模板话术、抽取已有句子或将详情下沉附录。编辑前后必须对 `fact_id/claim_id/citation_id`、数值、单位、日期和限定词做覆盖校验。

编辑模型可以推荐页级蓝图，但确定性代码必须验证：ID 存在、内容未增删、阅读顺序合法、表格续页合法、图表组合合法。

### 渲染器

- 使用显式 `.report-page` 容器或等价分页结构，每个容器对应一页。
- 页面容器输出 `data-role` 与 `data-chapter`，块级元素输出 `data-bid`，与蓝图 `render_contract` 声明一致——渲染后审计完全依赖这些钩子。
- **不要给内容区设标称固定高度**（`height: 236mm` 这类）。固定高度只约束盒子不约束内容，溢出会静默发生并撞到页脚；高度交给内容决定，溢出交给测量判定。
- **页脚区要在版心上预留物理隔离**：页面 `padding-bottom` > 页脚高度 + 安全间距，使正文在物理上无法触达页脚。
- 正文必须经 `skills/report-page-composer/scripts/text_rules.py` 的 `sanitize_public()` 清洗后再输出。不要在模板或 Agent 5 里另写一套替换词表。
- 只对真正必须原子化的块使用 `break-inside: avoid`。
- 将全宽、双栏、2×2、主图+辅图实现为明确模板，而不是由 `flex-wrap` 猜测。
- 为每个内容段产生多个候选页，用确定性代价函数选择并支持回溯重平衡；浏览器流式分页仅作兼容回退。
- 表格跨页应由分页器生成续表标题和重复表头；列宽用 `<colgroup>` 显式声明，不交给浏览器自动分配。
- 内容相同的连续表格行成组为一行并注明归并关系。
- 对外版默认不显示机器状态和完整质量日志。
- HTML 预览与 PDF 使用同一份设计 token，分别定义屏幕和打印表现；打印开启背景色保留并去除不必要阴影。

### 渲染管线（五个可执行闸门）

把下列五步接进 `Agent 5 → HTML → PDF` 之间，每一步用退出码当门禁：

| 步骤 | 命令 | 通过条件 |
|---|---|---|
| ① 渲染前文本门 | `python3 skills/report-page-composer/scripts/text_hygiene.py inventory.json --write-fixed inventory.fixed.json` | 复检 `clean=True` |
| ② 蓝图契约 | `python3 skills/report-page-composer/scripts/validate_page_plan.py page_composition_plan.json` | `valid=true` |
| ③ 渲染 | 本工程渲染器消费蓝图 | 输出 `report.html` |
| ④ 渲染后几何审计 | `measure_pages.js` + `audit_render.py --plan … --out audit.json` | `deliverable=true`（critical=0, major=0） |
| ⑤ PDF 导出 | `playwright-cli run-code --filename scripts/export_pdf.js` | A4 `210×297mm`，页数=分页容器数 |

注意 ⑤：**不要用 `playwright-cli pdf`**。它默认按 US Letter 出纸并忽略 `@page { size: A4 }`，也不保留背景，封面底色会整片消失。用 skill 自带的 `export_pdf.js`。

### 视觉质量门

在现有检查之外增加（`audit_render.py` 已实现，接入时直接消费其 JSON 输出）：

- `PAGE_CONTENT_OVERFLOW`：内容越过安全版心下沿；
- `FOOTER_COLLISION` / `HEADER_COLLISION`：正文压住页脚页眉；
- `ELEMENT_OVERLAP`：同页文本元素重叠；
- `CHART_LABEL_COLLISION`：图内标签互相重叠；
- `MIN_FONT_SIZE`：最终字号低于可读下限；
- `CJK_NARROW_WRAP`：中文标题/标签窄列压字（判据可量化：净宽 ÷ 字号 < 5 字且折成 ≥3 行）；
- `TABLE_EMPTY_CELL`：对外正文出现空数据格；
- `CHART_CANVAS_UNDERUSED`：绘图区明显小于图表容器；
- `UNEXPLAINED_WHITESPACE`：同章节内容流中途出现无法解释的大空白；
- `PIPELINE_NAME_IN_CHROME`：页眉页脚泄漏生成管线信息；
- `MACHINE_FIELD_IN_BODY` / `PRECISION_OVERFLOW`：正文出现机器字段或审计级精度；
- `DUPLICATE_TEXT`：重复段落；
- `ORPHAN_CONTINUATION_REFERENCE` / `CONTINUED_TABLE_WITHOUT_PRECEDENT`：续页引用不成对；
- `PAGE_NUMBER_MISSING`：页脚缺页码；
- `AXIS_TICK_VERBOSE`：刻度冗长。

原有约定项仍适用：`CJK_VERTICAL_STACK`、`CONTINUED_TABLE_NO_CAPTION`、`CONTINUED_TABLE_ORPHAN`、`PAGE_ROLE_CONFLICT`、`CHART_PAIR_SEPARATED`、`CAPTION_OVERLOAD`、`AUDIT_DOMINATES_REPORT`、`NO_PUBLICATION_CHROME`、`EDITORIAL_REDUNDANCY`、`EMPTY_STATE_AMPLIFIED`、`CHART_ENCODING_INVALID`、`NAVIGATION_MISMATCH`。其中可在蓝图期判定的部分已下沉到 `validate_page_plan.py`，避免渲染后才发现。

## 迁移顺序

1. 先引入 `PageCompositionPlan` 数据结构、`render_contract` 与确定性校验，不改事实结构。
2. 接上渲染前文本门（`text_hygiene.py`），让内容清单在进入编排前就消灭重复与机器字段。
3. 再让 HTML 模板消费显式页面蓝图，输出 `data-role` / `data-chapter` / `data-bid`，并保留旧报告的兼容回退。
4. 改造图表容器，支持多种同页组合、中文标签方向、标签独占槽位与离群值降级。
5. 改造续表与内部附录。
6. 接上渲染后几何审计（`measure_pages.js` + `audit_render.py`），把它作为交付门禁而不是事后报表。
7. 最后接入编辑模型推荐与视觉模型复检。

不要先通过追加提示词期待模型突破现有枚举和 CSS 限制；模型只能在代码允许的动作空间内改善结果。同理，不要期待模型“每次都记得”不要压住页脚——把约束写进 CSS 与审计脚本，而不是写进提示词。
