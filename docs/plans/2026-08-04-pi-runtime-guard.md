# Pi 风格 P0 运行护栏实施计划

## 范围

保留 LangGraph、SQLite Checkpointer、五阶段契约和现有 Agent 2/4 提示词，仅借鉴 Pi Agent Harness 的运行循环与工具执行顺序。不引入 Pi 运行时依赖，不实现 P1 上下文自动摘要、完整成本看板或分布式取消。

参考源码：`earendil-works/pi`（原 `badlogic/pi-mono`）的 `packages/agent/src/agent-loop.ts`，MIT License。借鉴点为 `shouldStopAfterTurn`、`transformContext`、参数校验、`beforeToolCall`、执行、`afterToolCall`、错误结果回灌和生命周期事件。

### Task 1：失败状态与恢复路由

**Files:**
- Modify: `backend/app/workflow/graph.py`
- Test: `backend/tests/workflow/test_pipeline.py`

- [x] 写测试证明阶段返回 `FAILED` 后下游不得执行，并进入人工恢复节点。
- [x] 写测试证明失败结果不能直接 `approve`，只允许 `revise`、`regenerate` 或 `cancel`。
- [x] 修改阶段路由并运行 `pytest backend/tests/workflow/test_pipeline.py -q`，预期通过。

### Task 2：运行状态、预算和阶段超时

**Files:**
- Create: `backend/app/runtime/models.py`
- Create: `backend/app/runtime/guard.py`
- Create: `backend/app/runtime/__init__.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/workflow/state.py`
- Modify: `backend/app/workflow/stages.py`
- Modify: `backend/app/workflow/graph.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/workflow/test_pipeline.py`

- [x] 写预算耗尽、阶段超时和事件数量有界测试。
- [x] 实现持久化 `RuntimeState`，包含阶段、模型、工具调用计数、截止时间、停止原因和脱敏事件。
- [x] 用 `asyncio.timeout` 包装阶段执行；异常转换成标准 `StageResult`，不得让图崩溃或继续下游。
- [x] 将运行快照放入 `StageContext`，保持 Agent 2/4 现有调用兼容。

### Task 3：模型调用计数

**Files:**
- Create: `backend/app/runtime/model_gateway.py`
- Modify: `backend/app/workflow/factory.py`
- Test: `backend/tests/runtime/test_model_gateway.py`

- [x] 写模型调用计数和超额阻断测试。
- [x] 用装饰器包装 `AnalysisModel` 与 `ChapterWritingModel`，在当前运行上下文中执行调用前后事件。
- [x] 在 StageRegistry 工厂统一包装模型，避免修改金融分析提示词和业务输出模型。

### Task 4：统一 ToolGateway

**Files:**
- Create: `backend/app/runtime/tool_gateway.py`
- Test: `backend/tests/runtime/test_tool_gateway.py`

- [x] 写未注册工具、参数错误、Hook 阻断、超时、异常回灌、结果截断和工具预算测试。
- [x] 实现 Pi 同序流程：查找工具 → 参数转换/Schema 校验 → before Hook → 超时执行 → after Hook → 标准化 `ToolResult`。
- [x] 所有错误返回给 Agent 可读的 `ToolResult`，不抛出导致 Agent 循环中断的业务异常。

### Task 5：验证和交接

**Files:**
- Modify: `backend/app/workflow/README.md`
- Modify: `backend/app/integrations/skillhub/README.md`
- Modify: `THIRD_PARTY_NOTICES.md`

- [x] 记录 Agent 1/3/5 如何接入 ToolGateway 和运行预算。
- [x] 运行后端全量测试、Black/Flake8/Mypy，以及前端`verify`与生产构建。
- [x] 确认没有改动提示词资产、公开业务 Schema 和前端。
