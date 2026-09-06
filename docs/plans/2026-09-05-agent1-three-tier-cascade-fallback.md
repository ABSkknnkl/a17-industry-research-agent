# 智能体1 三层级联降级取数方案

- 日期：2026-09-05
- 状态：**待评审 · 方案设计稿**（未改生产代码）
- 范围：`backend/app/agents/data_fetcher/`、`backend/app/integrations/`、`backend/app/schemas/`、`contracts/`、`frontend/src/`
- 关联文档（本方案是它们的**整合与扩展**，不替代）：
  - [2026-09-04-doc-channel-fallback.md](2026-09-04-doc-channel-fallback.md) —— 已实现的第一级→文档通道降级（`AGENT1_FALLBACK_CHAIN`，默认关）
  - [../2026-09-04-联网搜索兜底方案选型.md](../2026-09-04-联网搜索兜底方案选型.md) —— 已选型未实现的联网兜底（博查 / Tavily）

---

## 0. 一句话结论与术语对齐

**结论**：把现有"结构化失败→文档通道"的两级结构，扩展为 **L1 主技能 → L2 同花顺备选技能 → L3 联网插件** 的三级级联；三级全部失败才判缺口。沿用既有 `evidence_tier`（`structured > document > web_unverified`）作为证据分级，**不新增第二套标签体系**；新增 `acquisition_level`（1/2/3）作为降级层级标识，经 `stage_results.data_fetch.data.acquisition_degradation` 传到前端；**仅当最终数据来自 L3 时前端弹风险提示**。

### 0.1 与旧文档的术语对照（避免混淆）

选型文档里的 L0/L2/L3 与本方案的 L1/L2/L3 **不是同一套编号**，对照如下：

| 本方案 | 选型文档的叫法 | 落点 |
|---|---|---|
| **L1 主技能层** | 结构化技能 | 已实现 |
| **L2 备选技能层** | 旧文档 "L0 文档通道降级"（是其**真超集**，见 §4） | 部分实现（仅文档通道，映射表固定） |
| **L3 联网插件层** | 旧文档 "L2 博查 / L3 Tavily" | 未实现（本方案落地） |

> 关键差异：旧方案的 L2 只覆盖"文档通道"，本方案的 L2 = **同域结构化替代技能 + 文档通道**，结构化优先。这样能最大概率在离开同花顺之前拿到权威结构化数据。

---

## 1. 现状盘点：已有什么、缺什么

| 环节 | 现状 | 代码位置 |
|---|---|---|
| L1 主技能调用 | ✅ 已实现，15 个 SkillName 注册进 ToolGateway | `catalog.py:18-69`、`registry.py:23-38` |
| L1 成功判定（含 P0-6 字段校验前移） | ✅ 已实现：`rows and fields_relevant` | `executor.py:285-296` |
| L1→文档通道降级 | ✅ 已实现，但 `AGENT1_FALLBACK_CHAIN=False` 默认关闭 | `planner.py:1378`、`executor.py:121-152`、`config.py:65` |
| L2 同域结构化替代 | ❌ 缺：现有映射表只到文档通道，不尝试其他结构化技能 | `planner.py:1385-1398` |
| L3 联网插件 | ❌ 完全缺失：`app/integrations/` 无 web 能力 | — |
| 证据分级三态 | ✅ 枚举已存在，但 `web_unverified` **从未被赋值** | `evidence.py:73`、`normalizer.py:447` |
| 降级层级传到前端 | ❌ 缺：`RequirementCoverage` / `SkillCallRecord` 无层级字段 | `acquisition.py:129-141`、`acquisition.py:185` |
| 前端风险提示 | ❌ 缺：仅审核门渲染 `decision_package.risk_notices` | `ReviewActions.vue:268-273` |

---

## 2. 三级执行顺序

```
需求（sub-requirement）
   │  路由：metric_registry + SKILL_CAPABILITIES + LLM 语义路由
   ▼
┌─────────────────────────────────────────────────────────────┐
│ L1  主技能层（同花顺，与需求最匹配）                          │
│   query 变体 ≤3 条试完（同技能内换措辞）                      │
│   判定：有效 = 无错误 AND rows>0 AND 字段相关 AND 可用性预检   │
└─────────────────────────────────────────────────────────────┘
   │ 失败 ──► 且 depth<max 且 有候选 且 预算>0
   ▼
┌─────────────────────────────────────────────────────────────┐
│ L2  备选技能层（同花顺域内，其他可用技能）                    │
│   2a 同域结构化替代（capability 推导，≤2 个）                 │
│   2b 文档通道（report / announcement / news，≤2 个）          │
│   串行尝试，任一命中即停                                      │
└─────────────────────────────────────────────────────────────┘
   │ 全部失败 ──► 且 开关开 且 配额足 且 本 task 未调过
   ▼
┌─────────────────────────────────────────────────────────────┐
│ L3  联网插件层（外网检索，非同花顺）                          │
│   单 task 仅 1 次、不重试、硬超时 8s                          │
│   结果恒为 evidence_tier=web_unverified，qualitative_only    │
└─────────────────────────────────────────────────────────────┘
   │ 仍失败
   ▼
┌─────────────────────────────────────────────────────────────┐
│ 兜底：判缺口（missing）→ 写 DataGap → 澄清门/决策包披露        │
│       「各通道均无数据，已列入研究边界，未编造」              │
└─────────────────────────────────────────────────────────────┘
```

**三条硬约束**：

1. **单向**：L3 → L2 → L1 的反向升级**永久禁止**；层级随证据固化，后续阶段不得改写。
2. **不递归**：L2/L3 任务自身失败不再触发新的降级（`task_origin != "main"` 即停）。
3. **串行**：L1 主任务可并发（`asyncio.Semaphore(4)`），降级调用串行执行，避免并发放大配额消耗。

---

## 3. L1 主技能层

### 3.1 输入输出

| | 内容 |
|---|---|
| **输入** | `SkillQueryTask{skill_name, query, fallback_queries[≤2], expected_fields, target_entities, tier, research_dimension}` |
| **输出（成功）** | `ExecutedTask{record: status="succeeded", payloads, trace_ids}` → `SkillPayload{rows, total_count, trace_id, raw_sha256, source_name, source_locator}` |
| **输出（失败）** | `status ∈ {empty, failed}` + `DataGap{reason_code}` |
| **证据层级** | `evidence_tier="structured"` |

### 3.2 判定条件（有效数据）

沿用 `executor.py:285-296` 已实现的判定，并补一条轻量预检：

```
有效 ⇔  error_code is None
     AND rows > 0
     AND _fields_relevant(payloads, task)          # P0-6：字段不是行情回退
     AND _rows_usable_precheck(payloads, task)     # 【新增】至少一行含非空业务字段
```

`_rows_usable_precheck` 的必要性：现有判定只看行数和字段相关性，无法识别"行存在但目标列全为空"的情况——补这一条可避免空壳数据冒充命中。

### 3.3 触发 L2 的规则

| L1 结果 | `reason_code` | 是否进 L2 | 说明 |
|---|---|---|---|
| 空结果 | `empty_result` | ✅ 立即 | 库里确实没有 |
| 静默降级为行情 | `market_quote_fallback` | ✅ 立即 | **不再换措辞重试**（换措辞会拿到更多无关行情数据，P0-6 回归风险） |
| 可重试错误 | `tool_timeout` / `provider_unavailable` / `rate_limited` | ⚠️ **先同技能重试 1 次**，仍失败才进 L2 | 网络抖动不该浪费降级配额 |
| 不可重试错误 | `invalid_tool_payload` / `request_rejected` | ✅ 进 L2，同时**记异常日志** | 可能是接口变更，属故障信号 |
| 鉴权/权限 | `auth_required` / `permission_denied` | ⛔ **跳过 L2，直达 L3 或兜底** | 见 §9.3 全局熔断 |
| 护栏拦截 | `tool_call_blocked` | ❌ **不降级** | 绕过护栏=安全事件 |

---

## 4. L2 备选技能层（同花顺域内）

### 4.1 候选技能推导（不是拍脑袋，从能力边界推导）

依据 `SKILL_CAPABILITIES`（`skill_capabilities.py:24-105`）的 `entity_types` + `metric_types` 三元组：
**2a 同域结构化替代** = `metric_types` 有交集 且 `entity_types` 有交集 且 非自身；
**2b 文档通道** = 承接既有映射表（哪类文档会讨论这类指标）。

| 主技能 (entity / metric) | 2a 结构化替代（按序） | 2b 文档通道（按序） |
|---|---|---|
| **BUSINESS** (company / business) | `INDUSTRY` ⚠️见 4.3 | `REPORT` → `ANNOUNCEMENT` |
| **FINANCE** (company / financial) | `STOCK_SELECTOR` → `INSTITUTIONAL_RESEARCH` | `REPORT` → `ANNOUNCEMENT` |
| **STOCK_SELECTOR** (industry,sector,company / market_share,financial) | `INDUSTRY` → `FINANCE` | `REPORT` |
| **INDUSTRY** (industry,sector,company / industry) | `SECTOR` → `INDUSTRY_CHAIN` | `REPORT` → `NEWS` |
| **INDUSTRY_CHAIN** (industry,sector / industry) | `INDUSTRY` → `SECTOR` | `REPORT` |
| **SECTOR** (industry,sector / industry) | `INDUSTRY` → `INDUSTRY_CHAIN` | `REPORT` → `NEWS` |
| **INDEX** (index,industry,sector / price,industry) | `SECTOR` | `NEWS` |
| **INSTITUTIONAL_RESEARCH** (company,industry,sector / financial,qualitative) | `FINANCE` | `REPORT` |
| **EVENT** (company,industry,sector / event) | — | `NEWS` → `ANNOUNCEMENT` |
| **BASIC_INFO** (company / qualitative) | — | `ANNOUNCEMENT` → `REPORT` |
| **MACRO** (region / macro) | — | `NEWS` |
| **FUTURES** (commodity / price) | — | `NEWS` |
| **REPORT / NEWS / ANNOUNCEMENT** | — | 自身即文档通道，互降级一次即止 |

### 4.2 输入输出与判定

- **输入**：`{main_task, candidate_skills[]}`，每个候选按 `fallback_query_for()` 重新构造 query（保留实体+指标，剥离"从高到低""市盈率 市净率"等结构化措辞——研报检索是关键词召回，沿用原措辞会显著降低召回质量）。
- **输出（命中）**：`ExecutedTask` + `rescued_task_ids.add(main.task_id)`；证据层级取决于命中的是 2a（structured）还是 2b（document）。
- **判定**：与 §3.2 完全相同的有效性判定；**2b 文档通道额外要求** `source_locator`（链接）非空，否则视为无效命中。
- **触发 L3**：候选全部尝试完毕且均未命中。

### 4.3 ⚠️ 跨口径降级的强制标注（重要）

BUSINESS → INDUSTRY 这类降级会**改变口径**（公司口径需求 → 实际取到行业口径数据）。必须：

- 证据打 `caliber="industry_level"`，`notes` 注明"降级自公司口径需求，实取行业口径"；
- §4.1 表中 2a 命中若发生口径变化，`RequirementCoverage.status` **最高只能判 `partial`**（与红线 3 一致，绝不 `supported`）。

### 4.4 护栏

| 护栏 | 取值 | 现有字段 |
|---|---|---|
| L2 候选数上限 | 3（2a ≤2 + 2b ≤2，取前 3） | 新增 `AGENT1_L2_MAX_CANDIDATES` |
| L2 全局调用预算 | ≤15 次/轮 | 现有 `AGENT1_FALLBACK_CALL_BUDGET` |
| 单任务降级深度 | ≤2（整条链 L2+L3 合计 ≤3 次尝试） | 现有 `AGENT1_FALLBACK_MAX_DEPTH` |
| 禁递归 | `task_origin != "main"` 不再降级 | 现有 `executor.py:133` |

---

## 5. L3 联网插件层

### 5.1 Provider 选型（沿用既有选型结论）

| 场景 | Provider | 理由 |
|---|---|---|
| 中文 / 国内主题（默认） | **博查 Web Search API** | 国内服务器处理、中文财经覆盖好、≈3.6 元/千次 |
| 明显涉海外 / 英文主题 | **Tavily** | 国际源覆盖好，可 `include_domains` 锁财经站点 |

判定"涉海外"：研究问题或 `market_scope` 命中非 A 股市场（美股/港股/全球），由 `research_brief.market_scope` 决定。

**已排除**：Deepseek 联网（红狐中转，阻塞 5 分钟、无结构化结果、非官方中转）、Bing（2025-08 退役）、Brave（2026-02 免费档下线）、SearXNG 自托管（反爬导致间歇空结果，运维成本高）。

### 5.2 接入方式（关键：不用改执行器的并发/预算逻辑）

选型文档 §1.1 已确认：新增能力只要**实现 `SkillHubClient` 协议 + 在 catalog 加一行**，就能被现有执行器、超时、预算、hooks、遥测完全接管。

```python
# integrations/websearch/client.py
class WebSearchClient:
    provider_mode = "live"
    async def execute(self, skill_name: SkillName, args: SkillQueryArgs) -> SkillPayload:
        # 内部按 market_scope 路由 bocha / tavily
```

```python
# integrations/skillhub/catalog.py —— endpoint Literal 扩一位 "web_search"
SkillName.WEB_SEARCH: SkillSpec(SkillName.WEB_SEARCH, SkillTier.P1, "web-search", "web_search"),
```

> ⚠️ **不要伪造 `SkillPayload` 的 `trace_id` / `raw_sha256`**——那是问财网关语义。`trace_id` 用本地生成的 64 位 ID，`raw_sha256` 对**本次响应原文**取摘要（保留可复现性），`source_locator` 用结果 URL。

### 5.3 输入输出

| | 内容 |
|---|---|
| **输入** | `{query（改写后，实体+指标关键词）, gap_id, task_id, market_scope, freshness}` |
| **输出** | `WebSearchHit{gap_id, task_id, provider, query, title, url, site_name, snippet, summary, published_at, retrieved_at, source_org, raw_sha256}` |
| **证据层级** | 恒为 `evidence_tier="web_unverified"`，`qualitative_only=True` |
| **必带校验** | `url` 与 `source_org` **缺一不可**；缺失即判该条无效 |

### 5.4 判定条件

有效 = `HTTP 200` AND `hits ≥ 1`（过滤后）AND **通过域名白名单** AND **内容相关性校验**（snippet 至少命中 1 个目标实体或指标词）。

失败即判 L3 失败，**不重试**（避免额度翻倍与延迟叠加）。

### 5.5 触发条件（严格白名单）

只有以下情况进 L3：

- L1 判失败 且 L2 全部候选失败；
- L1/L2 因 `auth_required`/`permission_denied` 被全局熔断跳过（§9.3）；
- ❌ 以下**不进 L3**：`tool_call_blocked`（护栏拦截）、L1 成功、L2 命中、本 task 已调过 L3、单次运行配额耗尽、开关关闭。

---

## 6. 三级全败的兜底处理

| 动作 | 处置 |
|---|---|
| **写缺口** | `DataGap{reason_code="all_tiers_exhausted"}`，`blocking=False`（沿用现状：单次失败不阻断整体） |
| **覆盖率** | `RequirementCoverage.status = "missing"`；`acquisition_level = None`；`degradation_path` 记录三级尝试轨迹 |
| **澄清门** | `criticality="blocking"` 的需求进决策包（`ADVISORY-FRAGMENT-UNAVAILABLE` 现有机制），`advisory` 的随报告披露 |
| **文案** | 「该指标各通道均无数据，已列入研究边界，未编造。」 |
| **绝对红线** | **不补造数值、不用 LLM 记忆填充、不用行业均值代替公司值** |
| **报告呈现** | 研究边界章节列出该项；图表候选因缺数据被 suppress 的写入 `quality_appendix.skipped_chart_notes` |

---

## 7. 降级层级如何传递到前端

### 7.1 数据模型改动（三处，均为可空/有默认值的增量字段）

**① `SkillCallRecord`（`schemas/acquisition.py`）**

```python
acquisition_level: Literal[1, 2, 3] = 1              # 本次调用所处层级
degraded_from_skill: SkillName | None = None          # 从哪个技能降级而来
web_provider: Literal["bocha", "tavily"] | None = None  # 仅 L3
```

**② `EvidenceItem`（`schemas/evidence.py`）**

```python
acquisition_level: Literal[1, 2, 3] = 1   # evidence_tier 保留，两者正交
```

> `evidence_tier` 表达**数据可信度**（structured/document/web_unverified），`acquisition_level` 表达**取到第几级**。两者正交：L2 命中结构化替代技能时 `tier=structured` 但 `level=2`。

**③ `RequirementCoverage`（`schemas/acquisition.py`）**

```python
acquisition_level: Literal[1, 2, 3] | None = None   # 该需求最终数据来源层级；None=全败
degradation_path: list[str] = Field(default_factory=list, max_length=4)
```

### 7.2 阶段产出汇总块（前端唯一读取入口）

在 `StageResult.data["data_fetch"]` 增加：

```json
{
  "acquisition_degradation": {
    "web_fallback_used": true,
    "web_evidence_count": 2,
    "levels_used": { "1": 8, "2": 5, "3": 2 },
    "web_sources": [
      { "title": "…", "url": "…", "site_name": "…", "published_at": "2026-08-30" }
    ],
    "requirements": [
      {
        "question": "新能源汽车海外出口规模及主要出口区域分布？",
        "level": 3,
        "status": "partial",
        "path": ["hithink_business_query", "hithink_industry_query", "report_search", "web_search"]
      }
    ]
  }
}
```

### 7.3 传递链路

```
executor（写 acquisition_level / degraded_from_skill）
  → normalizer（写 evidence_tier + acquisition_level 到每条证据）
  → service（聚合 RequirementCoverage + acquisition_degradation 汇总块）
  → StageResult.data  → workflow state.stage_results["data_fetch"]
  → GET /runs/{run_id}  → 前端 store → 风险提示组件
```

**契约影响**：`contracts/schemas/workflow-state.schema.json` 的 `stageResult` 是 `additionalProperties` 开放的 `data` 字典，新增键**不破坏现有契约**；但需在 `contracts/README.md` 登记该字段，并补一条 `tests/test_contracts.py` 断言。

### 7.4 审核门（可选但建议）

除前端弹窗外，同时挂一条 `RiskNotice`：

```python
RiskNotice(
    risk_code="WEB-SOURCE-UNVERIFIED",
    stage="data_fetch",
    severity=RiskSeverity.HIGH,
    disposition=RiskDisposition.ACKNOWLEDGEMENT_REQUIRED,
    title="部分数据来自公开网络检索",
    detail="同花顺结构化数据与研报/公告通道均无结果，已通过公开网络检索补充 N 条材料，未经权威口径校验。",
    can_override=True,
)
```

作用：让"人工复核"这件事**留痕**（`accepted_risk_codes` 进决策快照），而不只是一次可被关掉的弹窗。

---

## 8. 前端风险提示

### 8.1 触发条件（严格）

```ts
const deg = stageResults.data_fetch?.data?.acquisition_degradation
const shouldWarn = deg?.web_fallback_used === true && (deg?.web_evidence_count ?? 0) > 0
```

**且仅此一条**——L1 命中（`level=1`）与 L2 命中（`level=2`，无论 structured 还是 document）**都不触发**。

### 8.2 触发时机

| 时机 | 行为 |
|---|---|
| `data_fetch` 阶段 `completed` 且 `web_fallback_used=true` | **弹出一次**（主时机，用户即将看到后续分析前先知情） |
| 报告预览 / `report_fusion` 完成后 | 不重复弹；改为报告内固定标注块 |
| 审核门已确认（`accepted_risk_codes` 含 `WEB-SOURCE-UNVERIFIED`） | 不再弹 |
| 同一 `run_id` + `revision` 重复进入页面 | 不重复弹（幂等，见 8.5） |
| 下一轮 `revision`（重新取数） | 重新允许弹一次 |

### 8.3 提示文案

**弹窗标题**：`部分数据来自公开网络，需人工复核`

**正文**：

> 本次研究有 **N 项**数据在同花顺结构化数据与研报/公告通道中均未获取到，系统已通过**公开网络检索**补充相关材料。
>
> 此类数据未经权威口径校验，可能存在**口径不一致、时效滞后或来源不可靠**的情况。报告中引用了这些数据的结论与图表，请务必**人工复核后再对外使用**。

**来源列表**（可折叠，逐条展示 `title / site_name / published_at`，点击跳转 `url`）：

> 补充来源（公开网络检索，非同花顺结构化数据）
> · 《标题》—— 站点名 · 2026-08-30
> · 《标题》—— 站点名 · 2026-09-01

**按钮**：
- 主按钮：`我知道了，稍后复核`
- 次按钮：`查看报告中的引用位置`（滚动定位到首个 `web_unverified` 证据所在章节）

**无具体 URL 时的处理**：L3 判定要求 `url` 必带（§5.3），因此不存在"有证据无来源"的情况；若发生（属缺陷），提示文案降级为：

> 部分数据来源暂时缺失出处信息，已标记为不可用，**不建议引用**。

并同时上报一条 `WEB-EVIDENCE-MISSING-URL` 异常日志。

### 8.4 报告内固定标注（不可关闭）

- 引用了 `web_unverified` 证据的段落，脚注加 **"〔网〕"** 标识（与现有 `〔来源N〕` 体系同构，样式区分）；
- 来源表增加分组标题：**"补充来源（公开网络检索，非同花顺结构化数据）"**；
- 指标数值列 / KPI 卡片**禁止**出现 web 数据（`qualitative_only=True` + `calculations.py:55` 的 `structured` 前置校验已天然拦住，需补一条单测固化）。

### 8.5 幂等实现

```ts
const key = `web-risk-ack:${runId}:${revision}`
if (sessionStorage.getItem(key)) return   // 已提示过，不再弹
sessionStorage.setItem(key, '1')
```

用 `sessionStorage` 而非 `localStorage`：换标签页/新会话重新提示，避免用户长期忽略。

---

## 9. 边界情况处理

### 9.1 超时

| 层 | 超时 | 机制 |
|---|---|---|
| L1 / L2 | `TOOL_TIMEOUT_SECONDS`（现有，默认随配置） | `tool_gateway.py:176` `asyncio.timeout` → `tool_timeout`，`retryable=True` |
| L3 | **`WEB_SEARCH_TIMEOUT_SECONDS = 8s`**（新增独立配置） | 同上；超时即判 L3 失败，**不重试** |
| 单 task 降级总时间盒 | 20s（新增） | 超出则停止后续层级尝试，直接兜底 |
| 整轮 | 沿用 `RuntimePolicy` 的 `max_total_stage_runs` 与 ToolGateway 总预算 | 不变 |

### 9.2 异常分类处置

| 异常 | `error_code` | 重试 | 降级 | 日志级别 |
|---|---|---|---|---|
| 鉴权失败 | `auth_required` (401) | 否 | ⛔ 触发全局熔断（§9.3） | **ERROR**（配置故障） |
| 权限不足 | `permission_denied` (403) | 否 | ⛔ 同上 | **ERROR** |
| 限流 | `rate_limited` (429) | 是（1 次，指数退避） | 重试失败后进 L2 | WARN |
| 对端不可用 | `provider_unavailable` (5xx) | 是 | 同上 | WARN |
| 响应非法 | `invalid_provider_response` / `invalid_tool_payload` | 否 | 直接进 L2 | **ERROR**（接口可能变更） |
| 请求被拒 | `request_rejected` (4xx) | 否 | 直接进 L2 | WARN |
| 护栏拦截 | `tool_call_blocked` | 否 | ❌ **禁止降级** | **ERROR**（安全事件） |
| 工具不存在 / 参数非法 | `tool_not_found` / `tool_arguments_invalid` | 否 | 直接进 L2 | **ERROR**（代码缺陷） |

### 9.3 全局熔断（新增，避免无意义的级联调用）

单轮 run 内任一技能返回 `auth_required` / `permission_denied` 时：

1. 置 `provider_auth_failed = True`；
2. **L2 全部同花顺候选跳过**（同 Key 必然同样失败），直接进 L3；
3. 若 L3 也因配额/鉴权失败 → 置 `web_provider_failed = True`，后续所有 task **不再调 L3**，直接判缺口；
4. 两者同时成立 → 本轮所有剩余需求直接兜底，并在阶段产出一个 `PROVIDER-AUTH-FAILED` 阻塞级风险，**不静默降级**。

### 9.4 预算与配额

| 项 | 上限 | 配置项 |
|---|---|---|
| L2 调用数/轮 | 15 | `AGENT1_FALLBACK_CALL_BUDGET`（现有） |
| L3 调用数/轮 | 20 | `AGENT1_WEB_CALL_BUDGET`（新增） |
| 单 task L3 次数 | 1（不重试） | 硬编码 |
| 月度 provider 配额 | 80% 告警 / 100% 熔断 | 新增计数器 + 告警 |

熔断后：**只记 DataGap，不再调用**，不允许静默失败也不允许超额扣费。

### 9.5 缓存（沿用选型文档 §5.4）

- 缓存键：`sha256(规范化 query + provider + freshness 窗口)`；
- TTL：行情/新闻 30 分钟 → 政策/公告 6 小时 → 研报观点 24 小时 → 静态资料 7 天；
- **负面缓存** 10 分钟（某 query 明确无结果，避免同一轮内重复烧额度）；
- 命中缓存**不消耗 provider 额度、不计入单次运行上限**。

### 9.6 日志与遥测

**必记字段**（结构化，一行一事件）：

```
run_id, task_id, requirement_id, acquisition_level, skill_or_provider,
query_sha256（不落原文）, rows, reason_code, duration_ms, cache_hit,
trace_id, fallback_from, degraded_from_skill
```

**禁止落盘**：API Key、Bearer Token、供应商原始响应全文、用户问句原文。
L3 额外记录：`url` 的**域名**（不落完整 URL 到日志，完整 URL 只进证据）、`snippet` 仅落摘要、`raw_sha256` 用于可复现。

**新增观测指标**：

| 指标 | 定义 | 目标 |
|---|---|---|
| L1 命中率 | L1 直接命中 / 总需求 | 观测 |
| **L2 挽救率** | L2 命中 / 触发 L2 的任务 | **≥ 60%** |
| L3 触发率 | 触发 L3 / 总需求 | ≤ 10% |
| **L3 挽救率** | L3 有效命中 / 触发 L3 | ≥ 50% |
| Web 证据进计算链 | 计数 | **必须为 0**（一票否决） |

### 9.7 并发与幂等

- L1 主任务：`asyncio.Semaphore(4)` 并发（现状不动）；
- 降级调用：串行（现状不动）；
- 同一 `(task_id, candidate_skill)` 不重复调用（用 `attempted` 集合去重）；
- 幂等键：`sha256(run_id + revision + task_id + level)`，重复提交不产生第二次外网调用。

---

## 10. 红线对齐

既有四条红线（来自 doc-channel-fallback §4）全部继承，并在 L3 上逐条加固：

| # | 红线 | L3 上的落地 |
|---|---|---|
| 1 | 证据层级锁死，不可上调 | `evidence_tier="web_unverified"` 永久，任何阶段不得改写为 structured/document |
| 2 | 只补定性，不填数值 | `qualitative_only=True`；`calculations.py:55` 的 `structured` 前置校验天然拦截，补单测固化 |
| 3 | 不计入完整性判定 | 仅 L3 命中的需求 `status` 最高 `partial`，**绝不 `supported`** |
| 4 | 冲突保留 + 可追溯 | `url` + `site_name` + `published_at` + `retrieved_at` 缺一不可；缺失该条判无效 |
| **5（新增）** | **L3 数据必须显式告知用户** | 进入报告的 web 证据**必须**触发前端风险提示（§8）+ 报告内标注，系统不得静默使用 |

> 红线 3 的理由（沿用原方案）：若降级命中算 `supported`，会出现"覆盖率很高、报告全是研报/网页凑的"的假象。**让缺口继续暴露在报告里，比藏在数字后面安全。**

---

## 11. 配置项清单

```bash
# ---- 既有（L2 文档通道，默认关）----
AGENT1_FALLBACK_CHAIN=false            # 建议先置 true
AGENT1_FALLBACK_MAX_DEPTH=2
AGENT1_FALLBACK_CALL_BUDGET=15

# ---- 新增：L2 结构化替代 ----
AGENT1_L2_STRUCTURED_ALTERNATES=true   # 2a 开关，独立于文档通道
AGENT1_L2_MAX_CANDIDATES=3

# ---- 新增：L3 联网插件 ----
AGENT1_WEB_FALLBACK_ENABLED=false      # 默认关，PoC 验证后开
AGENT1_WEB_PROVIDER=bocha              # bocha | tavily（可按 market_scope 自动选）
AGENT1_WEB_API_KEY=                    # 留空即禁用 L3
AGENT1_WEB_CALL_BUDGET=20
AGENT1_WEB_TIMEOUT_SECONDS=8
AGENT1_WEB_DOMAIN_ALLOWLIST=           # 逗号分隔；留空则用内置财经域名白名单
```

**分级开关的意义**：L2 与 L3 可独立启停。建议顺序：**先开 L2 观察挽救率 → 再开 L3**。

---

## 12. 实施步骤与文件清单

| 步骤 | 内容 | 是否动生产代码 |
|---|---|---|
| **S0** | 用例固化：三级降级用例写入 `eval/cases/cascade_fallback.yaml`；评分项注册进 scorer | ❌ 评测层 |
| **S1** | 录制基线快照（record-replay v4） | ❌ |
| **S2** | 单测骨架（红着提交） | ❌ |
| **S3** | Schema：`acquisition_level` / `degraded_from_skill` / `degradation_path` / `WebSearchHit` | ✅ |
| **S4** | L2 候选推导器 `_l2_candidates()`（capability 推导 + 文档通道映射）+ query 构造 | ✅ |
| **S5** | executor 三级编排：`_execute_task` 加 `_rows_usable_precheck`；L2 循环；L3 分支 | ✅ |
| **S6** | `WebSearchClient` + catalog 注册 + `endpoint="web_search"` | ✅ 纯新增 |
| **S7** | normalizer：`acquisition_level` 打标 + `web_unverified` 赋值 + 口径变化标注（§4.3） | ✅ |
| **S8** | service：覆盖率判定 + `acquisition_degradation` 汇总块 + `WEB-SOURCE-UNVERIFIED` 风险通知 | ✅ |
| **S9** | 全局熔断、预算、缓存、遥测 | ✅ |
| **S10** | 契约登记 + `test_contracts.py` 断言 | ✅ |
| **S11** | 前端：提示组件 + 幂等 + 报告内标注 | ✅ |
| **S12** | replay 全量回归 + L4a 全链路 | ❌ |

**文件清单**

| 文件 | 改动 |
|---|---|
| `app/schemas/acquisition.py` | `SkillCallRecord` 三字段；`RequirementCoverage` 两字段；`WebSearchHit` 新增 |
| `app/schemas/evidence.py` | `EvidenceItem.acquisition_level` |
| `app/agents/data_fetcher/executor.py` | 三级编排、可用性预检、熔断 |
| `app/agents/data_fetcher/planner.py` | `_l2_candidates()` 替换/扩展 `_fallback_skills()` |
| `app/agents/data_fetcher/field_relevance.py` | `_rows_usable_precheck()` |
| `app/agents/data_fetcher/normalizer.py` | 层级打标、口径标注 |
| `app/agents/data_fetcher/service.py` | 覆盖率判定、汇总块、风险通知 |
| `app/integrations/websearch/{client,mock,protocol}.py` | **新增** |
| `app/integrations/skillhub/catalog.py` | `WEB_SEARCH` 条目 + endpoint 扩位 |
| `app/core/config.py` | §11 配置项 |
| `app/agents/data_fetcher/routing_telemetry.py` | 层级字段 |
| `contracts/README.md` + `tests/test_contracts.py` | 字段登记与断言 |
| `frontend/src/components/WebSourceRiskDialog.vue` | **新增** |
| `frontend/src/api/types.ts` | `AcquisitionDegradation` 类型 |
| `backend/tests/agents/data_fetcher/test_cascade_fallback.py` | **新增** |

---

## 13. 验证用例

| ID | 构造 | 期望 |
|---|---|---|
| **C-01** | L1 直接命中（如"宁德时代 2025 年营业收入"） | `acquisition_level=1`，**零降级调用**，前端不提示 |
| **C-02** | L1 静默降级行情（BUSINESS 出货量） | 进 L2；2a `INDUSTRY` 命中 → `level=2`、`tier=structured`、**跨口径标注存在**、前端不提示 |
| **C-03** | L1 空 + 2a 失败 + 2b 研报命中 | `level=2`、`tier=document`、`qualitative_only=True`、`status=partial`、前端不提示 |
| **C-04** | L1/L2 全败 + L3 命中 | `level=3`、`tier=web_unverified`、`web_fallback_used=true`、**前端弹提示**、来源可点开 |
| **C-05** | 三级全败 | `status=missing`、缺口文案正确、**无编造数值**、`level=None` |
| **C-06** | `auth_required` | L2 全部跳过（熔断），记 ERROR，不产生无效调用 |
| **C-07** | `tool_call_blocked` | **不触发任何降级**（安全红线） |
| **C-08** | L3 预算设 0 | 只记 DataGap，不调 provider |
| **C-09** | 同一 query 连跑两次 | 第二次缓存命中，`provider_calls` 不增加 |
| **C-10** | web 证据参与计算 | `calculations.py` 拦截，**计算输入中不得出现 web_unverified**（一票否决） |
| **C-11** | 前端幂等 | 同 `(run_id, revision)` 二次进入不重复弹；revision+1 后重新弹 |
| **C-12** | L3 结果缺 `url` | 该条判无效，不进证据；异常日志 `WEB-EVIDENCE-MISSING-URL` |

---

## 14. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| **L2 结构化替代扩大调用量** | ToolGateway 预算压力 | 候选 ≤3、全局 ≤15、仅失败任务触发 |
| **跨口径降级被当同口径用** | 行业数据冒充公司数据 | §4.3 强制 `caliber` 标注 + `status` 封顶 `partial` |
| **L3 数据进了 KPI 数值** | 报告门面数字出错 | 红线 2 + C-10 一票否决单测 |
| **前端提示形同虚设**（用户直接关掉） | 合规留痕缺失 | 同时挂 `WEB-SOURCE-UNVERIFIED` 到决策包（§7.4），需人工确认才能放行 |
| **provider 额度耗尽** | 静默失败或超额扣费 | 80% 告警 / 100% 熔断，熔断后只记 DataGap |
| **联网内容准确性** | 报告出现错误结论 | 只补定性、标注来源、前端强提示、报告内〔网〕标识 |
| **合规（数据出境）** | Tavily 国内交付风险 | 默认博查（境内）；涉海外主题才走 Tavily，可配置禁用 |

**回滚**：L2 与 L3 各自独立 feature flag（§11），关闭后行为与现状完全一致；所有 Schema 新增字段均有默认值，`evidence_tier` / `acquisition_level` 关闭后恒为 `structured` / `1`，前端 `web_fallback_used` 恒为 `false`，提示永不触发。

---

## 15. 一致性声明

- ✅ 一、二级**全部来自同花顺技能**（15 个 `SkillName` 内），第三级才离开同花顺域；
- ✅ 沿用 `evidence_tier` 三态与"单向可降不可升"，**不新增第二套标签体系**；
- ✅ 沿用既有四条红线，新增第 5 条"L3 必须显式告知"；
- ✅ 沿用选型文档的 provider 结论（博查 / Tavily），不重复选型；
- ✅ 新增能力通过实现 `SkillHubClient` 协议接入，不改 executor 的并发/预算机制；
- ✅ 全部新增 Schema 字段有默认值，feature flag 可逐级关闭回滚。
