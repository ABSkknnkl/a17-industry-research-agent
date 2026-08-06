# A17 项目从零搭建到当前阶段完成说明

## Agent 3（可视化图表智能体）P0 交接版

**适合阅读对象：** 没有参与过本项目的新成员、前端开发者、Agent 1/Agent 5 开发者、测试人员。
**文档目的：** 让新成员知道项目为什么这样设计、如何在电脑上启动、每个目录做什么、五个 Agent 如何协作，以及当前已经完成了什么。
**项目目录：** `/Users/Zhuanz1/PycharmProjects/同花顺`
**本文档对应阶段：** Agent 3 后端 P0 已完成，前端图表页面和 Agent 1/Agent 5 仍需继续开发。
**完成日期：** 2026-08-06

---

## 目录

1. [项目是做什么的](#1-项目是做什么的)
2. [项目从哪里开始搭建](#2-项目从哪里开始搭建)
3. [第一次搭建需要哪些环境](#3-第一次搭建需要哪些环境)
4. [项目目录如何理解](#4-项目目录如何理解)
5. [后端是如何搭建的](#5-后端是如何搭建的)
6. [前端是如何搭建的](#6-前端是如何搭建的)
7. [五阶段工作流如何运行](#7-五阶段工作流如何运行)
8. [五个 Agent 分别负责什么](#8-五个-agent-分别负责什么)
9. [Agent 3 为什么需要单独开发](#9-agent-3-为什么需要单独开发)
10. [Agent 3 当前完成的功能](#10-agent-3-当前完成的功能)
11. [Agent 3 的输入和输出](#11-agent-3-的输入和输出)
12. [Agent 3 的完整处理过程](#12-agent-3-的完整处理过程)
13. [人机审核和版本管理](#13-人机审核和版本管理)
14. [数据、文件和安全设计](#14-数据文件和安全设计)
15. [当前项目状态](#15-当前项目状态)
16. [如何启动和验证项目](#16-如何启动和验证项目)
17. [后续成员如何接着开发](#17-后续成员如何接着开发)
18. [开源项目借鉴说明](#18-开源项目借鉴说明)
19. [常见问题](#19-常见问题)
20. [当前阶段验收结论](#20-当前阶段验收结论)

---

## 1. 项目是做什么的

### 1.1 用通俗的话说明

用户输入一个行业，例如“新能源汽车”或“半导体”，系统需要自动完成：

1. 获取行业、公司、财务、行情、宏观和产业链数据。
2. 检查数据来源、时间、单位、币种和可比范围。
3. 分析数据背后的趋势、竞争、风险和产业链变化。
4. 生成折线图、柱状图和产业链图。
5. 按标准行业研究报告结构撰写正文。
6. 将正文、表格、图表、摘要和结论组装成 Markdown、HTML 或 PDF。
7. 让用户在每个阶段审核、补充和重新生成。

因此，本项目不是一个简单的“问一句答一句”聊天工具，而是一条可暂停、可审核、可修改、可恢复的研究报告生产流水线。

### 1.2 比赛题目要求对应关系

比赛要求五阶段智能体流水线：

```text
数据获取 → 数据解读 → 可视化图表 → 分章节生成 → 报告融合
```

项目将它实现为五个稳定的 LangGraph 节点：

| 比赛要求 | 代码中的阶段名 | 主要职责 |
|---|---|---|
| 数据获取 | `data_fetch` | 获取数据、清洗数据、保存证据 |
| 数据解读 | `data_interpret` | 进行金融分析、输出结论和图表候选 |
| 可视化图表 | `chart_generate` | 根据标准数据生成图表配置 |
| 分章节生成 | `chapter_write` | 生成 7 章 21 节报告内容 |
| 报告融合 | `report_fusion` | 融合章节并导出最终报告 |

### 1.3 为什么要分成五个 Agent

如果由一个大模型一次性完成所有工作，会出现以下问题：

- 数据获取、数据分析和文字生成混在一起，出错后难以定位。
- 用户无法知道某个数字从哪里来。
- 图表可能和正文使用不同的数据口径。
- 一次失败只能全部重新生成，浪费时间和模型调用量。
- 用户无法只修改某一个阶段。

分阶段后，每个 Agent 只负责一种工作，阶段之间通过公共契约传递结构化结果。

---

## 2. 项目从哪里开始搭建

### 2.1 第一步：确定技术路线

项目初始先确定以下技术路线：

- 后端：Python 3.12 + FastAPI。
- 工作流：LangGraph 1.x。
- 数据模型：Pydantic 2。
- 大模型：OpenAI 兼容接口，可接 Qwen、DeepSeek 等模型；开发阶段使用 Mock。
- 前端：Vue 3 + TypeScript + Vite + Element Plus。
- 图表：ECharts，前端使用 `vue-echarts`。
- 检查点：SQLite 版 LangGraph Checkpointer。
- PDF：Playwright Chromium。
- 契约：根目录 `contracts/` 下的 JSON Schema。

选择这套结构的原因是：

1. Python 适合金融数据处理和后端 Agent 开发。
2. LangGraph 支持节点编排、暂停、审核、恢复和持久化。
3. Pydantic 可以在 Agent 边界阻止错误字段进入下一阶段。
4. Vue + ECharts 适合浏览器端展示图表和审核流程。
5. Mock 可以让成员在没有真实 Token 的情况下并行开发。

### 2.2 第二步：建立 Monorepo 目录

项目采用一个仓库同时保存前端、后端、公共契约和文档：

```text
同花顺/
├── backend/       # Python 后端、五个 Agent、Workflow、API
├── frontend/      # Vue 3 浏览器前端
├── contracts/     # 前后端和 Agent 之间的唯一公共契约
├── docs/          # 架构、环境、分工、计划和交接文档
├── config/        # 工具和外部服务配置
├── scripts/       # 全仓验证脚本
├── skills/        # 项目使用的技能资产
├── production/    # 生产记录和会话记录
├── .python-version
├── .nvmrc
└── README.md
```

### 2.3 第三步：先让骨架可以启动

项目搭建初期没有马上实现完整业务，而是先完成：

- 后端 FastAPI 可以启动。
- `/health` 健康检查可用。
- `/api/v1/ping` API 连通性检查可用。
- `/docs` 可以打开 FastAPI OpenAPI 文档。
- 前端 Vite 可以启动并访问后端代理。
- 五个阶段先使用 Mock，保证工作流可以从头走到尾。
- 前后端都能执行自动化测试和构建。

这样做的好处是：即使 Agent 1、Agent 3 或 Agent 5 尚未完成，其他成员也可以基于稳定接口开发和测试。

### 2.4 第四步：冻结跨模块契约

项目规定 `contracts/` 是跨端唯一契约源。也就是说，前端、后端和各个 Agent 不能各自随意设计字段。

目前主要契约包括：

- `WorkflowState`：整个运行任务的状态。
- `StageResult`：一个阶段的结果。
- `ArtifactRef`：JSON、图片、HTML 或 PDF 文件的引用。
- `ReviewRequest`：人工审核、修改、重新生成和取消命令。
- `ChartGenerationResult`：Agent 3 的图表生成结果。
- `ChapterWritingResult`：Agent 4 的 7 章 21 节结果。

---

## 3. 第一次搭建需要哪些环境

### 3.1 统一版本

项目已经固定主版本：

| 工具 | 版本要求 | 项目文件 |
|---|---|---|
| Python | 3.12 | `.python-version` |
| Node.js | 22 | `.nvmrc` |
| npm | 10+ | `frontend/package.json` |
| 浏览器 | Playwright Chromium | 用户缓存目录 |

所有成员必须使用相同主版本。不要把虚拟环境、Node 模块、浏览器缓存或 `.env` 提交到 Git。

### 3.2 创建后端虚拟环境

```bash
cd /Users/Zhuanz1/PycharmProjects/同花顺/backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
```

这里的 `.venv` 只属于本机开发环境，不需要上传给其他成员。其他成员根据依赖文件重新创建即可。

### 3.3 安装 Chromium

```bash
python -m playwright install chromium
```

Playwright 的 Python 包和 Chromium 浏览器是两件事：

- `playwright` 是 Python 调用接口。
- Chromium 是实际执行网页渲染和 PDF 导出的浏览器。

浏览器默认保存在用户缓存目录，不放入项目仓库，也不随代码上传。部署服务器需要单独执行安装命令。

### 3.4 配置后端环境变量

```bash
cp .env.example .env
```

开发阶段可使用 Mock：

```env
LLM_USE_MOCK=true
LLM_API_KEY=
SKILLHUB_API_KEY=
```

真实密钥只能写在本机的 `.env`，不能写进 Python 文件、Prompt、前端代码、报告、日志或 Git。

### 3.5 安装前端依赖

打开另一个终端：

```bash
cd /Users/Zhuanz1/PycharmProjects/同花顺/frontend
npm ci
cp .env.example .env
```

前端主要依赖：

| 依赖 | 用途 |
|---|---|
| Vue 3 | 页面和组件框架 |
| TypeScript | 类型安全 |
| Vite | 开发服务器和生产构建 |
| Element Plus | UI 组件 |
| Pinia | 跨页面工作流状态 |
| Vue Router | 页面路由 |
| Axios | 调用后端 API |
| ECharts | 浏览器图表渲染 |
| vue-echarts | Vue 对 ECharts 的封装 |
| Vitest | 前端测试 |

### 3.6 依赖为什么必须保持一致

成员之间必须保持：

- Python 主版本一致。
- Node.js 主版本一致。
- `requirements.txt` 版本范围一致。
- `package-lock.json` 一致。
- Playwright 浏览器版本一致。
- Pydantic、LangGraph、ECharts 的契约版本一致。

否则可能出现：本地能运行、其他成员不能运行；同一个 JSON 在不同环境校验结果不同；PDF 字体或图表渲染效果不同。

---

## 4. 项目目录如何理解

### 4.1 后端目录

```text
backend/app/
├── api/              # FastAPI 路由
├── agents/           # 五个阶段的 Agent
├── core/             # 应用配置
├── infrastructure/   # SQLite、文件存储等基础设施
├── integrations/     # SkillHub 和 LLM 适配器
├── reporting/        # 图表、HTML、PDF 渲染设施
├── runtime/          # 运行预算、超时、ToolGateway
├── schemas/          # Pydantic 公共模型
├── security/         # 认证、归属、限流、审计和输入防护
└── workflow/         # LangGraph 编排、暂停、恢复和状态转换
```

### 4.2 Agent 目录

```text
backend/app/agents/
├── data_fetcher/       # Agent 1，当前占位
├── data_interpreter/   # Agent 2，真实实现
├── chart_generator/    # Agent 3，P0 已完成
├── chapter_writer/     # Agent 4，真实实现
└── report_fusion/      # Agent 5，当前占位
```

每个阶段都要实现同一个接口：

```python
class StageAgent(Protocol):
    stage: StageName

    async def run(self, context: StageContext) -> StageResult:
        ...
```

新 Agent 不能绕过 `StageRegistry`，也不能由 API 直接调用某个 Agent。

### 4.3 前端目录

```text
frontend/src/
├── api/          # Axios 和 Workflow API
├── components/   # 可复用组件
├── modules/      # 报告和审核模块职责说明
├── stores/       # Pinia 工作流状态
├── types/        # 后端契约的 TypeScript 镜像
├── router/       # 前端路由
└── views/        # 页面
```

当前前端仍是功能骨架，Agent 3 的 ECharts 实际展示组件需要后续开发。

### 4.4 文档和契约目录

```text
docs/
├── architecture/  # 架构总览和 ADR
├── development/   # 环境搭建和开发规范
├── plans/         # 各阶段开发计划
├── ownership.md   # 成员职责和交接
└── agent3-current-stage-completion.md  # 本文档

contracts/
├── README.md
└── schemas/       # 跨端 JSON Schema
```

---

## 5. 后端是如何搭建的

### 5.1 FastAPI 应用入口

后端入口是：

```text
backend/app/main.py
```

它负责：

1. 创建 FastAPI 应用。
2. 注册 API 路由。
3. 配置 CORS。
4. 限制请求体大小。
5. 应用启动时打开 SQLite Checkpointer。
6. 创建 Workflow Runner。
7. 应用关闭时释放数据库连接。

### 5.2 后端公开接口

当前主要接口：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 服务健康检查，不需要 Token |
| GET | `/api/v1/ping` | API 连通性检查，不需要 Token |
| POST | `/api/v1/runs` | 创建一个研究任务 |
| GET | `/api/v1/runs/{run_id}` | 查询任务状态 |
| POST | `/api/v1/runs/{run_id}/reviews` | 审核、修改、重新生成或取消 |
| GET | `/docs` | FastAPI 自动生成的接口文档 |

任务创建、查询和审核需要：

```http
Authorization: Bearer <token>
```

服务端会生成 `owner_id` 和 `run_id`，客户端不能自行指定任务归属或运行编号。

### 5.3 为什么需要 Workflow Runner

长任务不应该由 API 路由自己执行全部业务。Workflow Runner 负责：

- 启动 LangGraph。
- 读取和写入 Checkpoint。
- 暂停到人工审核节点。
- 根据审核动作继续、重新运行或取消。
- 在每次运行前检查任务归属。

### 5.4 SQLite Checkpointer 的作用

SQLite Checkpointer 保存的是 LangGraph 的工作流状态，例如：

- 当前执行到哪个阶段。
- 每个阶段之前生成了什么结果。
- 当前 revision 是多少。
- 是否正在等待审核。
- 任务是否被取消。

它不是完整的业务数据库，也不是 PDF 文件存储。当前比赛版使用单 Worker 的 SQLite；未来多 Worker 或多实例部署需要迁移到共享数据库。

默认路径：

```text
backend/data/checkpoints.sqlite
```

---

## 6. 前端是如何搭建的

### 6.1 前端启动方式

```bash
cd /Users/Zhuanz1/PycharmProjects/同花顺/frontend
npm run dev
```

浏览器访问：

```text
http://localhost:5173
```

Vite 会把 `/api` 请求代理到：

```text
http://localhost:8000
```

### 6.2 前端目前完成的内容

- Vue 3 应用入口。
- Element Plus 基础布局。
- Vue Router。
- Pinia 工作流状态 Store。
- Workflow API 类型和请求函数。
- Agent 3 图表公共 TypeScript 类型。
- 前端类型检查、Lint、格式检查和测试。

### 6.3 前端还没有完成的内容

- GPT 风格的完整报告工作台。
- 五阶段进度条和审核页面。
- Agent 3 图表预览卡片。
- ECharts `option` 的实际渲染页面。
- Bearer Token 登录或安全输入流程。
- 历史报告页面和 PDF 下载页面。

因此，当前后端 Agent 3 已经能够生成 ECharts Option，但浏览器页面还需要前端成员接入。

---

## 7. 五阶段工作流如何运行

### 7.1 阶段顺序

代码中固定顺序是：

```text
data_fetch
    ↓
data_interpret
    ↓
chart_generate
    ↓
chapter_write
    ↓
report_fusion
```

每个阶段结束后，系统会根据结果决定：

- 继续下一阶段。
- 进入审核。
- 停止并等待修复。
- 取消任务。

### 7.2 运行状态

典型状态变化：

```text
pending → running → waiting_review → approved → completed
                         ↓
                    revise/regenerate
                         ↓
                       running
                         ↓
                    cancelled/failed
```

### 7.3 为什么阶段失败后不能直接继续

如果 Agent 2 没有通过证据校验，Agent 3 不应该继续画图；如果 Agent 3 没有生成有效图表，Agent 4 不应该引用一张不存在的图表。

因此，失败阶段会停止下游，并要求用户选择：

- 修改输入。
- 重新生成当前阶段。
- 取消任务。

### 7.4 Pi 风格运行护栏在哪里

项目借鉴了 Pi 的运行控制思想，但没有把 Pi 作为第二套 Agent 框架引入。现有 `runtime/` 和 `workflow/` 负责：

- 工作流和阶段超时。
- 单任务最大阶段次数。
- 模型调用次数限制。
- 工具调用次数限制。
- 运行事件记录。
- 阶段取消和失败恢复。
- 结构化错误结果。

---

## 8. 五个 Agent 分别负责什么

### 8.1 Agent 1：数据获取

负责：

- 接收行业主题和关注问题。
- 通过 ToolGateway 调用 SkillHub 技能。
- 获取行业、财务、行情、宏观、研报和资讯数据。
- 清洗、去重、统一时间、单位和币种口径。
- 输出证据包和 `ChartDataset[]`。

不能负责：

- 生成最终研究结论。
- 直接调用 CLI 或 HTTP 绕过 ToolGateway。
- 把完整外部异常写入日志。

当前状态：真实 Agent 1 尚未完成。当前 Mock 只为联调生成最简单的测试数据集。

### 8.2 Agent 2：数据解读

负责：

- 基于证据进行金融分析。
- 输出竞争、增长、宏观政策、产业链和风险五个维度。
- 检查财务质量和数据可比性。
- 生成 `ChartCandidate[]`，告诉 Agent 3 哪些数据值得可视化。

它可以调用内部 Router + 金融分析 Skill，但不应把未经证据支持的结论交给 Agent 3。

### 8.3 Agent 3：可视化图表

负责：

- 读取 Agent 1 的标准化图表数据。
- 读取 Agent 2 的图表候选。
- 验证数据与证据。
- 选择 P0 图表类型和柱状图变体。
- 生成纯 JSON ECharts Option。
- 去重和质量检查。
- 保存图表 Artifact。

不负责：

- 调用 SkillHub。
- 调用 LLM。
- 从自然语言猜数字。
- 生成金融结论。
- 生成最终 PDF。

### 8.4 Agent 4：章节生成

负责按 7 章 21 节结构撰写专业文本。它只引用已通过质量门并且状态为 `ready` 的图表。

### 8.5 Agent 5：报告融合

负责将章节、摘要、目录、结论、图表和产物组装为最终报告。当前仍是 Mock，后续需要接入报告模板、Markdown、HTML 和 Playwright PDF。

---

## 9. Agent 3 为什么需要单独开发

### 9.1 不应该让大模型直接画图

大模型适合解释文字，不适合直接保证以下事情：

- 每个数值都准确。
- 时间排序不出错。
- 不同币种不会混合。
- 同一数据不会重复绘制。
- 图表 JSON 每次都能被浏览器解析。

因此 Agent 3 使用确定性代码：同样的输入一定得到同样的输出。

### 9.2 Agent 2 只提出候选，Agent 3 负责落地

Agent 2 输出的候选类似：

```json
{
  "title": "行业收入变化趋势",
  "chart_type": "line",
  "evidence_ids": ["E-001", "E-002"]
}
```

它没有直接输出 ECharts 配置，也没有决定前端布局。Agent 3 会用证据编号找到真正的数据集，再生成图表。

---

## 10. Agent 3 当前完成的功能

### 10.1 P0 图表类型

#### 折线图 `line`

用于时间序列趋势。

规则：

- 至少两个有效时间点。
- 按 `period_end` 排序。
- 最多五条序列。
- 缺失数据保留为 `null`。
- 不自动插值。

#### 柱状图 `bar`

规则：

```text
单系列、类别较少、标签较短 → vertical
标签较长或类别较多       → horizontal
多系列并列比较            → grouped
明确可以相加的组成部分    → stacked
```

堆叠柱状图必须设置：

```json
"is_additive": true
```

否则会被拒绝。

#### 产业链图 `industry_chain`

使用：

```text
nodes + edges + stage
```

约束：

- 所有边的起点、终点必须存在。
- 禁止自循环。
- 禁止重复边和重复节点编号。
- 最多 30 个节点、60 条边。
- 默认上游→中游→下游从左到右展示。
- 没有流量数据时不生成边权。

### 10.2 未完成的 P1/P2 图表

暂时不进入代码契约：

```text
pie、radar、area、combo、scatter、bubble、heatmap、boxplot、treemap
```

新增图表必须新增数据结构、Builder、路由规则、互斥规则和测试，不能只在前端临时加一个图标。

---

## 11. Agent 3 的输入和输出

### 11.1 `ChartDataset` 是什么

`ChartDataset` 是 Agent 1 整理后的标准数据。它不是一段自然语言，而是有固定字段的 JSON。

#### 时间序列示例

```json
{
  "dataset_id": "DS-REVENUE",
  "kind": "time_series",
  "metric_name": "行业收入",
  "unit": "亿元",
  "currency": "CNY",
  "points": [
    {
      "label": "2024",
      "value": 100,
      "series": "行业",
      "period_end": "2024-12-31",
      "evidence_id": "E-001"
    },
    {
      "label": "2025",
      "value": 120,
      "series": "行业",
      "period_end": "2025-12-31",
      "evidence_id": "E-002"
    }
  ],
  "evidence_ids": ["E-001", "E-002"]
}
```

#### 分类数据示例

```json
{
  "dataset_id": "DS-SHARE",
  "kind": "categorical",
  "metric_name": "市场份额",
  "unit": "%",
  "currency": null,
  "is_additive": false,
  "points": [
    {"label": "公司A", "value": 35, "series": "默认", "evidence_id": "E-101"},
    {"label": "公司B", "value": 25, "series": "默认", "evidence_id": "E-102"}
  ],
  "evidence_ids": ["E-101", "E-102"]
}
```

#### 产业链数据示例

```json
{
  "dataset_id": "DS-CHAIN",
  "kind": "industry_chain",
  "metric_name": "新能源产业链",
  "nodes": [
    {
      "node_id": "lithium",
      "label": "锂资源",
      "stage": "upstream",
      "evidence_ids": ["E-201"]
    },
    {
      "node_id": "battery",
      "label": "动力电池",
      "stage": "midstream",
      "evidence_ids": ["E-202"]
    }
  ],
  "edges": [
    {
      "source": "lithium",
      "target": "battery",
      "label": "供应关系",
      "evidence_ids": ["E-201", "E-202"]
    }
  ],
  "evidence_ids": ["E-201", "E-202"]
}
```

### 11.2 `ChartCandidate` 是什么

这是 Agent 2 给 Agent 3 的候选建议：

```json
{
  "title": "行业收入变化趋势",
  "chart_type": "line",
  "evidence_ids": ["E-001", "E-002"]
}
```

候选只说明“画什么、用哪些证据”，真正的数值来自 `ChartDataset`。

### 11.3 `ChartSpec` 是什么

`ChartSpec` 是 Agent 3 生成的完整图表配置，包括：

- `chart_id`：图表编号。
- `title`：标题。
- `chart_type`：图表类型。
- `variant`：图表变体。
- `option`：ECharts JSON 配置。
- `evidence_ids`：数据来源。
- `data_fingerprint`：数据指纹。
- `dedupe_key`：去重键。

### 11.4 `ChartReference` 是什么

Agent 4 不需要读取全部 Option，而是使用轻量引用：

```json
{
  "chart_id": "CHART-ABC123",
  "title": "行业收入变化趋势",
  "chart_type": "line",
  "status": "ready",
  "evidence_ids": ["E-001", "E-002"],
  "artifact_id": "ARTIFACT-CHART-ABC123"
}
```

只有 `status=ready` 且有 `artifact_id` 的图表才能被正文引用。

---

## 12. Agent 3 的完整处理过程

### 第一步：读取上游结果

Agent 3 从：

- `StageName.DATA_FETCH` 读取 `chart_datasets`。
- `StageName.DATA_INTERPRET` 读取 `chart_candidates`。

如果缺少 Agent 2 候选或 Agent 1 数据集，会进入 `waiting_review`，不会猜数据。

### 第二步：按证据编号匹配

规则：

- 候选的全部证据编号都在某一个数据集中：继续。
- 没有完整匹配：记录 `no_matching_dataset`。
- 多个数据集都完整匹配：记录 `chart_dataset_ambiguous` 并要求用户选择。

### 第三步：校验数据

检查内容包括：

- 数据集类型是否和候选图表类型匹配。
- 时间点、类别、节点和边是否满足最小要求。
- 数据点是否引用真实证据。
- 数据单位和币种是否存在且一致。
- 节点和边是否有重复或非法引用。

### 第四步：Router + Skill 路由

固定路由如下：

```text
kind=time_series     + line           → line Builder
kind=categorical     + bar            → bar Builder
kind=industry_chain  + industry_chain → industry_chain Builder
```

如果候选类型和数据集类型不一致，会记录 `chart_dataset_mismatch`。

### 第五步：生成 ECharts Option

Builder 生成普通 Python 字典，例如：

```json
{
  "animation": false,
  "title": {"text": "行业收入变化趋势", "left": "center"},
  "xAxis": {"type": "category", "data": ["2024", "2025"]},
  "yAxis": {"type": "value", "name": "CNY 亿元"},
  "series": [
    {"name": "行业", "type": "line", "data": [100, 120]}
  ]
}
```

`animation=false` 是为了让浏览器预览和 PDF 导出更稳定。

### 第六步：质量门检查

质量门检查：

- 是否可以安全序列化为 JSON。
- 是否包含有效 `series`。
- 是否包含 JavaScript 函数或可执行代码。
- 是否有严重数据校验错误。

### 第七步：去重和预算控制

系统用 SHA-256 生成数据指纹：

```text
data_fingerprint = SHA256(图表类型 + 标准化数据)
dedupe_key = 图表族 + data_fingerprint
```

相同数据不会重复生成同族图表。单份报告最多生成 8 张 P0 核心图表。

### 第八步：保存 Artifact

保存路径：

```text
artifacts/{run_id}/charts/r{revision}/{chart_id}.json
```

同时返回：

- Artifact ID。
- 相对 URI。
- revision。
- SHA-256 校验和。

---

## 13. 人机审核和版本管理

### 13.1 审核为什么是必要的

金融数据即使来自可靠来源，也可能存在：

- 口径不一致。
- 报告期不同。
- 币种不同。
- 用户真正关注的重点与自动选择不同。
- 图表虽然技术上正确，但不适合放在正文。

因此，用户可以在图表阶段进行人工确认。

### 13.2 可以修改什么

审核白名单允许修改：

- 图表标题。
- P0 图表类型。
- 柱状图变体。
- 指标或数据集选择。
- 颜色主题。

不能直接提交任意 ECharts JSON，不能修改系统提示词、Token 或内部状态。

### 13.3 审核流程示例

```text
Agent 3 生成 revision=1
        ↓
用户发现公司名称太长
        ↓
用户选择 bar_variant=horizontal
        ↓
系统生成 revision=2
        ↓
用户点击通过
        ↓
Agent 4 开始撰写章节
```

修改会增加 revision，不应该覆盖历史版本。

---

## 14. 数据、文件和安全设计

### 14.1 三种数据不要混淆

| 类型 | 作用 | 示例 |
|---|---|---|
| 证据数据 | 真实来源和原始指标 | `E-001`、收入 120 亿元 |
| 工作流状态 | 当前执行到哪一步 | `waiting_review`、revision 2 |
| 文件产物 | 可下载或渲染的文件 | 图表 JSON、HTML、PDF |

SQLite Checkpoint 主要保存工作流状态；图表 JSON 和未来的图片、HTML、PDF 保存到 Artifact 目录；业务数据库未来保存项目、报告、反馈等信息。

### 14.2 已完成的基础安全

- Bearer Token 认证。
- 服务端生成 `owner_id` 和 `run_id`。
- 查询、审核和取消任务时检查任务归属。
- 创建请求和审核请求使用字段白名单。
- 请求体和文本长度限制。
- 创建任务和审核频率限制。
- 外部文本和审核意见的轻量提示词注入检测。
- Agent 2/Agent 4 输出敏感信息检查。
- 安全日志脱敏，不记录 Token、完整 Prompt 和可疑原文。
- 图表 Artifact 路径字段安全校验。
- ECharts Option 禁止嵌入可执行 JavaScript。

### 14.3 当前安全边界

前端 Token 交互尚未完成，当前安全层主要在后端。浏览器正式联调前，前端需要处理：

- Token 配置或登录方式。
- `401` 未认证。
- `403/404` 任务归属错误。
- `413` 请求过大。
- `422` 输入或提示词注入被拒绝。
- `429` 触发限流。

---

## 15. 当前项目状态

| 模块 | 当前状态 | 说明 |
|---|---|---|
| 项目骨架 | 已完成 | 前后端目录、契约、基础启动和验证脚本已建立 |
| Agent 1 | 开发中 | 需要正式接入 SkillHub 并输出 `ChartDataset[]` |
| Agent 2 | 已完成真实实现 | 多市场金融分析、证据校验、Router + 金融 Skills |
| Agent 3 | P0 已完成 | line、bar、industry_chain 后端确定性生成 |
| Agent 4 | 已完成真实实现 | 7 章 21 节内容生成和质量门 |
| Agent 5 | 开发中 | 需要完成报告融合、HTML/PDF 产物 |
| 前端基础 | 已完成骨架 | Vue、路由、Store、API 类型和测试 |
| 前端图表工作台 | 未完成 | 需要接入 `chart_specs[].option` |
| SQLite Checkpointer | 已完成 | 支持暂停、恢复和 revision |
| Playwright Chromium | 已安装并通过测试 | 用于后续 HTML/PDF 渲染 |

### Agent 1 临时适配器

Agent 1 尚未完成时，`MockStageAgent(DATA_FETCH)` 会把数值型证据原样重组为测试用分类数据集。

这个适配器：

- 不调用 SkillHub。
- 不补充外部数据。
- 不修改原始数值。
- 不推断产业链关系。

正式 Agent 1 接入后，应删除它。

---

## 16. 如何启动和验证项目

### 16.1 启动后端

```bash
cd /Users/Zhuanz1/PycharmProjects/同花顺/backend
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

验证：

```text
http://localhost:8000/health
http://localhost:8000/api/v1/ping
http://localhost:8000/docs
```

### 16.2 启动前端

另开终端：

```bash
cd /Users/Zhuanz1/PycharmProjects/同花顺/frontend
npm run dev
```

浏览器访问：

```text
http://localhost:5173
```

### 16.3 运行 Agent 3 测试

```bash
cd /Users/Zhuanz1/PycharmProjects/同花顺/backend
.venv/bin/python -m pytest tests/agents/chart_generator -q
```

重点测试：

- 时间序列排序。
- 缺失值断点。
- 柱状图四种变体。
- 证据编号匹配。
- 产业链边和节点校验。
- 重复候选抑制。
- Artifact 校验和。
- 三类 P0 图表生成。
- 图表审核重新生成 revision 2。

### 16.4 运行后端全量检查

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m mypy app
.venv/bin/python -m flake8 app tests
.venv/bin/python -m black --check app tests
```

### 16.5 运行前端检查

```bash
cd /Users/Zhuanz1/PycharmProjects/同花顺/frontend
npm run verify
npm run build
```

### 16.6 一键验证

从项目根目录执行：

```bash
./scripts/verify.sh
```

该脚本会依次执行后端测试和质量检查，再执行前端验证和生产构建。

---

## 17. 后续成员如何接着开发

### 17.1 Agent 1 开发人员

必须完成：

1. 通过 `ToolGateway` 注册和调用 SkillHub 技能。
2. 获取行业、财务、宏观、产业链、研报和资讯等数据。
3. 清洗和统一时间、币种、单位和市场口径。
4. 输出证据包。
5. 输出符合 `ChartDataset` 结构的数据。
6. 为每个数据点保留证据编号。
7. 给外部异常、空数据和超时增加测试。

Agent 1 不应该让 Agent 3 从一段自然语言中自己猜结构。

### 17.2 前端开发人员

需要完成：

1. 用 Vue 组件读取 `chart_specs[].option`。
2. 使用 `vue-echarts` 渲染 line、bar 和 industry_chain。
3. 展示图表来源证据。
4. 展示质量门失败原因和被抑制候选。
5. 添加五阶段进度条。
6. 添加每阶段通过、修改、重新生成、取消按钮。
7. 添加图表审核表单。
8. 处理请求错误和 Token。
9. 支持浏览器预览和下载 Artifact。

### 17.3 Agent 5 开发人员

需要完成：

1. 读取章节结果和图表 Artifact。
2. 生成目录、封面、摘要和结论。
3. 统一正文与图表的术语、单位和数据口径。
4. 组装确定性 HTML 模板。
5. 使用 Playwright Chromium 导出 PDF。
6. 保存最终报告 Artifact。

### 17.4 P1 图表开发人员

后续增加 `heatmap`、`scatter`、`boxplot`、`treemap` 等图表时必须同时增加：

- 数据结构。
- Router 规则。
- Builder。
- 质量门。
- 去重和互斥规则。
- 前端渲染测试。
- PDF 导出测试。

不能只在前端增加一个图表名称而没有后端数据契约。

---

## 18. 开源项目借鉴说明

当前实现没有复制任何第三方项目的源文件，借鉴的是公开的设计和工程思路：

- Apache ECharts：借鉴 Option、line/bar/graph 和数据配置方式。
- pyecharts：借鉴 Python 构造 ECharts JSON、空值处理和柱状图参数映射。
- stock-industry-chain：借鉴 `nodes + edges + stage` 的产业链数据结构。
- BettaFish：借鉴 Validator、质量报告和问题汇总方式。
- Pi：借鉴超时、取消、结构化错误和运行事件思想。

Pi 没有加入运行依赖，Agent 3 仍使用项目已有的 LangGraph、Pydantic、ECharts 和 Playwright 体系。

---

## 19. 常见问题

### Q1：为什么 Agent 3 不调用大模型？

因为图表生成需要准确、稳定和可复现。让大模型决定排序、数值或坐标可能产生幻觉。Agent 3 只做确定性转换。

### Q2：为什么 Agent 3 不自己去 SkillHub 查数据？

数据获取归 Agent 1 负责。如果 Agent 3 再次查询，可能和 Agent 2 使用的数据时间或口径不同，导致图表和正文不一致。

### Q3：为什么要有 `ChartDataset`，不能直接把 `EvidenceItem` 画出来吗？

`EvidenceItem` 通常表示单条证据，不能稳定表达多时间点、多序列或节点边关系。`ChartDataset` 专门描述可以绘图的数据结构，避免 Agent 3 猜测。

### Q4：为什么同一个行业可能只能生成一张产业链图？

同一报告重复放多张相同产业链关系图会降低专业度，也会增加 PDF 排版风险。当前每份报告限制一张，后续如果需要多张必须定义不同数据范围和分析目的。

### Q5：当前可以看到最终的漂亮报告页面吗？

还不能。当前 Agent 3 后端可以生成 ECharts Option，但前端实际图表组件和完整报告工作台还需开发。

### Q6：当前可以生成最终 PDF 吗？

Playwright Chromium 基础 PDF 测试已通过，但 Agent 5 仍未完成完整报告融合，所以当前阶段不能宣称完整 PDF 流程交付。

### Q7：为什么不能把整个虚拟环境上传给成员？

虚拟环境包含本机路径、平台相关二进制和大量缓存文件。正确方式是提交 `requirements.txt`、`requirements-dev.txt`、`package.json` 和 `package-lock.json`，由每位成员在相同版本的 Python/Node 环境中重新安装。

### Q8：为什么浏览器部署还需要配置后端？

前端只是浏览器页面，真正的任务创建、Agent 执行、数据处理和 PDF 生成都在 FastAPI 后端。生产环境必须同时部署静态前端、后端 API、持久化目录和 Chromium。

---

## 20. 当前阶段验收结论

### 已完成

- 项目从零搭建所需的前后端骨架。
- Python 3.12、Node 22 和依赖文件约束。
- FastAPI、LangGraph、SQLite Checkpointer 和公共契约。
- 后端认证、任务归属、限流、白名单和基础安全防护。
- Agent 2 真实金融分析能力。
- Agent 4 真实 7 章 21 节内容生成能力。
- Agent 3 P0 确定性图表生成能力。
- line、bar、industry_chain 三类图表的校验、路由、去重和 Artifact 存储。
- 图表审核、修改和 revision 重新生成。
- 后端全量测试、类型检查、代码检查和前端构建验证。

### 尚未完成

- Agent 1 正式 SkillHub 数据接入。
- 前端完整 GPT 风格工作台。
- 前端 ECharts 实际渲染和图表审核界面。
- Agent 5 完整报告融合。
- HTML/PDF 最终报告模板和完整导出链路。
- 生产环境多 Worker 或多实例部署。

最终结论：

> 当前完成的是“从项目初始化、基础框架、公共契约到 Agent 3 P0 后端”的阶段性成果。新成员可以按照本文档完成环境搭建、启动项目、理解工作流并继续开发 Agent 1、前端和 Agent 5。

---

## 附录：关键文件速查表

| 文件 | 用途 |
|---|---|
| `README.md` | 项目总览和快速开始 |
| `docs/development/setup.md` | 环境和依赖安装说明 |
| `docs/architecture/overview.md` | 系统架构总览 |
| `docs/ownership.md` | 成员职责和交接规则 |
| `backend/app/main.py` | FastAPI 应用入口 |
| `backend/app/workflow/graph.py` | LangGraph 工作流 |
| `backend/app/workflow/factory.py` | Agent 注册表 |
| `backend/app/schemas/workflow.py` | 工作流和审核契约 |
| `backend/app/schemas/chart.py` | Agent 3 图表契约 |
| `backend/app/agents/chart_generator/service.py` | Agent 3 主服务 |
| `backend/app/agents/chart_generator/router.py` | Agent 3 路由和指纹 |
| `backend/app/agents/chart_generator/builders.py` | 三类图表 Builder |
| `backend/app/agents/chart_generator/datasets.py` | 数据集匹配和校验 |
| `backend/app/agents/chart_generator/quality.py` | 图表质量门 |
| `backend/app/infrastructure/storage/local.py` | Artifact 文件存储 |
| `contracts/schemas/chart-generation-result.schema.json` | Agent 3 跨端契约 |
| `frontend/src/types/workflow.ts` | 前端契约类型 |
| `scripts/verify.sh` | 全仓自动验证 |
