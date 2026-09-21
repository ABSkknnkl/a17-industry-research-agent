# Agent 5 外部实现与模板同步落地计划（方案 A）

> 本文可直接交给代码智能体执行。执行者必须按任务顺序推进、逐项勾选，不得整目录覆盖，不得清理或回退用户现有改动。

## 0. 任务定义

### 0.1 目标

把下列外部目录中的 Agent 5（`report_fusion`）实现同步到当前项目：

```text
外部来源：/Users/Zhuanz1/Downloads/a17-industry-research-agent-agent-chart-mvp-sync
目标项目：/Users/Zhuanz1/PycharmProjects/同花顺
目标分支：agent/chart-mvp-sync
```

同步完成后必须满足：

1. Agent 5 使用外部项目的 `report.html.j2` 作为唯一生产模板。
2. 目标项目现有的 `report-industry.html.j2` 和 `report-style-industry.css.j2` 保留，但生产路径不得引用，也不得自动回退到它们。
3. 外部 Agent 5 的编辑规划、页面组合、HTML 组合、质量检查、PDF 诊断和视觉复检能力能够在目标项目中运行。
4. 保留目标项目当前 Agent 3、Agent 4、前端和报告质量评分器的已有能力。
5. 特别保留目标项目的 `comparison_bar` 图表支持；外部代码不包含该能力，任何覆盖都会造成回归。
6. 保留所有当前未提交修改，不执行会丢失工作区内容的操作。
7. 后端、公开 JSON Schema、前端 TypeScript 类型保持一致。

### 0.2 非目标

- 不同步外部项目的整套 Agent 1—4。
- 不替换目标项目的 `backend/app/schemas/chart.py`。
- 不整体替换 `backend/app/core/config.py`、`workflow/factory.py` 或 LLM 集成目录。
- 不自动删除旧模板。
- 不把旧模板做成运行时自动回退方案。
- 不提交 `.env`、缓存、日志、SQLite、构建产物、`__pycache__` 或 `.pytest-tmp`。
- 不推送远端、不合并 `main`，除非用户另行明确授权。

## 1. 核心判断

这不是单个 Jinja 模板替换任务。外部 `report.html.j2` 依赖下列新增数据和运行能力：

- `TemplateProfile`
- `EditorialPlan`
- `PageCompositionPlan`
- `ReportBlueprint`
- `VisualReviewReport`
- `VisualReviewSummary`
- 页面组合和 HTML 组合决策
- 文本净化规则与 HTML 布局目录
- PDF 页面诊断、联系表和视觉复检
- 可选的报告编辑模型和视觉审核模型

因此只复制模板会被 `StrictUndefined`、缺失字段或缺失过滤器阻断。正确方式是以目标项目为基线，选择性移植外部 Agent 5 的完整依赖闭包。

## 2. 不可违反的保护规则

### 2.1 工作区保护

目标分支当前存在大量未提交修改，其中包括 Agent 3、Agent 4、Agent 5、渲染器、Schema、测试和前端文件。执行者必须：

- 不运行 `git reset --hard`。
- 不运行 `git checkout -- <path>` 或 `git restore <path>` 覆盖现有内容。
- 不使用 `git clean`。
- 不自动 stash 用户改动。
- 不直接执行 `cp -R` 覆盖已有目录。
- 修改已有文件时使用小范围补丁或三方合并。
- 每完成一个任务先运行定向测试，再进入下一任务。

开始前记录：

```bash
cd /Users/Zhuanz1/PycharmProjects/同花顺
git status --short --branch
git diff -- backend/app/agents/report_fusion backend/app/reporting backend/app/schemas/report.py
```

这些命令只用于观察，不得据此删除或恢复任何文件。

### 2.2 上游保护

下列目标项目能力必须视为权威实现：

- `backend/app/schemas/chart.py`
- `backend/app/agents/chart_generator/`
- `contracts/schemas/chart-generation-result.schema.json`
- Agent 3 的 `comparison_bar`
- 当前产业链图生成和图片渲染能力
- 当前 Agent 4 章节结构、并发和可读性能力
- 当前报告质量 100 分评分器及其测试
- 当前前端工作台与报告预览能力

外部同名文件只能作为参考，不能覆盖这些权威实现。

### 2.3 事实边界

Agent 5 可以重新组织版式、编辑层级、页面节奏和视觉结构，但不得：

- 新造财务事实；
- 修改 Agent 2 已确认的数值；
- 删除证据 ID；
- 把缺失数据补成确定值；
- 让视觉模型自由改写正文；
- 绕过 Agent 3 的图表契约重新推断业务含义。

## 3. 最终架构

```text
Agent 2 分析结果 ─┐
Agent 3 图表结果 ─┼─> Agent 5 assembler
Agent 4 章节结果 ─┘          │
                             ▼
                   ReportViewModel
                             │
                  ┌──────────┴──────────┐
                  ▼                     ▼
          EditorialPlan         PageCompositionPlan
                  │                     │
                  └──────────┬──────────┘
                             ▼
                  HTMLCompositionPlan
                             │
                             ▼
                 外部 report.html.j2
                             │
                  ┌──────────┴──────────┐
                  ▼                     ▼
                 HTML                  PDF
                                        │
                              确定性视觉检查
                                        │
                             可选视觉模型复检
                                        │
                              有限次数布局修复
```

### 3.1 模板选择规则

生产模板固定为：

```text
backend/app/reporting/templates/report.html.j2
```

旧模板保留为：

```text
backend/app/reporting/templates/report-industry.html.j2
backend/app/reporting/templates/report-style-industry.css.j2
```

约束：

- `render_html()`只能主动加载 `report.html.j2`。
- 不增加 `layout="industry"`、自动探测或模板轮询。
- 外部模板缺失或渲染失败时返回结构化错误/等待审核，不能切换旧模板。
- 旧模板只作为人工回滚材料存在。

### 3.2 可选模型启用策略

第一轮迁移推荐：

```text
REPORT_EDITORIAL_ENABLED=false
REPORT_VISUAL_REVIEW_ENABLED=false
```

原因：先证明确定性组装、模板、HTML和PDF链路稳定，再开启真实模型调用，避免迁移同时引入费用、网络和模型输出变量。

代码和 mock 必须完整接入；完成确定性验收后再由用户决定是否开启。若用户明确要求完全按外部项目默认值运行，可把两项设为 `true`，但必须先验证相应模型、Base URL 和 API Key 配置。

## 4. 文件级同步矩阵

### 4.1 可从外部新增，但仍需检查导入路径

| 外部文件 | 目标路径 | 策略 |
| --- | --- | --- |
| `backend/app/agents/report_fusion/composition.py` | 同路径 | 新增 |
| `backend/app/agents/report_fusion/editorial.py` | 同路径 | 新增 |
| `backend/app/agents/report_fusion/html_composition.py` | 同路径 | 新增 |
| `backend/app/reporting/html_composer_loader.py` | 同路径 | 新增 |
| `backend/app/reporting/html_quality.py` | 同路径 | 新增 |
| `backend/app/reporting/scenario.py` | 同路径 | 新增 |
| `backend/app/reporting/text_rules_loader.py` | 同路径 | 新增 |
| `backend/app/reporting/visual_review.py` | 同路径 | 新增 |
| `backend/app/reporting/templates/report.html.j2` | 同路径 | 新增并作为唯一生产模板 |
| `contracts/schemas/editorial-plan.schema.json` | 同路径 | 新增后执行契约测试 |
| `contracts/schemas/report-blueprint.schema.json` | 同路径 | 新增后执行契约测试 |

### 4.2 必须人工合并，禁止覆盖

| 目标文件 | 合并内容 |
| --- | --- |
| `backend/app/agents/report_fusion/service.py` | 编辑模型、页面组合、视觉复检、PDF诊断与修复循环 |
| `backend/app/agents/report_fusion/assembler.py` | 外部报告视图、图表分散落位、场景摘要、编辑上下文 |
| `backend/app/agents/report_fusion/evidence.py` | 外部证据目录增强，同时保留当前来源命名规则 |
| `backend/app/agents/report_fusion/quality.py` | 外部质量规则与当前100分评分逻辑合并，不能二选一 |
| `backend/app/agents/report_fusion/visual.py` | 外部模板配置和布局模式，保留当前视觉密度选项 |
| `backend/app/reporting/html.py` | 外部模板上下文、SVG文字覆盖层、页面组合、质量门；保留当前兼容入口 |
| `backend/app/reporting/markdown.py` | 接入统一文本净化，保留现有Markdown字段 |
| `backend/app/reporting/pdf.py` | 外部诊断与循环复用，保留现有调用方兼容性 |
| `backend/app/reporting/presentation.py` | 外部人类可读标签，保留目标项目新增图表类型标签 |
| `backend/app/reporting/svg.py` | 以目标版本为基线吸收外部绘图增强，必须继续识别 `comparison_bar` |
| `backend/app/schemas/report.py` | 添加外部编辑/分页/复检模型，不覆盖当前质量评分字段 |
| `backend/app/schemas/workflow.py` | 只添加外部 `ReportFusionOptions` 字段 |
| `backend/app/core/config.py` | 只添加 `REPORT_EDITORIAL_*`、`REPORT_VISUAL_REVIEW_*` 配置 |
| `backend/.env.example` | 只添加新配置示例，不覆盖当前模型与视觉服务配置 |
| `backend/app/integrations/llm/protocol.py` | 添加两个协议 |
| `backend/app/integrations/llm/mock.py` | 添加两个 mock |
| `backend/app/integrations/llm/factory.py` | 添加两个创建函数 |
| `backend/app/integrations/llm/openai_compatible.py` | 合并报告编辑和视觉复检客户端，不覆盖当前调用实现 |
| `backend/app/workflow/factory.py` | 将新模型与配置注入 `ReportFusionAgent` |
| `backend/app/main.py` | readiness 增加规则/布局目录问题；保留现有生命周期逻辑 |
| `contracts/schemas/report-fusion-result.schema.json` | 与最终Pydantic结果同步，不能直接覆盖 |
| `frontend/src/api/types.ts` | 添加可选的Agent 5新字段，保留当前Agent 3类型 |

### 4.3 运行依赖资源

同步以下外部目录：

```text
skills/report-html-composer/
skills/report-page-composer/
skills/report-style-benchmark/
```

其中运行时硬依赖至少包括：

```text
skills/report-html-composer/references/layout-catalog.json
skills/report-html-composer/references/design-brief.json
skills/report-page-composer/scripts/text_rules.py
```

规则：

- 后端只加载这些资源，不复制第二份规则表。
- 加载失败时使用外部实现定义的安全单栏/文本降级，并在 `/health/ready` 中上报 issue。
- 降级不允许启用旧模板。

### 4.4 明确禁止复制

不得从外部覆盖：

```text
backend/app/agents/chart_generator/
backend/app/schemas/chart.py
contracts/schemas/chart-generation-result.schema.json
backend/app/agents/chapter_writer/
backend/app/schemas/chapter.py
frontend/src/components/ChartGallery.vue
backend/app/core/config.py（整文件）
backend/app/workflow/factory.py（整文件）
backend/app/integrations/llm/（整目录）
```

## 5. 公共接口兼容决策

### 5.1 `render_html`

目标项目当前存在：

```python
render_html(report, *, continuous_numbering=True)
```

外部实现新增：

```python
render_html(report, *, repair_classes=())
```

合并后的兼容签名应为：

```python
def render_html(
    report: ReportViewModel,
    *,
    continuous_numbering: bool = True,
    repair_classes: tuple[str, ...] = (),
) -> str:
    ...
```

行为：

- 默认继续满足当前项目的整份报告连续编号要求。
- `continuous_numbering=False`时允许使用外部模板的章内编号形式。
- `repair_classes`用于视觉修复循环。
- 两个参数必须同时可用，并有组合测试。

### 5.2 `render_pdf`

保留目标项目现有公开入口；在其上增加外部诊断入口：

```python
async def render_pdf(html: str) -> bytes
async def render_pdf_with_diagnostics(html: str) -> tuple[bytes, dict[str, Any]]
```

如现有调用方仍使用 `render_pdf_with_toc_page_numbers`，应保留兼容包装函数，内部委托新实现，而不是一次性删除入口。

### 5.3 图表契约

- `comparison_bar`继续与 `bar`走同一确定性SVG族，但保留自己的标签。
- 外部 `svg.py`中的新增颜色、坐标、热力、箱线、树图和产业链增强逐段移植。
- 不导入外部旧版 `ChartType`枚举。
- 所有目标项目当前支持的图表类型都必须进入渲染回归参数化测试。

### 5.4 ReportFusion结果

新增字段优先采用可选字段或安全默认值，保证旧任务存档仍可被读取。至少考虑：

- `decision_brief`
- `editorial_plan`
- `page_composition_plan`
- `report_blueprint`
- `visual_review`
- `visual_review_summary`
- `template_profile`
- `html_composition`相关摘要

如果外部模型将这些字段设为必填，必须在装配器中为旧输入生成确定性默认值，并增加旧存档兼容测试。

## 6. 分阶段实施任务

### Task 1：建立迁移护栏和失败测试

**目标：** 在改生产代码前锁定现有能力和模板选择规则。

**修改/新增：**

- `backend/tests/agents/report_fusion/test_external_agent5_migration.py`
- 必要时扩展 `backend/tests/reporting/test_svg.py`
- 必要时扩展 `backend/tests/agents/report_fusion/test_render_contract.py`

**步骤：**

- [ ] 记录当前定向测试基线。
- [ ] 增加测试：生产模板名只能是 `report.html.j2`。
- [ ] 增加测试：旧模板文件存在，但不被 `render_html()`访问。
- [ ] 增加测试：模板缺失/渲染错误不会回退旧模板。
- [ ] 增加测试：`comparison_bar`仍能输出有效SVG和HTML。
- [ ] 增加测试：`continuous_numbering`与`repair_classes`兼容。
- [ ] 增加测试：旧版 `ReportViewModel` fixture仍可渲染。
- [ ] 运行测试并确认测试按预期失败，而不是因为测试夹具损坏。

建议命令：

```bash
cd /Users/Zhuanz1/PycharmProjects/同花顺/backend
.venv/bin/python -m pytest \
  tests/agents/report_fusion/test_render_contract.py \
  tests/reporting/test_svg.py \
  tests/agents/report_fusion/test_external_agent5_migration.py -q
```

### Task 2：扩展报告Schema和公开契约

**目标：** 先建立外部模板需要的数据模型。

**文件：**

- `backend/app/schemas/report.py`
- `backend/app/schemas/workflow.py`
- `contracts/schemas/report-fusion-result.schema.json`
- 新增 `contracts/schemas/editorial-plan.schema.json`
- 新增 `contracts/schemas/report-blueprint.schema.json`
- `frontend/src/api/types.ts`
- `backend/tests/test_contracts.py`

**步骤：**

- [ ] 从外部 `report.py`提取新增模型，不覆盖当前评分模型。
- [ ] 解决字段名、默认值和枚举差异。
- [ ] 新字段对旧产物使用默认值或可选字段。
- [ ] 只把外部 `ReportFusionOptions`新增字段合并进当前 `workflow.py`。
- [ ] 更新JSON Schema。
- [ ] 同步TypeScript可选字段。
- [ ] 用真实Pydantic输出验证JSON Schema，而不是只比较静态文本。
- [ ] 确认前端对未知/缺失新字段不会崩溃。

**完成条件：**

- 旧Agent 5 fixture能通过新模型校验。
- 新外部fixture能通过新模型校验。
- `backend/tests/test_contracts.py`通过。
- 前端类型检查通过。

### Task 3：同步布局规则和文本规则资源

**目标：** 建立外部模板依赖的唯一规则源。

**文件：**

- 新增 `skills/report-html-composer/`
- 新增 `skills/report-page-composer/`
- 新增 `skills/report-style-benchmark/`
- 新增 `backend/app/reporting/html_composer_loader.py`
- 新增 `backend/app/reporting/text_rules_loader.py`
- 修改 `backend/app/main.py`

**步骤：**

- [ ] 复制三个相关skill目录，排除缓存和产物。
- [ ] 接入两个loader。
- [ ] `/health/ready`聚合两个loader的issue code。
- [ ] 规则资源存在时 readiness issues为空。
- [ ] 规则资源缺失时进入安全降级并报告issue。
- [ ] 验证HTML和Markdown共用同一文本净化入口。
- [ ] 不在Python渲染器中复制另一份替换词表。

**测试：**

- 外部 `test_html_composer.py`
- 外部 `test_text_rules_parity.py`
- 当前 readiness 测试

### Task 4：同步Agent 5确定性装配和视觉规划

**目标：** 不依赖外部模型也能产生完整的新 `ReportViewModel`。

**文件：**

- 新增 `composition.py`
- 新增 `editorial.py`
- 新增 `html_composition.py`
- 合并 `assembler.py`
- 合并 `evidence.py`
- 合并 `visual.py`
- 合并 `quality.py`

**关键决策：**

- 外部 `standard_editorial_plan()`作为没有模型时的确定性默认方案。
- 图表落位优先使用当前 `placement_section_id`和用户覆盖。
- 外部 `spread_chart_placements()`只能分散位置，不能修改图表事实和证据。
- 当前100分报告评分继续作为正式质量结果；外部质量检查补充为布局/交付维度，不得覆盖总分口径。
- 证据目录继续使用目标项目具名来源策略。

**步骤：**

- [ ] 移植新增模块。
- [ ] 逐函数合并现有模块。
- [ ] 合并后运行类型检查/导入检查。
- [ ] 添加同一小节多图时的分散落位测试。
- [ ] 添加用户placement override优先级测试。
- [ ] 添加缺少编辑模型时确定性规划测试。
- [ ] 添加当前评分器不被外部质量结果覆盖的测试。

### Task 5：启用外部模板并合并HTML渲染器

**目标：** 外部模板成为唯一生产模板，同时保持现有公共入口。

**文件：**

- 新增/恢复 `backend/app/reporting/templates/report.html.j2`
- 合并 `backend/app/reporting/html.py`
- 新增 `backend/app/reporting/html_quality.py`
- 新增 `backend/app/reporting/scenario.py`
- 合并 `backend/app/reporting/presentation.py`
- 合并 `backend/app/reporting/markdown.py`

**步骤：**

- [ ] 把外部 `report.html.j2`加入目标项目。
- [ ] 保留两个旧模板文件，不移动、不删除。
- [ ] 将模板加载固定为 `report.html.j2`。
- [ ] 合并外部模板需要的Jinja上下文和过滤器。
- [ ] 合并SVG文字覆盖层和ID命名空间处理。
- [ ] 实现兼容版 `render_html()`签名。
- [ ] 保留连续编号默认行为。
- [ ] 接入HTML质量门和场景卡片。
- [ ] HTML质量失败返回可诊断错误，不回退旧模板。
- [ ] 增加模板未引用内部流程词汇的测试。

**必须验证：**

- 正文、图表、证据表、质量附录都能渲染。
- 图表与证明它的正文保持相邻。
- 多张图不集中堆放在单一章节尾部。
- 引用编号和图表编号不漂移。
- 旧模板独立存在但运行时不可达。

### Task 6：合并SVG与当前Agent 3能力

**目标：** 吸收外部SVG改善，同时不回退目标项目图表能力。

**文件：**

- `backend/app/reporting/svg.py`
- `backend/tests/reporting/test_svg.py`
- `backend/tests/reporting/test_chart_delivery.py`

**步骤：**

- [ ] 以目标项目 `svg.py`为合并基线。
- [ ] 逐段移植外部调色板、文字、坐标轴和图形增强。
- [ ] 明确保留 `comparison_bar`路由。
- [ ] 为所有当前图表类型建立参数化渲染测试。
- [ ] 验证相同ChartSpec在前端语义与SVG/PDF语义一致。
- [ ] 验证SVG ID在同页多图时不会冲突。

禁止做法：用外部 `svg.py`整文件替换目标文件后再补测试。

### Task 7：合并PDF诊断和视觉复检

**目标：** 支持PDF诊断、确定性视觉检查和有限修复循环。

**文件：**

- 合并 `backend/app/reporting/pdf.py`
- 新增 `backend/app/reporting/visual_review.py`
- 合并 `backend/app/agents/report_fusion/service.py`
- 合并相关测试

**步骤：**

- [ ] 保留现有PDF公开入口。
- [ ] 新增 `render_pdf_with_diagnostics()`。
- [ ] 保留同事件循环内浏览器复用和应用关闭清理。
- [ ] 接入PDF页数、文字布局、空白页和溢出检查。
- [ ] 接入页图、联系表和可选视觉模型。
- [ ] 视觉修复最多执行配置允许的有限次数。
- [ ] 修复只能选择白名单CSS/布局类别，不能改事实正文。
- [ ] 缺少Poppler或ImageMagick时按外部约定软降级并留痕。
- [ ] 模板失败、PDF失败和视觉审核失败分别给出结构化诊断。

### Task 8：接入报告编辑模型和视觉审核模型

**目标：** 完整接入外部可选模型，但默认不强制真实调用。

**文件：**

- `backend/app/integrations/llm/protocol.py`
- `backend/app/integrations/llm/mock.py`
- `backend/app/integrations/llm/factory.py`
- `backend/app/integrations/llm/openai_compatible.py`
- `backend/app/core/config.py`
- `backend/.env.example`
- `backend/app/workflow/factory.py`

**步骤：**

- [ ] 添加 `ReportEditorialModel`协议。
- [ ] 添加 `VisualReviewModel`协议。
- [ ] 添加mock实现和确定性fixture。
- [ ] 合并OpenAI兼容客户端，不替换现有实现。
- [ ] 添加factory创建函数。
- [ ] 只添加新配置字段。
- [ ] 将依赖注入 `ReportFusionAgent`。
- [ ] 配置关闭时不得实例化或调用模型。
- [ ] 配置开启但凭据缺失时遵守现有runtime/readiness策略。
- [ ] 日志不得记录API Key、完整prompt或模型敏感原文。

### Task 9：同步外部测试并保留当前回归测试

**原则：** 测试同样使用合并策略，不能用外部测试目录覆盖当前测试目录。

**建议新增外部测试：**

```text
backend/tests/agents/report_fusion/test_cover_and_scenarios.py
backend/tests/agents/report_fusion/test_page_composition.py
backend/tests/agents/report_fusion/test_html_composer_regressions.py
backend/tests/agents/report_fusion/test_chart_placements.py
backend/tests/agents/report_fusion/test_visual_review.py
backend/tests/reporting/test_public_wording.py
backend/tests/reporting/test_scenario_cards.py
backend/tests/reporting/test_html_quality.py
backend/tests/reporting/test_presentation.py
backend/tests/reporting/test_text_rules_parity.py
backend/tests/reporting/test_html_composer.py
```

**需人工合并的测试：**

```text
backend/tests/agents/report_fusion/test_agent.py
backend/tests/agents/report_fusion/test_render_contract.py
backend/tests/agents/report_fusion/test_visual_planning.py
backend/tests/reporting/test_svg.py
backend/tests/reporting/test_pdf_renderer.py
backend/tests/reporting/conftest.py
```

当前项目特有测试必须保留：

```text
backend/tests/agents/report_fusion/test_quality_scoring.py
backend/tests/reporting/test_emphasis.py
backend/tests/reporting/test_chart_delivery.py
```

### Task 10：前端与契约兼容

**目标：** 新的Agent 5结果不会破坏工作台、质量面板和报告预览。

**文件：**

- `frontend/src/api/types.ts`
- 必要时 `frontend/src/components/QualityPanel.vue`
- 现有mock fixture及其测试

**步骤：**

- [ ] 新字段以可选方式加入TypeScript。
- [ ] 更新Agent 5 mock fixture。
- [ ] QualityPanel在新旧结果上都能工作。
- [ ] 不把完整视觉复检内部对象直接堆到主界面。
- [ ] 报告HTML预览继续读取最终artifact。
- [ ] 运行lint、单测和生产build。

### Task 11：完整验证

按以下顺序执行，某层失败不得跳过：

```bash
cd /Users/Zhuanz1/PycharmProjects/同花顺/backend

.venv/bin/python -m pytest tests/agents/report_fusion -q
.venv/bin/python -m pytest tests/reporting -q
.venv/bin/python -m pytest tests/test_contracts.py tests/workflow -q
.venv/bin/python -m pytest -q
```

前端：

```bash
cd /Users/Zhuanz1/PycharmProjects/同花顺/frontend
npm run lint
npm run test:unit -- --run
npm run build
```

如项目脚本名称不同，先读取 `package.json`后使用已有命令，不自行发明脚本。

生成一份真实演示报告，至少检查：

- [ ] HTML使用外部模板特征。
- [ ] HTML不含旧模板专属标记。
- [ ] PDF可打开且页数大于0。
- [ ] 无空白页、异常续表、中文竖排或大面积异常留白。
- [ ] 图表分散在相关正文附近。
- [ ] `comparison_bar`可见。
- [ ] 图表标题、编号、来源和证据一致。
- [ ] 报告正文没有内部状态码和流程字段名泄漏。
- [ ] 关闭模型时能够完整生成。
- [ ] 开启mock模型时编辑和视觉审核流程可运行。
- [ ] 旧模板文件仍存在，但运行时未读取。

### Task 12：变更审计与交付

**步骤：**

- [ ] `git diff --check`无空白错误。
- [ ] 检查禁止路径未被暂存。
- [ ] 检查没有把外部Agent 3/4旧代码带入。
- [ ] 检查没有新增真实密钥或 `.env`。
- [ ] 输出文件级变更清单。
- [ ] 输出测试命令和结果。
- [ ] 输出已知软降级项，例如缺少Poppler/ImageMagick。
- [ ] 输出模型开关默认状态。
- [ ] 未经用户确认不执行 `git push`。

## 7. 测试矩阵

| 维度 | 必测场景 | 期望 |
| --- | --- | --- |
| 模板 | 正常渲染 | 只加载外部 `report.html.j2` |
| 模板 | 外部模板缺失 | 明确失败，不回退旧模板 |
| 兼容 | 旧ReportViewModel | 可生成报告 |
| 编号 | 默认模式 | 整份报告连续编号 |
| 编号 | `continuous_numbering=False` | 允许章内编号 |
| 图表 | `comparison_bar` | HTML/SVG/PDF均正常 |
| 图表 | 所有当前chart type | 无渲染异常 |
| 落位 | 多图同一小节 | 分散且仍靠近相关正文 |
| 落位 | 用户覆盖 | 用户指定位置优先 |
| 证据 | 多来源和重复来源 | 去重、编号稳定、可追溯 |
| 文本 | 内部状态码/机器ID | 输出前净化 |
| HTML | StrictUndefined | 所需上下文全部提供 |
| PDF | Chromium正常 | PDF有效且诊断通过 |
| PDF | 系统工具缺失 | 软降级并上报，不伪装通过 |
| 编辑模型 | 关闭 | 使用确定性编辑计划 |
| 编辑模型 | mock开启 | 计划可解析并应用 |
| 视觉模型 | 关闭 | 确定性视觉检查仍运行 |
| 视觉模型 | mock开启 | 批量审核和修复次数受限 |
| 质量评分 | 外部规则加入 | 当前100分评分口径不被覆盖 |
| 前端 | 新旧Agent 5结果 | 工作台与预览均不崩溃 |

## 8. 故障处理

### 8.1 外部模板字段缺失

处理顺序：

1. 检查 `ReportViewModel`是否缺少外部字段。
2. 在装配器生成确定性默认值。
3. 增加旧fixture回归测试。
4. 不允许在模板里大量使用静默空值掩盖数据契约缺口。
5. 不回退旧模板。

### 8.2 Agent 3图表渲染回归

1. 确认是否误用了外部 `schemas/chart.py`或 `svg.py`。
2. 恢复以目标实现为基线的合并方式。
3. 增加具体chart type测试。
4. 特别检查 `comparison_bar`。

### 8.3 PDF视觉复检不可用

- Playwright/Chromium不可用：报告交付状态不得标记为完全就绪。
- `pdftoppm`不可用：跳过页面图视觉模型，保留确定性PDF检查并记录降级。
- ImageMagick不可用：跳过联系表，不影响单页检查。
- 视觉模型不可用：使用确定性检查，不允许无限重试。

### 8.4 Skill规则资源不可用

- 使用安全单栏或最小文本净化降级。
- readiness上报缺失资源。
- 不能切回旧模板。

## 9. 回滚设计

本次不删除旧模板，因此人工回滚路径清晰：

1. 回滚Agent 5同步提交。
2. 恢复同步前 `html.py`模板常量和旧渲染入口。
3. 保留新生成artifact，不覆盖历史产物。

禁止实现运行时“外部模板失败就自动切旧模板”。自动回退会掩盖生产故障，并产生不可预测的交付风格。

## 10. 完成定义

只有同时满足以下条件，才能宣称同步完成：

- [ ] 外部模板是唯一生产模板。
- [ ] 旧模板保留但不可达。
- [ ] Agent 5新增模块已接入。
- [ ] 必要skill资源已接入且readiness正常。
- [ ] 当前Agent 3和`comparison_bar`无回归。
- [ ] 当前Agent 4无回归。
- [ ] 当前100分报告质量评分无回归。
- [ ] 新旧报告fixture均能渲染。
- [ ] HTML、PDF、证据、图表和编号测试通过。
- [ ] 后端全量测试通过。
- [ ] 前端lint、单测和build通过。
- [ ] 没有禁止路径、密钥、缓存或产物进入暂存区。
- [ ] 已向用户报告模型开关、软降级项和测试证据。
- [ ] 未经授权没有推送远端或合并main。

## 11. 给执行AI的最终指令

执行本计划时：

1. 先读目标项目 `AGENTS.md`。
2. 先用代码索引定位调用关系，再读取和修改源码。
3. 把目标项目视为主线，把外部目录视为只读参考源。
4. 新文件可以移植；已有文件必须人工合并。
5. 每个任务先写或运行失败测试，再改生产代码。
6. 遇到目标项目已经存在的更新能力，以目标实现为准。
7. 不要用“测试太多”作为跳过全量验证的理由。
8. 不要提交或推送，除非用户明确要求。
9. 如果任何步骤需要删除、覆盖或放弃用户改动，立即停止并向用户说明冲突。

最终汇报必须包含：

- 修改文件清单；
- 外部文件到目标文件的映射；
- 旧模板仍在但不可达的证据；
- 定向测试和全量测试结果；
- HTML/PDF实物验证结果；
- 当前模型开关状态；
- 尚存风险与后续建议。
