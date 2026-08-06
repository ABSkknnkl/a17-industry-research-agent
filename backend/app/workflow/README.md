# Workflow

后端 C 负责。当前已实现基于 LangGraph 1.x 的五阶段注册式骨架、通用人工审核中断与恢复，以及供前端轮询的运行接口。API 只能通过 Workflow 调度 Agent，不得跨层直接调用。

## 接入接口

每个阶段实现 `StageAgent`：

```python
class StageAgent(Protocol):
    stage: StageName

    async def run(self, context: StageContext) -> StageResult:
        ...
```

新智能体完成后，在 `factory.py` 中用真实实现替换对应 `MockStageAgent`，不得修改其他智能体代码或绕过 `StageRegistry`。

`StageContext`提供所有者、项目/运行/修订编号、初始输入、已完成的上游结果、人工审核意见、已否决结论编号和只读运行预算快照。

## 当前状态

- `data_interpret`使用真实`DataInterpreterAgent`，`chapter_write`使用真实`ChapterWriterAgent`。
- `data_fetch`、`chart_generate`和`report_fusion`仍使用契约兼容Mock，便于在其他成员开发期间验证完整流程。
- `chapter_write`已消费Agent 2真实契约，并兼容Agent 3 Mock；默认在Agent 2和Agent 4后进入人工审核。
- Checkpointer已使用生命周期托管的`AsyncSqliteSaver`，默认写入`./data/checkpoints.sqlite`；同一`run_id`可在后端重启后继续查询、审核和恢复。
- SQLite Checkpointer面向比赛版单实例/单Worker部署；多Worker或多实例上线前应迁移到共享的PostgreSQL Checkpointer。
- 当前进度获取采用`GET /api/v1/runs/{run_id}`轮询，全部智能体完成后再统一评估SSE/WebSocket。
- 任务接口已启用Bearer Token；`run_id`只由服务端生成，查询、审核和取消都校验`owner_id`。
- 创建请求与五阶段审核均使用Pydantic白名单，任意`input_data/edited_data`不再进入Workflow。
- Agent 2和Agent 4通过`SecuredStageAgent`执行外部文本注入检测和敏感输出检查；命中时保留`waiting_review`但不传递可疑原文。
- 比赛版限流与安全事件仍为进程内实现；切换多Worker或多实例部署时，必须换成共享存储实现。
- 已加入Pi风格P0运行护栏：阶段返回`failed`时停止下游并进入人工恢复；失败结果不得直接`approve`，只能修订、重生成或取消。
- `RuntimeState`随LangGraph检查点保存，限制总阶段执行、单阶段尝试、模型调用、工具调用和任务时限；历史旧检查点缺少该字段时会自动初始化。
- 每个阶段由`asyncio.timeout`限制执行时间；未处理异常被转换为脱敏`StageResult`，不会击穿整条Workflow。
- 模型通过`RuntimeAwareAnalysisModel`和`RuntimeAwareChapterWritingModel`统一计数，不修改Agent 2/4的业务协议或提示词。
- 运行事件只保存阶段/模型/工具名称、结果码和计数，不保存Prompt、工具参数、外部原文、模型正文或供应商异常信息。

## 运行状态存储

- 使用环境变量`CHECKPOINT_DATABASE_PATH`修改检查点数据库路径。
- 应用启动时自动创建父目录和LangGraph检查点表，应用关闭时释放SQLite连接。
- `checkpoints.sqlite`只保存LangGraph运行记忆，不替代项目、报告、用户偏好等业务数据库。
- 部署或备份时必须保留检查点文件；Docker运行时应把`data/`挂载到持久化Volume。

## 通用API

- `POST /api/v1/runs`
- `GET /api/v1/runs/{run_id}`
- `POST /api/v1/runs/{run_id}/reviews`

三个接口均需`Authorization: Bearer <token>`。审核使用`expected_revision`进行乐观版本校验。`revise`和`regenerate`增加修订号并重新运行当前阶段；`approve`进入下一阶段；`cancel`结束流程。

## Agent接入约束

- Agent 1/3/5仍实现同一个`StageAgent.run(context)`接口，不自行创建无限循环。
- Agent 3 已替换 Mock：使用确定性 Router + P0 Builder 生成 ECharts JSON；Agent 1 当前仍通过开发适配器提供测试用 `ChartDataset`。
- 外部API、SkillHub和可执行工具必须通过`app.runtime.tool_gateway.ToolGateway`调用，顺序固定为：工具查找、Pydantic参数校验、before Hook、限时执行、after Hook、结构化结果回灌。
- `ToolResult.is_error=true`是可交给Agent纠正的正常结果；不得把供应商原始异常、Cookie、Token或完整请求参数写入结果和日志。
- 工具结果超过`MAX_TOOL_RESULT_CHARS`会返回截断预览。Agent 1应拆分查询；P1产物存储完成后再升级为“摘要+产物引用”。
