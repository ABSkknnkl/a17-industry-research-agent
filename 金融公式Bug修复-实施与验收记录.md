# 金融公式 Bug 修复 · 实施与验收记录

> 对应方案：`金融公式Bug修复与验收方案.md`（P-01～P-20、T01–T20、6.1–6.9）
> 对应清单：`金融公式审查清单.md`
> 实施日期：2026-11-12（决定执行与阶段验收：2026-11-13）
> 代码仓库：`同花顺赛题-T3交接`（HEAD `cfd92e5`）+ 工作树改动
> 解释器：`/opt/anaconda3/bin/python3`（Python 3.13.5，pydantic 2.12.4）

---

## 1. 结论摘要

- 6.1 / 6.2 / 6.3 / 6.4 / 6.5 / 6.6 / 6.7 / 6.8 **已全部实施并测绿**；三条待拍板事项与第四项 A4 净现比收口均已按你的决定落地。
- 方案第 3 节指定的四条测试：**76 passed, 9 skipped**（改动前 57 passed, 8 skipped，新增 19 个用例）。
- 项目全量回归：**2156 passed / 38 failed / 66 skipped**；干净基线 2095 / 38 / 79，**失败集合逐条一致**（`SAME_FAILURE_SET`）→ 无新增回归。38 个失败均为环境或既有缺陷（缺 `trio`、PDF 模板、5 个旧用例用 `SimpleNamespace` 缺 `comps_matrix`）。
- **阶段验收已用同一份冻结 A1 全链路跑通**：A2（新版）→ A3（真实模型，2 图 / 18 抑制）→ A4（7 章 21 节，真实模型）→ A5（report.md/html，19 处一致性修正）。
- 关键结果：研发费用率在原始快照缺单位时**整组按缺口抑制**；A4 已改为只引用 A2 的净现比，落盘时不再出现「约 1.8 倍」，缺口统一写「缺少同口径归母净利润，净现比无法计算」。

---

## 2. 逐条修复状态

| 编号 | 状态 | 代码入口 | 覆盖测试 |
|---|---|---|---|
| P-01 单位倍率 | ✅ | `financial_semantics.py`（`MONEY_UNIT_SCALES`/`normalize_money_unit`/`money_to_yuan`/`money_to_yi`）；`engine._normalize_money`；`fusion._split_value_unit` | `test_amount_unit_from_value_header_and_row` |
| P-02 市值字段名 | ✅ | `engine.compute_financial_ratios` 新增 `market_cap_100m_cny`，保留 `market_cap_billion` 兼容别名 + `market_cap_unit` | `test_market_cap_exposes_semantic_field_and_keeps_legacy_alias` |
| P-03 CR3/CR5 | ✅（按决定 A） | 测试拆「可用输入 / 基准同源 / 误差比较」，去掉 `or 0.0`；生产不新增 CR；基准显式 `status="unsatisfied"` + 原因 | `test_c1_missing_market_cap_is_not_zero_cr`、`test_unimplemented_concentration_groups_are_marked_unsatisfied` |
| P-04 ROE 改名 | ✅ | `eval/cases/baselines.json` 键 `dupont_roe → roe_pct`（保留 `legacy_key`，`calculation_type=reported_roe_single_value`） | `test_c1_roe_matches_baseline` |
| P-05 周转率/产能缺口 | ✅（文档级） | C1 三组显式 `skipped` + 原因，基准标 `unsatisfied`，不编数 | `test_c1_unresolved_groups_are_skipped_explicitly` |
| P-06 组内均值口径 | ✅ | `analysis_guard.build_group_comparison`：收集结构改「成员×指标×年→记录列表」，新增 `_resolve_cell`；毛利率 `equal_weighted_mean`、研发率 `aggregate_ratio` | `test_group_means_separate_equal_weight_and_aggregate_ratio` |
| P-07 研发率量纲 | ✅ | A2 以 `value_unit="ratio"` 发布；A3 `reviewed_rd_points` 只做一次 ×100 | `test_rd_ratio_ratio_unit_multiplies_once` / `..._percent_unit_is_not_multiplied_again` |
| P-08 正负基数同比 | ✅ | `engine._key_metrics` 仅基期为正时给 `change_pct`，新增 `change_basis`；`_trends` 新增 `total_change_basis`；`_verified_change` 负基期拒绝百分比断言 | `test_negative_base_has_no_yoy_percentage` / `test_turnaround_claim_cannot_be_written_as_yoy_growth` |
| P-09 研发率证据缺口 | ✅ | `_resolve_cell` + `money_to_yuan`；`gaps_by_year` 三种原因；A3 删除 `units_missing` 与 `scales.get(unit,1)` | `test_group_rd_ratio_gaps_when_units_are_unverified` / `test_rd_ratio_missing_middle_year_keeps_break` |
| P-10 净现比分母 | ✅ | `engine._paired_calculation` 候选列表 + 同值判定；`_cross_validate` 拆 `parent_net_profit` / `net_profit` | `test_cash_ratio_uses_parent_not_consolidated_profit` 等 4 例 |
| P-11 舍入冲突 | ✅ | `financial_semantics` 统一精度判定（`disclosure_step`/`matches_disclosed`/`rounding_verdict`）；**跨单位金额先换算到元再比较**，A1 与 A2 共用同一判定 | 冲突精度 4 例 + 跨单位 4 例 + A2 跨单位 2 例 |
| P-12 重述匹配 | ✅ | `fusion._computed_match`：完全相等即匹配，否则只用**已存值**精度复核重算值；重算值的小数位不再当作披露精度 | `test_restatement_matches_pre_value_by_disclosure_precision` 等 3 例 |
| P-13 死分支 | ✅ | `data_formulation._try_formulate_combo` 删除 `is_market_cap_ratio` 分支与 `100.0` 兜底 | `test_market_cap_pair_keeps_two_money_series_without_derived_ratio` |
| P-14 轴单位 | ✅ | `metric_guard.determine_series_currency_unit`、`data_formulation._currency_axis_unit/_resolve_series_target_unit` 统一委托 `choose_display_money_unit` | `test_amount_axis_matches_across_chart_paths` / `test_back_million_units_are_accepted_on_axis` |
| P-15 中位数 | ✅（可见变化已确认） | `compiler` 柱图极值、`render` 散点十字线改 `statistics.median` | `test_bar_extreme_marker_uses_standard_median` / `test_bar_without_extreme_keeps_no_marker` |
| P-16 百分数与倍 | ✅ | `engine._normalize_pct`、`metric_guard.normalize_financial_value` 去掉 `"倍"`；`20 倍` 不再变 2000% | `test_multiple_is_not_percent` |
| P-17 PEG 文案 | ✅ | `_cross_validate` 方法名改「高估值与负增长背离检验（未计算 PEG）」 | 现有 L1 契约测试 |
| P-18 IQR 脚注 | ✅（含计划外修复） | `render.py` 脚注写入最终页脚并预留一行高度（原实现 append 在页脚生成之后，脚注从未显示） | `test_scatter_axis_truncation_footnote_states_iqr_rule` |
| P-19 未知单位不继承 | ✅ | `metric_guard` / `data_formulation` 未登记单位直接抑制 | `test_unknown_amount_unit_does_not_inherit_axis_unit` |
| P-20 数量别名 | ✅ | `fusion._split_value_unit` 万套/亿台/万辆/万吨只换算一次；复合单位不换算 | `test_quantity_prefix_applied_once` |

---

## 3. 决定执行记录（2026-11-13）

### 决定 1 · P-03：保留缺口，显式「未满足」

- 生产仍未实现 CR3/CR5，也不发布市值代理口径。
- `eval/cases/baselines.json`：`cr3`、`cr5` 增加 `status="unsatisfied"` 与 `status_reason`（“生产未实现市值代理口径…待业务确认”）；`inventory_turnover` / `receivables_turnover` / `capacity_utilization` 同样标 `unsatisfied`。
- 新增测试 `test_unimplemented_concentration_groups_are_marked_unsatisfied`：基准必须显式未满足；生产结果里不得出现 `cr3/cr5` 键，不得用 0% 冒充。
- 已修好的缺失值处理保留：无合格市值样本时返回 `None`，CR 计算不产生 0 值。

### 决定 2 · P-11：金额跨单位先换算，再接入门禁

实现（A1 与 A2 共用 `agents_core.financial_semantics.measurement_conflict_verdict`）：

- **A1 `_find_conflicts`**：财务分组键改为「主体 / 指标 / 观测期 / 范围 / 币种 / 期间形态」，**单位不再进键**。
- 同一组内：非金额单位（`%`、`倍`）仍按单位分桶，各桶独立比较；金额单位统一换算到元后比较。
- 只比较 `unit_provenance` 可信的金额记录；不可信 → 返回 `None`（保守拦，不静默放行）。
- 披露精度可确认时：`10,000 万元` 与 `1 亿元` 等价；`100 万元` 与 `1 亿元` 判冲突；精度无法确认时标待核（阻断）。
- **A2 `_has_conflicting_measurement` / `_cross_unit_ambiguous`**：同一测量若跨单位冲突或待核，关键指标与趋势整体屏蔽，避免一边按万元、一边按亿元各算一条。

**差异清单（冻结快照实测，先出清单后接门禁）：**

| 数据集 | 改动前冲突数 | 改动后冲突数 | 新增冲突 |
|---|---|---|---|
| 主快照 `run-20261110013520-220857d7/dataset.json`（550 条） | 0 | 0 | **0** |
| `output/nev_specific_fix/artifacts/dataset.json`（带“元”标注候选） | 0 | 0 | **0** |

→ 真实数据上**没有新增冲突**；新门禁只在合成用例中触发（`100万元` vs `1亿元` 等）。

### 决定 3 · 两处可见变化：两处都保留

- P-15：`[1,10,30,110]` 继续把 110 标为极值。
- P-01：`1 万亿元` 继续显示为 `10,000 亿元`。

### 第四项决定 · A4 净现比只引用 A2（选 A）

**代码**
- 新增 `agents_core/chapter-writer/chapter_writer/net_cash_ratio.py`：
  - `build_net_cash_ratio_policy(report)` 只把「有值 + `denominator_metric=parent_net_profit` + 分子分母两条证据都在 evidence_index 里」的 A2 行判为可引用；旧产物缺口径字段一律按缺口处理。
  - 生成前把「可引用清单 / 缺口公司 / 禁止自算」写进章节上下文 `net_cash_ratio_policy`。
  - `apply_net_cash_ratio_guard(chapters, policy)` 在落盘前扫描摘要、要点、段落、callout、指标卡、对比表：数字与 A2 核验值对不上（或 A2 无值）的净现比断言，当场改写为「缺少同口径归母净利润，净现比无法计算」；无依据的净现比指标卡直接删除；命中核验值则补上 A2 的分子/分母证据 ID。
- `chapter_writer/agent.py`：`run()` 里构建 policy、注入每个章节的上下文，章节汇总后、质量审计与落盘前执行守卫；有修正时记录 `net_cash_ratio_guard_applied` 事件并写入 `content_audit` 与 warnings。

**行为**
- A2 有值：只允许原样引用，单位「倍」；主体对不上、值对不上、期间/证据不匹配 → 按缺口改写。
- A2 缺值或口径不明：不给任何倍数；经营现金流与净利润仍可分别描述（守卫按小句替换，不整段删除）。

**测试（9 例，全部通过）**
- `test_by_draft_claim_is_rewritten_to_gap_before_persist`：比亚迪「净现比约 1.8 倍」落盘前被改成缺口句，591 亿 / 326 亿保留。
- `test_verified_ratio_is_kept_and_cited`（正向）：A2 有效值 0.80 + 双证据，A4 原样保留 0.80 并补上两条证据 ID。
- `test_wrong_value_when_verified_exists_is_corrected`：A2 有 0.80、正文写 1.8 → 改写。
- `test_unverified_metric_card_is_removed` / `test_verified_metric_card_is_kept`
- `test_unverified_table_cell_is_rewritten`
- `test_policy_prompt_lists_only_verified_and_gap`
- `test_legacy_ratio_without_denominator_is_not_referenceable`
- `test_wrong_period_is_not_cited_even_when_value_matches`：值相同但正文年份与 A2 期间不一致 → 按缺口改写。

**真实回归（比亚迪）**
- 新 A4：`output/a4_acceptance_p01_p20/runs/chapters-20261113001656-5f8143d3/`，7 章 21 节。
- `chapter_result.json` 中 `1.8` 出现 **0 次**；CH-01 / CH-05 的净现比表述均为「因缺少同口径归母净利润…无法计算，不给出倍数」。
- 守卫修正数 **0**：模型按上下文里的强制口径直接写对，没有先写错再改。
- 新 A5：`output/a5_acceptance_p01_p20/runs/report-20261113001800-050c94d5/`，`report.md` 无「1.8」，`fact_audit` 的 54 条审计记录里没有一条与净现比相关 → **A5 对这一项无需自动修正**。
- 质量门禁按各自结果记录：A4 `quality.passed=false`（覆盖率 5.8%，历史同类问题），A5 `consistency.passed=false`（64 条 issues / 184 条 quality issue / 19 处其他编辑）。

### 重述精度口径（P-12）

- 新函数 `fusion._computed_match`：公告只给分子/分母时，`before/after` 是**我方重算值**，其小数位不作为披露精度。
- 匹配规则：完全相等 → 匹配；否则只用**已存值**的精度把重算值舍入后复核；精度不可确认 → `None`（待核）。
- 测试结果：`16.9% -> 16.92%/17.14%` 仍能按 0.1 个百分点替换；`16.9%` 同时兼容前后值时保持 `pending_restatement`；重放不重复替换。

### 阶段验收（同一份冻结 A1）

1. **A2 新版**：`output/a2_acceptance_p01_p20/interpretation_report.json`，550 条证据，20 指标 / 33 趋势 / 74 异常；电池组研发率 2023–2025 全部 `unverified_member_value` 缺口，整车组 `本组缺少 rd_expense`，均不跨组顶替。
2. **A3 真实模型**：`output/a3_acceptance_p01_p20_stage/runs/charts-20261113000701-ac36da66/`，2 图、18 抑制、`quality.passed=true`；真实选型参与（`llm_plan_parsed` 1、`skill_invoked_by_llm` 5、`llm_candidate_rejected` 12）。
3. **A4 真实模型（净现比收口后）**：`output/a4_acceptance_p01_p20/runs/chapters-20261113001656-5f8143d3/`，7 章 21 节，`status=partial`，`quality.passed=false`（证据覆盖率 5.8%，大量「数值语义未通过」）。
   - 净现比：落盘文件里 `1.8` 出现 0 次，CH-01 / CH-05 均写「缺少同口径归母净利润…无法计算」。
   - 对照：2026-11-12 的历史真实 A4（`chapters-20261112160130-b72b37c6`）同样 `quality_passed=false`、覆盖率 9.7%、同类数值问题 → **属既有行为，不是本轮引入**；改造前一轮 `chapters-20261113000820-66de13a8` 的「1.8 倍」已作为回归样本。
4. **A5 真实模型（净现比收口后）**：`output/a5_acceptance_p01_p20/runs/report-20261113001800-050c94d5/`（report.md / report.html / fact_audit.json / consistency_report.json）。
   - `consistency_report.passed=false`：64 条问题、184 条 quality issue、19 处其他自动修正、0 处拒绝修正。
   - 净现比：A4 已写缺口，A5 无需对本项做修正；`fact_audit` 的 54 条审计记录中没有净现比相关条目。

---

## 4. 测试执行结果

### 4.1 方案第 3 节指定命令

```bash
python3 -m pytest -q \
  backend/tests/test_ab1_metric_unit_provenance.py \
  backend/tests/l1/test_c1_formula_baselines.py \
  agents_core/data-analysis/tests/test_measurement_semantics_audit.py \
  agents_core/chart-generator/tests/test_shared_axis_unit_v8_final.py
```

结果：**76 passed, 9 skipped**（8 个 skip 仍为历史黄金样本缺失与同比重算未接入，新增 1 个 skip 为 CR 组显式缺口）。

### 4.2 冲突/重述专项

```bash
python3 -m pytest -q backend/tests/test_financial_conflict_precision.py \
  backend/tests/test_official_restatement_reconciliation.py
```

结果：全部通过（含新增跨单位 4 例、未知来源保守拦 1 例）。

### 4.3 全量回归

| 工作树 | passed | failed | skipped |
|---|---|---|---|
| 基线（`git worktree` HEAD `cfd92e5`） | 2095 | 38 | 79 |
| 当前（决定执行后） | 2156 | 38 | 66 |

`diff` 两棵树的 `FAILED` 名单：**完全一致**（`SAME_FAILURE_SET`）。

---

## 5. 仍未完成 / 新发现

1. **A4 净现比已改为只引用 A2（已完成，见第 3 节第四项）**：新 A4 落盘不再出现「1.8 倍」，缺口一律写「无法计算」；正向用例验证 A2 有值时 A4 可原样引用并补证据。
2. **A4/A5 质量门禁未通过**：A4 `quality.passed=false`、A5 `consistency.passed=false`。历史真实 A4 同样未过，属既有问题；本轮未修改 A4/A5 的数值校验算法（方案只要求消费同一口径）。
3. **CR3/CR5 仍为「未满足」**：按决定 A 不发布市值代理；任务书若将其列为强制项，当前状态应记为未通过。
4. **历史黄金样本 `run-20260926022235-107` 本地缺失**：C1 的 6 个用例仍按 skipped 处理。
5. **A1→A2 的 `sources` 字段不同构**：`scripts/run_a2_offline_review.py` 直接读原始 `dataset.json` 会失败，本轮用剔除 `sources` 的副本（`output/a2_acceptance_p01_p20/inputs/a1_frozen_dataset.json`）绕过，未改脚本。

---

## 6. 变更文件清单

**源码（11）**
- `agents_core/financial_semantics.py`（+ 统一精度判定、跨单位冲突判定、金额族清单）
- `agents_core/data-analysis/data_interpreter/engine.py`（跨单位屏蔽、`_has_conflicting_measurement` 共用判定）
- `agents_core/data-analysis/data_interpreter/models.py`
- `agents_core/data-analysis/data_interpreter/analysis_guard.py`
- `agents_core/chapter-writer/chapter_writer/net_cash_ratio.py`（净现比引用策略 + 落盘前守卫）
- `agents_core/chapter-writer/chapter_writer/agent.py`（注入策略、落盘前执行守卫）
- `agents_core/data-fetcher/data_fetcher/fusion.py`（冲突分组、`_computed_match`）
- `agents_core/chart-generator/chart_generator/metric_guard.py`
- `agents_core/chart-generator/chart_generator/data_formulation.py`
- `agents_core/chart-generator/chart_generator/evidence_policy.py`
- `agents_core/chart-generator/chart_generator/compiler.py`
- `agents_core/chart-generator/chart_generator/render.py`

**测试（10）**
- `backend/tests/test_ab1_metric_unit_provenance.py`（+3）
- `backend/tests/test_financial_conflict_precision.py`（+4 精度 +4 跨单位）
- `backend/tests/test_official_restatement_reconciliation.py`（+3）
- `backend/tests/l1/test_c1_formula_baselines.py`（CR 三段 + ROE 兼容 + 未满足标记）
- `agents_core/data-analysis/tests/test_measurement_semantics_audit.py`（+7 +2 跨单位）
- `agents_core/chart-generator/tests/test_shared_axis_unit_v8_final.py`（+3）
- `agents_core/chart-generator/tests/test_a3_reviewed_delivery.py`（+3）
- `agents_core/chart-generator/tests/test_chain_facts.py`（夹具补 `unit/scope/currency`）
- `agents_core/chart-generator/tests/test_local_cleanup_p13_p15_p18.py`（新增 4）

**数据/基准**
- `eval/cases/baselines.json`（`dupont_roe → roe_pct`、`status`/`status_reason`）

**验收产物**
- `output/a2_acceptance_p01_p20/`（冻结 A1 副本 + 新版 A2）
- `output/a3_acceptance_p01_p20_stage/runs/charts-20261113000701-ac36da66/`
- `output/a4_acceptance_p01_p20/runs/chapters-20261113000820-66de13a8/`（改造前对照）
- `output/a4_acceptance_p01_p20/runs/chapters-20261113001656-5f8143d3/`（净现比收口后）
- `output/a5_acceptance_p01_p20/runs/report-20261113001010-926208d3/`（改造前对照）
- `output/a5_acceptance_p01_p20/runs/report-20261113001800-050c94d5/`（净现比收口后）
