# 图表能力落地 · AI 可执行改造文档（全链路版）

- 日期：2026-09-13
- 状态：可执行（基于真实代码勘察，所有改动点带 file:line 证据）
- 上游输入：《图表能力最终落地方案-20260913》（28 项清单）、`docs/plans/2026-09-12-chart-dual-panel-and-broker-style.md`（规格）、`图表专业度对比分析-20260912.md`（诊断）
- 本文档定位：把 28 项清单**钉在真实代码现状上**，补全上游方案缺失的**全链路依赖**与**双渲染路径**，给出 AI 可逐步执行的精确指令。
- 阅读顺序：先读第 1 节（全链路数据流，决定每项改动要不要"双改"），再按第 3 节顺序执行第 2 节的任务卡。

> ⚠️ 执行铁律：本文档每个任务卡都标注了 **【渲染面】**——`ECharts`（前端预览）/ `SVG`（交付报告）/ `双面`。凡标 `双面` 的视觉项，**只改 builders.py 不会出现在最终报告里**（见 §1.4），必须同步改 `app/reporting/svg.py`。这是上游方案的最大盲区。

---

## 0. 作用域原则（2026-09-13 修订：Agent3 优先，上下游仅低风险才动）

**总原则**：默认**只改 Agent3**（`backend/app/agents/chart_generator/**` + `backend/app/schemas/chart.py`）。涉及上下游时，**仅当低风险才纳入**；中/高风险的跨模块改动一律**降级为 Agent3 内等价实现**或**延后单独立项**。

**风险分级判据**：
- **低风险（可纳入）**：附加式（新增字段/常量/绘制分支，不改既有行为）、局部（单函数内）、向后兼容（schema 放宽 max_length / 新增可选字段）、有独立测试守护。
- **中风险（默认延后，除非必要）**：改既有渲染/数据契约行为、概率性改动（LLM 提示词）、跨多模块联动。
- **高风险（禁止本轮触碰）**：改取数逻辑、改红线门禁、改阶段间数据契约语义。

**跨模块触点白名单（本轮允许的低风险上下游）**：
| 触点 | 模块 | 为何低风险 | 关联项 |
|---|---|---|---|
| `app/reporting/svg.py` | 下游渲染 | 附加绘制（标签/脚注/主题/标注），不改 option 契约；有 §6.4 parity 测试守护 | 所有【双面】项 |
| `app/schemas/chart.py` | Agent3 主导的共享契约 | 仅放宽 `series_meta` max_length、新增**可选** `panels`，向后兼容 | P2-2/P2-4 |
| `app/reporting/html.py` + `templates/report.html.j2` | 下游 Agent5 | 附加「图表目录」章节 + 编号选项，不改既有图表渲染 | P0-5/P1-2 |
| `app/agents/report_fusion/evidence.py`、`visual.py`、`quality.py` | 下游 Agent5 | display_label 改取 publishers、密度档/阈值改引用常量，局部替换 | P0-6/P0-4 |
| `app/agents/data_fetcher/fusion.py`（unit 归一） | 上游 Agent1 | 仅在构建 ChartDataset 时把占位符 unit→None，不动 EvidenceItem、不动取数 | P0-2 根因（可选） |

**延后清单（中/高风险，本轮不做）**：
| 项 | 触点 | 风险 | 处置 |
|---|---|---|---|
| P1-1 标题**生成**侧 | 上游 Agent2 `data_interpreter/prompt_adapter.py` | 中（概率性 LLM 行为 + 跨阶段） | **延后**；本轮 Agent3 只做 `title_not_conclusive` **校验+降级**（in-scope） |
| P3-2 断点续跑 | 可能触 `workflow/` | 中（跨阶段编排） | **延后**；本轮只做 Agent3 内失败项落盘 |

### 0.1 全 28 项作用域分类表（执行前先看这张）

| 项 | Agent3 内改动 | 跨模块触点 | 风险 | 本轮处置 |
|---|---|---|---|---|
| P0-1 combo 量纲分支 | router.py + builders.py | — | 低 | ✅ Agent3-only |
| P0-2 单位占位符不进轴名 | builders._axis_name + datasets.py:189 + quality.py | (可选)Agent1 fusion unit 归一 | 低 / fusion 低 | ✅ Agent3-only 即达验收；fusion 根因修复为**低风险上游，建议同批**（修后 P0-3 匹配率↑） |
| P0-3 去重键归一+恢复抑制 | router.build_dedupe_key + service.py:784-786 | — | 低 | ✅ Agent3-only |
| P0-4 数量阈值单一来源 | 新建 constants.py + planner.py + service.py | (可选)Agent5 visual.py/quality.py 对齐 | 低 / 低 | ✅ Agent3 先收敛自身 2 处；Agent5 对齐为**低风险下游，可选同批** |
| P0-5 图表目录 | — | reporting/html.py + report.html.j2 | 低(附加) | ✅ 下游-only，低风险附加，纳入 |
| P0-6 资料来源具名 | — | report_fusion/evidence.py + 模板 | 低-中 | ✅ 下游-only，纳入（display_label 取 publishers） |
| P1-1 标题结论化 | quality.py 校验+降级 | (延后)Agent2 prompt | 低 / 中 | ⚠️ **Agent3 只做校验降级**；生成侧（Agent2 提示词）**延后** |
| P1-2 编号格式全文连续 | — | reporting/html.py | 低(附加选项) | ✅ 下游-only，纳入 |
| P1-3 数值标签开关 | builders.py | reporting/svg.py | 低(附加绘制) | ✅ Agent3+SVG 双面 |
| P1-4 截断轴提示 | builders.py | svg.py | 低 | ✅ 双面 |
| P1-5 三种标注技术 | builders.py | svg.py | 低-中(SVG 绘制较复杂) | ✅ 双面（SVG 侧工作量较大，可拆子任务） |
| P1-6 对比度 ≥4.5:1 | builders/quality 主题层 | — | 低 | ✅ Agent3-only |
| P1-7 输出前自查清单 | service/quality 出口 | — | 低 | ✅ Agent3-only |
| P1-8 质量门三问 | quality.py | — | 低 | ✅ Agent3-only |
| P2-1 broker_thin 主题 | builders.THEMES | svg.py | 低-中 | ✅ 双面 |
| P2-2 dual_panel 双图 | schemas/chart.py(可选 panels)+builders+router | svg.py | 中(schema+SVG 布局) | ✅ 纳入但谨慎：schema 向后兼容、SVG 布局单独验收 |
| P2-3 红涨绿跌 | builders option.color | —（svg.py:98-100 自动透传） | 低 | ✅ **Agent3-only（唯一单面生效）** |
| P2-4 series_meta 2→4 | schemas/chart.py + router 校验 | — | 低(放宽) | ✅ Agent3 契约 |
| P2-5 Okabe-Ito 色板 | builders.THEMES | svg.py | 低 | ✅ 双面 |
| P2-6 高亮法 | builders.py | svg.py | 低 | ✅ 双面 |
| P2-7 灰度测试 | 抽查脚本/文档 | — | 低 | ✅ 文档+脚本 |
| P3-1 操作审计日志 | service.py 出口 | — | 低 | ✅ Agent3-only |
| P3-2 错误报告+断点续跑 | service.py 落盘 | (延后)workflow | 低 / 中 | ⚠️ **本轮只做 Agent3 内失败落盘**；跨阶段续跑**延后** |
| P3-3 运行前自检 | service/quality | — | 低 | ✅ Agent3-only |
| P3-4 能力边界表 | 文档 | — | 低 | ✅ 文档 |
| P3-5 数据体检阈值 | quality.py | — | 低 | ✅ Agent3-only |
| P3-6 禁用清单 | 文档 | — | 低 | ✅ 文档 |
| P3-7 选型决策树对照 | 核对 router.py | — | 低 | ✅ Agent3-only |

**一句话总结**：28 项里 **23 项纯 Agent3 或仅含低风险 svg.py/schema 双面**；**4 项必须落在下游 Agent5 报告渲染**（P0-5/P0-6/P1-2，附加式低风险）；**2 项的上游/跨阶段部分延后**（P1-1 生成侧、P3-2 续跑），本轮只做其 Agent3 内等价部分。

---

## 1. 全链路数据流与依赖（证据来自整条链路，非仅 Agent3）


### 1.1 Agent3 的输入来源（三路汇入）

`chart_generator/service.py:503-546` 的 `run()` 入口：

| 输入 | 来源阶段 | 取值位置 | 证据 |
|---|---|---|---|
| `chart_datasets`（结构化数值数据集） | **Agent1 data_fetch** | `source["chart_datasets"]` | `service.py:533-536`；产于 `data_fetcher/fusion.py:84-141`，写入 `data_fetcher/service.py:561` |
| `chart_candidates`（LLM 图表提议） | **Agent2 data_interpret** | `interpretation.data["chart_candidates"]` | `service.py:525-528`；产于 `AnalysisDraft.chart_candidates`（`schemas/analysis.py:304`），经 `data_interpreter/service.py:607-613` 落 StageResult.data 顶层键 |
| `calculated_metrics`（确定性计算指标） | **Agent2** | `_calculated_metric_datasets` | `service.py:547-551`，生成 `DS-CALC-<digest>` |
| `chart_generate_options`（用户选项） | 用户请求 | `context.input_data` | `service.py:537-539`；`metric_ids` 决定 `_select_datasets` 过滤（`service.py:158-169`） |
| `evidence_items`（证据池，产业链派生用） | **Agent1** | `source["evidence_items"]` | `service.py:148-155`、`617-624` |

**Agent3 不读 `selected_chart_ids`**（该键只被 Agent4 `chapter_writer/service.py:158` 与 Agent5 `report_fusion/service.py:152` 读取）。

`source = _source_payload(context)`（`service.py:137-145`）= `{**context.input_data, **fetch_result.data}`——**Agent1 的 data 覆盖 input_data**；无 fetch_result 时退化为纯 input_data。

### 1.2 上游合流点与断点（P0-3 去重的真正根因在这里）

candidate（Agent2）与 dataset（Agent1）**唯一的桥是 `evidence_ids` 子集包含**：`datasets.py:45-47` `candidate_evidence_set.issubset(set(ds.evidence_ids))`，**不比对 metric_name / unit / title / kind**。

**断点（全链路证据）**：
- `ChartCandidate`（`schemas/analysis.py:162-195`）**没有 dataset_id / metric_name / unit 字段**，LLM 只给 evidence_ids + 自由文本 insight_goal。
- `ChartDataset.evidence_ids` 被截断到前 100 条（`fusion.py:135`）且按 `(metric_name, unit, currency, scope_key)` 切分（`fusion.py:88-98`）。
- **致命交互**：同一指标若因 unit 占位符差异（`"未提供"` vs 真实单位）被 Agent1 拆成**两个 dataset**（`fusion.py:97` 分组键含 unit），则 candidate 的 evidence_ids 跨这两个组 → subset 判定失败 → 落入 `no_matching_dataset` / `incomplete_dataset_union` **静默抑制**（`datasets.py:58-82`，`review_required=False`）。
- 结论：**P0-2（unit 占位符）不修，P0-3（去重）的匹配断点就修不干净**——这是上游方案没点破的依赖。

### 1.3 unit 占位符的上游根源（P0-2 根因在 Agent1，但验收可在 Agent3 内达成）

- 占位符**生于 Agent1**：`data_fetcher/normalizer.py:1218` `normalized = (unit or "未提供").strip()` 位于数值路径；`normalizer.py:743` `unit=numeric[1] if numeric else "文本"`。
- `fusion.py` 对 `currency` 有归一（`"不适用"→None`，`fusion.py:117`），**但对 unit 无任何归一/剔除** → `"未提供"`/`"文本"` 直接流进 `ChartDataset.unit`。
- Agent3 侧 `datasets.py:189` `unit=dataset.unit or "未提供"` 只是**二次兜底**，不是根源。
- 结论（按 §0 作用域修订）：**根因在 Agent1 fusion.py，但 P0-2 的验收（轴名不含"未提供"、26/87→0）在 Agent3 内即可达成**——`builders.py::_axis_name` 过滤占位符 + quality.py 兜底规则。Agent1 fusion 的 unit 归一是**低风险上游根因修复（可选）**：不做也达验收；做了则从源头消除占位符，并**附带缓解 §1.2 的 dedup 断点**（同指标不再因 unit 占位差异被拆成两个 dataset）。本轮按"Agent3 优先、上下游低风险可选"处理：Agent3 两层必做，fusion 归一列为同批可选。

### 1.4 ⚠️ 双渲染路径（本文档最重要的全链路发现）

Agent3 产出 `ChartSpec.option`（完整 ECharts option JSON，`schemas/chart.py:254-299`），但**下游有两条互不相同的渲染路径**：

| 渲染面 | 消费方 | 机制 | 证据 |
|---|---|---|---|
| **ECharts** | 前端预览 | `ChartGallery.vue:46-59` 浅覆盖后**直接 `setOption(option)` 透传** | `frontend/src/components/ChartGallery.vue` |
| **SVG** | 交付报告（HTML/PDF/Markdown） | `assembler.py:_render_chart → render_chart_svg(spec)`，**svg.py 按 chart_type 自己重绘 SVG**，只读 option 的 `xAxis.data`/`series`/`color` | `report_fusion/assembler.py:29-42`；`app/reporting/svg.py:1-3,66-100` |

**含义**：
- `EmbeddedChart` **无 option 字段**（`schemas/report.py:42-64`），ECharts option **不进报告视图**；报告里是 svg.py 重绘的 SVG。
- 因此：**网格线/线宽/字体/数据标签/markLine/markPoint/双 panel 布局**这些视觉特性，若只加进 builders.py 的 option，**前端预览能看到、交付报告看不到**。
- 唯一能透传到 SVG 的是 `option.color`（`svg.py:98-100` 读 color 数组给 series 上色）→ **红涨绿跌语义配色（P2-3）只要写进 option.color 就能双面生效**；其余视觉项必须**双改 svg.py**。
- 执行要求：每个 P1/P2 视觉任务卡都标注【渲染面】，标 `双面` 的必须同时改 `builders.py` 和 `app/reporting/svg.py`，并在 SVG 侧补对应绘制逻辑。

### 1.5 Agent3 的输出去向

- 产物：`ChartGenerationResult`（`schemas/chart.py:324-333`）= `charts` / `chart_specs` / `suppressed_candidates` / `quality` / `decision_package`，落 `StageResult.data`（`service.py:1154-1159,1207`）。
- **给 Agent4 的是轻量 `ChartReference`**（`schemas/chart.py:212-251`，**无 option**）：`artifact_id` / `recommended_chapter_id` / `candidate_status`；`status="ready"` 必须有 `artifact_id`（`:247-251`）。
- Agent4 只读 `chart_result.data["charts"]`（`chapter_writer/service.py:51-54`，**从不读 chart_specs**），引用落在 `SectionDraft.chart_ids`（`schemas/chapter.py:138`）/`ChapterDraft.chart_ids`（`:160`）；**段落级无图表引用**。
- Agent4 校验非阻断：引用未就绪图 → `graph.py:216-220` 记 issue → revise 至上限仍 accept（`graph.py:357-364`）。
- `alternative_chapter_ids` **全链路未被消费**（`chart_generator/service.py:469` 恒置 `[]`）——死字段，本次不动但记录在案。
- Agent5：`report_fusion/service.py:124` 校验，`assembler.py:117-151` 按 `section.chart_ids` 首现定 placement，只嵌 `ready ∩ specs ∩ 用户选中`。

### 1.6 阈值四处不对齐（P0-4 的真实范围比方案大）

| 位置 | 当前值 | 证据 |
|---|---|---|
| `chart_generator/planner.py:18` | `RECOMMENDED_CHARTS=(5,8)` | 定义① |
| `chart_generator/service.py:84` | `RECOMMENDED_CHARTS_PER_REPORT=(5,8)` | 定义②（重复） |
| 预算常量 PER_CHAPTER/PER_FAMILY/P1/CHAIN | `planner.py:19-22` 与 `service.py:85-88` **各一份** | 重复 |
| `report_fusion/visual.py:108` | 密度档 `low≤4 / medium≤10 / high>10` | **与 (5,8) 不对齐** |
| `report_fusion/quality.py:95-98` | `len>8` → advisory「超过推荐上限8张（技术上限30张）」 | 硬编码 8 |

结论：P0-4「单一来源」必须收敛**全部 5 处**（不止方案说的 planner.py:18 + quality.py:97），否则 visual.py 密度档与 report_fusion 硬编码 8 仍会漂移。

---

## 2. 任务卡（28 项，按 P0→P3；每卡含 现状证据/目标/精确改动/渲染面/验收/上下游影响）

> 改动文件根：`backend/app/`。每张卡的「精确改动」给出当前代码与目标代码骨架；AI 执行时以真实文件为准，行号若漂移用 grep 锚定函数名。

### P0 · 交付要件 + 规则修正（M1，6 项）

---

**P0-1 combo 量纲改分支**
- 现状证据：`chart_generator/router.py:202` `units={(item.currency,item.unit) for item in dataset.series_meta}`；`:205` 要求 `len(series_meta)!=2` 拒绝；`:207` `or len(units)!=2` 拒绝（必须恰好两种量纲）。同量纲（len(units)==1）→ route 拒绝 `combo_requirements_not_met` → `service.py:655` `downgrade_chart` → `fallbacks.py:21` `combo+time_series→"line"`。**同量纲 combo 被降级为 line 已证实**。
- 目标：`len(units)==2`→双轴柱线（标注两轴单位）；`len(units)==1`→**单轴柱线**（共用左轴，柱=绝对量、线=第二序列）；`len(units)==0`→拒绝出图（单位不可知）。保留 `business_linked` + 时间轴一致校验（双轴陷阱防线，不放宽）。
- 精确改动：`router.py:205-207` 把 `len(units)!=2` 硬拒改为分支；单轴分支在 `builders.py` combo builder（`builders.py:131-176`）增加 `len(units)==1` 路径（单 yAxis，两 series 同轴，柱+线）。
- 渲染面：**双面**（builders.py 出 option + svg.py `_render_combo`/`_render_line` 支持单轴柱线重绘）。
- 验收：营收+归母净利润（同为亿元）→ combo、单 yAxis、不降级；`tests/agents/chart_generator` 新增用例断言 `chart_type=="combo"` 且 `len(option["yAxis"])==1`。
- 上下游影响：依赖 P2-4（series_meta 放开到 4）才能支持 >2 序列；本卡先做 2 序列单轴。

---

**P0-2 单位占位符不进轴名**【作用域：Agent3-only 达验收；Agent1 fusion 根因修复=低风险可选】
- 现状证据：占位符生于 `data_fetcher/normalizer.py:1218`（`unit or "未提供"`）、`:743`（`"文本"`）；`fusion.py` 对 unit **无归一**（对比 currency 有 `fusion.py:117`）；Agent3 `datasets.py:189` `unit=dataset.unit or "未提供"` 二次兜底；`builders.py:14-15` `_axis_name` 直接拼 unit。26/87 轴名含"未提供"。
- 目标：轴名不再出现"未提供"；占位符规范化为 `[需核实:货币单位]` 只进图注（footnotes）；26/87→0。
- 精确改动（**Agent3 两层即达验收**）：
  1. **Agent3 轴名（必做）**：`builders.py::_axis_name`（:14-15）仅当 `unit` 为真实值（非 None/不在 `{"未提供","文本","不适用",""}`）才拼接；否则轴名不含单位。
  2. **Agent3 图注 + 质量门（必做）**：`datasets.py:189` 占位符改 `[需核实:货币单位]` 并下沉 footnotes；`chart_generator/quality.py` 新增硬规则 `unit_missing_or_placeholder`（当前**无此规则**，grep 全仓 0 命中）兜底阻断。
  3. **（可选·低风险上游根因）** `data_fetcher/fusion.py` 构建 ChartDataset 时 unit 归一——`unit if unit not in {"未提供","文本","不适用",""} else None`（与 currency 归一对称，`fusion.py:117` 附近）。**不做也能达成本卡验收**（轴名已在 Agent3 过滤）；做了则从源头消除占位符，且**缓解 §1.2 dedup 断点**（同指标不再因 unit 占位差异被拆成两个 dataset → P0-3 匹配率↑）。按 §0 属低风险上游，**建议同批但非强制**。
- 渲染面：ECharts（轴名/图注在 option 内）+ SVG（svg.py 画轴名时同步过滤占位符）。**双面**。
- 验收：`yAxis.name` 不含"未提供"；quality 报告出现 `unit_missing_or_placeholder` 当且仅当 unit 缺失；26/87 归零。（验收只依赖 Agent3 两层，可选层 3 不纳入本卡判据。）
- 上下游影响：层 3（可选）若做，顺序上 P0-2 应在 P0-3 之前或同批以收 dedup 之效；若不做，P0-3 仍能归一去重，但跨 dataset 拆分的假性不重复需靠 P0-3 的 data_fingerprint 兜底。

---

**P0-3 去重键归一化 + 恢复抑制（两步不可颠倒）**
- 现状证据：`router.py:283-292` `build_dedupe_key` = `f"{family}:{purpose}:{normalized_goal}:{data_fingerprint}"`，`normalized_goal`（:291）仅 `" ".join(split()).lower()`——**无语义归一**，"展示趋势"vs"展示变化"产生不同 key。`service.py:784-786` 去重抑制**已禁用**（`if is_duplicate: pass`，注释"图表仍然生成，不抑制"）。重复图仅经 `_build_risk_notices`（`service.py:409-422` CHART-DUPLICATE INFO/ADVISORY）标记。单报告最多 6 张同类图。
- 目标：同报告同类图 ≤1 张；6 张同类归 1。
- 精确改动（**严格两步，顺序不可颠倒**）：
  1. **先归一 key**：`router.py:291` `normalized_goal` 改为语义槽位映射——`{"展示趋势","展示变化","观察…变化","…走势"}→"trend"`，槽位枚举 `trend/composition/comparison/ranking/positioning`（与 `ChartCandidate.analysis_purpose` 的 Literal 对齐，`schemas/analysis.py:172-181`）。建议新增 `_normalize_insight_goal(text)->slot` 函数。
  2. **再恢复抑制**：key 可靠后，`service.py:784-786` 把 `pass` 改回 `suppressed.append(...); continue`——完全重复（key 相同）→抑制；同 family 相似（family 同、key 不同）→告警不抑制。
- 渲染面：无关（逻辑层）。
- 验收：构造 6 张"趋势/变化"同类候选 → 输出 ≤1 张 spec + 5 条 suppressed；`tests/agents/chart_generator` 断言 `len(specs)==1`。
- 上下游影响：依赖 P0-2（unit 归一减少 dataset 拆分→减少假性不重复）。**只改 key 不恢复抑制→重复照旧；只恢复抑制不改 key→误杀**，故两步必须同批且按序。

---

**P0-4 数量阈值单一来源**【作用域：Agent3 收敛自身 2 处=必做；Agent5 对齐 2 处=低风险可选】
- 现状证据：见 §1.6——`planner.py:18` + `service.py:84` 两份 (5,8)；预算常量 `planner.py:19-22` 与 `service.py:85-88` 各一份；`visual.py:108` 密度档 `≤4/≤10/>10` 不对齐；`report_fusion/quality.py:95-98` 硬编码 8。
- 目标：Agent3 内仅一处 `RECOMMENDED_CHARTS`；（可选）visual.py 密度档对齐、report_fusion 无硬编码 8。档次：推荐 5–8；<5 告警"图表偏少"；>8 `chart_count_over_recommended`；密度 ≤4 low / 5–8 medium / 9–10 high- / >10 high；技术硬上限 30（候选）/10（单章）不变。
- 精确改动：
  1. **（必做·Agent3）** 新建 `chart_generator/constants.py`：`RECOMMENDED_CHARTS=(5,8)`、`HARD_LIMIT_MAX_CANDIDATES=30`、`PER_CHAPTER_LIMIT=10`、预算常量（PER_CHAPTER/PER_FAMILY/P1/CHAIN）、密度档边界。
  2. **（必做·Agent3）** 删 `planner.py:18-22` 与 `service.py:84-88` 的重复定义，改 `from .constants import ...`。
  3. **（可选·低风险下游）** `report_fusion/visual.py:108` 密度档改引用 constants（对齐 5–8）。
  4. **（可选·低风险下游）** `report_fusion/quality.py:95-98` 硬编码 8 改引用 `RECOMMENDED_CHARTS[1]`。
- 渲染面：无关。
- 验收：**必做部分**——`grep -rn "RECOMMENDED_CHARTS\|= (5, 8)" backend/app/agents/chart_generator` 仅 constants.py 一处定义。**可选部分**——visual/quality 引用 constants、无裸 `> 8`（若本轮做）。
- 上下游影响：步骤 3/4 跨 Agent5，按 §0 属低风险（仅改引用），可同批也可延后；不做则 Agent3 内已单一来源，Agent5 侧密度档/阈值仍各自定义（功能不冲突，只是未全局收敛）。

---

**P0-5 图表目录（在 Agent5，非 Agent3）**
- 现状证据：编号已有——`app/reporting/html.py:39-46`（`^SEC-(\d{2})-\d{2}$` 取章号）、`:74-84`（章内递增 `图{章}-{序}`，placement 缺失→`附图-{N}`）。模板 `templates/report.html.j2:151-154` 仅章节 toc，**无「图表目录」章节**（全仓 grep「图表目录」仅命中方案文档）。
- 目标：报告正文前生成「图表目录」（编号+标题+页码）。
- 精确改动：`reporting/html.py` 新增 `build_chart_toc(placements)->list`（复用现有 display_number）；`report.html.j2` 在章节 toc 后插入「图表目录」块（编号+标题+页码占位；HTML 无真实页码则用章节锚点）。
- 渲染面：SVG/HTML（报告侧）。
- 验收：报告 HTML 含「图表目录」章节，列出全部图表编号+标题。
- 上下游影响：依赖 P1-2（编号格式）先定，否则目录编号与正文不一致。

---

**P0-6 资料来源具名标注（在 Agent5）**
- 现状证据：**混合**——段落级纯引用编号「来源{{citation_number}}」（`report.html.j2:184`）；图表级 `display_label=f"来源{number}：{source_name}"`（`report_fusion/evidence.py:105-110`，source_name 截断 30 字，**不含 publishers**）；publishers 只在来源索引表「发布主体」列（`presentation.py:165-190`→`j2:228-231`）。
- 目标：每图下方「资料来源：<具名来源>」（如「Wind，国信证券经济研究所整理」），非 [1][2]。来源名从 `evidence_catalog` 的 publishers/source_name 推导；无来源标 `[需核实:数据来源]`。
- 精确改动：`report_fusion/evidence.py:105-110` 的 display_label 改为优先取 `publishers`（证据 catalog 的发布主体）拼 source_name；`report.html.j2:186-188` figcaption 的「数据来源：」位改渲染具名串。
- 渲染面：SVG/HTML（报告侧）。
- 验收：每图 figcaption 为「资料来源：<具名>」；无来源时 `[需核实:数据来源]`。
- 上下游影响：依赖 Agent1 evidence_catalog 的 publishers 字段完整性（`source_records`/`evidence_items`）。

---

### P1 · 表达层（M2：P1-1~4；M3：P1-5~8）

**P1-1 标题结论化**【渲染面：ECharts+质量门】【作用域：Agent3 校验降级=必做；Agent2 生成侧=延后】
- 现状：title 仅 `schemas/chart.py:262 max_length=200` 约束，**无结论化校验**（quality.py 无 title 规则）。标题由 Agent2 LLM 生成（`ChartCandidate.title`）。
- 改动：
  1. **（必做·Agent3）** `chart_generator/quality.py` 新增 `title_not_conclusive` 规则——标题不含数值/比较词（同比/环比/增/降/领先/承压/攀升/回落等）→ 标记并降级。这是 Agent3 内的纯校验，不依赖上游。
  2. **（延后·中风险上游）** Agent2 提示词（`data_interpreter/prompt_adapter.py`）要求标题含结论（"X 同比高增"而非"X 趋势"）。按 §0 属概率性 LLM 改动 + 跨阶段，**本轮延后**；延后期间 Agent3 校验对不合格标题降级即可（标题仍由 Agent2 现状生成，校验负责兜底标记）。
- 验收：纯描述性标题→`title_not_conclusive` 并降级；结论式标题通过。（验收只依赖 Agent3 校验层。）
- 上下游：本轮仅 Agent3；生成侧改进留待后续与 Agent2 一并评审。

**P1-2 编号格式全文连续**【渲染面：SVG/HTML】
- 现状：`html.py:74-84` 已有 `图{章}-{序}`/`附图-N`，无全文连续。
- 改动：`html.py` 加选项 `continuous_numbering`（图1/图2…全文连续），保留章序号制作可选。
- 验收：支持 图1/图2…；与 P0-5 目录编号一致。

**P1-3 数值标签开关**【渲染面：**双面**】
- 现状：`builders.py` pie（:433 `{b}:{d}%`）/scatter（:203 ≤12）/heatmap（:269 ≤80）/treemap 有标签；**bar/line/combo 无数据标签**，无 markPoint。
- 改动：builders.py bar/line/combo 增加 `点数≤12 自动 label，>12 不加`；**svg.py 对应 `_render_bar`/`_render_line`/`_render_combo` 补数值标签绘制**（否则报告无标签）。
- 验收：≤12 点图有 label（option + SVG 双面）；>12 无。

**P1-4 截断轴提示**【渲染面：**双面**】
- 现状：无 scale=true 的 footnote 机制。
- 改动：builders.py 任何 `yAxis.scale=true` 的图，footnotes 加「纵轴未从 0 开始」；svg.py 渲染 footnote 文本。
- 验收：所有 scale=true 图 option.footnotes + SVG 均含提示。

**P1-5 三种标注技术**【渲染面：**双面**】
- 现状：builders.py 无 markLine/markPoint/视觉标注（grep 0 命中）。
- 改动：builders.py 支持 reference line（markLine 目标线）/ shaded region（markArea 时间段）/ call-out（markPoint 标注点）；**svg.py 补对应 SVG 绘制**（线/矩形/标注），否则报告丢失标注。
- 验收：三类标注在 option 与 SVG 双面可见。

**P1-6 对比度 ≥4.5:1**【渲染面：主题层】
- 改动：主题层（builders.py THEMES + 新增校验）计算配色对比度，低于 WCAG AA→告警。
- 验收：低对比配色触发告警。

**P1-7 输出前自查清单**【渲染面：质检】
- 改动：生成后交付前 5 问（3D？颜色>5？标签缺？类型匹配？布局优先级？）落 quality.py 或 service 出口。
- 验收：5 问全过才放行。

**P1-8 质量门三问**【渲染面：质检】
- 改动：质检入口加「5 秒看懂？轴骗人？重点被埋没？」三问（专家·图官）。
- 验收：三问纳入 quality 报告。

---

### P2 · 视觉增强（M3，7 项；多数【双面】）

**P2-1 broker_thin 券商风主题**【**双面**】
- 现状：`builders.py:8-11` THEMES 仅 `research_blue`/`colorblind_safe`，**无 broker_thin**（grep 0 命中）。
- 改动：builders.py THEMES 新增 `broker_thin`（无网格、细线 1.5px、无数据点、衬线字体）；**svg.py 主题层同步**（SVG 自绘网格/线宽/字体，必须改 svg.py 才能在报告生效）。与 P0-2 耦合：占位符进图注后 broker_thin 的图注样式一并定义。
- 验收：broker_thin 报告 SVG 无网格、线宽 1.5、无点。

**P2-2 dual_panel 双图并排**【**双面 + schema**】
- 现状：`schemas/chart.py` **无 panels 字段**（ChartDataset/ChartSpec 均 extra="forbid"，grep panels/dual_panel 0 命中）→ 当前 schema 不支持。
- 改动：① `schemas/chart.py` 增 `panels` 可选字段；② builders.py 双 grid option（左销量右增速，互不交叉）；③ router.py 路由 4 series×12月→dual_panel；④ **svg.py 新增双 panel SVG 布局重绘**；⑤ 缺 panels 元数据→回退 line 不抛错。
- 验收：4 series×12月→双 grid 双面；缺 panels 回退 line。

**P2-3 红涨绿跌语义配色**【**ECharts 透传即可**】
- 现状：无（grep 红涨/绿跌 0 命中）。
- 改动：builders.py 主题层涨跌序列 `UP=#C0392B/DOWN=#1E8449` 写进 `option.color`；**svg.py:98-100 已读 option.color → 自动透传，无需改 svg.py**（这是唯一单面生效的视觉项）。非涨跌序列不受影响。
- 验收：涨跌序列红涨绿跌，双面一致。

**P2-4 series_meta 放开 2→4**【schema】
- 现状：`schemas/chart.py:191 series_meta max_length=2`。
- 改动：max_length 2→4；**同步改 router.py combo 校验**（当前 `:205` 依赖 `len(series_meta)!=2`）→改为"按实际 series 分组数校验"。依赖 P0-1。
- 验收：4 序列 combo 不被拒；router 按分组数校验。

**P2-5 Okabe-Ito 色盲色板**【**双面**】
- 现状：`colorblind_safe` 已用 Okabe-Ito 系色（#0072B2/#E69F00/#009E73/#CC79A7/#56B4E9）但未命名。
- 改动：builders.py THEMES 新增第 4 套 `okabe_ito`（8 色科学标准）；svg.py 主题层同步色板。
- 验收：okabe_ito 主题双面生效。

**P2-6 "Highlight one thing" 高亮法**【**双面**】
- 改动：builders.py 重点序列上色、其余灰化（option.color + series 样式）；svg.py 同步灰化绘制。
- 验收：重点序列突出、其余灰，双面一致。

**P2-7 灰度测试**【抽查流程】
- 改动：抽查流程加黑白打印可辨验证（文档+人工抽查脚本）。
- 验收：灰度下仍可辨。

---

### P3 · 工程与规范（M4，7 项）

**P3-1 操作审计日志**：新增，记录 7 字段 chart_id/stage/decision/evidence_ids/quality_issues/degradation/retry_of。落 `chart_generator/service.py` 出口 + routing_telemetry 风格。
**P3-2 错误报告+断点续跑**【作用域：Agent3 内失败落盘=本轮；跨阶段续跑=延后】：**本轮只做** Agent3 内失败项落盘（`chart_generator/service.py` 记录失败 chart_id + 原因，供排查）；**"只重跑失败项"的跨阶段断点续跑触及 workflow 编排（中风险），按 §0 延后单独立项**。与三层降级链不冲突（降级=运行中换源，续跑=运行后补跑）。
**P3-3 运行前自检**：出图前校验数据完整性/依赖/对比度（与 P1-6/P3-5 联动）。
**P3-4 能力边界表**：文档明确"9 种类型能做 / 3D·地图·自动补值不做"。
**P3-5 数据体检阈值**：质检规则 字段≥2列 / 行数≥5 / 缺失≤20% / 列内类型一致。落 quality.py。
**P3-6 禁用清单（Never Use）**：选型文档每种数据结构标注"推荐"与"禁用"图表。
**P3-7 选型决策树对照**：用 5 大类决策树核对 router.py 路由覆盖度。

---

## 3. 执行顺序（Agent3 优先；依赖链顺序不可乱）

> 分批原则：**A 批 = 纯 Agent3 必做**；**B 批 = 低风险跨模块（svg.py/schema/Agent5 渲染），随 A 批同改**；**C 批 = 低风险上下游可选（做则更彻底，不做不影响 A 批验收）**；**D 批 = 延后（中/高风险，本轮不碰）**。

```
第一批（M1 基础·A，可并行，纯 Agent3）：
  P0-2 Agent3 两层（_axis_name 过滤占位符 + datasets:189 图注 + quality 兜底规则）
  P0-4 Agent3 收敛（新建 constants.py + planner/service 改引用）
  P2-4 series_meta 2→4（schema 放宽）+ router 校验改"按分组数"   ← P0-1 前置
       ↓
第二批（M1 核心·A，依赖第一批）：
  P0-1 combo 量纲分支（router:205-207 + builders combo；依赖 P2-4）
  P0-3 去重键归一→恢复抑制（router:291 + service:784-786；两步按序）
       ↓
第三批（M1 视觉基础·B，双面项，依赖第一/二批稳定）：
  P2-3 红涨绿跌（仅 builders option.color，svg 自动透传——单面，先做）
  P1-3 数值标签 / P1-4 截断轴提示（builders + svg 双面）
       ↓
第四批（M2 表达层·A+B）：
  P1-1 Agent3 校验降级（quality.py；生成侧延后见 D 批）
  P1-5 三种标注（builders + svg，SVG 工作量大可拆子任务）
  P1-6/7/8 质检三件套（纯 Agent3）
       ↓
第五批（M3 视觉增强·B，双面）：
  P2-1 broker_thin → P2-2 dual_panel（schema panels + builders + router + svg）→ P2-5 Okabe-Ito → P2-6 高亮 → P2-7 灰度抽查
       ↓
第六批（M1 报告侧·B，低风险下游 Agent5，依赖 P0-3 图不重复）：
  P1-2 编号格式 → P0-5 图表目录 → P0-6 资料来源具名
       ↓
第七批（M4 工程·A）：P3-1 审计日志 / P3-3 运行前自检 / P3-5 数据体检 / P3-7 决策树核对（纯 Agent3）+ P3-4/P3-6 文档

可选同批（C·低风险上下游，做则更彻底）：
  P0-2 层3：Agent1 fusion.py unit 归一（根因修复 + 缓解 §1.2 dedup 断点）
  P0-4 步骤3/4：Agent5 visual.py 密度档 + quality.py 阈值改引用 constants（全局收敛）

延后（D·中/高风险，本轮不做，单独立项）：
  P1-1 生成侧：Agent2 prompt_adapter 标题结论化（概率性 + 跨阶段）
  P3-2 跨阶段断点续跑（触 workflow 编排）；本轮仅做 Agent3 内失败项落盘
```

**硬约束（违反即返工）**：
1. P2-4 必须先于 P0-1（series_meta 不放开→combo 多序列被拒）。
2. P0-3 两步不可颠倒（先归一 key 再恢复抑制）。
3. P0-2（Agent3 层）建议先于 P0-3（unit 占位符过滤减少假性不重复）；若同批做 C 批的 fusion 归一，则 P0-3 匹配率更稳。
4. P1-2 必须先于 P0-5（编号不定→目录编号错）。
5. **凡标【双面】的 P1/P2 视觉项，builders.py 与 svg.py 必须同批改**，否则报告（SVG）看不到改进（§1.4）；svg.py 按 §0 属低风险下游，允许改。
6. **D 批延后项不得在 A/B 批中偷偷夹带**（尤其 Agent2 提示词、workflow 续跑）——超出"Agent3 优先 + 低风险上下游"作用域。

---

## 4. 预期效果（量化，对照 87 实例诊断基线）

| 指标 | 现状 | M1 后 | M3 后 |
|---|---|---|---|
| 声明类型/实际使用 | 12/2 | 12/≥4（combo 单轴+dual_panel 落地） | 12/≥6 |
| Y 轴单位缺失/含"未提供" | 26/87=30% | **0** | 0 |
| 有数据标签 | 0/87 | bar/line/combo ≤12 点有 | 全类型按规则 |
| 有关键点标注 | 0/87 | — | reference line/shaded/call-out 支持 |
| 同报告同类图重复 | 最多 6 张 | **≤1 张** | ≤1 |
| 候选浪费率 | 85% 丢弃 | 去重归一后下降 | 持续下降 |
| 数量阈值定义 | 5 处+1 重复 | **1 处 constants.py** | 1 处 |
| 图表目录 | 无 | **有** | 有 |
| 资料来源 | 引用编号[1][2] | **具名** | 具名 |
| 券商风视觉 | 无 | — | broker_thin 双面生效 |

终态目标：达到券商研报可交付水平（图号+资料来源+无网格细线+结论式标题），对照 `artifacts/图表样板集-理想态样例-20260912.html` 16 张图。

---

## 5. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 双改遗漏 svg.py | 前端好看、报告没变（最易踩） | 每卡【渲染面】标注；CI 加"option 特性→SVG 也需有"对照测试 |
| P0-3 恢复抑制误杀 | 该出的图被抑 | 先归一 key 再恢复；同 family 相似只告警不抑制 |
| P0-2 改 Agent1 fusion 波及取数 | 上游回归 | unit 归一只动 ChartDataset 构建，不动 EvidenceItem；跑 data_fetcher 全套 |
| P2-2 panels 字段 extra=forbid | schema 校验失败 | panels 设可选+默认 None；缺元数据回退 line |
| series_meta 2→4 涟漪 | router combo 校验失效 | P2-4 与 router 校验同批改 |

回滚：每项独立 commit；P0-2 的 Agent1 unit 归一可用 feature flag 包裹；constants.py 收敛是纯重构可 revert。

---

## 6. 测试方案（捏造数据驱动 + 双面验证 + 分项验收）

> 本节是验收的唯一依据。原则：**上下游智能体可能未完善，故用捏造测试数据直接驱动 Agent3**（绕过 Agent1/2 真实取数），每个改动项都有"单元 + 集成 + 视觉"三层验收，且凡【双面】项必须同时验证 ECharts option 与 SVG 重绘。

### 6.1 测试策略总则

1. **捏造数据驱动**：构造 `ChartDataset`（含 points/evidence_id/unit/series_meta）+ `ChartCandidate`，直接喂 `chart_generator/service.py:run()` 或 `builders.py`，不依赖真实问财/LLM。测试环境 `SKILLHUB_USE_MOCK`  irrelevant（Agent3 不触网）。
2. **双面验证（铁律）**：凡标【双面】的项，断言分两路——① `spec.option`（ECharts，前端面）含目标特性；② `render_chart_svg(spec)` 输出的 SVG 字符串含对应绘制（报告面）。**只验 option 不验 SVG = 漏测**（§1.4 双渲染路径）。
3. **证据链不变**：所有测试断言每个 `ChartPoint.evidence_id` 仍存在、`evidenceMap` 覆盖全部点（全程门禁，见上游方案五）。
4. **回归范围**：每项改动后跑 `tests/agents/chart_generator/` 全套；触碰 Agent1（P0-2 fusion）加跑 `tests/agents/data_fetcher/`；触碰 Agent5（P0-4/5/6、P1-2）加跑 `tests/agents/report_fusion/` + `tests/reporting/`。
5. **测试先行**：按用户习惯，每项先写测试（红）→ 再改生产代码（绿）。

### 6.2 捏造测试数据规格（构造模板）

固定一套"动力电池/新能源车"捏造数据，覆盖各 kind 与 chart_type：

| 数据集 | kind | 内容（捏造） | 验证目标 |
|---|---|---|---|
| DS-REV-PROFIT | time_series | 营收 2021-2025（亿元）+ 归母净利润（亿元），**同量纲** | P0-1 单轴 combo |
| DS-VOL-GROWTH | time_series | 销量（万辆）+ 增速（%），**双量纲**，4 series×12月 | P0-1 双轴 combo / P2-2 dual_panel |
| DS-LITHIUM | time_series | 碳酸锂价格 12 月（元/吨），含目标线/事件区间 | P1-5 标注 / P1-4 截断轴 |
| DS-UNIT-MISSING | categorical | unit=None / "未提供" 的数据集 | P0-2 占位符不进轴名 |
| DS-DUP-TREND | time_series | 6 个 insight_goal="展示趋势/展示变化/…走势" 的同类候选 | P0-3 去重归一+抑制 |
| DS-UPDOWN | time_series | 涨跌序列（+/-） | P2-3 红涨绿跌 |
| DS-COMPOSITION | categorical | 市场份额构成（pie/treemap） | P1-3 标签 |
| DS-CHAIN | industry_chain | 上中下游节点 | 产业链图 |

每个 point 必带 `evidence_id`（如 `E-FAKE-001`），`ChartCandidate.evidence_ids` 为对应子集（保证 `match_datasets` 的 subset 命中，隔离 §1.2 断点对测试的干扰）。

### 6.3 分项验收测试用例（与第 2 节任务卡一一对应）

**P0 层（M1 门禁，全绿才进 M2）**

| 用例 | 类型 | 断言 |
|---|---|---|
| `test_p01_combo_same_unit_single_axis` | 单元(router+builders) | DS-REV-PROFIT → `chart_type=="combo"` 且 `len(option["yAxis"])==1`，**不降级 line** |
| `test_p01_combo_dual_unit_two_axis` | 单元 | DS-VOL-GROWTH → combo 且 `len(option["yAxis"])==2`，两轴单位均标注 |
| `test_p01_combo_zero_unit_rejected` | 单元 | unit 全空 → 拒绝出图（reason=combo_requirements_not_met） |
| `test_p02_axis_name_no_placeholder` | 单元(builders) | DS-UNIT-MISSING → `option["yAxis"][0]["name"]` 不含"未提供"/"文本" |
| `test_p02_unit_normalized_at_source` | 集成(Agent1 fusion) | 构造 unit="未提供" 的 EvidenceItem → `build_chart_datasets` 产出 `dataset.unit is None` |
| `test_p02_placeholder_to_footnote` | 单元 | 占位符出现在 `spec.footnotes`（`[需核实:货币单位]`），不在轴名 |
| `test_p02_quality_gate_unit_missing` | 单元(quality) | unit 缺失 → quality 报告含 `unit_missing_or_placeholder` |
| `test_p03_dedupe_goal_normalized` | 单元(router) | "展示趋势"与"展示变化" → `build_dedupe_key` 相同（slot=trend） |
| `test_p03_duplicate_suppressed` | 集成(service) | DS-DUP-TREND 6 候选 → `len(specs)==1` 且 `len(suppressed)==5` |
| `test_p03_same_family_warns_not_suppress` | 集成 | 同 family 不同 slot → 告警但不抑制 |
| `test_p04_single_source_threshold` | 静态(grep) | **必做**：`RECOMMENDED_CHARTS` 在 `chart_generator/` 内仅 constants.py 一处定义。**可选(C批)**：visual.py/quality.py 引用它、无裸 `> 8` |
| `test_p05_chart_toc_present` | 集成(Agent5 html) | 报告 HTML 含「图表目录」章节，列出全部图号+标题 |
| `test_p06_source_named` | 集成(Agent5) | figcaption 为「资料来源：<具名>」非 `[1][2]`；无来源→`[需核实:数据来源]` |

**P1 层（M2/M3）**

| 用例 | 断言 |
|---|---|
| `test_p11_title_conclusive` | 描述性标题"碳酸锂价格趋势"→`title_not_conclusive`；结论式"碳酸锂价格同比下跌23%"→通过 |
| `test_p12_continuous_numbering` | 开启选项→图1/图2…全文连续；与 P0-5 目录编号一致 |
| `test_p13_datalabel_le12`【双面】 | ≤12 点：option.series.label.show=True **且 SVG 含数值文本**；>12 点：均无 |
| `test_p14_truncated_axis_footnote`【双面】 | scale=true → option.footnotes 含「纵轴未从 0 开始」**且 SVG 渲染该 footnote** |
| `test_p15_annotations`【双面】 | reference line/shaded region/call-out 三类在 option（markLine/markArea/markPoint）**且 SVG 有对应线/矩形/标注** |
| `test_p16_contrast_check` | 低对比配色（<4.5:1）→告警 |
| `test_p17_preflight_checklist` | 5 问全过才放行；任一不过→标记 |
| `test_p18_quality_three_questions` | 三问纳入 quality 报告 |

**P2 层（M3，多数双面）**

| 用例 | 断言 |
|---|---|
| `test_p21_broker_thin_theme`【双面】 | broker_thin：option 无网格/线宽1.5/无点 **且 SVG 无网格线、线宽1.5** |
| `test_p22_dual_panel`【双面+schema】 | 4series×12月→option 双 grid 互不交叉 **且 SVG 双 panel 布局**；缺 panels→回退 line 不抛错 |
| `test_p23_updown_colors`【ECharts透传】 | 涨跌序列 option.color=[#C0392B,#1E8449]；SVG 经 svg.py:98-100 读 color 自动一致（无需改 svg.py） |
| `test_p24_series_meta_4` | series_meta max_length=4；router combo 按实际分组数校验（非 len==2） |
| `test_p25_okabe_ito`【双面】 | 第4套主题 okabe_ito 8 色，option+SVG 双面生效 |
| `test_p26_highlight`【双面】 | 重点序列上色、其余灰化，option+SVG 一致 |
| `test_p27_grayscale` | 灰度转换后序列仍可辨（抽查脚本） |

**P3 层（M4）**：审计日志 7 字段落盘断言；断点续跑只重跑失败项；运行前自检拦截不完整数据；能力边界表/禁用清单/决策树为文档验收（人工核对）。

### 6.4 双渲染路径专项验证（最关键，单列）

新增 `tests/reporting/test_svg_option_parity.py`：对每个【双面】特性，参数化断言"option 含特性 ⇒ SVG 含对应绘制"。例如：
- option.series.label.show=True ⇒ SVG 文本节点含该数值
- option.yAxis.scale=true ⇒ SVG 含截断提示文本
- option.series.markLine ⇒ SVG 含对应 reference line 元素
- option.color=[UP,DOWN] ⇒ SVG series 填充色匹配（这条本就透传，作回归保护）

此测试是 §1.4 盲区的守门员：**防止"前端好看、报告没变"**。

### 6.5 回归门禁（每里程碑出口）

| 里程碑 | 必须全绿 |
|---|---|
| M1（P0 全部） | `tests/agents/chart_generator/`（必）；**若做 C 批** P0-2 fusion 归一加跑 `tests/agents/data_fetcher/`；**第六批 B（P0-5/6/P1-2）**加跑 `tests/agents/report_fusion/` + `tests/reporting/` |
| M2（P1-1~4） | 上述 + 新增 P1 用例 |
| M3（P1-5~8+P2） | 上述 + `test_svg_option_parity.py` |
| M4（P3） | 全量 `backend/tests/` |

环境：`env -u CORS_ORIGINS -u API_BEARER_TOKENS -u LLM_* -u IWENCAI_API_KEY -u AGENT1_BOCHA_API_KEY` 包裹，用 `backend/.venv` 全路径 python（mock 模型，禁真实 LLM）。

### 6.6 理想态图表样例清单（捏造数据，16 张，视觉验收基准）

用 §6.2 捏造数据产出，对照 `artifacts/图表样板集-理想态样例-20260912.html`。每张标注验证项：

| # | 图 | 验证项 |
|---|---|---|
| 1 | 营收+归母净利润 combo（单轴，亿元） | P0-1 单轴 / P2-4 |
| 2 | 销量+增速 combo（双轴，万辆/%） | P0-1 双轴 |
| 3 | 4series×12月 dual_panel（左销量右增速） | P2-2 |
| 4 | 碳酸锂价格 line + 目标线 + 事件区间 + 标注点 | P1-5 |
| 5 | 碳酸锂价格 line（scale=true）+ 截断提示 | P1-4 |
| 6 | bar（≤12点）带数值标签 | P1-3 |
| 7 | line（>12点）无标签 | P1-3 |
| 8 | 涨跌序列红涨绿跌 | P2-3 |
| 9 | 市场份额 pie（结论式标题） | P1-1 |
| 10 | 竞争格局 radar | 类型覆盖 |
| 11 | 厂商对比 scatter | 类型覆盖 |
| 12 | 产业链 industry_chain | 类型覆盖 |
| 13 | 成本结构 treemap | P1-3 |
| 14 | broker_thin 主题样张（无网格/细线/衬线） | P2-1 |
| 15 | Okabe-Ito 色板样张 | P2-5 |
| 16 | 高亮法样张（重点上色其余灰） | P2-6 |

全部图：图号连续（P1-2）、资料来源具名（P0-6）、报告含图表目录（P0-5）、轴名无占位符（P0-2）、同类不重复（P0-3）。

> 样例可用捏造数据离线生成（不依赖真实链路）；如需实际 HTML 产物，按 §6.2 数据 + builders.py 理想态主题渲染即可。

