# 前端人机审核交互原型 AI 严格执行方案

## 使用方式

把本文件完整交给代码智能体执行。执行目标是生成一个可独立启动、可点击、可演示的前端原型，用来确认最终界面和审核交互。当前阶段不连接后端，不实现真实工作流、SSE、数据库或外部 Skill。

本文件中的“必须”“禁止”“验收”均为强约束。智能体不能把未完成的功能描述为已完成，也不能用静态图片代替交互页面。

## 执行目标

在现有 Vue 3 前端界面和现有路由中增加 Mock 模式。继续使用当前首页 `/`、任务列表 `/runs`、任务工作台 `/runs/:runId`，不另建一套 `/prototype` 页面，不重做导航、三栏布局、报告预览和既有组件。Mock 模式完整展示 Agent 1 至 Agent 5 的审核流程，所有展示数据来自前端固定 fixture；所有可见按钮均能产生明确、可验证的界面变化。

本次工作的性质是“在现有前端上补齐交互”，不是重新设计前端。实现前必须建立“已有组件和按钮映射”，已有能力优先扩展原组件；只有当前组件无法承载的对象级交互才允许新增子组件。

完成后，用户应能独立完成下面的演示：

1. 启动一份 AMD 计算芯片产业研究演示任务。
2. 查看五个智能体的产出和审核状态。
3. 排除或恢复一条证据，查看下游影响提示。
4. 驳回或恢复一个分析结论。
5. 编辑、删除、重生成一张图表，并控制是否纳入报告。
6. 直接编辑一个报告段落，查看修改前后差异。
7. 切换报告风格和输出格式，生成模拟产物。
8. 通过各阶段审核，看到版本号、状态和审核队列同步变化。
9. 刷新页面后保留当前演示进度，并可一键恢复初始状态。

## 不可变更的范围

### 允许修改

- `frontend/src/mock/**`
- `frontend/.env.prototype`
- `frontend/src/App.vue`
- `frontend/src/router.ts`
- `frontend/src/api/client.ts`
- `frontend/src/api/types.ts`
- `frontend/src/views/HomeView.vue`
- `frontend/src/views/RunsView.vue`
- `frontend/src/views/ReviewView.vue`
- `frontend/src/components/ReviewActions.vue`
- `frontend/src/components/WorkbenchActions.vue`
- `frontend/src/components/StageStepper.vue`
- `frontend/src/components/StageDigest.vue`
- `frontend/src/components/MetricCards.vue`
- `frontend/src/components/ChartGallery.vue`
- `frontend/src/components/ReportPreview.vue`
- `frontend/src/components/ReportReader.vue`
- `frontend/src/components/ArtifactList.vue`
- `frontend/src/components/PipelineOverlay.vue`
- `frontend/src/components/review/**`
- `frontend/src/style.css` 中仅增加复用现有设计变量的新组件样式
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/vite.config.ts`
- `frontend/playwright.config.ts`
- `frontend/src/components/__tests__/**`
- `frontend/src/mock/__tests__/**`
- `frontend/e2e/prototype.spec.ts`

### 禁止修改

- `backend/**`
- 现有后端接口、工作流 schema 和数据库
- `frontend/src/api/client.ts` 与 `frontend/src/api/http.ts`
- 现有页面的视觉方向、导航结构和三栏工作台结构
- 现有认证流程
- 任何 API Key、Token 或本机环境凭据

如实现原型不需要改动允许范围外的文件，不得扩大改动范围。

## 技术约束

- 保持现有 Vue 3.5、TypeScript、Pinia、Vue Router、Element Plus、ECharts 技术栈。
- `VITE_DATA_MODE=mock` 时不得发起任何 `/api`、HTTP 或 WebSocket 请求；默认真实模式继续使用现有 API。
- Mock 数据必须是固定 fixture，不使用 `Math.random()`、当前时间或网络数据。
- 所有虚构数字和来源区域显示“演示数据，不代表真实研究结论”。
- Mock 状态持久化到 `localStorage`，键固定为 `trc:prototype:v1`。
- Mock 数据适配器必须与 UI 分离，返回与现有 `client.ts` 相同的核心类型，不得让页面到处出现 `if (mock)` 分支。
- 所有异步演示使用固定延迟；Vitest 使用 fake timers，E2E 使用可检测状态，不依赖盲目 sleep。
- 不安装新的 UI 组件库。端到端测试允许新增 `@playwright/test`。
- 所有交互元素具有键盘焦点样式、可读标签和 `data-testid`。
- 在 1280px 及以上显示三栏工作台；小于 1024px 时右侧检查器改为抽屉，不能出现水平溢出。

## 启动方式

在 `frontend/package.json` 增加：

```json
{
  "scripts": {
    "dev:prototype": "vite --mode prototype",
    "test:prototype": "vitest run prototype",
    "test:e2e": "playwright test"
  }
}
```

新增 `frontend/.env.prototype`：

```ini
VITE_DATA_MODE=mock
```

原型启动命令：

```bash
cd frontend
npm ci
npm run dev:prototype
```

访问首页 `http://localhost:5173/`，从现有“创建研究任务”表单创建 Mock 任务；随后进入现有 `/runs/mock-amd-001` 工作台。

即使本机没有启动后端，页面也必须完整加载并完成全部交互。

## 视觉方向

完整保留当前前端的机构研报风格、颜色变量、字体、页头、卡片、三栏宽度和 Element Plus 组件语言。不得为了原型引入第二套颜色系统、重做首页、替换现有 `page-card`，或把工作台改成另一套通用 Dashboard。

新增组件直接复用 `--rp-navy`、`--rp-gold`、Element Plus 状态色和当前间距体系。新控件应当像现有界面的自然延伸：对象级次要操作使用 link、text 或下拉菜单；阶段级主操作仍由现有 `ReviewActions` 承担。只给“当前选中对象”和浮层添加轻量阴影，不增加高饱和渐变、玻璃拟态和大面积装饰。

## 页面结构

### 首页和任务列表

保留现有 `HomeView` 的表单、快速主题、使用指引和“开始生成研究报告”按钮。在 Mock 模式下，提交该表单直接创建固定演示任务并跳转 `/runs/mock-amd-001`；按钮文字、位置和页面布局保持不变，只在标题附近增加一个小型 `演示模式` 标签。

保留现有 `RunsView` 的表格、刷新按钮、分页和点击行进入任务的行为。Mock 模式返回固定的 3 条演示任务，刷新按钮重新读取 localStorage，不新增第二个“演示任务列表”。

### 任务工作台顶部

保留现有“任务工作台”、状态标签、项目/任务/版本/创建时间、`WorkbenchActions` 和 `刷新` 按钮。在 Mock 模式下只增加：

- 标题旁的 `演示数据` 标签
- `重置演示` 次要按钮
- 执行期间的非阻塞进度提示

现有 `重新融合`、`版本历史`、`刷新` 继续使用，不新增同义按钮。`重置演示` 使用 Popconfirm，确认后清除 `trc:prototype:v1` 并恢复 fixture。

### 左栏项目导航

保留现有 `ProjectTree` 和 250px 左栏，不替换成新的 ReviewQueue。Mock 模式下为项目树提供固定项目和任务数据。五个智能体的状态继续由中央 `StageStepper` 表达，避免左侧项目树与审核队列显示两套相同阶段。

### 中栏阶段工作区

保留现有 `StageStepper`、`QualityPanel`、`MetricCards`、`StageDigest` 和 `ReviewActions`。只做以下增量：

- `StageStepper` 的已产出阶段可点击，用它切换查看 Agent 1 至 Agent 5；当前阶段仍有明显选中态。
- 当前阶段卡片根据阶段在 `StageDigest` 下追加对象级审核区：证据表、结论列表、图表控制、章节控制或融合设置。
- 现有 `ReviewActions` 继续承担阶段级通过、风险确认、修改重跑、原条件重生成和取消任务。
- 不新增底部固定操作栏，不重复“通过”“重跑”“取消”等阶段级按钮。
- 收到模拟新结果时只更新状态和徽标，不强制切换阶段、不改变滚动位置。

### 右栏报告区域

保留现有 360px 右栏和四个标签：`报告预览`、`正文`、`图表`、`产出物`。继续复用 `ReportPreview`、`ReportReader`、`ChartGallery` 和 `ArtifactList`。

对象详情、证据引用、影响范围和版本差异使用一个 `ReviewInspectorDrawer` 抽屉展示，由 `查看详情` 或 `查看影响` 打开。不得常驻新增第四栏，也不得在抽屉中复制删除、通过、重生成和下载按钮。

### 已有按钮冲突处理

| 已有入口 | 保留方式 | 禁止新增的重复入口 |
| --- | --- | --- |
| `通过并继续` | 保留在 `ReviewActions` | 通过当前版本、批准阶段 |
| `确认全部风险并通过` | 保留并继续要求逐项勾选 | 快速风险通过、忽略风险 |
| `修改条件重跑` | 保留为当前阶段唯一自然语言修改入口，并增加输入限制 | 讨论并修改、补充要求、让 AI 修改等多个同义入口 |
| `原条件重新生成` | 保留 | 重新运行、本阶段重做 |
| `取消任务` | 保留 | 终止、停止生成 |
| `重新融合` | 保留在 `WorkbenchActions` | 重新生成报告、再次融合 |
| `修改指令提交` | 与 `修改条件重跑` 功能重复；等待审核时隐藏，非审核态仅作“发起新修订”入口 | 另建全局修改对话框 |
| `版本历史` | 保留并扩展为可查看差异 | 历史记录、版本对比的第二个主按钮 |
| `刷新` | 保留 | 重新加载、同步状态 |
| 图表点击预览 | 保留 | 图表卡片再放一个同义“打开”按钮 |
| `下载` | 保留在 `ArtifactList` | 报告设置区重复下载按钮 |

对象级新增按钮必须放在对应内容内部，不能进入 `ReviewActions` 与阶段级按钮混排。

## Mock 数据要求

新增 `frontend/src/mock/fixtures/amdResearchMock.ts`，至少包含：

- 8 条证据，覆盖公司公告、行业资料、技术资料和公开观点四类来源
- 5 条分析结论，每条带 `claim_id`、证据引用、反证条件和状态
- 4 张图表：折线图、横向柱状图、产业链结构图、双面板对比图
- 3 个章节，每章 2 节，每节至少 2 段；段落具有稳定 ID
- Markdown、HTML、PDF 三种模拟产物记录
- 3 个版本历史快照
- 4 个风险项，其中至少 1 个要求显式确认

所有 fixture ID 固定，例如：

```text
EV-001  CLM-001  CHART-001  SEC-01-01  P-01-01-01  ART-001
```

产业链结构图可用 SVG 或 ECharts graph/sankey 在前端绘制。它只表达设计、晶圆制造、封装测试、板卡、服务器和终端应用之间的结构关系，不显示虚构市场份额或真实公司判断。

## 状态模型

新增 `frontend/src/mock/prototypeRun.ts`。至少包含：

```ts
interface PrototypeState {
  runId: string
  globalRevision: number
  selectedStage: StageId
  selectedObjectId: string | null
  queueFilter: QueueFilter
  stages: Record<StageId, PrototypeStage>
  evidences: EvidenceItem[]
  claims: ClaimItem[]
  charts: ChartItem[]
  chapters: ChapterItem[]
  artifacts: ArtifactItem[]
  risks: RiskItem[]
  operations: PrototypeOperation[]
  history: PrototypeRevision[]
  lastAction: ActionReceipt | null
}
```

store 必须提供并由测试直接调用的 actions：

```text
startSimulation
resetPrototype
selectStage
selectObject
excludeEvidence
restoreEvidence
rejectClaim
restoreClaim
updateChartTitle
changeChartTemplate
regenerateChart
toggleChartInReport
deleteChart
restoreDeletedChart
updateParagraph
restoreParagraph
updateReportSettings
generateArtifacts
approveStage
returnStage
acknowledgeRisk
persist
hydrate
```

每个 action 返回结构化 `ActionReceipt`，包含动作、对象、前后版本、结果和影响对象，供界面显示，不允许按钮执行后无反馈。

## 五个智能体的必做交互

### Agent 1 数据采集

证据表每行提供：`查看`、`排除` 或 `恢复`。排除不是物理删除：状态改为 `excluded`，行保留并变灰。排除前在行内选择固定原因；点击后直接执行，不打开对话输入框。

排除 `EV-003` 后必须发生：

- `CLM-002` 变为 `provisional`
- `CHART-002` 变为 `provisional`
- `SEC-02-01` 显示上游证据变化提示
- 右侧检查器列出以上影响

需要补充研究问题、口径或范围时，使用现有 `ReviewActions` 的 `修改条件重跑`。不得在证据表增加“补充研究要求”按钮。

### Agent 2 数据分析

结论卡片提供：`通过`、`驳回`、`证据不足`、`恢复`、`查看引用`。驳回使用固定原因下拉框加按钮，不打开自由对话。

需要调整因果解释、对比维度或反证方向时，先选中结论，再使用现有 `修改条件重跑`。不得新增“调整分析方向”按钮。对话框不能修改数字事实或证据内容。

### Agent 3 图表生成

每张图表卡提供：

```text
[预览] [编辑标题] [换模板] [换配色] [重新生成]
[纳入/移出报告] [删除/撤销删除] [设为当前修改对象]
```

- 编辑标题使用行内输入。
- 换模板和换配色使用 Select。
- 删除使用 Popconfirm，直接进入 `deleted` 状态，并显示 `撤销删除`。
- 重新生成显示 800ms 固定的 `running` 状态，然后只增加该图的 `unitRevision`。
- 换模板只能显示该图数据兼容的模板选项。
- `设为当前修改对象` 只选中图表，不打开新弹窗。需要描述非标准要求时，继续使用下方现有 `修改条件重跑`。
- 预览弹窗同时支持 ECharts 和前端 SVG 产业链图。

生成图审核区显示节点、箭头、文字、企业、数据五项状态。企业 Logo 允许展示，但本原型使用文字占位；不得调用外部 Logo 服务。

### Agent 4 章节写作

章节区使用紧凑章节树选择稳定 ID，中央显示正文。每个段落只新增：`直接编辑`、`恢复上一版`、`查看引用`、`设为当前修改对象`。

- 直接编辑使用内嵌 textarea，保存后只增加该段落版本。
- 保存时自动生成逐行或逐词差异数据。
- `设为当前修改对象` 不打开弹窗。需要说明改写策略时，继续使用现有 `修改条件重跑`，对话框只接受需保留内容和应避免表达。
- 模拟 AI 改写使用预置的确定性候选文本，禁止运行时随机生成。

### Agent 5 报告融合

报告设置使用 Segmented、Select 和 Checkbox：

- 语气：专业、通俗
- 深度：简洁、标准、详细
- 图表密度：紧凑、均衡、详细
- 格式：Markdown、HTML、PDF
- 摘要长度：短、标准、长

使用现有 `重新融合` 后，产物列表显示所选格式、当前版本、生成时间占位文本和现有 `下载`。下载动作在 Mock 模式生成前端 Blob，文件正文必须带“演示产物”标识，不请求后端。不得新增“生成模拟产物”或“模拟下载”按钮。

需要调整整体叙事时，使用现有 `修改指令提交`；它与审核态的 `修改条件重跑` 互斥显示。章节排序只读显示“七章标准顺序，本原型不支持拖拽”，不新增“调整整体叙事”按钮。

## 受限对话框

新增共享的 `LimitedIntentDialog.vue`，替换 `ReviewActions` 与 `WorkbenchActions` 内部重复的表单内容，但保留两处现有按钮的适用场景和原有位置。任意时刻只能显示一个修改入口：审核态显示 `修改条件重跑`，非审核态需要创建新修订时显示 `修改指令提交`。每次打开必须显示当前对象、版本、允许输入和禁止操作。

根据阶段拒绝以下按钮型指令：

```text
删除、排除、恢复、通过、驳回、重新生成、换模板、换颜色、下载
```

输入包含这些词时：

1. 禁用 `预览修改`。
2. 显示“该操作已有明确按钮，请关闭窗口并使用 ×× 按钮”。
3. 高亮对应按钮所在区域。
4. 不修改 store，不创建版本。

合法输入点击 `预览修改` 后，展示固定的结构化预览：修改对象、准备调整的内容、不受影响的内容、将增加的版本。用户点击 `确认执行` 后才写入 store。

## 文件结构

优先修改和复用现有文件，只增加当前组件不能表达的对象级能力：

```text
frontend/src/
├── api/
│   ├── client.ts                         # 保留真实实现，按模式委托 Mock
│   └── types.ts                          # 补充对象级原型类型
├── mock/
│   ├── client.ts                         # 与现有 client 导出保持同形
│   ├── prototypeRun.ts                   # Mock 状态与 localStorage
│   └── fixtures/
│       └── amdResearchMock.ts             # 固定演示数据
├── components/
│   ├── ReviewActions.vue                  # 复用阶段级按钮
│   ├── WorkbenchActions.vue               # 复用融合与历史按钮
│   ├── StageStepper.vue                   # 增加阶段选择
│   ├── StageDigest.vue                    # 挂载对应对象级区域
│   ├── ChartGallery.vue                   # 在现有卡片增加单图操作
│   ├── ReportReader.vue                   # 在现有正文增加段落操作
│   └── review/
│       ├── EvidenceReviewTable.vue        # 新增
│       ├── ClaimReviewList.vue            # 新增
│       ├── ChartControlMenu.vue            # 新增，供 ChartGallery 使用
│       ├── ChapterEditPanel.vue            # 新增，供 ReportReader 使用
│       ├── FusionSettings.vue              # 新增，供报告融合阶段使用
│       ├── LimitedIntentDialog.vue          # 新增，共享唯一修改表单
│       ├── ReviewInspectorDrawer.vue        # 新增，详情与影响范围
│       └── RevisionDiffDialog.vue           # 新增，复用版本历史入口
└── views/
    ├── HomeView.vue                        # Mock 创建任务
    ├── RunsView.vue                        # Mock 任务列表
    └── ReviewView.vue                      # 组装增量组件，保留三栏
```

不增加新路由。Mock 与真实模式使用同一套页面；`VITE_DATA_MODE` 只切换数据提供方式。实现后若发现新增组件复制了现有组件超过一半的模板或按钮，应停止并改为向现有组件增加 props、slots 或 emits。

## 测试要求

### Store 单元测试

新增 `frontend/src/mock/__tests__/prototypeRun.spec.ts`，至少覆盖：

1. fixture 初始化结果固定。
2. 排除和恢复证据。
3. 证据排除后的下游 provisional 传播。
4. 驳回和恢复结论。
5. 单图重生成只增加目标图版本。
6. 删除图和撤销删除。
7. 段落编辑只改变目标段落。
8. 风险未确认时不能通过阶段。
9. localStorage 持久化和恢复。
10. reset 清除持久化状态。

### 组件测试

至少新增以下测试：

- 扩展现有 `ReviewActions` 测试：原按钮仍存在且行为不变，审核态不会同时显示 `修改指令提交`。
- `ChartGallery.prototype.spec.ts`：现有点击预览仍可用，新增图表菜单改变正确状态，图片/SVG 与 ECharts 都可预览。
- `ReportReader.prototype.spec.ts`：现有 Markdown 阅读和引用悬浮仍可用，段落编辑、取消、保存和差异展示正常。
- `LimitedIntentDialog.spec.ts`：按钮型指令被拒绝，合法意图可预览和确认。
- `ReviewView.prototype.spec.ts`：三栏结构、现有四个右侧标签和已有主按钮没有重复出现。

组件测试不能只检查组件成功挂载，必须触发真实点击并断言界面与 store 状态。

### Playwright 端到端测试

新增 `@playwright/test`、`frontend/playwright.config.ts` 和 `frontend/e2e/prototype.spec.ts`。至少覆盖：

1. 无后端时打开 `/`，使用现有表单创建任务并进入 `/runs/mock-amd-001`。
2. 拦截并记录全部请求；若出现 `/api` 请求，测试立即失败。
3. Mock 模式不弹 TokenDialog；真实模式的鉴权逻辑没有被删除。
4. 模拟生成期间页面仍能切换已产出阶段和查看内容。
5. 完成 Agent 1 至 Agent 5 的主要审核路径。
6. 刷新后状态保留，重置后恢复初始状态。
7. 受限对话框拒绝“删除这张图”，并提示使用删除按钮。
8. `通过并继续`、`修改条件重跑`、`原条件重新生成`、`取消任务`、`重新融合`、`版本历史`、`刷新`、`下载` 在各自作用域内最多出现一次。
9. 1440×960 桌面布局保持当前三栏结构，没有关键元素重叠。
10. 900×1000 视口可浏览全部内容且页面无水平滚动。

保存一张稳定的桌面截图作为视觉基线。截图中不允许出现当前时间、随机数或不稳定动画帧。

首次增加端到端测试依赖时执行，并同步提交更新后的 lockfile：

```bash
cd frontend
npm install --save-dev @playwright/test
npx playwright install chromium
```

## 最终验证命令

智能体完成代码后必须依次运行：

```bash
cd frontend
npm run type-check
npm run lint
npm run format:check
npm run test
npm run build
npm run test:e2e
```

还必须启动原型完成一次人工烟雾验证：

```bash
npm run dev:prototype -- --host 127.0.0.1
```

烟雾验证至少确认：页面可打开、浏览器控制台无 error、Network 中没有 `/api` 请求、五个阶段可切换、删除/恢复/重生成/编辑/通过均产生可见反馈。

若任何命令失败，智能体必须修复后重跑。不得用 `--no-verify`、跳过测试、删除失败测试或降低 TypeScript/ESLint 严格度来换取通过。

## 完成定义

只有同时满足以下条件才能报告完成：

- `/`、`/runs`、`/runs/mock-amd-001` 在后端未启动时可独立使用。
- 现有导航、首页、任务列表、三栏工作台和右侧四个标签保持原有视觉结构。
- 五个智能体都有可浏览内容和可执行审核动作。
- 所有可见按钮都有反馈，没有装饰性死按钮。
- 按钮与对话框功能不重复。
- 同一作用域没有重复的通过、重跑、修改、融合、历史、刷新或下载按钮。
- 对话框会明确限制输入范围并拒绝按钮型指令。
- Mock 状态、版本、影响传播和 localStorage 恢复正常。
- 桌面和窄屏布局可用。
- `type-check`、`lint`、`format:check`、`test`、`build`、`test:e2e` 全部通过。
- 最终回复列出新增/修改文件、启动方式、测试结果和仍未实现的真实后端能力。

## 明确不属于本次完成范围

- 真实数据可信度与真实报告结论
- 后端 API、SSE、数据库和任务队列
- 多用户并发审核
- 真实 PDF 服务端渲染
- 外部生图模型和真实 Logo 服务
- SkillHub 与 LLM 调用
- 正式权限、发布和审计存储

这些能力后续按照《前端人机审核与流式交互落地方案》接入。当前原型的价值是先确认界面、操作密度和五阶段人机审核方式。
