# Week 1 — 环境搭建与技术验证

## 目标

完成原项目方案要求的高风险技术链路验证，不追求完整业务功能。

## 并行任务

| 负责人 | 任务 | 交付物 |
|---|---|---|
| 后端 A | SkillHub 六类能力探测、Mock 与清洗样例 | 适配器、样例数据、Smoke Test 报告 |
| 后端 B | Qwen/DeepSeek 兼容客户端、结构化输出 | LLM 适配器、Mock、Prompt 样例 |
| 后端 C | LangGraph 五节点空流程、interrupt/resume、SQLite Schema | 可恢复 Pipeline Demo、迁移文件 |
| 前端 A | 报告与图表 UI 原型 | 可交互原型、Mock 图表页 |
| 前端 B | 五阶段状态与审核 UI 原型 | Store、步骤条、审核面板 |

## 必须共同确认的契约

- `WorkflowState`、`StageResult`、`ArtifactRef`
- 审核动作：通过、修改、重新生成、取消
- 修改上游阶段后下游状态的失效规则
- API 错误格式、长任务状态查询和进度推送方式

## 验收标准

- [ ] 前后端项目骨架可独立启动
- [ ] SkillHub 至少一个真实接口可返回数据，六类能力状态有记录
- [ ] 至少一个真实 LLM 可返回并通过结构化校验
- [ ] 五节点 Mock Pipeline 可在每阶段暂停、恢复
- [ ] SQLite 保存项目、运行、阶段、审核和产物索引
- [ ] 前端可基于 Mock 完成一轮审核交互
- [ ] 所有结果不包含明文密钥，并有可重复运行说明

