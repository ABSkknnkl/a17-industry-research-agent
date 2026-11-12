# 智能体3 · 真实运行环境上游数据侧专项适配报告

> 2026-11-12 · 约束：**不修改审核门及其他任何既有代码／既有产物**，仅从上游数据侧调整。
> 数据源：A1 `dataset.json`、A2 `interpretation_report.json`（冻结黄金样本 `a3-live-20261110235216656541`）+ 本轮真实重新取数。

---

## 0. 结论先行

**已做到**：把审核门三层拦截条件与所需字段逐条定位；真实重新取数 9 类、补回 58 条记录，成对同步 A1/A2 并纳入项目；真实 A3 复跑验证，渗透率序列由「仅 2025 年」扩展为 2021-02—2025-12 共 52 点；产出与现有示例一致的 8 张完整图表页。

**必须如实说明的边界**：你要的「真实运行中报告稳定包含示例页那 8 种指定图型、不再被审核门拦截」——**在不改审核门及既有代码的约束下达不到**。根因不是数据不够，而是两层结构性问题：

1. 示例页 8 张图是交接包独立工程 `nev_agent3_charts/` 手写 ECharts option 生成的，**从未经过审核门**；真实链路 45 次运行只发布过 `industry_chain / line / bar / combo / area / comparison_bar`，从未产出 `scatter / radar / donut / diverging_bar / horizontal_bar`。图型由既有代码 `selection.py::PROFILES` + LLM 选型 + 发布门禁决定，补上游数据不能改变选型。
2. A5 必答门禁读的是 **A2 已落盘的判定结论**（40 格 `passed=false`），不是实时数据。其中 30 格因金额 `unit_unknown`、10 格因年度全口径序列缺失。补 A1 数值不会自动翻转判定；补单位标签等于伪造来源，改判定逻辑又违反约束。

因此真实链路交付状态仍是「受限草稿 · 未通过正式质量门禁」，本报告不承诺正式交付。

---

## 1. 审核门拦截条件与所需数据字段

### 1.1 A3 图表发布门禁

| 判定入口 | 拦截条件 | 所需数据字段 | 不满足后果 |
|---|---|---|---|
| `evidence_policy.py:82-112` `source_conflicts` | A1 `dataset` 与 A2 `evidence_index` 逐字段比对 | `record_id / domain / entity_name↔entity / metric / value / unit / period_end↔period / period_start / period_type / scope / currency` | `source_record_missing` 或 `source_conflict`，数据点被排除 |
| `agent.py:2317` `_verify_numeric_candidate` | 期间长度一致、口径可比、可逐点追溯、分组符合 A2 `reviewed` 契约 | 每点 `record_id` + 同口径 `period_type` + `scope` + `chain_analysis.groups` | `measurement_contract` 抑制（近 8 次运行 192 条，主因） |
| `publication.py:20-96` `option_contract_issue` | 点级契约与 option 逐项相等 | `categories / series_order / series_units / points / observation_range` | 图表被剔除／`chart_contract` 错误 |
| `linter.py:164-210` | boxplot ≥15 点；treemap ≥8 项且仅广延量；负值不得截断零轴 | 样本量、指标可加总性 | `boxplot_insufficient_sample` 等 error |
| `agent.py:571-584` | `max_charts` / `requested_types` | `ChartPreferences` | `preference_limit` 抑制（该 run 8 条） |

### 1.2 A5 融合门禁

| 判定入口 | 拦截条件 | 所需数据字段 | 不满足后果 |
|---|---|---|---|
| `agent.py:773-776` | `requested_financial_coverage` 任一 `passed=false` | 每格 `passed / evidence_record_ids / requirement_id` | `required_financial_cell` error → 本样本 **40 条** |
| `agent.py:750-758`、`180-235` `_chart_contract_issues` | 每个 `data_contract.points[].record_id` 必须存在于 `evidence_index`，且 entity/metric_family/period/scope/currency 相符 | 点级证据契约 | 整张图从报告剔除 |
| `agent.py:746-749` | 共同期间与测量范围可比 | 期间、单位 | `chart_comparability` error |
| `agent.py:760-770` `link_requirement_outputs` | hard 需求必须被图表／正文／表格实际引用 | `coverage.evidence_record_ids` 与 `cited_evidence_record_ids` | `answer_withheld` → `final_blocking` |

### 1.3 状态机推进闸门

`state_machine.py:78-161` `assess_stage_progression`：`status=failed`、`hard_blocked`、`delivery_blocked`、`quality.passed=false`、`chain_delivery` 未完成 → 阻断下游。`report_fusion` 阶段额外检查 `agent_status=partial`。

---

## 2. 本轮真实重新取数并纳入项目的内容

只新增文件，**未改动任何既有代码、审核门、检查项、图表实现、既有 A1/A2 产物**。

| 产物 | 路径（相对 `a17-industry-research-agent/`） | 内容 |
|---|---|---|
| 取数脚本 | `scripts/a3_upstream_gap_refetch.py` | 9 类缺口定向查询，串行避开 401 竞态 |
| 原始台账 | `output/a3_upstream_adaptation/refetch_raw.json` | 每条查询的原始响应、行数、单位字段可得性 |
| 规范化记录 | `output/a3_upstream_adaptation/upstream_patch.json` | 165 条候选 |
| 取数结论 | `output/a3_upstream_adaptation/refetch_report.json` | 逐类 `fetched / empty / error` |
| 适配脚本 | `scripts/a3_upstream_adapt.py` | A1/A2 成对同步 |
| 补齐版产物 | `output/a3_upstream_adaptation/patched_run/artifacts/{dataset.json, interpretation_report.json}` | 58 条新增记录，A2 `evidence_index` 550→608 |
| 单位声明证据 | `output/a3_upstream_adaptation/unit_declarations.json` | 五家公司年报单位声明原文与 URL |
| 适配台账 | `output/a3_upstream_adaptation/adaptation_manifest.json` | 记录数、域分布、口径政策 |

| 补齐字段 | 新增记录 | 真实来源 | 口径处理 |
|---|---|---|---|
| `rd_ratio` 研发费用率 | 15（5 家 × 3 年） | 问财 `hithink-finance-query`「研发费用／营业收入」 | 原值小数 ×100，`unit_provenance=derived_ratio_x100`，保留原字段名 |
| 渗透率月度观测 | 42（2021-02—2025-12） | 问财 `hithink-industry-query` | 显式 `单位:%`、`period_type=month`；**不冒充年度** |
| 分产品收入构成 | 1（比亚迪 2024「汽车及相关产品」） | 问财 finance | metric=`segment_revenue_product`，**不冒充分部口径** |

**成对同步是硬要求**：A3 `source_conflicts` 逐字段比对 A1/A2，只补一侧会触发 `source_record_missing` 反把数据全排除。补齐后实测 `source_conflicts = 0`、`evidence_index = 608`。

---

## 3. 真实运行验证（同一命令、同一四问、同一 `--max-charts 9 --chain`）

| 项 | 基线（原 A1/A2） | 补齐版 A1/A2 |
|---|---|---|
| `run_id` | `charts-20261112110724-7d434a3d` | `charts-20261112111814-dd70766b` |
| 发布图数 | 6 | 6 |
| 图型 | industry_chain 1 / combo 2 / line 3 | 同左 |
| 渗透率图观测期 | 2025-03-31 — 2025-12-31 | **2021-02-28 — 2025-12-31** |
| 渗透率点数 | 10 | **52** |
| `quality.passed` | true | true |
| `question_coverage` 中 `evidence_gap` | 5 | 5 |
| `source_conflicts` | — | 0 |

**解读**：补齐数据确实让渗透率图从单年变成多年序列（示例页 C02 同款改善），但**图数、图型、`evidence_gap` 数量完全不变**——这直接证明剩余拦截不是「数据缺失」型，而是既有代码的选型／判定型。

A5 必答门禁静态核对：40 格 `passed=false` 中，30 格 A1 已有数值（仅缺单位元数据）、10 格 A1 确无匹配（`新能源汽车 2021—2025 年全年 nev_sales / nev_penetration`）。补齐后 A2 落盘判定未变，仍会生成 40 条 `required_financial_cell` error。

---

## 4. 确实无法取到的字段、受影响图表、原因

| 缺失字段 | 受影响图表／问题 | 原因（含实测证据） |
|---|---|---|
| 金额类 `unit` / `unit_provenance`（来源单位元数据） | A5 必答门禁 30 格财务硬需求；示例 C04（营收×归母净利）、C07（五维雷达）、C08（归母净利构成） | 问财 `hithink-finance-query` / `financial_data` / `hithink-basicinfo-query` 均**不返回单位列**（4 组查询实测 `unit-ish=[]`）。年报声明各家口径不一：比亚迪／赛力斯「人民币千元」、长安汽车「人民币元」、宁德时代／亿纬锂能未取到声明；而 A1 数值已统一换算成元且未留换算出处。补标签＝伪造证据，故保持 `unknown` |
| 2021—2025 **年度全口径**渗透率序列 | 示例 C02；真实链路 `q1.annual_penetration`（`evidence_gap`） | 数据源只有「国内零售渗透率:新能源汽车:当月值」月度零售口径。本轮已补回 2021-02 起 42 条月度观测，但无年度全口径值；月度不得冒充年度 |
| 2021—2025 年度 `nev_sales` 序列 | 10 格行业硬需求；Q2 口径对照 | A1 销量是 `ytd_month` 累计值、指标名为「新能源汽车:销量:累计值」，与年度口径／别名不匹配，非 annual |
| 汽车总量 vs 乘用车统计口径差异元数据 | Q2「不同统计口径会如何影响结论」 | 无对应结构化指标，属方法论说明，数据源范围外（`GAP-06` 实测只返回渗透率月度值） |
| 产业链上中下游供货关系边 | 示例 C05/C08 承载的 CH-03；真实 `q3.chain` | `hithink-business-query` 只返回概念／行情／纳入概念原因，无供货关系；A1 诊断报告已确认直接查询 `rows=0` |
| 整车分部独立财报口径 `scope=segment:整车` | 真实 `q5.segment`（`evidence_gap`）；Q3「能否对整车业务单独比较」 | 只取到分产品收入构成（比亚迪「汽车及相关产品」2024），无独立分部报表；只有集团合并口径 |
| 其余四行业配对的 A1/A2 产物 | 白酒、半导体设备、光伏、低空经济各 4 问的指定图表 | 工作区 `output/a1_five_industry_probe/` 只有新能源汽车与白酒行业目录，A2 review 只有新能源汽车一份配对报告；**四行业无配对输入，无法验证或保证出图** |

---

## 5. 结构性边界与需要你决策的路径

| 优先级 | 做法 | 能否达成「不再被拦」 | 代价／风险 |
|---|---|---|---|
| **P0（本次采用）** | 保持全部约束：上游数据补齐 + 独立示例工程交付完整图表与报告，真实链路维持受限草稿并留缺口清单 | 否，但完全合规、可复现 | 接受「受限草稿」，报告不能宣称正式交付 |
| **P1** | 允许**重跑 A1/A2** 让覆盖判定基于补齐数据重算（仍不改门禁代码） | 部分：10 格年度口径仍缺，30 格因 `unit_unknown` 仍不通过 | 需先解决金额单位来源；直接把 `passed` 改 true 属伪造判定，不可做 |
| **P2** | 允许改既有代码：`selection.py::PROFILES` 增补图型预设，或开启 `question_planner=apply` 让 LLM 选卡并预留指定图配额 | 是（图型层面） | 违反本次「不修改审核门及其他相关既有代码」约束，需你明确授权 |
| **P2** | 允许补一份**可核验的金额单位来源台账**（逐公司、逐年度、带年报页码与换算式），再重跑 A1 判定 | 是（A5 30 格） | 需逐公司核验年报口径，工作量大；本次仅取到 3 家声明 |

在你未授权 P1/P2 前，本次交付停在 P0，**不宣称「不再被审核门拦截」已达成**。

---

## 6. 交付清单与运行方式

| 交付物 | 路径（相对 `nev_agent3_charts/`） | 说明 |
|---|---|---|
| 完整图表页 | `index_adapted.html` | 8 张图，与现有示例同清单、同图型；改用补齐版上游数据；单文件离线自包含 |
| 本报告 | `ADAPTATION_REPORT.md` | 门禁契约、补齐台账、验证对照、缺口清单 |
| 生成脚本 | `a3_realrun_delivery.py` | 运行时注入补齐版数据源，不改既有文件 |

```bash
# 重新取数（需问财凭据）
cd ../a17-industry-research-agent
env -u PYTHONPATH /Users/Zhuanz1/miniconda3/bin/python3 scripts/a3_upstream_gap_refetch.py
env -u PYTHONPATH /Users/Zhuanz1/miniconda3/bin/python3 scripts/a3_upstream_adapt.py
# 真实 A3 复跑验证
env -u PYTHONPATH /Users/Zhuanz1/miniconda3/bin/python3 scripts/run_a3_single_industry.py \
  --run-dir output/a3_upstream_adaptation/patched_run/artifacts --max-charts 9 --chain
# 重建图表页
cd ../nev_agent3_charts && /Users/Zhuanz1/miniconda3/bin/python3 a3_realrun_delivery.py
```

## 7. 已知限制

- 工作区无项目 `.venv`，验证统一使用 `/Users/Zhuanz1/miniconda3/bin/python3`（含 httpx/pydantic/fastapi/playwright/python-docx）。
- `index_adapted.html` 属独立示例工程产物，**不经过**五阶段链路审核门；不得当作真实链路发布物引用。
- C02 标题按补齐后的多年序列调整，其余 7 张标题、图型、数据绑定与示例一致。
- 补齐的 42 条渗透率观测为月度零售口径，`period_type` 混杂未消除，仅作年内／跨年位置展示，不得解读为年度趋势外推。
