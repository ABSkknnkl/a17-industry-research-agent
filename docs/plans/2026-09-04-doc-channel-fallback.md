# 文档通道降级链：结构化取数失败时自动回补研报/公告/新闻

- 日期：2026-09-04
- 状态：已定稿 · 生产代码已实现（变更说明/映射表/回滚/运维观测见 [../DATA_FALLBACK_RELEASE_NOTES.md](../DATA_FALLBACK_RELEASE_NOTES.md)；§6–§8 评测/TDD 环节不在本次纯开发交付内）
- 范围：`backend/app/agents/data_fetcher/`（executor / planner / normalizer / service）+ 评测集
- 前置：不新增任何数据源、不接联网搜索、不改 SQLite
- 关联：[2026-09-01-agent1-semantic-first-arbitration.md](2026-09-01-agent1-semantic-first-arbitration.md)（四刀仲裁，独立交付，互不阻塞）

---

## 0. 一句话结论

**你手上缺的不是新数据源，是"降级"这一级调度。** 问财 15 技能里 `report_search` / `announcement_search` / `news_search` 三个定性通道早已存在，但结构化技能查不到时系统**直接判缺口，从未去取**。实测 `report_search "隆基绿能 组件出货量"` 返回 10 条研报命中——数据在手边，只是没调用。

本方案新增**跨技能降级链**：结构化技能失败 → 自动回补文档通道 → 证据标 `document` 层级、只补定性、不计入完整性判定、全程可追溯。**零新增依赖、零新增合规风险、零证据层级改造。**

---

## 1. 缺口定位：失败在哪一级

先摆清楚现在的执行链，以及它在哪里断掉。

### 1.1 当前链路（实测代码路径）

```
planner.build()  生成 SkillQueryTask{skill_name, query, fallback_queries[]}
        │
        ▼
executor._execute_task()   executor.py:87-169
        │  query_candidates = [task.query, *task.fallback_queries]
        │  注意：全部用同一个 task.skill_name —— 只有 query 变体，无技能维度
        │  成功判定：executor.py:134  if any(payload.rows for payload in payloads): break
        ▼
normalizer      P0-6 _field_relevance_check（normalizer.py:264 调用 / :593 定义）
        │  检出 market_quote_fallback → 行全部隔离 + 写 DataGap
        ▼
service._mark_market_quote_fallback_gaps()   service.py:1078
        │  受影响需求 supported → partial
        ▼
    判缺口，结束        ←── 断在这里：不再去文档通道取
```

### 1.2 断点的确切位置

`SkillQueryTask`（`app/schemas/acquisition.py:81`）：

```python
fallback_queries: list[str] = Field(default_factory=list, max_length=2)
```

**只有 query 字符串，没有技能维度。** 这是缺口的代码级证据——`_fallback_queries()`（`planner.py:1375-1416`）生成的也全是同技能内的措辞变体，例如：

```python
SkillName.FINANCE: [
    query,
    f"{industry_topic} 经营活动现金流量净额 总资产 负债合计",
],
```

即：**换措辞重试，不换通道。** 所以一旦问财某个结构化域没有该指标，重试多少次都是空。

### 1.3 两类失败，当前都不降级

| 失败类型           | 实例                                                          | 当前行为                       | 文档通道能否救           |
| -------------- | ----------------------------------------------------------- | -------------------------- | ----------------- |
| **A. 零行**      | `hithink_basicinfo_query "隆基绿能产能"` → 0 行                    | DataGap，判缺口                | ✅ 大概率能            |
| **B. 静默降级为行情** | `hithink_business_query "隆基绿能组件出货量"` → 1 行，列为 `最新价/涨跌幅/成交量` | P0-6 检出 → 隔离 → DataGap，判缺口 | ✅ **实测 10 条研报命中** |

B 类是最痛的：系统明明已经识别出"结构化通道给不了这个数"（`market_quote_fallback` 信号），却把这个信号**只用于披露，不用于补救**。

### 1.4 实测收益证据

| 探测                                   | 返回             |
| ------------------------------------ | -------------- |
| `hithink_business_query "隆基绿能组件出货量"` | 1 行行情字段（静默降级）  |
| `hithink_business_query "隆基绿能 销量"`   | 1 行行情字段（静默降级）  |
| `hithink_basicinfo_query "隆基绿能产能"`   | 0 行            |
| **`report_search "隆基绿能 组件出货量"`**     | **10 条研报命中** ✅ |
| `report_search "隆基绿能 产能利用率"`         | 定性素材可召回 ✅      |

61 条压测里的 13 项"真数据缺口"（产销率、良率、自给率、单瓦成本、单位扩产成本、进口依赖度……）中，相当一部分走研报/公告通道**能捞到定性素材**——现在它们被**判早了**。

> 需要说清楚：降级链**不能把这些变成可信数值**。它能做的是把"完全没数据"变成"有机构定性观点 + 明确标注非权威口径"，报告的研究边界因此更实。

---

## 2. 核心设计：字段校验前移，一次覆盖两类失败

### 2.1 关键决策

把 P0-6 的字段相关性校验**前移进 executor 的成功判定**。

现在 executor 认为"有行即成功"（`executor.py:134`），所以静默降级（有 1 行行情数据）会被判定为成功、直接 break，根本走不到 fallback。改成：

```python
# executor.py:134  现状
if any(payload.rows for payload in payloads):
    break

# 改后：有行 且 字段相关 才算成功
if payloads and _field_relevance_ok(payloads, task):
    break
```

**一次改动，同时把 A（零行）和 B（静默降级）两类失败并入同一条 fallback 路径**——不需要在 service 层做第二波异步编排。这是本方案最关键的一处简化。

### 2.2 循环依赖必须先拆（硬性前置）

`normalizer.py:12` 已经存在：

```python
from app.agents.data_fetcher.executor import ExecutedTask
```

即 **normalizer → executor**。若 executor 反过来 `from ...normalizer import _field_relevance_check`，立即成环。

**解法**：把 `_field_relevance_check` 及其词表从 `normalizer.py` 抽到新模块 `app/agents/data_fetcher/field_relevance.py`，两处都从新模块 import：

```
field_relevance.py   ← 新模块，无内部依赖
        ↑                    ↑
   executor.py          normalizer.py（改 import 路径，函数签名不变）
```

- 函数签名**保持不变**，现有 6 个 P0-6 单测（`backend/tests/agents/data_fetcher/test_p06_field_relevance.py`）零改动通过；
- 禁止用"函数内延迟 import"绕过——pytest mock 该模块时会失效。

### 2.3 Schema 改动

`SkillQueryTask` 新增**降级技能链**字段（与现有 `fallback_queries` 并存，职责分离）：

```python
# app/schemas/acquisition.py  SkillQueryTask
fallback_skills: list[SkillName] = Field(default_factory=list, max_length=2)
```

语义：**仅当本技能全部 query 变体均无有效数据时，才按序尝试这些技能。** 与主 query 是严格的串行降级关系，不是并行。

配套在 `SkillCallRecord` 加降级留痕：

```python
fallback_from: str | None = Field(default=None, max_length=64)   # 触发降级的主任务 task_id
fallback_depth: int = Field(default=0, ge=0, le=2)               # 0=主调用, 1/2=降级层级
```

---

## 3. 降级映射表（按能力边界推导，非拍脑袋）

映射依据 = `SKILL_CAPABILITIES`（`skill_capabilities.py`）里的 `entity_types` + `metric_types` + `qualitative` 三元组，以及"哪类文档会讨论这类指标"：

| 主技能（结构化）                                 | 降级链（按序）                   | 推导依据                         |
| ---------------------------------------- | ------------------------- | ---------------------------- |
| **BUSINESS**（公司经营/出货量/产能）                | `REPORT` → `ANNOUNCEMENT` | 出货量/产能/扩产写进券商研报与公司扩产公告       |
| **FINANCE**（公司财务）                        | `REPORT` → `ANNOUNCEMENT` | 财务数据问财**覆盖良好**，降级价值低；仅作兜底    |
| **INDUSTRY**（行业指标）                       | `REPORT` → `NEWS`         | 行业级数据问财**基本齐全**，降级主要补景气判断与政策 |
| **INDUSTRY_CHAIN**（产业链）                  | `REPORT`                  | 环节盈利分配常见于产业链深度研报             |
| **STOCK_SELECTOR**（市占率/CRn）              | `REPORT`                  | 竞争格局与份额多由研报测算给出              |
| **BASIC_INFO**（公司概况）                     | `ANNOUNCEMENT` → `REPORT` | 主营业务介绍见年报                    |
| **INSTITUTIONAL_RESEARCH**               | *不降级*                     | 本身已是机构观点源                    |
| **INDEX / FUTURES / MACRO / SECTOR**     | *不降级*                     | 行情与宏观数据问财域内完整，文档通道无增量        |
| **EVENT / NEWS / ANNOUNCEMENT / REPORT** | *不降级*                     | 自身即文档通道                      |

设计原则三条：

1. **只对"问财结构化覆盖薄弱"的域开降级**——BUSINESS 是最大受益者（出货量/产能正是它的痛点）；
2. **降级链长度 ≤ 2**——避免级联放大调用量与延迟；
3. **定性技能自身不降级**——防止环路。

### 3.1 降级 query 构造

降级技能的 query 必须**携带原任务的目标实体与指标**，不能沿用原 query（原 query 是针对结构化技能的措辞）：

```python
def _fallback_skill_query(
    main_skill: SkillName,
    fallback_skill: SkillName,
    task: SkillQueryTask,
) -> str:
    entities = " ".join(task.target_entities[:3])
    metrics = " ".join(m for m in task.expected_fields[:4] if _is_metric_like(m))
    return f"{entities} {metrics}".strip() or task.query[:120]
```

实体与指标优先（研报检索是关键词召回），丢弃原 query 里的结构化措辞（如"从高到低""市盈率 市净率"）。

---

## 4. 四条红线在降级链上的落地

降级证据必须比结构化证据"低一等"，且这个等级**不可上调**。沿用此前为联网搜索定下的四条红线，逐条落到代码判定上：

### 红线 1 — 证据层级锁死，不可上调

新增证据层级 `document`（低于 `structured`，高于未来的 `web_unverified`）。降级命中的证据在 `normalizer` 打标：

```python
evidence_tier: Literal["structured", "document", "web_unverified"] = "structured"
```

规则**单向**：可降不可升。无论被多少章节引用、LLM 写得多顺，层级标签不变。

### 红线 2 — 只补定性，不填数值

降级命中的证据强制标 `qualitative_only = True`，并在 payload 上带 `substitute_for`（被替代的主任务指标名）。

- **允许**：研报对出货量的定性描述、券商对产能利用率的测算口径说明、公司扩产进度的公开表态；
- **禁止**：把研报里的估算值当作可信数值直接进计算链。`C1`（公式误差 ≤0.01%）一票否决项**只接受 structured 层级输入**。

> 边界说明：研报里确实有数字，但那是**机构测算**，不是权威统计口径。它可以作为"观点"出现在报告里（标注机构名与日期），不能作为"事实"参与计算。

### 红线 3 — 不计入完整性判定

`RequirementCoverage.status` 判定规则：

| 命中情况          | status        | 说明                |
| ------------- | ------------- | ----------------- |
| 结构化命中         | `supported`   | —                 |
| 仅结构化了 partial | `partial`     | 现状                |
| **仅降级命中**     | **`partial`** | **绝不写 supported** |
| 结构化失败 + 降级失败  | `missing`     | 真缺口，正常披露          |

理由：若降级命中算 `supported`，会出现"覆盖率很高、报告全是研报凑的"的假象。**让缺口继续暴露在报告里，比藏在数字后面安全。**

同时 `_exclude_advisory_from_completeness`（`service.py:482`）的既有语义保持不变，降级证据不得借道 advisory 通道混入完整性判定。

### 红线 4 — 冲突保留 + 可追溯

- 降级证据同样过清洗与去重；
- **数值冲突时全部保留、全部标来源**，禁止 LLM 挑一个"看起来更合理"的；
- 每条证据必须带 `source_locator`（URL/文档定位）+ `retrieved_at` + `source_org`（发布机构）；
- 报告脚注呈现，读者自行判断。

### 4.1 澄清门文案按失败类型分流

当前统一文案"暂无对应查询技能，请修改后重试"应分三类（顺带落实从 findesk 抄的那条）：

| 失败类型             | 文案要点                                             |
| ---------------- | ------------------------------------------------ |
| 结构化缺 + 降级**命中**  | "该指标无权威结构化数据，已补充 N 条研报/公告定性材料（见证据编号 X），数值未参与计算。" |
| 结构化缺 + 降级**未命中** | "该指标各通道均无数据，已列入研究边界，未编造。"                        |
| 实体未解析            | "请指定具体公司。"                                       |

---

## 5. 触发条件与成本护栏

降级不是无条件触发，四条护栏：

1. **仅对 `fallback_skills` 非空的任务生效**——默认走 §3 映射表，未列出的技能不降级；
2. **仅主技能全部 query 变体失败后触发**——`[task.query, *task.fallback_queries]` 全部无有效数据；
3. **单任务降级深度 ≤ 2**，且降级链不递归（降级技能的失败不再触发新的降级）；
4. **全局降级预算**：单轮 run 降级调用数 ≤ 主任务失败数的 100%，且 ≤ 15 次总量上限（防雪崩）。

成本估算：以 61 条压测为参照，主任务失败数约 15-20，降级调用增量 ≤ 15 次/轮，**对 `ToolGateway` 的预算与调用上限无实质压力**。

### 5.1 可观测性

沿用 P0-5 的 `routing_telemetry`，`skill_call` 事件新增两字段：

```json
{"fallback_from": "Q-12", "fallback_depth": 1}
```

新增观测指标：

| 指标        | 定义                   | 目标        |
| --------- | -------------------- | --------- |
| 降级触发率     | 触发降级的任务 / 失败任务       | 观测，不设限    |
| **降级挽救率** | 降级命中的任务 / 触发降级的任务    | **≥ 60%** |
| 降级证据采用率   | 进入最终报告的降级证据 / 降级命中证据 | 观测        |

**降级挽救率 < 40% 说明映射表设计有误**，应回头调整，而不是继续加降级层级。

---

## 6. 测试方案（record-replay）

沿用 V8 评测体系，本次**正式开启 record-replay**。

### 6.1 快照录制（`snapshot_ver: v3`）

在改造**前**录制基线，确保修复前后可比：

| 录制对象       | 条数 | 说明                                     |
| ---------- | -- | -------------------------------------- |
| 61 条意图压测集  | 61 | 沿用 `eval/cases/intent_routing_61.yaml` |
| 光伏原始任务     | 1  | 含 4 个研究问题                              |
| **降级专用用例** | 12 | 见 §6.3                                 |

`eval/transport.py` strict mode：未命中 → `SNAPSHOT_MISS` 判失败，**绝不静默走真实接口**。

**关键**：静默降级样本（返回行情字段的那些）**照常落盘**——它们正是验证 P0-6 与降级链联动的素材。

### 6.2 Replay 回归

- Agent 1 语义层走 `surrogate_models`（V8 §2.7 已定义），**单次回归零外部调用、零 LLM 消耗**；
- 修复前后各跑一次，`grades.jsonl` 逐条 diff，确认"从缺口变 partial"的用例对得上；
- 降级调用也走快照，**replay 阶段不触发任何真实网络请求**。

### 6.3 降级专用用例（12 条，新增）

分三组：

**D-01 ~ D-06：应降级且应命中**（受益用例）

| ID   | 输入         | 主技能               | 期望                                  |
| ---- | ---------- | ----------------- | ----------------------------------- |
| D-01 | 隆基绿能组件出货量  | BUSINESS（静默降级）    | 触发 REPORT 降级，≥1 条证据，`tier=document` |
| D-02 | 隆基绿能产能利用率  | BUSINESS/INDUSTRY | 触发降级，`qualitative_only=True`        |
| D-03 | 宁德时代产线良率   | BUSINESS          | 降级未命中则 `missing`，**不得编造**           |
| D-04 | 光伏行业单瓦成本   | INDUSTRY          | 触发 REPORT 降级                        |
| D-05 | 隆基绿能扩产进度   | BUSINESS          | 触发 ANNOUNCEMENT 降级                  |
| D-06 | 光伏组件行业出口占比 | INDUSTRY          | 触发 REPORT 降级                        |

**D-07 ~ D-09：不应降级**（负向，防过度触发）

| ID   | 输入              | 期望                     |
| ---- | --------------- | ---------------------- |
| D-07 | 宁德时代 2025 年营业收入 | FINANCE 直接命中，**零降级调用** |
| D-08 | 沪深300 当前市盈率     | INDEX 直接命中，**零降级调用**   |
| D-09 | 碳酸锂期货价格         | FUTURES 直接命中，**零降级调用** |

**D-10 ~ D-12：红线校验**

| ID   | 校验点      | 期望                                                          |
| ---- | -------- | ----------------------------------------------------------- |
| D-10 | 仅降级命中的需求 | `RequirementCoverage.status == "partial"`，**不得为 supported** |
| D-11 | 降级证据参与计算 | `C1` 一票否决触发，**document 层不得进计算**                             |
| D-12 | 降级链深度    | `fallback_depth ≤ 2`，无递归，降级调用数 ≤ 15                         |

### 6.4 评分器新增（注册进 fail-closed 自检）

| #       | 判定项          | 检查点                                          |
| ------- | ------------ | -------------------------------------------- |
| **FB1** | 降级仅在主技能失败后触发 | 主技能成功的任务 `fallback_depth == 0`               |
| **FB2** | 降级证据层级正确     | 全部降级证据 `evidence_tier == "document"`         |
| **FB3** | 降级不冒充完整性     | 仅降级命中的需求 status 不得为 `supported`              |
| **FB4** | 降级不污染计算      | `document` 层证据不出现在 `calculated_metrics` 输入中  |
| **FB5** | 降级留痕完整       | `fallback_from` / `fallback_depth` 非空且可关联主任务 |

按 V8 §4.7 要求，五项必须注册进 scorer 注册表并通过 F0-07（检查项注册完备）自检，**未注册项必须判失败而非静默通过**。

### 6.5 单元测试（新增，跟随改造同步）

| 文件                                   | 用例                           |
| ------------------------------------ | ---------------------------- |
| `test_field_relevance_extraction.py` | 抽模块后原有 6 个 P0-6 用例零改动通过      |
| `test_fallback_chain.py`             | 映射表正确性、零行触发、静默降级触发、不递归、深度 ≤2 |
| `test_fallback_evidence_tier.py`     | FB2/FB3/FB4 三条红线             |



---

## 7. 量化目标

| 指标                   | 现状      | 目标          | 性质                |
| -------------------- | ------- | ----------- | ----------------- |
| **C1 计算错误**          | 0       | **0（保持不变）** | 一票否决              |
| **静默误判率**            | 待四刀修复   | **0（保持不变）** | 一票否决              |
| 假缺口率（走降级能捞到的 / 判缺口的） | ~40%（估） | **降至 ≤15%** | 核心目标              |
| **降级挽救率**            | 不存在     | **≥ 60%**   | 核心目标              |
| 降级证据误入计算             | 不存在     | **0**       | 一票否决（FB4）         |
| 仅降级命中被判 supported    | 不存在     | **0**       | 一票否决（FB3）         |
| 干净通过率                | 70.5%   | **≥ 75%**   | 综合（部分缺口转 partial） |

> 注意：**干净通过率的提升是"缺口变 partial"，不是"缺口变 supported"**。指标设计上必须防住后者，否则就是自欺欺人。

---

## 8. 实施顺序（TDD，与四刀并行不悖）

| 步骤      | 内容                                                                  | 是否动生产代码 | 门禁                      |
| ------- | ------------------------------------------------------------------- | ------- | ----------------------- |
| **S0**  | 用例固化：12 条降级用例写入 `eval/cases/fallback_chain.yaml`；FB1-FB5 注册进 scorer | ❌ 评测层   | F0-07 自检通过              |
| **S1**  | 录制 v3 基线快照（61 + 1 + 12）                                             | ❌       | 快照落盘，`manifest.json` 记录 |
| **S2**  | 单测骨架：`test_fallback_chain.py` / `test_fallback_evidence_tier.py`    | ❌       | **红着提交**（改造前必须失败）       |
| **S3**  | 拆循环依赖：`_field_relevance_check` → `field_relevance.py`               | ✅ 纯重构   | 6 个 P0-6 单测零改动通过        |
| **S4**  | Schema：`fallback_skills` + `fallback_from` + `fallback_depth`       | ✅       | 既有 acquisition 单测通过     |
| **S5**  | 字段校验前移：executor 成功判定加 `_field_relevance_ok`                         | ✅       | S2 单测开始转绿               |
| **S6**  | 降级映射表 + query 构造                                                    | ✅       | 12 条用例 replay 通过        |
| **S7**  | 证据分层打标 + 覆盖率判定（红线 1/3）                                              | ✅       | FB2/FB3 通过              |
| **S8**  | 澄清门文案三类分流                                                           | ✅       | 文案断言通过                  |
| **S9**  | replay 全量回归（61 + 1 + 12），前后 diff                                    | ❌       | 量化目标达成                  |
| **S10** | L4a 代打全链路                                                           | ❌       | 无降级相关回归                 |

**与四刀方案的关系**：两者改的文件**仅在 `service.py` 有交叉**（四刀改澄清门放行，本方案改澄清门文案与覆盖率判定）。建议**先四刀后降级**——四刀的 BUG-1（静默误判）会改变哪些任务走 BUSINESS，进而影响降级触发面；先修路由再补降级，避免降级链给错误路由"续命"。

---


## 9. 变更文件清单

| 文件                                                                     | 改动                                                                                  |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `app/agents/data_fetcher/field_relevance.py`                           | **新增**：`_field_relevance_check` 从 normalizer 抽出（拆循环依赖）                              |
| `app/agents/data_fetcher/executor.py`                                  | 成功判定加字段校验；`fallback_skills` 降级执行循环；降级留痕                                             |
| `app/agents/data_fetcher/planner.py`                                   | 新增 `_fallback_skills()` 映射表 + `_fallback_skill_query()` query 构造                    |
| `app/agents/data_fetcher/normalizer.py`                                | 改 import 路径；新增 `evidence_tier` / `qualitative_only` 打标                              |
| `app/schemas/acquisition.py`                                           | `SkillQueryTask.fallback_skills`；`SkillCallRecord.fallback_from` / `fallback_depth` |
| `app/schemas/evidence.py`                                              | `evidence_tier` 字段                                                                  |
| `app/agents/data_fetcher/service.py`                                   | 覆盖率判定（红线 3）；澄清门文案三类分流                                                               |
| `app/agents/data_fetcher/routing_telemetry.py`                         | `skill_call` 事件加降级字段                                                                |
| `eval/cases/fallback_chain.yaml`                                       | **新增**：12 条降级用例                                                                     |
| `backend/tests/agents/data_fetcher/test_fallback_chain.py`             | **新增**                                                                              |
| `backend/tests/agents/data_fetcher/test_fallback_evidence_tier.py`     | **新增**                                                                              |
| `backend/tests/agents/data_fetcher/test_field_relevance_extraction.py` | **新增**                                                                              |

---

## 10. 风险与回滚

| 风险            | 影响                 | 缓解                             |
| ------------- | ------------------ | ------------------------------ |
| **拆模块引入回归**   | P0-6 失效，静默降级重新污染证据 | 函数签名不变，6 个既有用例零改动；S3 独立交付可单独回滚 |
| **降级放大调用量**   | ToolGateway 预算超支   | 深度 ≤2 + 单轮 ≤15 次 + 仅失败任务触发     |
| **降级证据被当事实用** | 报告出现不可靠数值          | FB4 一票否决 + `document` 层不进计算链   |
| **映射表设计有误**   | 大量无效降级调用           | 降级挽救率 <40% 即回头调表，不加层级          |
| **给错误路由续命**   | 路由错的也去降级，掩盖 BUG-1  | 先四刀后降级（§8）                     |

**回滚**：每步独立 feature flag `AGENT1_FALLBACK_CHAIN`（默认关），可逐项关闭；Schema 新增字段均有默认值，关闭后行为与现状完全一致。

---

## 11. 一致性声明

本方案遵守此前定下的全部约束：

- ✅ **不新增数据源**——用现有问财 `report_search` / `announcement_search` / `news_search`
- ✅ **不接联网搜索**——红狐（Deepseek 联网）已评估否决：轮询 5 分钟、无结构化结果、无时间/域名过滤、第三方中转无官方授权
- ✅ **不动 SQLite**——按用户要求，词表外置仍走 YAML 双轨
- ✅ **遵守四条红线**——层级锁死 / 只补定性 / 不计完整性 / 可追溯
- ✅ **测试期不改生产代码**——S0-S2 全在评测层，S3 起每步单独申请授权
