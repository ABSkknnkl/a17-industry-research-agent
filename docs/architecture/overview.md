# 系统架构总览

## 1. 目标

系统接收行业主题，通过五个有序阶段生成可审核、可追溯的行业研究报告，并输出 HTML/PDF。每个阶段结束后进入人工审核，支持通过、修改、重新生成和取消。

## 2. 逻辑架构

```text
Vue 3
  ├─ 项目/报告展示
  ├─ Pipeline 状态与审核
  └─ ECharts 6/PDF 预览
          │ REST + SSE/WebSocket（后续技术验证确定）
FastAPI
  ├─ Bearer认证 / 归属 / 限流 / 安全审计
  ├─ API 与分阶段 Pydantic 白名单
  ├─ LangGraph Workflow
  │    data_fetch -> data_interpret -> chart_generate
  │    -> chapter_write -> report_fusion
  ├─ SkillHub / LLM 适配器
  ├─ 数据库 Repository
  └─ 图表、HTML、PDF 与文件存储
```

五个阶段是稳定的工作流节点，不代表每个节点都必须调用 LLM：

| 阶段 | 实现策略 | 负责人 |
|---|---|---|
| data_fetch | SkillHub 工具调用、清洗、标准化 | 后端 A |
| data_interpret | 基于证据的 LLM 解读 | 后端 B |
| chart_generate | 规则/模板优先，生成 ECharts 配置 | 后端 C |
| chapter_write | 基于数据与证据引用的 LLM 撰写 | 后端 B |
| report_fusion | 确定性编排、校验和 Playwright Chromium PDF 渲染 | 后端 B + 后端 C |

## 3. 状态和审核

跨端状态以 `contracts/schemas/` 为唯一契约源。关键状态为：

```text
pending -> running -> waiting_review
waiting_review -> approved -> completed
waiting_review -> rejected -> running
running -> failed | cancelled
```

用户修改产出时必须生成新 `revision`，不得覆盖历史版本。上游阶段重新生成后，下游产物应标记为过期并重新执行。

## 4. 数据与并发

- SQLite 作为比赛 Demo 默认数据库，启用 WAL、busy timeout 和短事务。
- 数据访问必须通过 Repository 边界，避免业务代码直接依赖 SQLite，以便切换 PostgreSQL。
- JSON、图片、HTML、PDF 存文件系统，数据库保存 URI、校验和、类型、版本和来源。
- 长任务不得阻塞普通 HTTP 请求。Week 1 验证后台执行与进度通道后再确定最终 Worker 方案。

## 5. 契约与依赖方向

```text
api -> workflow -> agents -> integration protocols
                    └------> repository/storage protocols
integrations 和 infrastructure 实现协议，不反向依赖 api
frontend 只依赖公开 API/JSON Schema，不读取后端内部模型
```

## 6. 非功能要求

- 所有外部调用具备超时、有限重试和结构化错误。
- 每个阶段保存输入摘要、输出、证据来源、模型/Prompt 版本和耗时。
- API Key 仅从环境变量读取，禁止写入仓库或日志。
- 核心状态转换、契约和外部适配器必须有单元测试。
- 所有任务由服务端生成UUID，内部状态保存`owner_id`，任务读取和恢复前必须校验归属。
- 用户文本、人工审核与外部证据统一视为不可信数据，不得获得系统指令或工具权限。
- 安全日志不保存Token、可疑原文、Prompt或Agent可疑输出，只保存规则编号、追踪ID、SHA-256和长度。
