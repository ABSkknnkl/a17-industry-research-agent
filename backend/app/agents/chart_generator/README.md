# Agent 3：确定性图表生成

Agent 3 是顶层五阶段 LangGraph 的第三个节点，内部不再创建 Agent 循环，也不调用 LLM、SkillHub、MCP 或网络。输入来自 Agent 1 的 `ChartDataset[]` 和 Agent 2 的 `ChartCandidate[]`，输出纯 JSON ECharts Option、`ChartReference[]` 与可校验的 `ArtifactRef[]`。

## P0 范围

- `line`：时间序列，按 `period_end` 排序，保留 `null` 断点，最多五条序列。
- `bar`：确定性选择 `vertical`、`horizontal`、`grouped`、`stacked`；堆叠要求 `is_additive=true`。
- `industry_chain`：使用 ECharts `graph` 和固定上游→中游→下游布局，不虚构边权。

P1/P2 图表不进入当前代码契约。后续扩展必须新增独立 Skill，并保持现有 P0 路由结果不变。

## Router + Skill

`router.py` 只根据候选类型与数据集 `kind` 分发到三个 Builder；`builders.py` 中每个 Builder 都是无副作用的确定性 Skill。相同数据通过 SHA-256 指纹和图表族组成的 `dedupe_key` 只生成一次。

## 借鉴边界

- Apache ECharts：使用 `dataset/option` 分离思想和 `line`、`bar`、`graph` 公开配置。
- pyecharts：参考 Python 字典到 ECharts JSON 的字段映射与 `NaN/null` 处理，不依赖其运行时生成主路径。
- stock-industry-chain：借鉴 `nodes + edges + stage` 数据结构，未复制业务数据。
- BettaFish：借鉴 Validator/QualityReport 的问题汇总模式。
- Pi：沿用项目现有的阶段超时、取消、结构化错误和运行事件；不引入 Pi 依赖或 LLM 工具循环。

## 人工审核

审核接口仅允许修改标题、P0 类型、柱状图变体、数据集选择和白名单主题。多个数据集同时命中、缺少数据集或质量门失败时返回 `waiting_review`；审核接口不能提交任意 ECharts JSON。

Agent 1 尚未完成时，`MockStageAgent(DATA_FETCH)` 只把数值型 `EvidenceItem` 原样重组为单点分类数据集，用于集成测试。正式 Agent 1 接入后必须移除这个开发适配器。
