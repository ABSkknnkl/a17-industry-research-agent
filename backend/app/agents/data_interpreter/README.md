# Data Interpreter

后端 B 负责。面向中国内地、香港、美国及其他主要股票市场，只基于 Data Fetcher 的证据数据生成结构化解读，禁止补造指标；输出必须记录证据 ID、模型和 Prompt 版本。

## 已实现能力

- 读取Agent 1的`StageResult.data`并通过`AnalysisRequest`校验。
- 检查报告期末、公告日/可得日、单位、审计状态、追溯调整、统计范围和证据定位。
- 检查市场、交易所、证券类型、币种、会计准则及价格复权/公司行动处理状态。
- 跨市场分析要求完成财年对齐、币种换算、多地上市去重和股份类别/存托凭证比例校验。
- 研究时点后的证据不会进入有效证据集合。
- 原始金融提示词按只读资源加载并校验SHA-256，业务代码不修改正文。
- 当前主提示词版本为`global-equity-analysis-v2`，A股作为支持市场之一，不再作为默认唯一核心。
- 已为Agent 2注册“行为金融分析”“竞争格局分析”“受限产业链解读”三个辅助技能；所有技能按只读资源加载、校验SHA-256，实际命中的技能记录在输出`skills`字段。
- `SupportingSkillRouter`只根据行业主题、关注问题、人工反馈和证据元数据中的显式关键词选择技能；未命中的技能不会进入System Prompt，减少无关上下文与模型消耗。
- 行为金融技能仅用于解释认知偏差、情绪周期和提出候选监测指标；竞争格局技能仅复用可比性、份额、壁垒与护城河方法，并忽略其PPT制作指令。
- 产业链技能受到额外限制：只复用链路拆解、利润池、议价权、咽喉节点和验证指标方法，禁止执行技能内的主动检索、投资映射、星级评分、长期预测和无证据定调。
- 三个技能均不得替代证据源；固定阈值、收益概率、经验数字及任何事实判断必须由当前`evidence_id`支撑，证据不足时转入`collaboration_requests`。
- 使用`AnalysisModel`协议支持Mock与OpenAI兼容模型。
- 使用结构化输出生成`AnalysisDraft`。
- Agent内部执行`Router → selected Skills → LangGraph`，Router为确定性代码，不调用LLM。
- LangGraph内部执行`prepare → generate → audit → revise/finalize`。
- 检查未知证据ID、已否决结论和金融内容红线，最多自动修订两次。
- 输出`AnalysisResult`并封装为`StageResult(stage=data_interpret)`。

## 下游适配

- Agent 3使用`chart_candidates`及其`evidence_ids`。
- Agent 4使用`claims`、`dimensions`、`scenarios`和`risks`。
- Agent 5使用`prompt`、`model_name`、`quality`、结论状态和证据引用。

关键输入缺失时不调用LLM，直接返回`waiting_review`和`collaboration_requests`。

## 模型配置

默认`LLM_USE_MOCK=true`。真实模型配置：

```text
LLM_USE_MOCK=false
LLM_API_KEY=...
LLM_BASE_URL=...
LLM_MODEL=qwen-plus
```

密钥只从环境变量读取。
