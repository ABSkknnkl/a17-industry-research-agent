# SQLite Checkpointer Implementation Plan

**目标：** 将FastAPI组合根中的`InMemorySaver`替换为生命周期托管的`AsyncSqliteSaver`，保证同一`run_id`在应用关闭并重新创建后仍可查询、审核和继续执行。

**范围：** 本计划只持久化LangGraph运行状态；不创建业务报告表、不实现PDF历史接口。

### Task 1: 锁定重启恢复行为

**Files:**
- Create: `backend/tests/workflow/test_sqlite_checkpoint.py`

- [x] **Step 1:** 使用同一个临时`checkpoints.sqlite`依次创建两个应用实例。
- [x] **Step 2:** 第一个实例创建停在`data_interpret`审核节点的任务并关闭。
- [x] **Step 3:** 第二个实例用原`run_id`查询任务并提交`approve`。
- [x] **Step 4:** 运行`.venv/bin/pytest tests/workflow/test_sqlite_checkpoint.py`，确认当前实现因不支持应用重建恢复而失败。

### Task 2: 创建SQLite Checkpointer基础设施

**Files:**
- Create: `backend/app/infrastructure/checkpoint/__init__.py`
- Create: `backend/app/infrastructure/checkpoint/sqlite.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/.env.example`

- [x] **Step 1:** 新增`CHECKPOINT_DATABASE_PATH: Path = Path("./data/checkpoints.sqlite")`配置。
- [x] **Step 2:** 实现异步上下文管理器：创建父目录，通过`AsyncSqliteSaver.from_conn_string(str(path))`打开连接，执行`await saver.setup()`并在退出时关闭。
- [x] **Step 3:** 使用独立检查点数据库，避免与后续业务数据库Schema耦合。

### Task 3: 在FastAPI生命周期中注入WorkflowRunner

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/api/routes.py`
- Modify: `backend/app/workflow/runner.py`

- [x] **Step 1:** 增加`create_app(checkpoint_database_path: Path | None = None)`应用工厂。
- [x] **Step 2:** 在lifespan启动阶段打开SQLite Saver、编译五阶段Graph，并把`WorkflowRunner`保存到`app.state.workflow_runner`。
- [x] **Step 3:** 路由通过FastAPI依赖从`request.app.state`读取Runner，不再导入模块级内存Runner。
- [x] **Step 4:** 删除生产路径中的`in_memory_checkpointer()`；单元测试仍可直接使用LangGraph官方`InMemorySaver`测试纯Graph行为。

### Task 4: 统一测试客户端生命周期

**Files:**
- Modify: `backend/tests/test_health.py`
- Modify: `backend/tests/test_workflow_api.py`
- Modify: `backend/tests/security/test_api_authentication.py`

- [x] **Step 1:** 所有API测试通过`with TestClient(create_app(...))`启动和关闭lifespan。
- [x] **Step 2:** 每个测试使用`tmp_path`中的独立SQLite文件，避免状态串扰。
- [x] **Step 3:** 多用户测试在同一应用实例中按请求传不同Bearer Token，确保共享同一持久化任务状态。

### Task 5: 验证与文档

**Files:**
- Modify: `backend/app/workflow/README.md`
- Modify: `backend/README.md`

- [x] **Step 1:** 运行持久化测试，预期任务可跨应用实例恢复。
- [x] **Step 2:** 运行`.venv/bin/pytest`，预期全部测试通过。
- [x] **Step 3:** 运行`.venv/bin/black --check app tests`、`.venv/bin/flake8 app tests`和`.venv/bin/mypy app`。
- [x] **Step 4:** 文档说明SQLite负责运行记忆、默认路径、单Worker边界和数据库备份要求。
