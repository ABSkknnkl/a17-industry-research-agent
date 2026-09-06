# 智能体1 三层级联降级 + 联网插件 · 最终落地实施方案（含测试）

- 日期：2026-09-06
- 状态：**可执行**（设计定稿 + 测试骨架已随附；生产代码按 §12 顺序落地）
- 前置阅读：`2026-09-04-doc-channel-fallback.md`、`2026-09-04-联网搜索兜底方案选型.md`、`2026-09-05-agent1-three-tier-cascade-fallback.md`（设计稿）
- 实测依据：博查真实 API 验证（2026-09-06，key 已配置），详见 §5.6

> 本文是**最终落地版**：整合了此前两份文档的设计与博查实测结论，给出可直接照做的代码改动、配置与测试。与前稿的差异：L2 从「仅文档通道」扩展为「结构化替代 + 文档通道」；L3 从「博查/Tavily 双选」**定稿为博查默认**；测试骨架随附（`backend/tests/agents/data_fetcher/test_cascade_fallback.py`，红着提交）。

---

## 0. 关键决策表（我做的选择 + 理由）

| # | 决策点 | 选择 | 理由（基于代码/实测证据） |
|---|---|---|---|
| D1 | L2 候选构成 | **结构化替代（2a）优先 → 文档通道（2b）兜底** | 结构化替代（如 BUSINESS 缺出货量 → INDUSTRY）大概率仍是权威结构化数据，比直接掉到研报更可取；候选从 `SKILL_CAPABILITIES` 的 entity/metric 交集推导，非拍脑袋 |
| D2 | L2 命中覆盖率判定 | 最高 `partial`，**绝不 supported**（跨口径降级再强制 `caliber` 标注） | 红线 3；跨口径（公司→行业）若静默当公司数据用，就是 P0-6 静默降级事故重演 |
| D3 | L3 provider | **默认博查**（Tavily 仅海外主题，本版本不实现，留配置位） | 2026-09-06 真实 API 实测：19 条命中全为权威财经源，多源交叉还能纠偏日期；Tavily 中文财经弱 + 数据出境合规风险 |
| D4 | 联网结果信任度 | 证据恒 `evidence_tier="web_unverified"` + `qualitative_only=True`；前端必须弹窗 + 决策包挂 `WEB-SOURCE-UNVERIFIED` 留痕 | 弹窗可关、留痕不可抵赖——“人工复核”才闭环 |
| D5 | 降级层级与证据层级 | `acquisition_level`(1/2/3) 与 `evidence_tier`(structured/document/web_unverified) **正交** | L2 命中结构化替代时 tier=structured 但 level=2，覆盖率仍封顶 partial |
| D6 | 鉴权失败 | **全局熔断**：`auth_required`/`permission_denied` → 跳过全部 L2 同花顺候选，直达 L3/兜底 | 同 Key 必同失败，不做熔断每个失败任务白跑 2-3 次无效降级 |
| D7 | 护栏拦截 | `tool_call_blocked` **禁止任何降级** | 绕过护栏 = 安全事件 |
| D8 | 联网结果新鲜度 | `freshness=oneYear` **必带** | 实测：不过滤会混入 2022/2025 旧闻冒充“最新” |
| D9 | 落地顺序 | **S0 先开现有降级链验证挽救率 → 再 L2 扩展 → 最后 L3** | 1 行配置先拿到真实数据，再决定投入多少代码 |

---

## 1. 三级执行顺序（总览）

```
研究需求（sub-requirement）
   │  路由：metric_registry + SKILL_CAPABILITIES + 语义路由
   ▼
┌─ L1 主技能层（同花顺，与需求最匹配）
│    query 变体 ≤3 条试完（同技能内换措辞）
│    有效 = 无错误 AND rows>0 AND 字段相关 AND 可用性预检
└──────────────┬──────────────────────────────────────┘
               │ 失败 → 且 depth<max 且 有候选 且 预算>0
               ▼
┌─ L2 备选技能层（同花顺域内）
│    2a 结构化替代（capability 推导，≤2 个，同 metric/entity 交集）
│    2b 文档通道（report / announcement / news，≤2 个）
│    串行尝试，任一命中即停；跨口径命中强制 caliber 标注
└──────────────┬──────────────────────────────────────┘
               │ 全部失败 → 且 开关开 且 配额足 且 本 task 未调过
               ▼
┌─ L3 联网插件层（博查，非同花顺）
│    单 task 仅 1 次、不重试、硬超时 8s、freshness=oneYear 必带
│    结果恒为 web_unverified + qualitative_only
└──────────────┬──────────────────────────────────────┘
               │ 仍失败
               ▼
┌─ 兜底：判缺口 missing → DataGap → 澄清门/决策包披露
│    「各通道均无数据，已列入研究边界，未编造」
└──────────────────────────────────────────────────────┘
```

**三条硬约束**：① 单向（L3→L2→L1 反向升级永久禁止）；② 不递归（L2/L3 任务失败不再触发新降级）；③ L1 可并发（semaphore=4），降级调用串行。

---

## 2. L1 主技能层

### 2.1 输入 / 输出

| 项 | 内容 |
|---|---|
| 输入 | `SkillQueryTask{skill_name, query, fallback_queries[≤2], expected_fields, target_entities, tier, research_dimension}` |
| 输出（成功） | `ExecutedTask{record.status="succeeded", payloads}` → `SkillPayload{rows, trace_id, raw_sha256, source_locator}` |
| 输出（失败） | `status ∈ {empty, failed}` + `DataGap{reason_code}` |
| 证据层级 | `evidence_tier="structured"`, `acquisition_level=1` |

### 2.2 有效判定（含新增的可用性预检）

```
有效 ⇔ error_code is None
     AND rows > 0
     AND _fields_relevant(payloads, task)      # 现有：P0-6 字段相关性
     AND _rows_usable_precheck(payloads, task)  # 新增：至少一行含非空业务字段
```

`_rows_usable_precheck` 新增原因：现有判定只看行数 + 字段相关性，识别不出“行存在但目标列全空”的空壳数据。

### 2.3 触发 L2 的规则

| L1 结果 | reason_code | 是否进 L2 | 说明 |
|---|---|---|---|
| 空结果 | `empty_result` | ✅ 立即 | 库里确实没有 |
| 静默降级为行情 | `market_quote_fallback` | ✅ 立即 | **不再换措辞重试**（会拿到更多无关行情，P0-6 回归风险） |
| 可重试错误 | `tool_timeout` / `provider_unavailable` / `rate_limited` | ⚠️ 先同技能重试 1 次，仍失败才进 L2 | 网络抖动不该浪费降级配额 |
| 不可重试错误 | `invalid_tool_payload` / `request_rejected` | ✅ 进 L2 + 记异常日志 | 可能是接口变更，属故障信号 |
| 鉴权/权限 | `auth_required` / `permission_denied` | ⛔ **跳过 L2，直达 L3 或兜底**（§9.3 熔断） | 同 Key 必同失败 |
| 护栏拦截 | `tool_call_blocked` | ❌ **不降级** | 安全红线 |

---

## 3. L2 备选技能层（2a 结构化替代 + 2b 文档通道）

### 3.1 候选推导（从能力边界推导，非拍脑袋）

依据 `SKILL_CAPABILITIES` 的 `entity_types` + `metric_types`：
- **2a 结构化替代** = `metric_types` 有交集 AND `entity_types` 有交集 AND 非自身；
- **2b 文档通道** = 承接既有映射表（哪类文档会讨论这类指标）。

| 主技能 | 2a 结构化替代（按序） | 2b 文档通道（按序） |
|---|---|---|
| **BUSINESS** (company/business) | `INDUSTRY` ⚠️跨口径见 3.3 | `REPORT` → `ANNOUNCEMENT` |
| **FINANCE** (company/financial) | `STOCK_SELECTOR` → `INSTITUTIONAL_RESEARCH` | `REPORT` → `ANNOUNCEMENT` |
| **STOCK_SELECTOR** (market_share,financial) | `INDUSTRY` → `FINANCE` | `REPORT` |
| **INDUSTRY** (industry) | `SECTOR` → `INDUSTRY_CHAIN` | `REPORT` → `NEWS` |
| **INDUSTRY_CHAIN** (industry) | `INDUSTRY` → `SECTOR` | `REPORT` |
| **SECTOR** (industry) | `INDUSTRY` → `INDUSTRY_CHAIN` | `REPORT` → `NEWS` |
| **INDEX** (price,industry) | `SECTOR` | `NEWS` |
| **INSTITUTIONAL_RESEARCH** (financial,qualitative) | `FINANCE` | `REPORT` |
| **EVENT** (event) | — | `NEWS` → `ANNOUNCEMENT` |
| **BASIC_INFO** (qualitative) | — | `ANNOUNCEMENT` → `REPORT` |
| **MACRO** (macro) | — | `NEWS` |
| **FUTURES** (price) | — | `NEWS` |
| **REPORT/NEWS/ANNOUNCEMENT** | — | 互降级一次即止 |

> 实现：新增 `planner._l2_candidates(main_skill) -> list[SkillName]`，返回去重后的 `[2a 结构化替代…, 2b 文档通道…]`，长度 ≤ `AGENT1_L2_MAX_CANDIDATES`（默认 3）。2b 沿用既有 `_fallback_skills()` 映射，不删除（向后兼容）。

### 3.2 输入 / 输出 / 判定

- **输入**：`{main_task, candidate_skills[]}`，每个候选按 `fallback_query_for()` 重构 query（保留实体+指标，剥离结构化措辞）。
- **输出（命中）**：`ExecutedTask` + `rescued_task_ids.add(main.task_id)`。
- **判定**：同 §2.2；**2b 文档通道额外要求 `source_locator`（链接）非空**，否则视为无效命中。
- **触发 L3**：候选全部尝试完毕且均未命中。

### 3.3 ⚠️ 跨口径降级强制标注

BUSINESS → INDUSTRY 这类降级会改变口径（公司需求 → 行业数据）。必须：
- 证据打 `caliber="industry_level"`，`notes` 注明“降级自公司口径需求，实取行业口径”；
- 发生口径变化时，`RequirementCoverage.status` **最高 `partial`**（绝不 `supported`）。

### 3.4 护栏

| 护栏 | 取值 | 配置项 |
|---|---|---|
| L2 候选数上限 | 3（2a ≤2 + 2b ≤2，取前 3） | `AGENT1_L2_MAX_CANDIDATES`（新） |
| L2 全局调用预算 | ≤15 次/轮 | `AGENT1_FALLBACK_CALL_BUDGET`（现有） |
| 单任务降级深度 | ≤2 | `AGENT1_FALLBACK_MAX_DEPTH`（现有） |
| 禁递归 | `task_origin != "main"` 不再降级 | 现有 `executor.py:133` |

---

## 4. L3 联网插件层（博查）

### 4.1 选型定稿

| 场景 | Provider | 说明 |
|---|---|---|
| 默认（中文/国内） | **博查 Web Search API** | 实测合格（§5.6）；国内服务器、中文财经覆盖好、≈3.6 元/千次 |
| 海外/英文主题 | Tavily | **本版本不实现**，仅留 `AGENT1_WEB_PROVIDER=tavily` 配置位，后续按需接入 |

**已排除**（沿用选型文档 + 实测）：Deepseek 红狐中转（阻塞 5 分钟、非官方）、Bing（已退役）、Brave（免费档下线）、SearXNG 自托管（反爬间歇空结果）、web-composite-search 技能（实测查“新能源汽车出口”返回汉字字典，质量灾难）。

### 4.2 接入方式（不改执行器并发/预算逻辑）

新增 `WebSearchClient`，实现 `SkillHubClient` 协议（`provider_mode` + `async execute(skill_name, args)`），在 catalog 加一行注册进 `create_skillhub_gateway()`，自动获得超时、预算、hooks、遥测。

```python
# app/integrations/websearch/client.py
class WebSearchClient:
    provider_mode = "live"

    def __init__(self, *, api_key: str | None, base_url: str = "https://api.bocha.ai",
                 timeout_seconds: float = 8, sleep=asyncio.sleep, max_retries: int = 0):
        ...

    async def execute(self, skill_name: SkillName, args: SkillQueryArgs) -> SkillPayload:
        # POST {base}/v1/web-search  body: {query, freshness:"oneYear", count, summary:true}
        # 返回 SkillPayload（rows 为清洗后的搜索命中）
```

```python
# app/integrations/skillhub/catalog.py
SkillName.WEB_SEARCH: SkillSpec(SkillName.WEB_SEARCH, SkillTier.P1, "web-search", "web_search"),
# endpoint Literal 需扩一位 "web_search"
```

> ⚠️ **不要伪造 `SkillPayload.trace_id` / `raw_sha256` 的问财语义**：`trace_id` 用本地 `secrets.token_hex(32)`；`raw_sha256` 对本次响应原文取摘要（保留可复现性）；`source_locator` 用结果 URL。

### 4.3 输入 / 输出

| 项 | 内容 |
|---|---|
| 输入 | `{query（实体+指标关键词改写）, gap_id, task_id, freshness="oneYear", count=10, summary=true}` |
| 输出 | `SkillPayload.rows = [{title, url, site_name, snippet, summary, published_at, retrieved_at, source_org}, …]` |
| 证据层级 | 恒 `evidence_tier="web_unverified"`, `acquisition_level=3`, `qualitative_only=True` |
| 必带校验 | `url` 与 `source_org` **缺一不可**，缺失该条判无效（记 `WEB-EVIDENCE-MISSING-URL`） |

### 4.4 判定条件

```
有效 = HTTP 200
     AND hits ≥ 1（过滤后）
     AND 域名在白名单（财经/权威源，可配置）
     AND 内容相关性（snippet/summary 命中 ≥1 个目标实体或指标词）
```

失败即判 L3 失败，**不重试**（避免额度翻倍与延迟叠加）。

### 4.5 触发条件（严格白名单）

只有以下情况进 L3：
- L1 判失败 且 L2 全部候选失败；
- L1/L2 因 `auth_required`/`permission_denied` 被全局熔断跳过；
- ❌ 以下**不进 L3**：`tool_call_blocked`、L1 成功、L2 命中、本 task 已调过 L3、单次运行配额耗尽、`AGENT1_WEB_FALLBACK_ENABLED=false`。

### 4.6 博查实测结论（2026-09-06 真实 API，3 组查询 19 条）

| 查询 | 命中质量 | 关键发现 |
|---|---|---|
| 钠离子电池 2026Q4 量产 | 4 高质量 + 4 旧闻噪音 | **不过滤会混入 2022/2025 旧闻** → `freshness=oneYear` 必带 |
| 麒麟凝聚态 350Wh/kg | 6/6 高质量（官方+证券时报+经济观察…） | `summary` 字段含关键数值，**搜索阶段即可提取大部分数据点，无需二次抓正文** |
| 海博思创 60GWh 订单 | 5/5 高质量（界面/证券时报/网易/新浪/腾讯 同日一致） | **多源交叉能纠偏单源日期漂移**（摘录写 06-24，实际 04-27） |

**两个坑（已在代码规避）**：① `totalResults=10000000` 是博查**固定假值**，不得用于覆盖率判定；② 必须带 `freshness=oneYear` 防旧闻。

---

## 5. 三级全败的兜底处理

| 动作 | 处置 |
|---|---|
| 写缺口 | `DataGap{reason_code="all_tiers_exhausted", blocking=False}` |
| 覆盖率 | `status="missing"`；`acquisition_level=None`；`degradation_path` 记录三级尝试轨迹 |
| 澄清门 | `criticality="blocking"` 需求进决策包（现有 `ADVISORY-FRAGMENT-UNAVAILABLE` 机制） |
| 文案 | 「该指标各通道均无数据，已列入研究边界，未编造。」 |
| 绝对红线 | **不补造数值、不用 LLM 记忆填充、不用行业均值代替公司值** |
| 报告呈现 | 研究边界章节列出；因缺数据被 suppress 的图表写入 `quality_appendix.skipped_chart_notes` |

---

## 6. 降级层级如何传递到前端

### 6.1 数据模型改动（三处，均为可空/有默认值的增量字段）

**① `SkillCallRecord`（`schemas/acquisition.py`）**

```python
acquisition_level: Literal[1, 2, 3] = 1
degraded_from_skill: SkillName | None = None
web_provider: Literal["bocha", "tavily"] | None = None
```

**② `EvidenceItem`（`schemas/evidence.py`）**

```python
acquisition_level: Literal[1, 2, 3] = 1
```

> `evidence_tier`（数据可信度）与 `acquisition_level`（取到第几级）正交：L2 命中结构化替代时 `tier=structured` 但 `level=2`。

**③ `RequirementCoverage`（`schemas/acquisition.py`）**

```python
acquisition_level: Literal[1, 2, 3] | None = None
degradation_path: list[str] = Field(default_factory=list, max_length=4)
```

### 6.2 阶段产出汇总块（前端唯一读取入口）

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
        "question": "…",
        "level": 3,
        "status": "partial",
        "path": ["hithink_business_query", "hithink_industry_query", "report_search", "web_search"]
      }
    ]
  }
}
```

### 6.3 传递链路

```
executor（写 acquisition_level / degraded_from_skill）
  → normalizer（写 evidence_tier + acquisition_level + 口径标注）
  → service（聚合 RequirementCoverage + acquisition_degradation 汇总块）
  → StageResult.data → workflow state.stage_results["data_fetch"]
  → GET /runs/{run_id} → 前端 store → 风险提示组件
```

**契约影响**：`stageResult.data` 是开放字典，新增键不破坏现有契约；但需在 `contracts/README.md` 登记，并补 `tests/test_contracts.py` 断言。

### 6.4 决策包留痕（建议同时挂）

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

---

## 7. 前端风险提示

### 7.1 触发条件（严格）

```ts
const deg = stageResults.data_fetch?.data?.acquisition_degradation
const shouldWarn = deg?.web_fallback_used === true && (deg?.web_evidence_count ?? 0) > 0
```

**且仅此一条**——L1（level=1）与 L2（level=2，无论 structured 还是 document）**都不触发**。

### 7.2 触发时机

| 时机 | 行为 |
|---|---|
| `data_fetch` 阶段 completed 且 `web_fallback_used=true` | **弹出一次**（主时机） |
| 报告预览 / report_fusion 完成后 | 不重复弹；改为报告内固定标注块 |
| 审核门已确认（`accepted_risk_codes` 含 `WEB-SOURCE-UNVERIFIED`） | 不再弹 |
| 同一 `run_id`+`revision` 重复进入页面 | 不重复弹（幂等，sessionStorage） |
| 下一轮 `revision`（重新取数） | 重新允许弹一次 |

### 7.3 提示文案

**标题**：`部分数据来自公开网络，需人工复核`

**正文**：

> 本次研究有 **N 项**数据在同花顺结构化数据与研报/公告通道中均未获取到，系统已通过**公开网络检索**补充相关材料。
>
> 此类数据未经权威口径校验，可能存在**口径不一致、时效滞后或来源不可靠**的情况。报告中引用了这些数据的结论与图表，请务必**人工复核后再对外使用**。

**来源列表**（可折叠，逐条展示 `title / site_name / published_at`，点击跳转 `url`）：

> 补充来源（公开网络检索，非同花顺结构化数据）
> · 《标题》—— 站点名 · 2026-08-30

**按钮**：主 `我知道了，稍后复核`；次 `查看报告中的引用位置`（滚动定位到首个 web_unverified 证据所在章节）。

**异常兜底文案**（web 证据缺 URL，属缺陷）：

> 部分数据来源暂时缺失出处信息，已标记为不可用，**不建议引用**。

并同时上报 `WEB-EVIDENCE-MISSING-URL` 异常日志。

### 7.4 报告内固定标注（不可关闭）

- 引用 `web_unverified` 证据的段落，脚注加 **"〔网〕"** 标识；
- 来源表增加分组：**"补充来源（公开网络检索，非同花顺结构化数据）"**；
- 指标数值列 / KPI 卡片**禁止**出现 web 数据（`qualitative_only=True` + `calculations.py:55` 的 `structured` 前置校验已天然拦住，需补单测固化）。

### 7.5 幂等实现

```ts
const key = `web-risk-ack:${runId}:${revision}`
if (sessionStorage.getItem(key)) return
sessionStorage.setItem(key, '1')
```

用 `sessionStorage` 而非 `localStorage`：换标签页/新会话重新提示，避免长期忽略。

---

## 8. 边界情况处理

### 8.1 超时

| 层 | 超时 | 机制 |
|---|---|---|
| L1 / L2 | `TOOL_TIMEOUT_SECONDS`（现有） | `tool_gateway.py` `asyncio.timeout` → `tool_timeout`，`retryable=True` |
| L3 | **`WEB_SEARCH_TIMEOUT_SECONDS = 8s`**（新增） | 同上；超时即判 L3 失败，**不重试** |
| 单 task 降级总时间盒 | 20s（新增 `AGENT1_DEGRADATION_TIME_BUDGET`） | 超出停止后续层级，直接兜底 |
| 整轮 | 沿用 `RuntimePolicy.max_total_stage_runs` + ToolGateway 总预算 | 不变 |

### 8.2 异常分类处置

| 异常 | error_code | 重试 | 降级 | 日志级别 |
|---|---|---|---|---|
| 鉴权失败 | `auth_required` (401) | 否 | ⛔ 触发全局熔断（§9.3） | **ERROR** |
| 权限不足 | `permission_denied` (403) | 否 | ⛔ 同上 | **ERROR** |
| 限流 | `rate_limited` (429) | 是（1 次，指数退避） | 重试失败后进 L2 | WARN |
| 对端不可用 | `provider_unavailable` (5xx) | 是 | 同上 | WARN |
| 响应非法 | `invalid_provider_response` / `invalid_tool_payload` | 否 | 直接进 L2 | **ERROR**（接口可能变更） |
| 请求被拒 | `request_rejected` (4xx) | 否 | 直接进 L2 | WARN |
| 护栏拦截 | `tool_call_blocked` | 否 | ❌ **禁止降级** | **ERROR**（安全事件） |
| 工具不存在/参数非法 | `tool_not_found` / `tool_arguments_invalid` | 否 | 直接进 L2 | **ERROR**（代码缺陷） |

### 8.3 全局熔断

单轮 run 内任一技能返回 `auth_required` / `permission_denied`：
1. 置 `provider_auth_failed = True`；
2. **L2 全部同花顺候选跳过**，直接进 L3；
3. 若 L3 也因配额/鉴权失败 → 置 `web_provider_failed = True`，后续所有 task **不再调 L3**，直接判缺口；
4. 两者同时成立 → 本轮所有剩余需求直接兜底，并在阶段产出 `PROVIDER-AUTH-FAILED` 阻塞级风险，**不静默降级**。

### 8.4 预算与配额

| 项 | 上限 | 配置项 |
|---|---|---|
| L2 调用数/轮 | 15 | `AGENT1_FALLBACK_CALL_BUDGET`（现有） |
| L3 调用数/轮 | 20 | `AGENT1_WEB_CALL_BUDGET`（新） |
| 单 task L3 次数 | 1（不重试） | 硬编码 |
| 月度 provider 配额 | 80% 告警 / 100% 熔断 | 新增计数器 + 告警 |

熔断后：**只记 DataGap，不再调用**，不允许静默失败也不允许超额扣费。

### 8.5 缓存（沿用选型文档）

- 缓存键：`sha256(规范化 query + provider + freshness 窗口)`；
- TTL：行情/新闻 30 分钟 → 政策/公告 6 小时 → 研报观点 24 小时 → 静态资料 7 天；
- **负面缓存** 10 分钟；
- 命中缓存**不消耗 provider 额度、不计入单次运行上限**。

### 8.6 日志与遥测

**必记字段**（结构化，一行一事件）：

```
run_id, task_id, requirement_id, acquisition_level, skill_or_provider,
query_sha256（不落原文）, rows, reason_code, duration_ms, cache_hit,
trace_id, fallback_from, degraded_from_skill
```

**禁止落盘**：API Key、Bearer Token、供应商原始响应全文、用户问句原文。
L3 额外记录：`url` 域名（不落完整 URL 到日志）、`snippet` 仅摘要、`raw_sha256` 用于可复现。

**新增观测指标**：

| 指标 | 定义 | 目标 |
|---|---|---|
| L1 命中率 | L1 直接命中 / 总需求 | 观测 |
| **L2 挽救率** | L2 命中 / 触发 L2 | **≥ 60%** |
| L3 触发率 | 触发 L3 / 总需求 | ≤ 10% |
| **L3 挽救率** | L3 有效命中 / 触发 L3 | ≥ 50% |
| Web 证据进计算链 | 计数 | **必须为 0**（一票否决） |

### 8.7 并发与幂等

- L1：`asyncio.Semaphore(4)` 并发（现状不动）；
- 降级调用：串行（现状不动）；
- 同一 `(task_id, candidate_skill)` 不重复调用（`attempted` 集合去重）；
- 幂等键：`sha256(run_id + revision + task_id + level)`。

---

## 9. 红线对齐（原 4 条 + 新增第 5 条）

| # | 红线 | L3 上的落地 |
|---|---|---|
| 1 | 证据层级锁死，不可上调 | `evidence_tier="web_unverified"` 永久，任何阶段不得改写为 structured/document |
| 2 | 只补定性，不填数值 | `qualitative_only=True`；`calculations.py:55` 前置校验天然拦截，补单测固化 |
| 3 | 不计入完整性判定 | 仅 L3 命中的需求 `status` 最高 `partial`，**绝不 `supported`** |
| 4 | 冲突保留 + 可追溯 | `url` + `site_name` + `published_at` + `retrieved_at` 缺一不可 |
| **5（新增）** | **L3 数据必须显式告知用户** | 进入报告的 web 证据**必须**触发前端提示（§7）+ 报告内标注，系统不得静默使用 |

---

## 10. 配置项清单

```bash
# ---- 既有（L2 文档通道，默认关）----
AGENT1_FALLBACK_CHAIN=false            # 建议先置 true
AGENT1_FALLBACK_MAX_DEPTH=2
AGENT1_FALLBACK_CALL_BUDGET=15

# ---- 新增：L2 结构化替代 ----
AGENT1_L2_STRUCTURED_ALTERNATES=true
AGENT1_L2_MAX_CANDIDATES=3

# ---- 新增：L3 联网插件 ----
AGENT1_WEB_FALLBACK_ENABLED=false      # 默认关，PoC 验证后开
AGENT1_WEB_PROVIDER=bocha              # bocha | tavily（本版仅 bocha 可用）
AGENT1_BOCHA_API_KEY=                  # 留空即禁用 L3
AGENT1_WEB_CALL_BUDGET=20
AGENT1_WEB_TIMEOUT_SECONDS=8
AGENT1_WEB_DOMAIN_ALLOWLIST=           # 逗号分隔；留空用内置财经域名白名单
AGENT1_DEGRADATION_TIME_BUDGET=20      # 单 task 降级总时间盒（秒）
```

**分级开关的意义**：L2 与 L3 可独立启停。建议顺序：**先开 L2 观察挽救率 → 再开 L3**。

---

## 11. 测试方案（含可运行骨架）

### 11.1 测试文件

`backend/tests/agents/data_fetcher/test_cascade_fallback.py`（**红着提交**——在生产代码落地前运行必然失败，落地后应转绿）。

骨架特点：
- 用 `pytest.importorskip` 保护尚未实现的 `app.integrations.websearch.client`，使骨架在未实现时被跳过而不是报错（避免拖垮整个测试集）；
- 已实现部分（L2 结构化替代候选推导、跨口径标注、覆盖率封顶）直接断言；
- L3 相关用例标注 `@pytest.mark.skip(reason="await WebSearchClient (S6)")`。

### 11.2 测试用例矩阵

| ID | 构造 | 期望 | 实现期 |
|---|---|---|---|
| **C-01** | L1 直接命中 | `acquisition_level=1`，零降级调用，前端不提示 | S5 |
| **C-02** | L1 静默降级行情（BUSINESS 出货量）→ 2a `INDUSTRY` 命中 | `level=2`、`tier=structured`、**跨口径标注存在**、`status=partial`、前端不提示 | S4/S5 |
| **C-03** | L1 空 + 2a 失败 + 2b 研报命中 | `level=2`、`tier=document`、`qualitative_only=True`、`status=partial`、前端不提示 | S5 |
| **C-04** | L1/L2 全败 + L3 命中 | `level=3`、`tier=web_unverified`、`web_fallback_used=true`、**前端弹提示** | S6/S8 |
| **C-05** | 三级全败 | `status=missing`、缺口文案正确、**无编造数值**、`level=None` | S5/S6 |
| **C-06** | `auth_required` | L2 全部跳过（熔断），记 ERROR，不产生无效调用 | S9 |
| **C-07** | `tool_call_blocked` | **不触发任何降级**（安全红线） | S9 |
| **C-08** | L3 预算设 0 | 只记 DataGap，不调 provider | S9 |
| **C-09** | 同 query 连跑两次 | 第二次缓存命中，`provider_calls` 不增加 | S9 |
| **C-10** | web 证据参与计算 | `calculations.py` 拦截，**计算输入中不得出现 web_unverified**（一票否决） | S8 |
| **C-11** | 前端幂等 | 同 `(run_id, revision)` 二次进入不重复弹；revision+1 重新弹 | S11 |
| **C-12** | L3 结果缺 `url` | 该条判无效，不进证据；异常日志 `WEB-EVIDENCE-MISSING-URL` | S6 |
| **C-13** | L2 跨口径命中覆盖率封顶 | `status == "partial"` 且 **绝不 supported**（红线 3） | S5 |
| **C-14** | `freshness` 必带 | L3 发出的请求体含 `freshness=oneYear` | S6 |

### 11.3 评分项注册（沿用 V8 fail-closed 自检）

| # | 判定项 | 检查点 |
|---|---|---|
| **FB1** | 降级仅在主技能失败后触发 | 主技能成功的任务 `acquisition_level == 1` |
| **FB2** | 降级证据层级正确 | 2b 命中 `tier="document"`；L3 命中 `tier="web_unverified"` |
| **FB3** | 降级不冒充完整性 | 仅降级命中的需求 `status` 不得为 `supported` |
| **FB4** | 降级不污染计算 | `document`/`web_unverified` 层不出现在 `calculated_metrics` 输入中 |
| **FB5** | 降级留痕完整 | `fallback_from`/`degraded_from_skill`/`degradation_path` 非空且可关联主任务 |
| **FB6** | 跨口径降级标注 | 口径变化证据 `caliber` 正确 + `notes` 含降级说明 |

按 V8 §4.7 要求注册进 scorer 并通过 F0-07 自检，未注册项判失败而非静默通过。

---

## 12. 实施顺序与文件清单

| 步骤 | 内容 | 动生产代码 | 门禁 |
|---|---|---|---|
| **S0** | 开 `AGENT1_FALLBACK_CHAIN=true` 验证现有 L2 挽救率 | 仅 `.env` | 真实 run 拿到 rescued_task_ids |
| **S1** | 录制基线快照（record-replay v4） | ❌ | 快照落盘 |
| **S2** | 测试骨架 `test_cascade_fallback.py`（红着提交） | ❌ | 运行确认按预期失败/跳过 |
| **S3** | Schema：`acquisition_level` / `degraded_from_skill` / `degradation_path` / `EvidenceItem.acquisition_level` | ✅ | 既有 acquisition 单测通过 |
| **S4** | `planner._l2_candidates()` 推导器（结构化优先） | ✅ | S2 中 C-02 相关断言开始转绿 |
| **S5** | executor 三级编排：`_rows_usable_precheck` + L2 循环扩展 + 跨口径标注 | ✅ | C-01/02/03/05/13 转绿 |
| **S6** | `WebSearchClient` + catalog `WEB_SEARCH` + `endpoint="web_search"` | ✅ 纯新增 | C-04/08/12/14 转绿 |
| **S7** | normalizer：`acquisition_level` 打标 + `web_unverified` 赋值 + 口径标注 | ✅ | FB2/FB6 通过 |
| **S8** | service：覆盖率判定 + `acquisition_degradation` 汇总块 + `WEB-SOURCE-UNVERIFIED` 风险通知 | ✅ | C-04/C-10/FB3/FB4 |
| **S9** | 全局熔断、预算、缓存、遥测 | ✅ | C-06/07/08/09 |
| **S10** | 契约登记 + `test_contracts.py` 断言 | ✅ | 契约断言通过 |
| **S11** | 前端：提示组件 + 幂等 + 报告内标注 | ✅ | C-11 |
| **S12** | replay 全量回归 + L4a 全链路 | ❌ | 量化目标达成 |

**文件清单**

| 文件 | 改动 |
|---|---|
| `app/schemas/acquisition.py` | `SkillCallRecord` 三字段；`RequirementCoverage` 两字段 |
| `app/schemas/evidence.py` | `EvidenceItem.acquisition_level` |
| `app/agents/data_fetcher/executor.py` | 三级编排、可用性预检、熔断 |
| `app/agents/data_fetcher/planner.py` | `_l2_candidates()` 替换/扩展 `_fallback_skills()` |
| `app/agents/data_fetcher/field_relevance.py` | `_rows_usable_precheck()` |
| `app/agents/data_fetcher/normalizer.py` | 层级打标、口径标注 |
| `app/agents/data_fetcher/service.py` | 覆盖率判定、汇总块、风险通知 |
| `app/integrations/websearch/{client,mock,protocol}.py` | **新增** |
| `app/integrations/skillhub/catalog.py` | `WEB_SEARCH` 条目 + endpoint 扩位 |
| `app/core/config.py` | §10 配置项 |
| `app/agents/data_fetcher/routing_telemetry.py` | 层级字段 |
| `contracts/README.md` + `backend/tests/test_contracts.py` | 字段登记与断言 |
| `frontend/src/components/WebSourceRiskDialog.vue` | **新增** |
| `frontend/src/api/types.ts` | `AcquisitionDegradation` 类型 |
| `backend/tests/agents/data_fetcher/test_cascade_fallback.py` | **新增**（本方案随附） |

---

## 13. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| L2 结构化替代扩大调用量 | ToolGateway 预算压力 | 候选 ≤3、全局 ≤15、仅失败任务触发 |
| 跨口径降级被当同口径用 | 行业数据冒充公司数据 | §3.3 强制 `caliber` 标注 + `status` 封顶 `partial` |
| L3 数据进了 KPI 数值 | 报告门面数字出错 | 红线 2 + C-10 一票否决单测 |
| 前端提示形同虚设 | 合规留痕缺失 | 同时挂 `WEB-SOURCE-UNVERIFIED` 到决策包（§6.4） |
| provider 额度耗尽 | 静默失败或超额扣费 | 80% 告警 / 100% 熔断，熔断后只记 DataGap |
| 联网内容准确性 | 报告出现错误结论 | 只补定性、标注来源、前端强提示、报告内〔网〕标识 |
| 合规（数据出境） | Tavily 国内交付风险 | 默认博查（境内）；Tavily 本版不启用 |
| 博查 key 泄漏 | 滥用扣费 | key 仅存 `backend/.env`（gitignored）；日志不落 key |

**回滚**：L2 与 L3 各自独立 feature flag（§10），关闭后行为与现状完全一致；所有 Schema 新增字段均有默认值，`evidence_tier`/`acquisition_level` 关闭后恒为 `structured`/`1`，前端 `web_fallback_used` 恒为 `false`，提示永不触发。

---

## 14. 一致性声明

- ✅ 一、二级**全部来自同花顺技能**（15 个 `SkillName` 内），第三级才离开同花顺域；
- ✅ 沿用 `evidence_tier` 三态与"单向可降不可升"，**不新增第二套标签体系**；
- ✅ 沿用既有四条红线，新增第 5 条"L3 必须显式告知"；
- ✅ 沿用选型文档 provider 结论，博查经真实 API 实测定稿（§4.6）；
- ✅ 新增能力通过实现 `SkillHubClient` 协议接入，不改 executor 的并发/预算机制；
- ✅ 全部新增 Schema 字段有默认值，feature flag 可逐级关闭回滚；
- ✅ 测试骨架随附（S2），先红后绿，生产代码按 §12 顺序落地。
