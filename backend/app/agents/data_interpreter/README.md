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
- 使用结构化输出生成`AnalysisDraft`；DeepSeek兼容模型采用`json_mode`并注入完整的机器可读JSON Schema，技术契约优先于金融提示词中的报告展示模板。
- 结构化失败统一分类为污染、JSON语法、Schema、业务语义、输出截断和供应商异常；只记录模型名、请求ID、结束原因、字符/token数量及校验字段路径，不保存密钥或原始证据正文。
- 安全解析只允许标准JSON、单层Markdown围栏及唯一完整JSON对象；不执行单引号替换、尾逗号修复或JSON5宽松接收。
- 首次JSON解析或Pydantic校验失败时最多执行一次结构修复；修复回合会携带上一份可读响应并明确冻结金融事实、数字、结论和`evidence_id`，第二次仍不合规则安全失败。供应商明确截断或JSON未闭合时不盲目补括号。
- 运行时Prompt达到`LLM_SEGMENTED_THRESHOLD_CHARS`（默认36000字符）时，自动拆为“核心分析”和“情景、风险、协同与图表补充”两个小Schema生成，再由服务端合并并通过完整`AnalysisDraft`终检；短请求仍保持单次调用。
- Agent内部执行`Router → selected Skills → LangGraph`，Router为确定性代码，不调用LLM。
- LangGraph内部执行`prepare → generate → audit → revise/finalize`。
- 检查未知证据ID、已否决结论和金融内容红线，最多自动修订两次。
- 输出`AnalysisResult`并封装为`StageResult(stage=data_interpret)`。
- 输出统一的`data_quality_issues`，区分缺失、过期、冲突、估算和不可比，并给出影响级别、处理方式与证据ID。
- 输出顾问式`financial_consistency_checks`，记录财务勾稽、现金利润匹配、营运资金异常或非经常项目；`warning/unavailable`只降低结论强度，不补造数据。
- 输出五维`dimension_coverage`（`supported/partial/insufficient`）；模型未填写时由确定性规则根据结论和证据补全。
- 支持可选`research_brief`限定地域、时间、包含/排除主题、重点企业与`brief/standard/deep`报告深度。

## 下游适配

- Agent 3使用`chart_candidates`及其`evidence_ids`。
- Agent 3还使用`data_quality_issues`为图表增加口径脚注。
- Agent 4使用`claims`、`dimensions`、`scenarios`、`risks`、维度覆盖和财务一致性检查。
- Agent 5汇总上述质量信息，生成数据质量与研究边界附录。

关键输入缺失时不调用LLM，直接返回`waiting_review`和`collaboration_requests`。

## 模型配置

默认`LLM_USE_MOCK=true`。真实模型配置：

```text
LLM_USE_MOCK=false
LLM_API_KEY=...
LLM_BASE_URL=...
LLM_MODEL=qwen-plus
LLM_SEGMENTED_THRESHOLD_CHARS=36000
```

密钥只从环境变量读取。
