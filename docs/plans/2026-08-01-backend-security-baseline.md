# 后端基础安全防护实施计划

## 范围

本迭代只修改后端、契约和自动化测试，不修改前端。安全层必须保持现有五阶段Workflow、Agent 2和Agent 4的业务输出契约不变。

### 任务1：Bearer认证与任务归属

**文件：**

- 新建：`backend/app/security/auth.py`
- 新建：`backend/app/security/audit.py`
- 修改：`backend/app/core/config.py`
- 修改：`backend/app/api/routes.py`
- 修改：`backend/app/workflow/state.py`
- 修改：`backend/app/workflow/runner.py`
- 测试：`backend/tests/security/test_api_authentication.py`

- [x] RED：未带Token创建任务返回401，无效Token返回401。
- [x] GREEN：通过HTTP Bearer依赖把Token映射为`owner_id`，只保存Token摘要。
- [x] RED：客户端提交`run_id`被契约拒绝。
- [x] GREEN：`WorkflowRunner`只使用UUID4生成`run_id`，内部状态保存`owner_id`。
- [x] RED：用户B查询、审核或取消用户A的任务失败。
- [x] GREEN：Runner在读取快照和恢复任务前校验归属，API不泄露任务内容。

### 任务2：创建与分阶段审核白名单

**文件：**

- 修改：`backend/app/schemas/run.py`
- 修改：`backend/app/schemas/workflow.py`
- 修改：`backend/app/schemas/evidence.py`
- 修改：`contracts/schemas/review-action.schema.json`
- 测试：`backend/tests/security/test_request_whitelists.py`

- [x] RED：创建请求中的未知字段、超长主题/问题、超量证据被拒绝。
- [x] GREEN：使用显式`ResearchInput`取代任意`input_data`。
- [x] RED：章节审核不能修改LLM配置、所有者或其他阶段字段。
- [x] GREEN：根据`stage`选择对应编辑模型，通过Pydantic完成嵌套白名单校验。

### 任务3：提示注入与敏感输出拦截

**文件：**

- 新建：`backend/app/security/policy.py`
- 新建：`backend/app/security/agent_guard.py`
- 修改：`backend/app/workflow/factory.py`
- 测试：`backend/tests/security/test_prompt_and_output_policy.py`

- [x] RED：审核意见要求忽略规则、显示系统提示词或读取密钥时不恢复LLM流程。
- [x] GREEN：轻量规则只拦截明确越权意图，正常金融审核意见继续执行。
- [x] RED：Agent 1外部文本中的伪指令在Agent 2调用模型前被拦截。
- [x] GREEN：Agent 2安全包装器把外部证据当作不可信数据扫描。
- [x] RED：Agent 2/4输出Bearer Token、API Key或系统提示词复述时不向下游传递原文。
- [x] GREEN：安全包装器返回脱敏`waiting_review`结果，保留错误码和事件追踪ID。

### 任务4：请求限制、限流与安全日志

**文件：**

- 新建：`backend/app/security/rate_limit.py`
- 新建：`backend/app/security/middleware.py`
- 新建：`backend/app/security/runtime.py`
- 修改：`backend/app/main.py`
- 修改：`backend/app/api/routes.py`
- 测试：`backend/tests/security/test_limits_and_audit.py`

- [x] RED：超过1MB请求体返回413。
- [x] GREEN：ASGI中间件在路由解析前根据`Content-Length`拒绝过大请求。
- [x] RED：超过每用户创建/审核频率时返回429。
- [x] GREEN：进程内滑动窗口限流器按`owner_id + operation`隔离计数。
- [x] RED：安全日志不包含原始Token、恶意文本和Agent可疑输出。
- [x] GREEN：结构化日志只保存事件类型、owner/run/stage、原因、结果、trace ID、内容SHA-256和长度。

### 任务5：全仓回归与交接

**文件：**

- 修改：`backend/.env.example`
- 修改：`backend/app/workflow/README.md`
- 修改：`docs/development/setup.md`

- [x] 运行`backend/.venv/bin/python -m pytest`，包含新增安全用例。
- [x] 运行Black、Flake8和Mypy。
- [x] 运行`./scripts/verify.sh`，确认前端在未修改的情况下仍可构建。
