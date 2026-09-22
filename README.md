# 同花顺问财 SkillHub — 行业研究报告智能生成系统

基于五阶段 Pipeline 的行业研究报告生成与人机协同审核系统，对应 2026 移动应用创新赛 A17 赛题。

## 当前阶段

- **全链路已接通**：Vue 前端、FastAPI/LangGraph 工作流与仓库内置的五个真实 Agent 已完成适配，沿用原有审核、鉴权、契约和断点恢复能力。
- **Agent 1 P0/P1已完成**：Router + Skill 查询规划、6类P0与5类P1能力、ToolGateway、并发分页、标准证据、冲突保留、质量门和采集范围审核。
- **Agent 2已完成**：多市场金融数据解读、Router + 辅助Skills、证据校验和有界修订。
- **Agent 3 P0已完成**：确定性生成折线图、柱状图、饼图、雷达图与产业链图，包含条件降级、互斥去重、数量预算和质量门；P1扩展图表已有条件路由。
- **Agent 4已完成**：固定7章21节撰写、章节/小节定向修订、图表降级兼容和内容质量门。
- **Agent 5 P0已完成**：确定性融合上游结果，输出 Markdown、单文件 HTML、Playwright PDF 和 SHA-256 产物清单。
- 五个生产阶段默认使用仓库根目录 `agents_core/` 内置的真实实现；Mock 仅存在于自动化测试进程，开发、演示和部署运行不会静默回退到测试数据。

## 仓库结构

```text
.
├── backend/       # FastAPI、Pipeline、Agent 与外部集成
├── agents_core/   # 五个可独立测试的真实 Agent 实现
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

## 真实五 Agent 配置与冒烟

复制 `backend/.env.example` 为 `backend/.env`，至少配置以下项目（密钥文件已被 Git 忽略，请勿提交）：

```dotenv
REAL_AGENTS_ENABLED=true
LLM_USE_MOCK=false
LLM_API_KEY=...
LLM_BASE_URL=...
LLM_MODEL=...
SKILLHUB_USE_MOCK=false
IWENCAI_API_KEY=...
```

报告 PDF 由 Playwright Chromium 生成，首次安装依赖后执行：

```bash
cd backend
.venv/bin/playwright install chromium
```

可以不启动 Web 服务，直接运行五阶段真实凭证冒烟。命令会依次执行数据获取、数据解读、图表生成、章节撰写和报告融合，并验证 Markdown、HTML、PDF 均已落盘：

```bash
cd backend
.venv/bin/python scripts/run_real_agents_smoke.py \
  --industry 低空经济 \
  --as-of 2026-09-22 \
  --focus 市场规模与产业链
```

未配置真实 LLM 或问财凭证、误开 Mock、或任一阶段失败时，脚本会直接失败，不生成伪造结果。产物写入 `backend/artifacts/<run-id>/artifacts/`。

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
