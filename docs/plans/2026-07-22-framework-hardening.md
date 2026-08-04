# 项目框架加固实施计划

> 日期：2026-07-22  
> 目标：把当前“最小可启动骨架”升级为可交给五名成员并行开发的统一框架；本计划不实现具体 Agent 业务逻辑。
> 状态：已完成并通过全仓验证；下列复选项保留为实施时的验收定义，最终结果见 `week-0-framework.md`。

## 范围

本次覆盖文档基线、能力目录、公共契约、依赖、质量工具和启动验证。SkillHub 真实调用、LLM Prompt、五个 Agent 业务实现、页面业务功能、数据库持久化和 PDF 模板由对应成员按 Week 1/2 任务继续开发。

## 目标结构

```text
.
├── contracts/                 # 跨端唯一契约源（JSON Schema）
├── docs/
│   ├── architecture/          # 架构总览与 ADR
│   ├── development/           # 环境、代码与协作规范
│   ├── plans/                 # 周计划与本实施计划
│   └── ownership.md           # 五名成员职责和交接面
├── backend/
│   ├── app/
│   │   ├── agents/            # 五个 Pipeline 节点
│   │   ├── integrations/      # LLM、SkillHub 外部适配器
│   │   ├── workflow/          # LangGraph 状态与编排
│   │   ├── infrastructure/    # DB、文件存储
│   │   ├── reporting/         # 图表与 PDF
│   │   └── schemas/           # API/运行时 Pydantic 模型
│   ├── tests/
│   ├── requirements.txt
│   └── requirements-dev.txt
└── frontend/
    └── src/
        ├── modules/reporting/ # 报告、图表、PDF 预览
        ├── modules/review/    # 审核、流程状态、配置
        ├── stores/            # Pinia
        └── types/             # 从 contracts 生成的类型出口
```

## Task 1：统一文档基线

**文件：**

- 修改：`README.md`
- 创建：`docs/README.md`
- 创建：`docs/architecture/overview.md`
- 创建：`docs/architecture/decisions/ADR-001-capability-oriented-monorepo.md`
- 创建：`docs/development/setup.md`
- 创建：`docs/development/conventions.md`
- 创建：`docs/ownership.md`
- 创建：`docs/plans/week-0-framework.md`
- 创建：`docs/plans/week-1-technical-validation.md`
- 删除：`backend/docs/`、`frontend/docs/` 中与根文档重复的旧副本

- [ ] 把现有成果定义为 Week 0，不再冒充原方案 Week 1 已完成。
- [ ] 在 Week 1 中保留原方案的 LangGraph、SkillHub、LLM、数据库 Schema 和 UI 原型验收。
- [ ] 写清五名成员的负责目录、输入、输出、依赖和验收命令。
- [ ] 根 README 只保留项目入口、快速启动和文档索引。

## Task 2：改为能力导向、可导入的目录

**文件：**

- 删除：`backend/app/modules/backend-a/`
- 删除：`backend/app/modules/backend-b/`
- 删除：`backend/app/modules/backend-c/`
- 创建：`backend/app/agents/{data_fetcher,data_interpreter,chart_generator,chapter_writer,report_fusion}/README.md`
- 创建：`backend/app/integrations/{skillhub,llm}/README.md`
- 创建：`backend/app/workflow/README.md`
- 创建：`backend/app/infrastructure/{db,storage}/README.md`
- 创建：`backend/app/reporting/README.md`
- 将上述 Python 目录补齐 `__init__.py`
- 删除：`frontend/src/modules/frontend-a/`、`frontend/src/modules/frontend-b/`
- 创建：`frontend/src/modules/reporting/README.md`
- 创建：`frontend/src/modules/review/README.md`
- 创建：`frontend/src/stores/README.md`

- [ ] 所有 Python 包名只使用小写字母和下划线。
- [ ] 目录按能力稳定存在，人员归属只写在 `docs/ownership.md`。
- [ ] 公共入口仍由后端 C/架构负责人维护。

## Task 3：建立跨端唯一契约

**文件：**

- 创建：`contracts/README.md`
- 创建：`contracts/schemas/workflow-state.schema.json`
- 创建：`contracts/schemas/review-action.schema.json`
- 创建：`backend/app/schemas/workflow.py`
- 创建：`backend/tests/test_contracts.py`
- 删除：`backend/shared/`、`frontend/shared/` 的重复说明副本

契约必须包含以下阶段：

```text
data_fetch -> data_interpret -> chart_generate -> chapter_write -> report_fusion
```

状态机必须包含：

```text
pending -> running -> waiting_review -> approved/rejected
running -> failed/cancelled
approved -> completed
```

- [ ] 增加 `project_id`、`run_id`、`current_stage`、`revision`、时间戳和产物引用。
- [ ] 审核动作固定为 `approve`、`revise`、`regenerate`、`cancel`。
- [ ] Pydantic 模型与 JSON Schema 的枚举和值一致，并由测试约束。

## Task 4：补齐依赖与质量工具

**文件：**

- 修改：`backend/requirements.txt`
- 创建：`backend/requirements-dev.txt`
- 创建：`backend/pyproject.toml`
- 修改：`frontend/package.json`
- 创建：`frontend/eslint.config.js`
- 创建：`frontend/.prettierrc.json`
- 创建：`frontend/src/stores/workflow.ts`

后端运行依赖包含 FastAPI、Pydantic、SQLAlchemy/aiosqlite、LangChain/LangGraph、OpenAI 兼容客户端、HTTP 客户端、重试、图表和 PDF；开发依赖包含 pytest、覆盖率、Black、Flake8 和 mypy。前端增加 Pinia、ECharts、Vue-ECharts，以及 ESLint、Prettier、Vitest。

- [ ] 依赖使用兼容范围，禁止无上限的“latest”。
- [ ] `package.json` 提供 `type-check`、`lint`、`format:check`、`test`、`verify`。
- [ ] `pyproject.toml` 统一 Black、Flake8、mypy、pytest 配置。

## Task 5：补齐最小测试和统一验证入口

**文件：**

- 创建：`backend/tests/test_health.py`
- 创建：`frontend/src/stores/workflow.test.ts`
- 创建：`scripts/verify.sh`
- 创建：`THIRD_PARTY_NOTICES.md`

验证命令及期望结果：

```bash
cd backend && .venv/bin/python -m pytest
# 期望：所有后端测试通过

cd frontend && npm run verify
# 期望：类型检查、lint、格式检查和单测全部通过

./scripts/verify.sh
# 期望：前后端验证均通过并以 0 退出
```

## Task 6：交接复核

- [ ] `rg 'backend-a|backend-b|backend-c|frontend-a|frontend-b'` 只允许在历史说明或人员映射中出现。
- [ ] 根目录不存在重复的 `backend/shared`、`frontend/shared` 契约源。
- [ ] 前端开发服务器可启动并返回 HTTP 200。
- [ ] 后端 `/health` 与 `/api/v1/ping` 测试通过。
- [ ] `docs/ownership.md` 中每位成员都有明确的首个任务和验收标准。
- [ ] 不改动 `.idea/` 和 `production/session-logs/` 中用户已有内容。
