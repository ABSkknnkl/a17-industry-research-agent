# 4条高难度话术回归验收——智能体1→2→3 链路测试报告

## 测试环境
- 智能体1：真实 iFinD/Iwencai 数据源（live）
- 智能体2：Assistant 充当大模型（验证模型，不调用外部 LLM）
- 智能体3：生产 ChartGeneratorAgent
- 运行脚本：`test_agents_chain_4cases.py`
- HTML 产物：`test_output/agents_chain_4cases/CASE{1..4}.html`

## 结果汇总

| 用例 | 智能体1 | 智能体2 | 智能体3 | 图表数 | 拦截拦截点 |
|------|:---:|:---:|:---:|:---:|------|
| CASE1 杜邦+周转+对标图 | waiting_review | waiting_review | completed | 6 | 缺少股东权益科目 |
| CASE2 市占率CRn+互斥 | waiting_review | waiting_review | completed | 8 | 市占率/份额未取到 |
| CASE3 逆变器CR5+多图 | waiting_review | waiting_review | completed | 8 | 市占率/份额未取到 |
| CASE4 产能利用率+产销率+产业链 | waiting_review | waiting_review | completed | 8 | 产量/产能/销量未取到 |

✅ 4 个用例全部进入拦截评审，符合"拦截也是成功"的验收标准。

## 全链路行为

1. **智能体1**：`blocking_issues=["required_data_unavailable"]`，但对 `data_fetch_options.metrics` 指定的**专项指标**（股东权益、市占率、市场份额、产量、产能、销量、有效产能、产能利用率、产销率）对应的专项检索任务（Q-12~Q-17）**全部返回 0 行**，产生 `missing_requirements` 并进入 WAITING_REVIEW。
2. **智能体2**：因关键输入科目缺失，确定性计算 `calculate_p0_metrics` 无法产出 CR3/CR5/产能利用率/产销率等 → `calculated_metrics=0`、`chart_candidates=0`。各用例被不同层拦截：
   - CASE1：前置计算缺口 `CALCULATION-DATA-MISSING`
   - CASE2：前置元数据 `EVIDENCE-METADATA`（前视偏差）
   - CASE3：验证大模型 `CONCENTRATION-NO-SAMPLE`
   - CASE4：验证大模型 `CAPACITY-INSUFFICIENT`
3. **智能体3**：无智能体2候选时，基于智能体1的 `chart_datasets` 兜底生成 6-8 张图表（原始指标：营业成本、存货、市盈率、涨跌幅、净资产收益率等）。

## 问题与根因

### 问题1（根因）：智能体1 无法通过 `data_fetch_options.metrics` 获取专项科目
- **现象**：市占率、市场份额、产量、产能、销量、股东权益等专项指标查询全部返回 0 行。
- **根因**：iFinD 的 `hithink_macro_query` 对自定义指标查询（`query2data`）无法解析这些自然语言指标名，返回空结果。智能体1 的 [planner.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_fetcher/planner.py) 对 `metrics` 生成的专项任务（Q-12 起）全部失败。
- **影响**：CR5、产能利用率、产销率、杜邦等依赖这些科目的计算全部无法执行。

### 问题2：智能体3 兜底图表与用户需求脱节
- **现象**：智能体2 被拦截（无候选）后，智能体3 兜底生成的是原始指标图表（涨跌幅、市盈率、成交额对比），而非用户要求的计算结果图表。
- **根因**：智能体3 的 `_backfill_dataset_candidates` 会对每个未用数据集生成默认候选，即使该数据集与用户话术无关。
- **影响**：生成的图表"能看"但不"对症"，需人工甄别。

### 问题3：unit 字段大量缺失
- iFinD 返回的财务指标 `unit="未提供"`，导致智能体2 的 `_compatible_units` 只能按空字符串比较，口径校验失真（CASE1 前置拦截即源于此）。

## 校验点逐项结论

| 用例 | 校验点 | 结论 |
|------|--------|------|
| CASE1 | 固定公式执行 | ❌ 因缺股东权益/期初，杜邦未产出 |
| CASE1 | 期初缺失自动降级 | ✅ 智能体1 明确 `missing_requirements`，未编造 |
| CASE1 | 携带公式/证据ID | ⚠️ 无产出，无法验证 |
| CASE1 | 结果流转至Agent3 | ⚠️ 智能体3 兜底产出原始图表，非计算图表 |
| CASE2 | 聚合算子CR3/CR5 | ❌ 市占率未取到，无法计算 |
| CASE2 | 同类图表二选一 | ⚠️ 无市占数据，互斥未触发 |
| CASE2 | 不捏造份额 | ✅ 严格拦截 |
| CASE3 | 识别多图需求+豁免开关 | ⚠️ 开关已传，但因无数据未生效 |
| CASE3 | 互斥限制解除 | ⚠️ 无数据未验证 |
| CASE3 | 不伪造数值 | ✅ 严格拦截 |
| CASE4 | 产能利用率/产销率计算 | ❌ 产量/产能/销量未取到 |
| CASE4 | 产业链图数量上限 | ✅ 智能体3 有 `industry_chain_single_default` 逻辑 |
| CASE4 | 季度/年度混用拦截 | ⚠️ 未触发（数据未取到） |

## 修复建议

1. **P0 智能体1 专项指标取数**：为 `data_fetch_options.metrics` 增加专用数据源映射（市占率走问财选股、产量/产能走行业经济指标EDB），或对专项任务使用 `hithink_industry_query`/`hithink_finance_query` 而非 `hithink_macro_query`。
2. **P1 unit 补全**：iFinD 返回空 unit 时，按指标类型推断默认单位（财务科目=元/亿元、比率=%，避免口径失真）。
3. **P1 智能体3 兜底约束**：当智能体2 无候选（被拦截）时，智能体3 应优先只生成与 `focus_questions` 相关的数据集图表，而非全量兜底。
4. **P2 互斥/豁免回归**：修复 P0 后可复测 CASE2/CASE3 的互斥二选一与多图豁免开关。

## 产物
- 图表 HTML：`test_output/agents_chain_4cases/CASE{1..4}.html`
- 链路 JSON：`test_output/agents_chain_4cases/CASE{1..4}.json`
- 汇总：`test_output/agents_chain_4cases/summary.json`