# 同花顺问财 SkillHub 五智能体行业研究研报系统
## 核心技术架构与微观组件全景规范说明书 (Architecture Specification)

> **版本**: v2.4 (Competition Production Ready)  
> **交互式架构图**: [`output/architecture/system-architecture.html`](output/architecture/system-architecture.html)  
> **技术栈**: Python 3.10+ · FastAPI · Vue 3 · Vite · Element Plus · ECharts · DeepSeek V4 Flash (Volcengine ARK) · 同花顺问财 SkillHub OpenAPI

---

## 一、 系统总体分层与微观拓扑 (Layered Architecture)

系统划分为 **前端交互工作台**、**服务网关与状态机编排层**、**五智能体流水线核心层**、**外部生态与基座模型** 四大层级。

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                   前端交互层 (Vue 3 + Vite + ECharts)                             │
│  [AgentLiveCockpit 驾驶舱]  [FeedbackWorkbench 审核台]  [ChartGallery 画廊]  [ReportReader 阅读器]   │
└─────────────────────────────────┬───────────────────────────────────────────────────────────────┘
                                  │ HTTP REST (15 Endpoints) + SSE Event Stream
┌─────────────────────────────────▼───────────────────────────────────────────────────────────────┐
│                                服务网关与编排层 (FastAPI + WorkflowEngine)                         │
│  [FastAPI Router :8000] ──► [WorkflowEngine 状态机] ──► [EventHub SSE广播] ──► [File Storage]     │
└─────────────────────────────────┬───────────────────────────────────────────────────────────────┘
                                  │ 驱动执行与数据契约流转
┌─────────────────────────────────▼───────────────────────────────────────────────────────────────┐
│                               五智能体流水线 (5-Stage Multi-Agent Pipeline)                       │
│                                                                                                 │
│  Stage 1: 数据获取智能体 (DataFetcherAgent)                                                       │
│    ├─ LLM 采集规划器 (Query Planner) ──► 覆盖度评估器 (Coverage Evaluator)                        │
│    ├─ 问财 7 大技能集: astock / sector / macro / finance / industry-chain / money-flow / valuation   │
│    └─ DataFusion 融合引擎: 实体模糊对齐 / 亿元-万元单位归一 / 缺失值智能补齐 ──► dataset.json       │
│                                                                                                 │
│  Stage 2: 数据解读智能体 (DataInterpreterAgent)                                                   │
│    ├─ 确定性量化引擎: CAGR 复合增速 / 稳健 Z-Score 极值检测 / 资产负债-利润-现金流三表勾稽平衡校验     │
│    ├─ 产业链拓扑提取器: 上中下游供需树构建 / 市值权重龙头识别 / 股票代码转中文简称消歧                │
│    └─ LLM 语义融合推理: 波特五力 / SWOT / 周期定位 / 研报事实与数据强绑定 ──► interpretation_report.json│
│                                                                                                 │
│  Stage 3: 图表生成智能体 (ChartGeneratorAgent)                                                   │
│    ├─ 图表规划引擎: 16 类金融图表智能匹配 / 8~12 动态图表配额 / 降级兜底回退                        │
│    ├─ 双通道渲染管线:                                                                            │
│    │    ├─ ECharts 编译器: JSON Option 编译 / 交互动画 / Tooltip / 时间轴自适应                    │
│    │    └─ SVG 矢量渲染器: 纯 Python 数学几何 / Bezier 曲线 / 960×520 出版级排版                  │
│    ├─ MetricGuard 金融质检: IQR 极值截断 / 坐标轴单位混用拦截 / X 轴长标签防重叠旋转                │
│    └─ 跨智能体补数回路: 图表数 < 4 且存在缺口时 ──► 自动回调 Stage 1 定向补数 ──► chart_result.json │
│                                                                                                 │
│  Stage 4: 章节撰写智能体 (ChapterWriterAgent)                                                     │
│    ├─ 7 大核心章节骨架: 摘要 / 概况 / 格局 / 财务 / 产业链 / 趋势与风险 / 投资建议                    │
│    ├─ 21 节全并发撰写管线: asyncio.gather 并发批处理 / 独立小节上下文创作                           │
│    └─ 锚点插桩引擎: 精准注入 Stage 2 数据事实与 Stage 3 图表资产 ──► chapter_result.json          │
│                                                                                                 │
│  Stage 5: 研报融合智能体 (ReportFusionAgent)                                                     │
│    ├─ 4 大主编级审校技能:                                                                        │
│    │    ├─ Chief Executive Summary: 首席摘要提炼与核心投资评级矩阵                                │
│    │    ├─ Consistency & Logic Audit: 跨章节数据一致性交叉审计与冲突消解                          │
│    │    ├─ Typography & Visual Styling: 出版级版心排版与视觉渲染规范                              │
│    │    └─ Evidence Catalog & Citation: 原始数据证据索引与引用文献溯源                            │
│    └─ 多格式编译发布引擎: Markdown 原生稿 / 交互式 HTML 长图 / 出版级 A4 矢量 PDF                  │
└─────────────────────────────────┬───────────────────────────────────────────────────────────────┘
                                  │ 外部依赖调用
┌─────────────────────────────────▼───────────────────────────────────────────────────────────────┐
│                                   外部生态与底层基座                                              │
│  [同花顺问财 SkillHub OpenAPI] (实时行情/财务)   [火山引擎 DeepSeek V4 Flash] (64K 语义推理基座)     │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 二、 五智能体核心微观架构与实现代码映射

### Stage 1: 数据获取智能体 (DataFetcher)
* **代码路径**: `agents_core/data-fetcher/data_fetcher/`
* **核心类与函数**:
  * `DataFetcherAgent.run()` (`agent.py`): 智能体执行入口，接收研究主题与深度参数。
  * `SkillHubAdapter` (`skillhub.py`): 问财技能路由适配器，管理 7 个金融 OpenAPI 技能：
    1. `hithink-astock-query`: 个股行情、基本面财务与估值指标。
    2. `hithink-sector-query`: 申万一二级行业、概念板块历史行情与指数。
    3. `hithink-macro-query`: GDP、CPI、PPI、M2、社融总额等宏观经济指标。
    4. `hithink-finance-query`: 资产负债表、利润表、现金流量表与核心财务比率。
    5. `hithink-industry-chain-query`: 产业链上下游拓扑关系、原材料与下游应用。
    6. `hithink-money-flow-query`: 主力资金流向与南北向资金动态。
    7. `hithink-valuation-query`: 行业历史市盈率 PE-TTM、市净率 PB 分位数。
  * `DataFusion.merge_and_normalize()` (`fusion.py`): 多源实体对齐（支持括号后缀模糊匹配 `[300750]` -> `宁德时代`）、单位标准化（统一将亿元、万元转换为统一单位）、缺失值清洗。
* **产出数据契约**: `dataset.json` (包含 `macro`, `sector`, `stocks`, `financials`, `chain` 等 7 个领域结构化数据)。

---

### Stage 2: 数据解读智能体 (DataInterpreter)
* **代码路径**: `agents_core/data-analysis/data_interpreter/`
* **核心类与函数**:
  * `DataInterpreterAgent.run()` (`agent.py`): 驱动确定性分析与 LLM 语义融合。
  * `DeterministicEngine` (`engine.py`): 确定性金融量化计算库：
    * `calculate_cagr(start_val, end_val, years)`: 复合年均增长率测算。
    * `detect_zscore_outliers(series, threshold=2.5)`: 稳健极值异常波动检测。
    * `reconcile_three_statements(balance, income, cashflow)`: 资产负债表平衡校验（资产=负债+权益）、净利润与经营现金流勾稽核验。
    * `extract_industry_chain(raw_data)`: 上中下游拓扑树构建、龙头标的权重提取。
    * `resolve_ticker(ticker_code)`: 股票代码消歧与公司中文全称/简称双向映射。
  * `SemanticFusion` (`agent.py`): 调用 DeepSeek 实施波特五力模型分析、SWOT 矩阵推演、行业生命周期定位，生成强事实绑定的量化洞察。
* **产出数据契约**: `interpretation_report.json` (包含量化指标、产业链拓扑结构、核心事实、异常预警与证据索引表)。

---

### Stage 3: 图表生成智能体 (ChartGenerator)
* **代码路径**: `agents_core/chart-generator/chart_generator/`
* **核心类与函数**:
  * `ChartGeneratorAgent.run()` (`agent.py`): 接收量化解读报告，自适应匹配 8~12 张图表。
  * **16 种金融图表全矩阵覆盖**:
    * **直角坐标系 (Cartesian)**: `line` (趋势折线图), `bar` (对比柱状图), `comparison_bar` (双指标柱状图), `horizontal_bar` (横向排名条形图), `diverging_bar` (发散正负条形图), `area` (堆叠面积图), `combo` (双轴折线柱状组合图)。
    * **非直角坐标系 (Non-Cartesian)**: `pie` (行业构成饼图), `donut` (环形占比图), `radar` (企业多维能力雷达图), `scatter` (估值与成长散点图), `bubble` (三维气泡图), `heatmap` (行业景气度热力图), `boxplot` (估值区间箱线图), `treemap` (细分市场树状分布图)。
    * **拓扑关系系 (Topology)**: `industry_chain` (上中下游产业链全景网络拓扑图)。
  * `EChartsCompiler.compile()` (`compiler.py`): 编译为标准前端 ECharts JSON Option，自带动态 Tooltip、DataZoom 缩放、图例联动与平滑加载。
  * `SVGRenderer.render()` (`render.py`): 纯 Python 数学几何引擎（不依赖任何第三方二进制浏览器渲染器），生成 960×520 出版级矢量 SVG 图，支持中文自动折行、阴影、微渐变。
  * `MetricGuard` (`metric_guard.py`) & `ChartLinter` (`linter.py`):
    * 拦截单位混用（禁止同一坐标轴混排“亿元”与“%”）。
    * IQR 极值截断与防破位处理。
    * X 轴时间标签防重叠引擎（自适应倾斜旋转与隔项显示）。
  * **跨智能体补数机制 (Feedback Loop)**: 当产出有效图表不足 4 张且存在未满足数据需求时，通过 `DataFetcherAgent.fetch_supplemental()` 自动触发单轮增补采集。
* **产出数据契约**: `chart_result.json` & `artifacts/charts/*.svg`。

---

### Stage 4: 章节撰写智能体 (ChapterWriter)
* **代码路径**: `agents_core/chapter-writer/chapter_writer/`
* **核心类与函数**:
  * `ChapterWriterAgent.run()` (`agent.py`): 全局统筹 7 章 21 节研报创作。
  * **7 大标准研报骨架章节**:
    1. `Chapter 1: 核心摘要与投资评级` (行业核心逻辑、评级展望、关键风险)。
    2. `Chapter 2: 行业全景与发展历程` (宏观环境、政策梳理、历史周期)。
    3. `Chapter 3: 市场格局与竞争分析` (CRn 集中度、龙头壁垒、市占率变迁)。
    4. `Chapter 4: 财务透视与盈利质量` (营收成长性、毛利率/净利率、三费控制、现金流质量)。
    5. `Chapter 5: 产业链生态深度剖析` (上游原材料/设备、中游制造加工、下游消费场景)。
    6. `Chapter 6: 未来发展趋势与风险矩阵` (技术路线更迭、替代品威胁、监管与地缘风险)。
    7. `Chapter 7: 投资策略建议与重点标的` (选股逻辑、估值安全边际、催化剂事件)。
  * `ConcurrentWriterEngine`: 使用 `asyncio.gather` 实现 21 个小节全并发 LLM 创作池，各节独立挂载针对性上下文，整体撰写速度提升 400% 以上。
  * `AnchorInjector`: 将 Stage 2 数据事实与 Stage 3 图表引用标签（`![图表X](charts/chart_x.svg)`）精准嵌入正文。
* **产出数据契约**: `chapter_result.json` (7 章 21 节结构化段落、表格与插图锚点)。

---

### Stage 5: 研报融合智能体 (ReportFusion)
* **代码路径**: `agents_core/report-fusion/report_fusion/`
* **核心类与函数**:
  * `ReportFusionAgent.run()` (`agent.py`): 聚合前置所有产物，执行主编审校。
  * **4 大主编级审校技能组**:
    1. `ExecutiveSummarySkill`: 提炼 800 字顶级券商首席投资备忘录。
    2. `ConsistencyAuditSkill`: 全文交叉审计，检查章节间数字、结论、龙头观点的一致性，自动消解冲突。
    3. `TypographySkill`: 统一排版版心、标题层级（H1~H4）、金融专业表格规范、高亮引用块。
    4. `EvidenceCatalogSkill`: 编译原始数据溯源目录，为每一项结论标注数据源（问财/官方统计局）。
  * `MultiFormatCompiler`:
    * `report.md`: Markdown 源码归档。
    * `report.html`: 响应式交互式长图网页，内置图表动态渲染与锚点导航。
    * `report.pdf`: 出版级 A4 矢量 PDF 文档（通过 WeasyPrint / Chrome Headless 编译）。
* **产出数据契约**: `report.md`, `report.html`, `report.pdf`。

---

## 三、 后端服务编排与事件总线规范 (Backend & Engine)

### 1. 状态机模型 (WorkflowEngine)
* **状态枚举**: `pending` ──► `running` ──► `waiting_review` ──► `approved` ──► `completed` (或 `failed`, `cancelled`)。
* **人机协同断点 (Review Gates)**:
  * 默认在前两个阶段 (`data_fetch`, `data_interpret`) 完成后自动挂起进入 `waiting_review`。
  * 支持 6 种人工审核动作：
    1. `approve`: 批准并继续下一阶段。
    2. `accept_recommendation`: 采纳智能体建议并推进。
    3. `accept_with_risks`: 标记风险并强制放行。
    4. `customize`: 注入定向修改提示词。
    5. `revise`: 回退修改当前阶段产物。
    6. `regenerate`: 清空当前阶段并重新执行。

### 2. EventHub 实时事件总线
* **环形缓冲池**: 内存维护 500 条最新事件的滑动窗口。
* **持久化**: 异步写入 `data/runs/{run_id}/events.jsonl`，崩溃重启后自动回放。
* **SSE 推送**: 端点 `/api/v1/runs/{run_id}/events/stream`，前端秒级接收智能体动线。

### 3. API 路由清单 (15 个核心端点)
| HTTP 方法 | 路径 | 功能描述 |
|---|---|---|
| `POST` | `/api/v1/runs` | 创建并异步启动研报生成任务 |
| `GET` | `/api/v1/runs` | 分页获取所有研报任务列表及状态摘要 |
| `GET` | `/api/v1/runs/{id}` | 获取特定任务的完整运行态工作流状态 |
| `DELETE` | `/api/v1/runs/{id}` | 彻底删除任务及其磁盘关联产物 |
| `POST` | `/api/v1/runs/{id}/reviews` | 提交人机协同审核决策 (approve/revise/regenerate) |
| `POST` | `/api/v1/runs/{id}/cancel` | 中止正在执行的智能体流水线 |
| `POST` | `/api/v1/runs/{id}/resume` | 从断点处恢复执行未完成的任务 |
| `GET` | `/api/v1/runs/{id}/events` | 获取任务的历史事件动线全记录 |
| `GET` | `/api/v1/runs/{id}/events/stream` | Server-Sent Events (SSE) 实时动线流 |
| `GET` | `/api/v1/runs/{id}/revisions` | 获取任务历史版本演进记录 |
| `GET` | `/api/v1/runs/{id}/feedback-history` | 获取人工反馈与修订历史记录 |
| `GET` | `/api/v1/runs/{id}/artifacts/{artifact_id}` | 下载指定产物 (MD/HTML/PDF/JSON/SVG) |
| `GET` | `/api/v1/settings/config` | 获取当前大模型与问财凭证配置 |
| `POST` | `/api/v1/settings/config` | 热更新大模型/问财配置 (无需重启后端) |
| `POST` | `/api/v1/settings/test-llm` | 实时测试火山引擎 DeepSeek 连通性 |

---

## 四、 前端架构与组件树 (Vue 3 + Vite)

前端采用 **Vue 3 Composition API** + **Pinia 状态管理** + **Element Plus UI** + **ECharts 5**，共包含 33 个核心组件与 7 个顶级视图：

```
frontend/src/
├── views/
│   ├── LandingView.vue           # 系统首页与研报能力总览
│   ├── HomeView.vue              # 研报看板主视窗
│   ├── CreateRunView.vue         # 研报任务新建视窗 (支持深度/模式配置)
│   ├── RunsView.vue              # 任务历史列表与产物下载中心
│   ├── ReviewView.vue            # 人机交互审核核心视窗
│   ├── ReportPreviewView.vue     # 研报大纲与全文在线阅读预览
│   └── ReportDownloadView.vue    # PDF/HTML/MD 多格式一键下载
└── components/
    ├── AgentLiveCockpit.vue      # 五智能体全链路动线实时驾驶舱
    ├── AgentLiveTrace.vue        # 实时流式工具调用与阶段脉冲组件
    ├── FeedbackWorkbench.vue     # 定向反馈与人工修订工作台
    ├── ReviewActions.vue         # 审核操作按钮组 (批准/放行/重跑)
    ├── ChartGallery.vue          # 16 类金融图表画廊 (防重叠/双通道展示)
    ├── StageStepper.vue          # 五阶段线性进度步进条
    ├── StageDigest.vue           # 各阶段结构化产物摘要卡片
    ├── MetricCards.vue           # 核心金融量化指标卡片群
    ├── QualityPanel.vue          # 研报合规与质检结果面板
    ├── EvidenceDrawer.vue        # 原始数据证据溯源抽屉
    ├── RevisionDiffViewer.vue    # 历史版本对比与差异比对器
    ├── SettingsModal.vue         # LLM 与问财参数热配弹窗
    └── TokenDialog.vue           # Token 消耗与性能监控统计
```

---

## 五、 测试验证与质量保障 (Verification Suite)

所有微观模块均具备独立完备的自动化单元测试与集成测试：

```bash
# 1. 前端自动化测试套件 (66 个测试用例全部通过)
cd frontend && npm test

# 2. 图表生成智能体测试 (32 个测试全部通过)
cd agents_core/chart-generator && pytest

# 3. 数据解读智能体测试 (16 个测试全部通过)
cd agents_core/data-analysis && pytest

# 4. 数据获取智能体测试 (27 个测试全部通过)
cd agents_core/data-fetcher && pytest -m "not live"

# 5. 章节撰写智能体测试 (8 个测试全部通过)
cd agents_core/chapter-writer && pytest

# 6. 研报融合智能体测试 (7 个测试全部通过)
cd agents_core/report-fusion && pytest

# 7. 后端网关与状态机测试 (5 个端到端测试全部通过)
PYTHONPATH=. pytest backend/tests
```
