# 后端应用

FastAPI 主应用及五阶段 Workflow。整体架构见 [`../docs/architecture/overview.md`](../docs/architecture/overview.md)，人员分工见 [`../docs/ownership.md`](../docs/ownership.md)。

## 目录职责

- `app/api/`：公开 HTTP API
- `app/schemas/`：Pydantic 边界模型
- `app/agents/`：五个稳定阶段节点
- `app/workflow/`：LangGraph 编排与审核恢复
- `app/runtime/`：运行预算、模型调用计数、ToolGateway与脱敏事件
- `app/integrations/`：SkillHub、LLM 适配器
- `app/infrastructure/`：数据库和产物存储
- `app/reporting/`：图表、HTML、PDF 渲染
- `tests/`：契约、API 和业务测试

## 本地命令

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
black --check app tests
flake8 app tests
mypy app
uvicorn app.main:app --reload --port 8000
```

五个阶段均已接入真实业务节点。`data_fetch` 具备 SkillHub P0/P1 真实适配器、ToolGateway、标准证据和质量门；应用运行只允许真实 SkillHub，Mock 仅保留给 `ENVIRONMENT=test` 的自动化测试。Agent 5 会将正式产物保存到 `artifacts/{run_id}/reports/r{revision}/`，并通过带 Bearer Token 和 owner_id 校验的下载接口返回文件。接入新 Agent 时必须保持 `StageAgent` 协议和公共 Pydantic/JSON Schema 契约一致。

Workflow已启用Pi风格P0运行护栏：失败阶段停止下游并进入恢复审核；单任务限制阶段、模型和工具调用次数；阶段与工具调用有超时；工具错误以结构化结果回灌Agent。该实现是LangGraph上的独立Python运行层，不依赖或嵌套第二套Agent框架。

## 生产模式与团队测试

生产或开发服务启动时会执行 fail-closed 配置检查：Agent 1 禁止使用 SkillHub
Mock，Agent 2/4 禁止使用 LLM Mock，并要求配置模型密钥、SkillHub 密钥和至少一个
应用 Bearer Token。任一条件缺失时服务拒绝启动，避免把测试模板误当成真实行业报告。

推荐的职责划分如下：

- Agent 1：真实问财 SkillHub 数据获取；
- Agent 2：`deepseek-v4-pro` 数据解读；
- Agent 3：确定性图表路由与 ECharts 配置生成，不调用 LLM；
- Agent 4：`deepseek-v4-pro` 章节撰写；
- Agent 5：确定性 Markdown/单文件 HTML/Playwright PDF 融合，不调用 LLM。

模型供应商密钥只能保存在服务器环境变量或密钥管理器中。团队测试者不接触模型密钥，
只使用管理员分配的应用 Bearer Token 调用后端。启动后可访问`GET /health/ready`确认真实
适配器、SQLite、产物目录和 PDF 渲染配置均已就绪；该接口不会返回任何密钥。

## 工作流持久化

LangGraph运行状态默认保存在`./data/checkpoints.sqlite`，路径可通过`CHECKPOINT_DATABASE_PATH`调整。FastAPI在应用生命周期内复用一个`AsyncSqliteSaver`连接，因此开发和测试客户端必须正常触发应用lifespan。比赛版按单Worker运行；部署时需持久化挂载并备份`data/`目录。
