# 同花顺问财 SkillHub — 行业研究报告智能生成系统

基于五阶段 Pipeline 的行业研究报告生成与人机协同审核系统，对应 2026 移动应用创新赛 A17 赛题。

## 当前阶段

- **框架基线已完成**：前后端骨架、LangGraph五阶段Workflow、通用人工审核、公共契约和质量门。
- **Agent 2已完成**：多市场金融数据解读、Router + 辅助Skills、证据校验和有界修订。
- **Agent 4已完成**：固定7章21节撰写、章节/小节定向修订、图表降级兼容和内容质量门。
- Agent 1、Agent 3和Agent 5仍使用Mock边界，可按 [职责与交接表](docs/ownership.md) 并行开发。

## 仓库结构

```text
.
├── backend/       # FastAPI、Pipeline、Agent 与外部集成
├── frontend/      # Vue 3、审核流程、报告展示
├── contracts/     # 跨端唯一 JSON Schema 契约源
├── docs/          # 架构、开发规范、计划和职责
├── scripts/       # 统一验证脚本
└── README.md
```

## 快速开始

完整环境说明见 [开发环境搭建](docs/development/setup.md)。

```bash
# 后端
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000

# 前端（另一个终端）
cd frontend
npm ci
npm run dev
```

验证地址：

- 前端：http://localhost:5173
- 后端健康检查：http://localhost:8000/health
- OpenAPI：http://localhost:8000/docs

任务创建、查询和审核接口已启用Bearer Token与任务归属校验，Token配置见[backend/.env.example](backend/.env.example)。当前按开发计划只完成后端安全层，前端Token交互尚未接入。

## 开发入口

- [文档索引](docs/README.md)
- [架构总览](docs/architecture/overview.md)
- [成员职责与交接](docs/ownership.md)
- [Week 1 技术验证计划](docs/plans/week-1-technical-validation.md)
- [开发规范](docs/development/conventions.md)
- [公共契约](contracts/README.md)

提交前运行：

```bash
./scripts/verify.sh
```
