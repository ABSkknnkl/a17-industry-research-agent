# Agent 3：确定性图表生成

Agent 3 是顶层五阶段 LangGraph 的第三个节点，内部不再创建 Agent 循环，也不调用 LLM、SkillHub、MCP 或网络。输入来自 Agent 1 的 `ChartDataset[]` 和 Agent 2 的 `ChartCandidate[]`，输出纯 JSON ECharts Option、`ChartReference[]` 与可校验的 `ArtifactRef[]`。

## P0 范围

- `line`：时间序列，按 `period_end` 排序，保留 `null` 断点，最多五条序列。
- `bar`：确定性选择 `vertical`、`horizontal`、`grouped`、`stacked`；堆叠要求 `is_additive=true`。
- `pie`：只接受单时点、正值、互斥且不超过5类的构成数据；不满足时审计降级为柱状图。
- `radar`：只接受3—8个已标准化、共享同一刻度的指标；不满足时审计降级为柱状图。
- `industry_chain`：使用 ECharts `graph` 和固定上游→中游→下游布局，不虚构边权。

P1 已提供 `combo`、`area`、`scatter`、`bubble`、`heatmap`、`boxplot`、`treemap` 的条件路由和降级能力，但不是每份报告的必备图表。P0 五类是比赛要求的基础能力。

## Router + Skill

`router.py` 只根据候选类型与标准化数据特征分发 Builder；`builders.py` 中每个 Builder 都是无副作用的确定性 Skill。同数据、同目的的同族图表通过 SHA-256 指纹和 `dedupe_key` 只保留一张。

5—8张、P1最多3张、同族/同章密度等均为推荐值，只生成风险提示，不阻断流水线。技术上限只会跳过当前不可安全渲染的图表；数据不足时不强行凑数，允许零图表进入 Agent 4/5。

每个就绪图表同时透传`insight_goal`、`quality_issue_ids`和`footnotes`。只要底层数值与证据契约可用，数据口径风险不会静默删除图表，而是在图表下方明确显示；无法安全渲染的候选仍会被跳过并写入最终报告附录。

## 借鉴边界

- Apache ECharts：使用 `dataset/option` 分离思想和各图表的公开配置。
- pyecharts：参考 Python 字典到 ECharts JSON 的字段映射与 `NaN/null` 处理，不依赖其运行时生成主路径。
- stock-industry-chain：借鉴 `nodes + edges + stage` 数据结构，未复制业务数据。
- BettaFish：借鉴 Validator/QualityReport 的问题汇总模式。
- Pi：沿用项目现有的阶段超时、取消、结构化错误和运行事件；不引入 Pi 依赖或 LLM 工具循环。

## 人工审核

审核接口仅允许修改标题、白名单图表类型、柱状图变体、数据集选择和白名单主题，不能提交任意 ECharts JSON。多个数据集同时命中时按证据贴合度确定性选择并告警；缺少数据集、单图构建失败或质量门未通过时跳过问题图并以 `completed` 返回风险清单。只有上游契约不可读、安全策略、取消或运行预算耗尽才停止。

Agent 1 已直接输出带证据 ID、单位、币种和数据时点的 `ChartDataset[]`。无密钥测试使用 `MockSkillHubClient`，但数据仍经过同一 Agent 1 标准化链路，不再由 Workflow 临时重组。
