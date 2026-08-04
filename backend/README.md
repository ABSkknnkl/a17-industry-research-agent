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

当前`data_interpret`与`chapter_write`已接入真实业务节点，`data_fetch`、`chart_generate`与`report_fusion`仍使用Mock边界。接入新Agent时必须保持`StageAgent`协议和`contracts/schemas/`跨端契约一致。

Workflow已启用Pi风格P0运行护栏：失败阶段停止下游并进入恢复审核；单任务限制阶段、模型和工具调用次数；阶段与工具调用有超时；工具错误以结构化结果回灌Agent。该实现是LangGraph上的独立Python运行层，不依赖或嵌套第二套Agent框架。

## 工作流持久化

LangGraph运行状态默认保存在`./data/checkpoints.sqlite`，路径可通过`CHECKPOINT_DATABASE_PATH`调整。FastAPI在应用生命周期内复用一个`AsyncSqliteSaver`连接，因此开发和测试客户端必须正常触发应用lifespan。比赛版按单Worker运行；部署时需持久化挂载并备份`data/`目录。
