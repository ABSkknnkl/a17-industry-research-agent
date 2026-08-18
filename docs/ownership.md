# 成员职责与交接表

## 后端 A — 数据接入

- 负责：`backend/app/agents/data_fetcher/`、`backend/app/integrations/skillhub/`
- 输入：行业主题、项目配置
- 输出：满足公共契约的标准化数据与证据来源
- 当前状态：Agent 1 P0/P1 已完成，包含 15 个逻辑技能（含条件型 `hithink-basicinfo-query`）、真实 SkillHub 适配器、ToolGateway、数据清洗、去重与质量门；Mock 只允许自动化测试使用。INDEX、FUTURES、STOCK_SELECTOR、BASIC_INFO 已完成授权账号真实冒烟验收。
- 待外部验收：使用赛事授权密钥对 6 类 P0 数据各完成一次真实 Smoke Test，并记录接口实际返回字段。

## 后端 B — AI 生成

- 负责：`data_interpreter/`、`chapter_writer/`、`report_fusion/`、`integrations/llm/`
- 输入：标准化数据、图表引用、审核反馈
- 输出：结构化分析、21 小节内容、融合后的报告模型
- 首个任务：LLM 客户端与 Mock、结构化输出校验、Prompt 版本目录
- 验收：不依赖真实密钥的单元测试通过；真实模型 Smoke Test 可返回契约化结果

## 后端 C — 编排与基础设施

- 负责：`backend/app/workflow/`、`chart_generator/`、`infrastructure/`、`reporting/`、公共 API 与契约
- 输入：五个节点接口和跨端契约
- 输出：可持久化、可暂停/恢复的 Pipeline，以及数据库/文件接口
- 首个任务：LangGraph 五节点空实现、interrupt/resume 技术验证、数据库 Schema
- 验收：同一 `run_id` 可暂停、恢复和重新生成；状态重启后可恢复

## 前端 A — 报告与可视化

- 负责：`frontend/src/modules/reporting/`、报告相关页面和共享图表组件
- 输入：报告、图表配置、产物 URI
- 输出：报告展示、ECharts 渲染、PDF 预览
- 首个任务：报告页面骨架和基于 Mock 契约的图表组件
- 验收：至少四类图表响应式展示；错误与空状态可见

## 前端 B — 审核与流程交互

- 负责：`frontend/src/modules/review/`、`frontend/src/stores/`、`frontend/src/api/`
- 输入：Workflow 状态与阶段产物
- 输出：审核动作、修改内容和流程状态界面
- 首个任务：Pinia Workflow Store、五阶段步骤条、审核操作面板
- 验收：Mock 状态可完整演示通过、修改、重新生成和取消

## 公共交接规则

1. 修改 `contracts/` 前先提交契约变更并通知所有消费者。
2. 每个功能同时提交测试和 README/API 说明。
3. 真实外部服务必须配套 Mock，保证其他成员不依赖密钥开发。
4. 不得绕过 Workflow 直接从 API 调用具体 Agent。
