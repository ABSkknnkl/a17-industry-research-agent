# L3 联网数据「官方数字计算通道」+ 博查时间范围动态化 · 完整实施方案

- 日期：2026-09-07
- 状态：**待评审**（本方案不含任何生产代码改动；落地按 §7 分期执行）
- 前置阅读：`2026-09-06-agent1-cascade-fallback-FINAL.md`（L3 三级级联）、`docs/2026-09-06-agent1-4-real-llm-eval-report.md`（真实链路评测）
- 触发问题：用户目标——「联网搜集更多数据，用户同意后参与计算，同时不污染其他数据、不影响下游」；并一起定博查 freshness 动态化

---

## 0. 一页结论

**不要再给现有 `AGENT2_WEB_NUMERIC_ENABLED` 通道续命。** 它功能上没达成「参与 C1 计算」的意图（被 `period_end=None` 双道护栏挡住），副作用却全发生了（图表破图 + LLM claims 引用冲突值）。正确做法是：

1. **一期（不碰红线，可立即做）**：下线首个数字抽取、修破图、来源分级（T0/T1/T2/T3 + 黄/红分级警告）、freshness 动态化。
2. **二期（动红线 2，需签字 + feature flag）**：新建 `official_figure` 官方数字计算通道——语义绑定抽取 + 证据清单制用户授权 + 计算/图表/claims 三道隔离。T0 官方来源的数字经用户逐条授权后参与计算，**与 structured 数据分池隔离、只补位不混算**，全链路带〔网·官方〕标记可回滚。

---

## 1. 现状核实（三笔账，全部带行号证据）

现行「阶段一」（2026-09-06，`AGENT2_WEB_NUMERIC_ENABLED`，默认 false）的实际行为：

### ① 计算：其实一次都没进去（意图未达成）

| 护栏                     | 位置                                                  | 效果                                                                    |
| ---------------------- | --------------------------------------------------- | --------------------------------------------------------------------- |
| `_numeric_evidence` 放行 | `calculations.py:57-67`                             | 开关开启时 web_unverified 数值**能进池**                                        |
| formal 期间指标分组          | `calculations.py:90` `item.period_end is not None`  | web 证据 `period_end=None`（`normalizer.py:745`）→ **进不了 YoY/利润率等全部期间计算** |
| CR3/CR5 集中度            | `calculations.py:701` 同样要求 `period_end is not None` | **也进不了**                                                              |

结论：开关打开后，web 数值能进 `_numeric_evidence` 的池子，但**没有任何一条 CalculatedMetric 会用到它**。「参与 C1 计算」意图 0% 达成。

### ② 图表：进去了，且会出破图（真实污染）

`fusion.py:91-98` `build_chart_datasets` 对任何数值证据**无 tier / qualitative_only 过滤**，按 `(metric_name, unit, currency, scope)` 分组。web 证据 `period_end` 全 None → `kind="categorical"` → 标签取 `scope` → **同指标多条 web 数值生成标签完全相同、数值不同的多根柱子**；不同口径指数（如 SMM 电池级 vs 生意社基准价）被画进同一张图当可比数据。

### ③ LLM claims：最不可控的一条

数值证据进 Agent 2 证据包后，LLM 可引用、平均、比较这些冲突数字。抽取本身（`normalizer.py:664-680`）是「全文第一个数字+单位」，注释明写「抽取不做语义择优」；单位表（`normalizer.py:606-658`）含裸 `亿/万/%/bp` → 摘要若以「持仓量12.3万手」「同比涨15%」开头，就会把 12.3万 / 15% 当成目标指标值。碳酸锂案例「成功」纯属摘要恰好以价格开头的运气。

### ④ freshness 现状

`client.py:203` `DEFAULT_FRESHNESS="oneYear"` 恒值（`:238`），`MAX_COUNT=10`（`:204`）；`_clean_hits`（`:297-348`）只筛 url/来源/白名单/相关性，**从不按日期过滤**；`fallback_query_for`（`executor.py:104-117`）只拼实体+指标，**用户时间词（如「近五年」）在降级 query 里丢失**。

---

## 2. 设计原则

1. **红线不重定义，权限走新通道**。红线 1（tier 锁死不上调）、红线 2（web 不进数值计算）、红线 3（降级不冒充完整性）对 T1/T2/T3 来源**原封不动**；二期只对「T0 官方来源 + 语义绑定抽取 + 用户逐条授权」的证据开一个独立放行口，且 `evidence_tier` 恒 `web_unverified`（诚实标注来源，不上调）。
2. **三权分立**：定性引用权（所有 web 证据默认有）＜ 图表权（默认禁止，官方数字单独成系列）＜ 计算权（最高门槛）。每一权独立开关。
3. **授权精确到证据，不是全局开关**。用户授权的是「这份清单里的这几条数字」，授权清单与快照 SHA 绑定，可审计、可回滚。
4. **只补位，不混算**。official 数字只在 structured 数据缺失时补位；同指标两边都有值，official 让位并披露口径差异，绝不混合运算。
5. **数值准确性由架构守住，不由 freshness 守住**。freshness 只管召回相关性；「web 数字能不能进报告」由 tier + 授权 + 隔离守住——这是 Part B 敢放开 `noLimit` 的底气。

---

## 3. Part A：官方数字计算通道（official figure）

### 3.1 总架构

```text
博查命中
  → 域名分级（T0/T1/T2/T3，子域黑名单优先）         §3.2
  → T3 丢弃；T0/T1/T2 进清洗
  → 语义绑定抽取（锚点窗口 + as-of 期间 + 单位归一）  §3.4
       ├─ 抽不到 / 缺 as-of / 非 T0 → 定性证据（现状，qualitative_only=True）
       └─ T0 + 锚点 + 单位 + as-of 齐全 → web_numeric_candidates 候选清单
  → Agent1 审核门决策包：用户逐条/整单授权            §3.3
       ├─ 未授权 → 定性证据（行为与现状完全一致）
       └─ 已授权 → EvidenceItem.official_figure=True（tier 仍 web_unverified）
  → Agent2：双池计算（structured 池 + official 池补位） §3.5
  → 图表：official 单独系列带〔网·官方〕；claims 强制标记
```

### 3.2 来源分级映射（替换扁平白名单）

`DEFAULT_DOMAIN_ALLOWLIST`（`client.py:39-120`）改为分级映射。**匹配顺序：先查 T3 子域黑名单，再查父域分级**（`eastmoney.com`=T2 但 `guba.eastmoney.com`=T3 必须先命中）。

| 级别               | 来源（域名）                                                                                                                                                                                                                                                  | 定性            | 图表      | 计算                  |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- | ------- | ------------------- |
| **T0** 官方/法定信披   | gov.cn 及各部委（pbc/stats/ndrc/miit/mof/mofcom/safe/csrc）、交易所（sse/szse/bse）、chinamoney/chinabond、7 家信披媒体（cs.com.cn/cnstock.com/stcn.com/**zqrb.cn**/**financialnews.com.cn**/**jjckb.cn**/chinadaily.com.cn，加粗为现白名单缺失需补）、新华社/人民日报/央视/新华财经(cnfin.com)/光明网/求是 | ✅             | 授权后单独系列 | **授权后补位计算（唯一可计算级）** |
| **T1** 专业财经      | 财新/第一财经/财联社(**cls.cn**，现缺需补)/21 经济/每经/界面/经济观察/中国经营报/财经/华尔街见闻/FT 中文/澎湃/新京报                                                                                                                                                                               | ✅             | 授权后单独系列 | ❌ 永不                |
| **T2** 门户聚合/产业垂直 | 新浪/网易/腾讯/搜狐/凤凰/和讯/金融界/东财/雪球/格隆汇/虎嗅/36kr/钛媒体/前瞻/艾媒 + 产业垂直（北极星/电池中国/盖世/第一电动等，即现白名单产业段）                                                                                                                                                                    | ✅（现状）         | ❌       | ❌ 永不                |
| **T3** 黑名单       | guba.eastmoney.com（股吧）、荐股站、营销号、散户自媒体                                                                                                                                                                                                                    | 客户端直接丢弃，不进证据池 | —       | —                   |

**T0 内部再分「原文页 vs 观点页」**：同一 T0 域名既发公告原文也发评论。仅当 URL 路径命中数据/公告栏目模式（如 `/statistics/`、`/gonggao/`、`/data/`、交易所披露页）且正文数字带单位+期间，才进候选清单；评论/解读栏目一律按 T1 处理。路径模式表作为配置外置（`backend/config/web_source_tiers.yaml`），不发版可改。

分级警告映射到现有枚举（`schemas/decision.py:13-23`），与 S8 汇总块（`service.py:525-549`）兼容：

| 级别    | severity  | disposition                | 前端                                        | 说明                    |
| ----- | --------- | -------------------------- | ----------------------------------------- | --------------------- |
| T0/T1 | `WARNING` | `ADVISORY`                 | 🟡 黄条告知，不拦截                               | 信息性 risk_notice，不挂决策包 |
| T2    | `HIGH`    | `ACKNOWLEDGEMENT_REQUIRED` | 🔴 红色确认门（现状 `WEB-SOURCE-UNVERIFIED` 语义不变） | 用户确认才放行               |
| 混合    | 红主导       | —                          | 一轮含任一 T2 即出红门，T0/T1 作子列表展示                | 最坏来源决定严格度（fail-safe）  |

### 3.3 双闸门授权（功能总闸 × 任务级证据清单授权）

**闸门 1 · 功能总闸**：`AGENT1_WEB_OFFICIAL_FIGURE_ENABLED`（新 env，默认 `false`）。关闭时不分级、不抽取、不生成候选清单——全链路行为与现状逐字节一致（回滚锚点）。

**闸门 2 · 任务级证据清单授权**（核心，落在现有审核体系上）：

1. Agent 1 normalizer 产出候选清单 `web_numeric_candidates`，每条含：`evidence_id / 指标名 / 数值 / 归一单位 / as-of 日期 / 来源(域名+tier) / 原文引句(≤200字) / 抽取置信度`。
2. data_fetch 审核门决策包挂风险码 `WEB-OFFICIAL-NUMERIC`（`severity=HIGH`，`disposition=ACKNOWLEDGEMENT_REQUIRED`），detail 渲染候选清单，用户可整单接受或剔除个别条目后接受。
3. 用户 `accept_with_risks` + `accepted_risk_codes` 含该码 → 授权结果写入 `StageResult.data["web_numeric_consent"] = {"granted": true, "evidence_ids": [...], "snapshot_sha256": ...}`（与 risk_snapshot 绑定，防篡改——复用 `compute_risk_snapshot_sha256`，`decision.py:50`）。
4. Agent 2 只对清单内 `evidence_id` 放开计算；未授权条目维持定性。**修订重跑（revision+1）时授权不自动继承**，候选清单重新生成、重新确认。
5. 废弃 `AGENT2_WEB_NUMERIC_ENABLED`：一期先标记 deprecated 并保持默认 false；二期合入总闸语义后移除（含 `_extract_web_numeric` 旧实现与对应测试的清理）。

### 3.4 语义绑定抽取（替换「首个数字+单位」）

新抽取器 `_extract_official_figure(text, *, anchor_terms)`，规则：

| 步骤         | 规则                                                                                                                             | 失败后果                  |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------ | --------------------- |
| ① 锚点定位     | 正文须含主指标词或其别名（锚点词表来自 `metric_registry` 别名 + `fallback_main_metric`，如「碳酸锂价格/锂价」）；定位锚点所在子句                                        | 无锚点 → 不抽，保持定性         |
| ② 窗口取值     | 锚点 ±40 字符（不跨子句）内找「数字+单位」；裸 `万/亿/%/bp` 单位要求与数字紧邻（≤2 字符）且同句含锚点                                                                   | 窗口无值 → 不抽             |
| ③ as-of 期间 | 同句或相邻子句抽日期（`YYYY-MM-DD`/`YYYY年M月D日`/`YYYY年M月`/`M月D日`）；抽到 → `available_at=该日期` 且 notes 标「as-of 取自正文」；抽不到 → `available_at=文章发布日` | 缺 as-of → 不进候选清单（可定性） |
| ④ 单位归一     | 抽取后立即归一：`万元/吨→元/吨`、`亿→×1e8 元`、`万→×1e4 元`；外币（美元/港元）无汇率证据 → 拒绝数值化                                                                | 不可归一 → 不进清单           |
| ⑤ 原文页校验    | URL 命中 T0 原文栏目模式（§3.2）                                                                                                         | 观点页 → 按 T1，不进清单       |
| ⑥ 多候选      | 同指标多条命中 → **全部进清单，不自动选值**                                                                                                      | 冲突保留，交用户/计算层判         |

置信度：`锚点+单位+as-of+原文页` 齐 = `high`（进清单的唯一档）；其余不产候选。

### 3.5 三道隔离（不污染其他数据、不影响下游）

**隔离 1 · 计算双池**（`calculations.py` 改动）：

```text
_numeric_evidence 返回 (structured_pool, official_pool)
  structured_pool = tier=="structured" 且非定性          （现状不变）
  official_pool   = tier=="web_unverified" 且 official_figure=True
                    且 evidence_id ∈ consent.evidence_ids
calculate_p0_metrics：
  先跑 structured_pool（现状逻辑逐行不动）
  official_pool 仅对「structured 池无该 canonical 指标」的缺口补位；
  同指标两边都有 → official 让位 + 记 data_quality_issue（口径差异披露）
  补位产出的 CalculatedMetric 带 inputs_provenance="web_official"（新可选字段）
```

C-10 测试语义**保持**（未授权/T1/T2 的 web 证据进计算链 = 一票否决）；新增 C-10b（授权+T0+清单内 → 可进；清单外 → 仍否决）。

**隔离 2 · 图表**（`fusion.py` 改动）：

- 一期先行修复（不等二期）：`evidence_tier=="web_unverified"` 的数值证据**不进** `build_chart_datasets` 分组（修破图）。
- 二期：`official_figure=True` 的证据单独分组键（加 provenance 维度），`series` 名带「网·官方」前缀，label 用 as-of 日期；与 structured 数据集不合并。

**隔离 3 · claims 与质量门**：

- `prompt_adapter.py` 注入规则：引用 official 证据的数字必须带〔网·官方〕标记；`graph.py` audit 节点加确定性校验（未标记 → issue → revise）。
- official 证据**不计入**核心数据组完整性（与 web 证据同规则，不拉高 completeness）；`dimension_coverage` 不因 official 补位从 partial 升 supported。
- `period_end` 语义不动：official 证据的 as-of 落在 `available_at`，**不伪造 `period_end`**（报告期是财报语义，价格/产量快照不是报告期——这正是现行通道被双道护栏挡住的原因，新通道尊重这道护栏，用 consent 白名单放行而不是填假期间）。

### 3.6 契约变更（全部向后兼容的可选项）

| 位置                                       | 变更                                                                 | 兼容                                                   |                     |
| ---------------------------------------- | ------------------------------------------------------------------ | ---------------------------------------------------- | ------------------- |
| `schemas/evidence.py` `EvidenceItem`     | + \`source_tier: Literal["T0","T1","T2"]                           | None`（仅 web 证据有值）；+ `official_figure: bool = False\` | 旧数据 None/False，无需迁移 |
| `schemas/analysis.py` `CalculatedMetric` | + \`inputs_provenance: str                                         | None\`                                               | 可选                  |
| `contracts/schemas/`                     | 同步上述两字段（跨端唯一契约源，必须同步）                                              | 前端按可选渲染                                              |                     |
| StageResult.data                         | + `web_numeric_candidates`（Agent1 输出）、`web_numeric_consent`（审核后写入） | 新键，下游缺省忽略                                            |                     |

### 3.7 下游影响矩阵（「不影响下游」的逐格回答）

| 下游             | 未授权（默认）                  | 已授权                              |
| -------------- | ------------------------ | -------------------------------- |
| Agent 2 claims | 与现状一致（web 仅定性，〔网〕标记）     | official 数字可引用，强制〔网·官方〕；audit 校验 |
| Agent 2 计算     | structured only（C-10 守住） | 双池补位，产物带 provenance              |
| Agent 3 图表     | web 数值不进图（一期修复后）         | official 单独系列，可单独取舍              |
| Agent 4 章节     | 现状                       | 沿用溯源体系，〔网·官方〕进正文标注               |
| Agent 5 附录     | 现状（web 归「补充来源」）          | official 数字在数据质量附录单列「官方网络来源授权清单」 |

---

## 4. Part B：博查 freshness 动态化

### 4.1 决策（与代码现状对齐）

采纳「query 单通道 + 默认 noLimit + 客户端不做后置日期过滤」：

- **为什么敢默认 noLimit**：web 证据恒 `web_unverified` + 定性（一期后数值恒不进计算）+ T2 红色确认门 + 来源列表逐条显示 `published_at` —— 旧闻**污染不了任何数字**，只是复核人多看两条旧源。换来的是不漏召回（`count=10` × `oneYear` 窗口叠加会把唯一相关条筛没，L3 直接返空判缺口——对最后兜底通道是灾难）。
- **为什么不做客户端后置过滤**：缺 `published_at` 即误杀唯一相关条；与引擎排序分叉双重维护。当前 `_clean_hits` 本就不过滤日期，客户端零改动过滤逻辑。
- 原方案 §4.6「必带 oneYear 防旧闻」的实测结论，真正的兜底是 `web_unverified` + 人工复核，freshness 只是附加层。

### 4.2 映射表（`client.py` 新增 `_resolve_freshness(query)`）

| query 时间词            | freshness                  |
| -------------------- | -------------------------- |
| 今天/今日/当日             | `oneDay`                   |
| 本周/这周/近一周            | `oneWeek`                  |
| 本月/最近/最新/近期          | `oneMonth`                 |
| 今年/年内/近三年以内（含「近一年」）  | `oneYear`                  |
| 近三年/近五年/近十年/历史/不限/全部 | `noLimit`                  |
| **默认（无时间词）**         | **`noLimit`（改，原 oneYear）** |

引擎能精确表达的（今天/最新/今年）白捡精确；表达不了的大窗口与默认值放 `noLimit` 最大化召回，交人工复核看 `published_at` 把关。

### 4.3 query 单通道（时间词怎么进 query）

问题：`fallback_query_for`（`executor.py:104-117`）重写 query 时丢了用户时间词。改动：

- `fallback_query_for` 从 `main_task.query` 提取时间片段（正则命中 §4.2 时间词的子句）拼接到降级 query 尾部；`SkillQueryTask`/`SkillQueryArgs` 契约**不加字段**（共享契约不背单技能语义）。
- `client._resolve_freshness(args.query)` 解析映射 → body 的 `freshness`；`DEFAULT_FRESHNESS` 改 `noLimit` 兜底。
- 不新增任何后置日期过滤。

### 4.4 连带改动

- **C-14 测试翻转**：现断言 `DEFAULT_FRESHNESS=="oneYear"` → 改为默认 `noLimit` + 新增动态映射用例（每个时间词档至少 1 例）。
- **文档注记防回改**：`2026-09-06-agent1-cascade-fallback-FINAL.md` §4.6/D8 与 `client.py:7-11` docstring 标注「2026-09-07 产品决策：默认改 noLimit，数值准确性由 web_unverified + 人工复核承担」。

---

## 5. 风险与回滚

| 风险                       | 缓解                                            |
| ------------------------ | --------------------------------------------- |
| 抽错数字（锚点误判）               | 置信度仅 high 进清单 + 用户逐条看到原文引句才授权 + 全留痕           |
| 用户误授权                    | 清单含原文引句+来源+as-of，红门确认；修订重跑授权不继承               |
| official 与 structured 冲突 | 只补位不混算；让位记 issue 披露                           |
| 默认 noLimit 召回旧闻          | tier 架构守数值；来源列表显示 published_at；T2 红门          |
| 回滚                       | 总闸默认 false（行为=现状）；freshness 回滚=一行常量；新字段全可选无迁移 |

---

## 6. 验收门禁

- 一期：全量后端测试绿 + C-10 语义不变 + C-14 翻转后绿 + 破图修复用例（同指标 3 条 web 冲突值不产生同标签多柱数据集）+ 分级映射用例（T3 丢弃 / guba 子域优先 / 黄红 severity）。
- 二期：C-10b 全绿（清单内放行 / 清单外否决 / 未授权否决 / T1 否决 / 缺 as-of 否决 / 外币否决）+ 双池补位与让位用例 + audit 〔网·官方〕标记校验用例 + 61 条路由基线与 V8 101 用例全链路回归无新增失败。
- 真实链路：构造一条同花顺确无数据的需求（如碳酸锂现价）跑 L3 自然触发，验证候选清单→授权→补位计算→〔网·官方〕标记全链留痕。

---

## 7. 分期执行（先测试红着提交，再改生产）

**一期（不碰红线，预计 3 个文件 + 测试）**

1. `fusion.py`：web_unverified 数值不进图表分组（修破图）+ 测试。
2. `normalizer.py`：`_extract_web_numeric` 下线（web 证据 value 恒文本、`qualitative_only` 恒 True）；`AGENT2_WEB_NUMERIC_ENABLED` 标 deprecated。
3. `client.py`：分级映射（含补 zqrb.cn/financialnews.com.cn/jjckb.cn/cls.cn）+ T3 子域黑名单优先 + `_clean_hits` 打 tier 标签丢 T3。
4. `service.py` S8：按 tier 分流黄/红 risk_notice（T2 维持现状红门）。
5. `client.py`+`executor.py`：freshness 动态化 + fallback 时间词拼接；C-14 翻转。
6. `schemas/evidence.py` + `contracts/`：`source_tier` 可选字段。

**二期（动红线 2，需你签字 + 总闸）**

1. `_extract_official_figure` 语义绑定抽取器（§3.4）+ 候选清单产出。
2. 决策包 `WEB-OFFICIAL-NUMERIC` + consent 流转（§3.3）+ `official_figure` 字段。
3. `calculations.py` 双池 + `inputs_provenance`；`fusion.py` official 单独系列；`prompt_adapter`+audit 标记校验；C-10b。

---

## 8. 待拍板（4 件事）

1. **红线 2 对 T0 放开**：同意按「总闸 + 逐条清单授权 + 只补位不混算 + 全留痕」放开？（本方案的核心签字项）
2. **授权粒度**：采用「每研究任务一次，候选清单逐条可见、可剔除后整单接受」？还是「每个证据单独确认」（更安全但打断多）？
3. **T0 原文 vs 观点**：采用「URL 栏目路径模式 + 数字须带单位与 as-of」区分，观点栏目降 T1？
4. **一期先行**：是否同意一期先交付（含下线旧抽取 + 破图修复 + freshness），二期在评审通过后单独立项？




