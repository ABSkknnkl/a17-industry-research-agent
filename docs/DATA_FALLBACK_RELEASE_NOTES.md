# 文档通道降级链 · 发布变更说明与运维观测

- 日期：2026-09-04
- 关联方案：[2026-09-04-doc-channel-fallback.md](plans/2026-09-04-doc-channel-fallback.md)（已由"待评审"转"已实现"）
- 交付范围：**纯开发交付**（生产代码 + 文档），不含单元测试/评测用例/快照录制/评分器回归（见文末交付边界）
- 部署顺序：**先四刀仲裁，后本降级链**（两者文件仅 `service.py` 交叉，互不阻塞）

---

## 一、功能摘要

结构化取数失败（零行，或被问财静默回退成行情垃圾数据）时，自动按映射表**串行**回补 `report_search` / `announcement_search` / `news_search` 三个既有文档技能，把原先直接判缺口的指标补成**定性文字证据**。全程：

- 不新增数据源、不改数据库、不接联网搜索；
- 降级证据强制 `document` 层级 + 定性只读，**不参与 C1 数值计算**、**不冒充完整数据**；
- 四条护栏：仅失败任务触发、单任务降级深度 ≤2、单轮全局 ≤15 次、降级任务禁递归。

总开关 `AGENT1_FALLBACK_CHAIN` **默认关闭**——关闭时行为与改造前逐字节一致，可一键回滚。

---

## 二、修改文件清单

| 文件 | 变更 | 类型 |
|------|------|------|
| `app/agents/data_fetcher/field_relevance.py` | 抽出 `_field_relevance_check` 及行情词表/元数据字段词表，打破 executor↔normalizer 循环 | **新增** |
| `app/agents/data_fetcher/executor.py` | 成功判定=有行且字段相关；`fallback_skills` 串行降级调度；降级留痕；护栏（深度/预算/禁递归） | 改 |
| `app/agents/data_fetcher/planner.py` | 新增 `_fallback_skills()` 映射表 + 任务填充 `fallback_skills` | 改 |
| `app/agents/data_fetcher/normalizer.py` | 改从 `field_relevance` 导入；降级证据打 `evidence_tier=document` + `qualitative_only` | 改 |
| `app/agents/data_fetcher/service.py` | 覆盖率仅降级命中→`partial`；澄清门文案三分流；解包降级任务集合 | 改 |
| `app/agents/data_fetcher/routing_telemetry.py` | `skill_call` 事件增 `fallback_from`/`fallback_depth` | 改 |
| `app/agents/data_fetcher/factory.py` | 接线三个配置开关到 `RetrievalExecutor` | 改 |
| `app/schemas/acquisition.py` | `SkillQueryTask.fallback_skills`；`SkillCallRecord.fallback_from/fallback_depth` | 改 |
| `app/schemas/evidence.py` | `EvidenceItem.evidence_tier` / `qualitative_only` | 改 |
| `app/agents/data_interpreter/calculations.py` | C1 计算拒收 `document`/`qualitative_only` 证据 | 改 |
| `app/core/config.py` | `AGENT1_FALLBACK_CHAIN` / `AGENT1_FALLBACK_MAX_DEPTH` / `AGENT1_FALLBACK_CALL_BUDGET` | 改 |

> 关键去环：`normalizer → executor`（既有）之上，`executor → field_relevance`、`normalizer → field_relevance`，`field_relevance` 无内部依赖，无新增环。`_field_relevance_check` **函数签名不变**，既有 6 个 P0-6 单测零改动通过。

---

## 三、Schema 变更（全部向后兼容，均带默认值）

| 模型 | 新字段 | 类型/约束 | 默认 | 语义 |
|------|--------|-----------|------|------|
| `SkillQueryTask` | `fallback_skills` | `list[SkillName]`，`max_length=2` | `[]` | 仅当本技能全部 query 变体无有效数据时按序尝试；空=不降级 |
| `SkillCallRecord` | `fallback_from` | `str|None`，`max_length=64` | `None` | 触发本次降级的主任务 `task_id`；主调用为 `None` |
| `SkillCallRecord` | `fallback_depth` | `int`，`0..2` | `0` | 0=主调用，1/2=降级层级 |
| `EvidenceItem` | `evidence_tier` | `Literal["structured","document","web_unverified"]` | `"structured"` | 证据层级，**单向可降不可升** |
| `EvidenceItem` | `qualitative_only` | `bool` | `False` | 定性只读标记 |

`extra="forbid"` 模型新增声明字段为官方扩展路径；默认值保证旧数据反序列化不受影响。`contracts/` 中 `reason_code` 等为自由字符串，未受本次枚举影响。

---

## 四、降级映射表（`planner._fallback_skills`）

| 主技能（结构化） | 降级链（按序） | 依据 |
|---|---|---|
| `BUSINESS`（经营/出货量/产能） | `REPORT` → `ANNOUNCEMENT` | 出货量/产能/扩产常见于券商研报与扩产公告 |
| `FINANCE`（公司财务） | `REPORT` → `ANNOUNCEMENT` | 财务问财覆盖良好，仅兜底 |
| `INDUSTRY`（行业指标） | `REPORT` → `NEWS` | 行业数据基本齐全，降级补景气判断与政策 |
| `INDUSTRY_CHAIN`（产业链） | `REPORT` | 环节盈利分配见于产业链深度研报 |
| `STOCK_SELECTOR`（市占率/CRn） | `REPORT` | 竞争格局与份额多由研报测算 |
| `BASIC_INFO`（公司概况） | `ANNOUNCEMENT` → `REPORT` | 主营业务介绍见年报/公告 |
| `INSTITUTIONAL_RESEARCH` | 不降级 | 本身即机构观点源 |
| `INDEX`/`FUTURES`/`MACRO`/`SECTOR` | 不降级 | 问财域内完整，文档通道无增量 |
| `EVENT`/`NEWS`/`ANNOUNCEMENT`/`REPORT` | 不降级 | 自身即文档通道（防环路） |

**降级 query 构造**（`executor.fallback_query_for`）：取目标实体前 3 个 + 请求指标前 4 个（剔除标题/日期/链接等元数据词），不再沿用结构化措辞；无实体/指标时回退原 query 前 120 字符。

---

## 五、四条红线落地对照

| 红线 | 落地点 | 机制 |
|------|--------|------|
| 1 层级锁死不可上调 | `normalizer` 打标 | 降级证据恒 `evidence_tier="document"`；无上调路径 |
| 2 只补定性不填数值 | `normalizer` + `calculations` | `qualitative_only=True`；C1 的数值漏斗拒收 `document`/`qualitative_only` |
| 3 不计完整性 | `service._mark_fallback_partial_coverage` | 仅降级命中的需求强制 `partial`，**绝不 `supported`** |
| 4 冲突保留+可追溯 | `normalizer`/`executor` | 降级证据照常清洗去重；`fallback_from`/`fallback_depth` + `source_locator`/`source_org` 留痕 |

**C1 一票否决**：`calculate_p0_metrics` 的数值候选过滤追加 `evidence_tier=="structured" and not qualitative_only`——研报估算值只能作观点出现，绝不作为运算数。

**澄清门文案三分流**（`service`）：
- 结构化缺 + 降级命中 → `partial`，note：“已补充研报/公告/新闻定性材料（document 层级），数值未参与计算”；
- 结构化缺 + 降级未命中 → `missing`，note：“结构化与文档通道均无数据，已列入研究边界，未编造”；
- 实体未解析 → “请指定具体公司”。

---

## 六、触发条件与护栏

1. 仅 `fallback_skills` 非空的任务生效（默认按 §四 映射表）；
2. 仅主技能全部 query 变体无有效数据后触发；
3. 单任务降级深度 ≤ `AGENT1_FALLBACK_MAX_DEPTH`(=2)，且降级任务自身 `fallback_skills` 置空、`task_origin="fallback"`，**天然禁递归**；
4. 单轮全局降级调用 ≤ `AGENT1_FALLBACK_CALL_BUDGET`(=15)；命中即停（串行，遇到第一个成功的降级技能即止，不级联放大）。

成本估算：参照 61 条压测，主任务失败约 15–20，降级增量 ≤15 次/轮，对 `ToolGateway` 预算无实质压力。

---

## 七、上线风险与回滚

| 风险 | 影响 | 缓解 |
|------|------|------|
| 拆模块引入回归 | P0-6 失效 | 函数签名不变，6 个既有用例零改动；`field_relevance.py` 独立可回滚 |
| 降级放大调用量 | 网关预算超支 | 深度≤2 + 全局≤15 + 仅失败触发 + 命中即停 |
| 降级证据被当事实用 | 报告出现不可靠数值 | C1 拒收 `document` 层（FB4 一票否决语义） |
| 映射表设计有误 | 大量无效降级 | 降级挽救率 <40% 即回头调表，不加层级 |
| 给错误路由续命 | 掩盖四刀 BUG‑1 | 部署顺序先四刀后降级 |

**回滚**：设 `AGENT1_FALLBACK_CHAIN=false` 即回到改造前行为（新字段均有默认值，数据兼容）。逐文件回滚亦可，`field_relevance.py` 抽出为独立可回滚单元。

---

## 八、运维观测

### 监控字段（`routing_telemetry` `skill_call` 事件）

| 字段 | 类型 | 说明 |
|------|------|------|
| `fallback_from` | str/null | 触发降级的主任务 `task_id`；主调用为 `null` |
| `fallback_depth` | int | 0=主调用，1/2=降级层级 |
| `status` | str | `succeeded`/`empty`/`failed` |
| `returned_rows`/`cleaned_rows`/`quarantined_rows` | int | 行数观测 |

（其余 `ts`/`run_id`/`revision`/`skill`/`query`/`task_id` 沿用 P0‑5。）

### 指标释义

| 指标 | 定义 | 目标 |
|------|------|------|
| 降级触发率 | 触发降级的任务 / 失败任务 | 观测，不设限 |
| **降级挽救率** | 降级命中的任务 / 触发降级的任务 | **≥60%** |
| 降级证据采用率 | 进入最终报告的降级证据 / 降级命中证据 | 观测 |

计算口径（按日聚合 `artifacts/routing_telemetry/*.jsonl`）：
- 触发降级任务数 = `fallback_depth>0` 的去重 `fallback_from` 数；
- 降级命中数 = `fallback_depth>0 且 status="succeeded"` 的去重 `fallback_from` 数；
- 采用率需结合报告证据引用（`evidence_tier=="document"` 且被章节引用）。

### 告警建议

- **挽救率 <40%（持续 2 天）**：映射表设计有误，回头调整映射，而非加降级层级；
- **单轮降级调用逼近 15**：失败面异常扩大，优先排查上游路由/取数质量；
- **降级证据出现在 `calculated_metrics` 输入**：红线告警（理论上被 C1 拦截，出现即缺陷）；
- **仅降级命中被判 `supported`**：红线告警（理论上被 `_mark_fallback_partial_coverage` 拦截，出现即缺陷）。

---

## 九、上线验收底线（一票否决）对照

| 底线 | 状态 |
|------|------|
| C1 计算错误 = 0，降级定性素材绝不参与数值运算 | ✅ `calculations` 数值漏斗拒收 `document`/`qualitative_only`（mock 冒烟：结构化产出 `revenue_yoy`，document 产 0） |
| 降级命中不可伪装成完整数据 | ✅ 仅降级命中强制 `partial`，绝不 `supported` |
| 不存在递归降级调用 | ✅ 降级任务 `fallback_skills` 置空 + `task_origin="fallback"` 跳过 |
| 原 61 条意图压测集功能无退化 | ⚠️ 本交付不含评测执行；既有 `tests/` 全量 mock 回归通过，61 条压测回放请按评测流程另行执行 |

---

## 十、交付边界说明

- **不含**：单元测试、评测用例、快照录制（`snapshot_ver`）、评分器（FB1–FB5）回归。方案 §6/§7/§8 的 TDD 与 replay 环节**未在本次交付内**，需评测侧另行排期；
- **已含**：生产代码改造、Schema 扩展、四条红线落地、澄清门文案、遥测埋点、本文档；
- **已做验证**（非交付物，供参考）：`tests/` 全量 mock 回归 **666 passed / 1 skipped**（跳过项为需真实 LLM 的评审器红队门，默认不开；Chromium PDF 链路已可用）；`_field_relevance_check` 6 个 P0‑6 单测零改动通过；降级链端到端 mock 冒烟（触发→命中→留痕→分层→C1 拦截）通过。

> 注：本实现将"字段相关性前移"落为**循环后统一判定**而非作为同技能 query 变体重试的触发条件——后者会让静默回退的行情数据借换措辞拿到无关数据冒充成功（与 P0‑6 回归冲突）。降级仍正确路由到文档通道，语义与方案目标一致。
