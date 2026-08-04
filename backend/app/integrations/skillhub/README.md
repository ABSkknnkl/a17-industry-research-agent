# SkillHub Adapter

后端 A 负责。先定义统一客户端接口，再提供真实实现与本地 Mock。调用必须设置超时、有限重试、限流处理，并保存查询参数和来源元数据。

Agent 1不得直接从业务节点调用CLI或HTTP客户端。每个SkillHub能力注册为`ToolDefinition`，参数使用独立Pydantic模型，然后交给`app.runtime.tool_gateway.ToolGateway`。Gateway已统一提供：

- 未注册工具拦截与参数Schema校验；
- `beforeToolCall`/`afterToolCall`式Hook；
- 单次调用超时和单任务工具调用预算；
- 工具异常、超时和阻断原因的标准化`ToolResult`回灌；
- 长结果截断及不记录参数、Token和供应商异常的脱敏事件。

工具实现只返回原始业务数据与必要来源元数据，不负责生成金融结论。Agent 1负责清洗和形成标准证据包，Agent 2继续负责解读。
