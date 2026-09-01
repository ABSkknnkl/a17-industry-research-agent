# Agent 1 意图路由 P1 方案：层间仲裁修复 + Record-Replay 评测回归

- 日期：2026-09-01
- 状态：待评审
- 前置文档：[2026-08-31-agent1-routing-fix.md](2026-08-31-agent1-routing-fix.md)（P0 方案）、[2026-08-31-agent1-routing-fix-P0-验收报告.md](2026-08-31-agent1-routing-fix-P0-验收报告.md)
- 测试依据：`docs/AGENT1_ROUTING_TEST_REPORT.md`（61 条金融问句压测，真实确定性层 + 人工扮演 LLM 语义层 + 真实仲裁层）
- 评测框架：复用 V8《自动化评测体系方案》（`EVALUATION_PLAN.md`）的 L0-L5 分层、record-replay 快照、surrogate 代打、fail-closed 自检与门禁矩阵
- 范围：`backend/app/agents/data_fetcher/`（Agent 1）+ `eval/`（评测层）
- 数据库说明：本轮词表外置用**配置文件**落地，不动 SQLite；DB 化后置。

---

## 0. 一句话结论

61 条压测暴露的 34 条问题中，**32 条的根因是 P0 没有触碰的"层间仲裁"三处代码**——确定性锁定永远生效、LLM 只能补充不能否决、advisory 标了不放行。本方案用**四刀**修复（仲裁三处 + L1 派生词否定表 + 契约类补齐 + miss 闭环），全部修复以 **record-replay 快照回放**做零成本回归验证，门禁硬指标：**静默误判率 = 0、错配率 < 1.5%、过度阻塞率 < 10%、干净通过率 ≥ 65%**。

**不做的事（红线）**：不训练路由模型、不接联网搜索、不新增数据技能、不动 Agent 2-5、不动数据库。

---

## 1. 为什么 P0 验收通过了，61 条还有 bug（归因总表）

P0 修的是**层内**（拆解粒度、分析型识别、泛称解析、4 族词表、遥测埋点），61 条暴露的是**层间**（L1↔L2 谁说了算、澄清门放不放行）与 **L1 匹配规则本身**。逐类对应：

| 61 条发现 | 数量 | 根因代码位置 | P0 是否覆盖 | 本方案归属 |
|---|---|---|---|---|
| 静默误判（"产能投资→查产能"等） | 9 | `intent_merger._merge_llm_plan:368`（LLM 空 skills 被 `continue` 跳过，**无否决权**）+ `locked_skill_missing_after_merge:477-485`（确定性 locked **强制补回**）+ L1 子串包含 `conf=1.0` | ❌ | 第一刀 + 第二刀 |
| 关键词压过 LLM（F02/B10） | 2 | 同上两处 | ❌ | 第一刀 |
| 过度阻塞（已路由却要澄清） | 23 | `plan_validator:clarification_should_be_advisory` 已标记但**未据此放行** | ❌ | 第一刀·改动点 3 |
| 重复子查询（A02/C06） | 2 | `_find_merge_target` 要求 entity **且** metric 同时重叠 | ❌（P0-1 只管裸实体继承） | 第三刀 |
| 口径合并丢失（A06/B06） | 2 | 有效/在建/规划产能未独立注册，被归一为 `capacity` | ❌ | 第三刀 |
| 词表差（库存周转/外销占比/CR10/渗透率） | 5 | registry 字面不匹配（"存货周转"≠"库存周转"） | ❌（P0-4 只加 4 族） | 第三刀 |
| 真数据缺口（产销率/良率/自给率等） | 13 | 数据本身不存在 | 无需修（架构正确：走澄清门不编造） | 评测集保留为负向金标准 |
| 干净通过 | 20 | — | — | — |

**正确读法**：20 干净通过 + 13 真缺口（架构正确拒绝）= **33/61 是架构正常工作的结果**。真正要修的是 28 条，其中高危（取错数且静默）只有 6 条：4 条静默误判 + 2 条仲裁压制。其余 23 条过度阻塞是体验问题，9 条是契约完备性问题。

**P0-6 与 61 条"静默误判"是两层**：P0-6（`normalizer.py:565 _field_relevance_check`）在**取数后**查问财返回列名对不对；61 条静默误判在**路由前** L1 关键词误锁定，根本走不到取数。两层都要，互不替代。

---

## 2. 修复方案（四刀）

### 第一刀：层间仲裁三处（治 11 条高危，优先级最高）

**原则**：LLM 语义优先 + 确定性契约兜底 + **LLM 拥有否决权**。确定性 `conf=1.0` 不再是免死金牌。

#### 改动点 1：`_merge_llm_plan` 允许显式否决（`intent_merger.py:368` 附近）

现状（伪代码）：

```python
for sub in llm_plan.sub_requirements:
    valid_skills = [s for s in sub.candidate_skills if s in SkillName]
    if not valid_skills:
        continue   # ← LLM 输出空 skills 被跳过，确定性 locked 存活
```

改为：

```python
for sub in llm_plan.sub_requirements:
    valid_skills = [s for s in sub.candidate_skills if s in SkillName]
    if not valid_skills:
        if sub.intent_type == "analysis_only" or sub.reject_reason:
            # LLM 显式否决：该碎片不进取数路由，写入 analysis_notes 透传 Agent 2；
            # 同时从 deterministic locked 中移除同碎片锁定（改动点 2 联动）
            plan.analysis_notes.append(sub.text)
            vetoed_fragment_ids.add(fragment_id_of(sub))
            telemetry.record("llm_veto", ...)
            continue
        continue
```

契约细节：

- 否决必须**显式**：`candidate_skills=[]` **且**（`intent_type="analysis_only"` 或给出 `reject_reason`）。LLM 单纯没选出技能不构成否决（防止 LLM 偷懒导致 recall 下降）。
- `LLMSubRequirement` 需新增可选字段 `reject_reason: str | None`（`intent_models.py`），P0-2 已加的 `analysis_only` 枚举直接复用，两处 schema（`intent_models.py` / `semantic_router.py`）同步。
- 否决事件写 telemetry 第五类点位 `llm_veto`（`routing_telemetry.py` 扩展），每周审查**否决率**（健康区间预估 5%-20%；>30% 说明 LLM 在滥用否决，触发 prompt 审查）。

#### 改动点 2：`locked_skill_missing_after_merge` 条件补回（`intent_merger.py:477-485`）

现状：确定性 locked 在合并后若丢失，**无条件强制补回** `subs[0]`。

改为：**仅当该碎片未被显式否决时**才补回：

```python
if missing_locked and fragment_id not in vetoed_fragment_ids:
    restore_locked(subs[0], missing_locked)
```

#### 改动点 3：`clarification_should_be_advisory` 真放行（`service.py` 澄清门）

现状：plan_validator 已能识别"有技能可接、但置信度不足/参数欠完整"并打 `clarification_should_be_advisory`，但澄清门一律按 hard block 处理 → 23 条过度阻塞。

改为澄清门**两级**：

| 级别 | 触发 | 行为 |
|---|---|---|
| `hard` | 无技能可接 / 无实体 / 显式否决后无可执行碎片 | 阻塞，走澄清门（现状不变） |
| `advisory` | 有技能可接但置信度不足、参数欠完整、合并存疑 | **放行执行**，证据标 `low_confidence` 层级，报告披露"该数据置信度不足，建议人工复核"，telemetry 记 `advisory_passed` |

防滥用：advisory 放行的证据**不计入**核心数据组完整性判定（与联网搜索旁路证据同规则）；若 advisory 碎片取数后触发 P0-6 字段校验失败，升级为 hard。

**验收**：61 条中 23 条过度阻塞重跑后，≥20 条转为正常执行或 advisory 放行；`E01/E04/E05` 这类被 LLM 救回又被阈值阻塞的不再白救。

### 第二刀：L1 派生词否定表 + 最长匹配优先（治子串误命中）

子串包含本身没错，错在**命中即 `conf=1.0` 锁死**。两道后校验加在确定性匹配命中之后、lock 之前（`metric_registry.py` 匹配逻辑 / `deterministic_intent_parser`）：

#### 改动点 1：最长匹配优先

先匹配最长 alias（"在建产能"4 字 > "产能"2 字；"有效产能" > "产能"），命中长 alias 后短 alias 不再独立命中。顺带治第三刀的口径合并丢失。

#### 改动点 2：派生词否定表

命中 alias 后，扫描该 alias 在原文中的**前后窗口（±8 字符）**，检出派生词则**不 lock**，标 `derivative_suspected` 降级给 L2 判：

| 命中 alias | 否定词（检出即降级） | 典型误命中句 |
|---|---|---|
| 产能 | 投资、爬坡、过剩、周期、释放、扩张、跑满、落地 | 单位产能投资 / 产能爬坡周期 / 产能是否过剩 / 新产能多久跑满 |
| 出货量 | 目标、计划、预期、指引 | 出货量指引（应走 EVENT/研报定性） |
| 价格 | 影响、传导、弹性、敏感性 | 碳酸锂价格对组件成本的影响（analysis_only，P0-2 已治一半） |
| 毛利率 | 影响、贡献、驱动、敏感性 | 毛利率变动对估值的影响 |
| 市场份额 | 影响、变化原因、趋势判断 | — |

词表外置在 `backend/config/metric_derivative_blacklist.yaml`（新词不发版，改配置即生效；SQLite 表后置）。降级事件写 telemetry。

**与第一刀的关系**：否定表把碎片从 L1 手里放给 L2，L2 判"这是派生诉求"后走改动点 1 的显式否决通道——两道缺一不可：否定表是确定性兜底（LLM 不在场时也有保护），否决权是语义终审（否定表词表外的情况）。

### 第三刀：契约类 9 条（词表 5 + 合并 2 + 口径 2）

#### 改动点 1：词表 5 项补别名（`metric_registry.py`，同步写入外置配置）

| MetricSpec | 补 alias | 说明 |
|---|---|---|
| inventory_turnover_days 存货周转天数 | +库存周转天数、库存周转 | 用户口语"库存"≠书面"存货"，两条都留 |
| overseas_revenue_ratio 海外收入占比 | +外销占比、出口占比 | |
| cr_concentration CR 集中度 | +CR10（CR3/CR5 已有） | |
| penetration_rate 渗透率 | +渗透率、渗透水平 | **先评估数据源**（问财行业库有没有渗透率字段，用 pywencai 反向探测；无数据源则注册为 unsupported，走澄清门，不硬路由） |
| capacity_utilization 产能利用率 | +开工饱和度 | E05"生产饱和吗"类口语 |

#### 改动点 2：合并规则放宽（`intent_merger._find_merge_target`）

现状：entity **且** metric 同时重叠才合并 → 顿号切分碎片（A02/C06）合并失败产生重复子查询。

改为：entity **或** metric 重叠即可合并，**加两个护栏**防止误合：

1. 两碎片 `intent_type` 必须相同；
2. 合并后重跑 `capability_supports` 校验，技能不兼容则不合。

#### 改动点 3：口径细分（`metric_registry.py` 新增 3 族）

| 新增 MetricSpec | aliases | primary_skill | 说明 |
|---|---|---|---|
| effective_capacity 有效产能 | 有效产能、现有产能 | INDUSTRY | |
| under_construction_capacity 在建产能 | 在建产能、建设中产能 | INDUSTRY | |
| planned_capacity 规划产能 | 规划产能、拟建产能 | INDUSTRY | |

配合第二刀的最长匹配优先："有效/在建/规划产能分别多少"（A06/B06）拆出 3 个独立指标子需求，不再归一为 `capacity`。

### 第四刀：miss 回流闭环跑起来（治"无穷无尽口语"的焦虑）

P0-5 埋点已积累 1021 条真实路由日志，但**没人定期消费它**。本刀把闭环从"埋点"推进到"运转"：

1. **miss 提取脚本** `eval/tools/miss_report.py`（新增）：每周从 `artifacts/routing_telemetry/*.jsonl` 提取 `route_decision` miss 事件 + `clarification` 事件 + `llm_veto` 事件，按 sha256 聚合频次，输出周报（Top miss 句式、否决率、advisory 率）。
2. **周度分流规则**（固定节奏，写入团队日历）：
   - 高频词/别名（周 ≥3 次）→ 进词表配置文件（不发版）；
   - 仲裁规则 case → 改否定表/仲裁代码，走评测集回归；
   - 长尾口语 → 留给 L2，不进 L1；
   - 真数据缺口 → 登记研究边界词表，**永不**试图硬路由。
3. **词表双轨**：`metric_registry.py` 保留核心高频指标（代码即契约），`backend/config/metric_aliases.yaml`（新增）承载长尾别名与否定表，启动时合并加载。SQLite 表化后置（本期不做）。
4. **61 条评测集固化**：见 §4.3，作为每次改动的回归基线。

### 红线（不变）

- 不训练路由模型（触发条件仍是：离线评测准确率 < 95% 且 prompt/否定表调优无效，见 P0 方案 §5 决策树）；
- 不接联网搜索（P2 议题，选型已定博查，接入时机在 P1 数据达标后）；
- 不新增数据技能（13 条真缺口靠澄清门 + 研究边界披露，不靠堆技能）。

---

## 3. 量化验收目标（首次定义"修好了"）

| 指标 | 基线（61 条实测） | 目标 | 口径 |
|---|---|---|---|
| **静默误判率** | ~15%（9/61） | **= 0** | 取错数且未走澄清/未标记低置信，硬指标，一票否决 |
| **错配率** | ~5%（3/61） | **< 1.5%** | 路由到错误技能（对标 Red Hat 805 条训练后标杆） |
| **过度阻塞率** | ~38%（23/61） | **< 10%** | 有技能可接却被 hard 阻塞的比例 |
| **干净通过率** | 33%（20/61） | **≥ 65%** | 无缺陷执行完成 |
| 真缺口正确拦截率 | 100%（13/13） | 保持 100% | 缺口全走澄清门，零编造 |
| LLM 否决率 | — | 5%-20% 健康区间 | telemetry 周审，>30% 触发 prompt 审查 |

13 条真数据缺口**不算分母**——它们是架构正确工作的证据，不是失败。

---

## 4. 测试方案（Record-Replay 正式开启）

> 框架复用 V8 评测体系：L0-L5 执行分层、transport 快照（agentrr 式 strict miss=fail）、surrogate 代打、fail-closed 自检、四类问题分流（§13.1）。**本轮所有生产侧 bug 均属 ③类（确定性生产 bug）——授权后即修，pytest + replay 本地回归验证，零 LLM 额度消耗。**

### 4.1 执行分层与时机

| 阶段 | 层 | 内容 | 成本 | 门禁 |
|---|---|---|---|---|
| S0 | L0 | 评测器 fail-closed 自检 + 新增 scorer 自测 | 零 | 100% 通过才允许继续 |
| S1 | L1 | 新增单元测试（§4.4），pytest 全量回归 | 零 | 全绿 |
| S2 | **record** | 修复**前**录制 61 条 + 光伏原始任务的真实 SkillHub 快照 | SkillHub 配额 | 快照落盘完整 |
| S3 | 修复实施 | 第一刀→第二刀→第三刀，每刀独立 feature flag | 零 | 每刀过 S1 |
| S4 | **replay** | strict 模式回放，61 条金标准断言（§4.3）+ 修复前后对比 | **零**（不调真实接口、不烧 LLM） | §3 全部指标达标 |
| S5 | L4a | surrogate 代打全链路：光伏原始任务端到端（7 章 21 节产物非空） | 零 | 正向完整报告产出率 100% |
| S6 | L4b | 真实 LLM 冒烟（**置后**：replay 全绿且额度恢复后，只跑一轮） | 高 | 无阻断、无虚假完成 |

### 4.2 Record-Replay 开启细节（本轮新增，重点）

**录制（S2，修复前基线）**：

```bash
# 61 条评测集 + 光伏原始任务，真实 SkillHub 落盘
python -m eval.runner --mode record --cases eval/cases/intent_routing_61.yaml
python -m eval.runner --mode record --cases eval/cases/pv_original_task.yaml
```

- **match key**：`sha256(canonical_json({skill, endpoint, query, page}))[:16]`（canonical_json = 键排序、`separators=(",",":")`、`ensure_ascii=False`），与 V8 §2.1 一致；
- **落盘**：`eval/snapshots/{case_id}/{skill}__{match_key}.json` = 原始 payload + `raw_sha256` + `recorded_at` + `schema_hash`；
- **快照版本升版**：`snapshot_ver: v2`（P0 修复后问财返回已变，旧 v1 快照对 61 条无意义，整批重录）；
- **manifest.json**：录制日期、问财字段 schema 哈希、`snapshot_ver`、录制时的 git commit；
- **特别录制项——静默降级快照**：61 条中问"出货量/产能利用率"的用例，问财会静默回退行情数据。这类快照**照常落盘**（它是真实返回），replay 时由 P0-6 `_field_relevance_check` 识别并判"正确拦截"——这正是验证 P0-6 与第一刀联动的金标准。

**回放（S4，strict 默认）**：

```bash
python -m eval.runner --mode replay --strict --cases eval/cases/intent_routing_61.yaml
```

- **strict miss = fail**：未命中快照记 `SNAPSHOT_MISS` 失败，**绝不静默走真实接口**（agentrr `--on-miss strict` 同义）；
- **Agent 1 语义层供给**：replay 轮 Agent 1 的 LLM 由 surrogate（`eval/surrogate_models.py`）或 mock 承担，SkillHub 全部走快照——**单次回归零外部调用**；
- **修复前后对比**：同一快照跑两遍（修复前基线 grades.jsonl vs 修复后 grades.jsonl），diff 出每条用例的判定变化，逐条人工确认"从错变对"而非"从对变错"。

**遥测卫生**（61 条实测踩过的坑）：跑测试会经 `record_decomposition` 往 `artifacts/routing_telemetry/YYYYMMDD.jsonl` 写记录。测试批次统一打 `run_id=eval-{date}-{batch}` 前缀，清理时**只删本批 run_id**，严禁整文件删除（里面混有生产真实日志）。

### 4.3 61 条离线评测集固化（`eval/cases/intent_routing_61.yaml`）

把测试报告里的 61 条转成金标准 YAML，schema 沿用 V8 §5.0.3 的 I 类形态，扩展三个仲裁断言字段：

```yaml
- id: R-A09
  group: arbitration          # 新组：与 intent_routing 并列的 PR 一票否决组
  input: 企业单位产能投资是多少
  industry_topic: 光伏组件
  runs: 3
  threshold: 1.0
  must_pass: true
  veto: [ARB1]                # 静默误判一票否决
  checks: [ARB1, ARB2, ARB3, I2, I3]
  intent:
    not_locked_metrics: [产能]           # 不得被 L1 锁定
    expected_skills_any: [hithink_finance_query]  # 投资额→财务
    or_clarification: true               # 或走澄清门，二选一都算对
  snapshot_ver: v2
  subgoals: [a1_plan]

- id: R-E02
  group: arbitration
  input: 光伏组件行业产能有没有过剩？
  veto: [ARB1]
  intent:
    not_locked_metrics: [产能]
    expect_analysis_only_or_clarification: true    # 判断题→否决或澄清，禁止静默取数
  snapshot_ver: v2

- id: R-F02
  group: arbitration
  input: 光伏组件行业竞争格局分析
  veto: [ARB1]
  intent:
    expected_skills: [hithink_stock_selector]      # 份额→选股，不得锁 INDUSTRY
    forbidden_skills: []
  snapshot_ver: v2
```

**新增评分器 checks**（`eval/scorers/arbitration.py`，新文件）：

| # | 判定项 | 检查点 | 性质 |
|---|---|---|---|
| ARB1 | 无静默误判 | deterministic locked 指标与金标准不符且未走澄清/未标低置信 → fail | **一票否决** |
| ARB2 | advisory 不阻塞 | 有技能可接 + `clarification_should_be_advisory` 标记 → 必须放行执行，hard 阻塞即 fail | 过度阻塞率口径 |
| ARB3 | 派生词不锁定 | 输入含否定表派生词 → L1 不得 `conf=1.0` lock，必须降级 L2 或走否决 | 第二刀验收 |
| ARB4 | 否决留痕 | LLM 显式否决的碎片必须出 `llm_veto` telemetry 且不再补回 locked | 第一刀验收 |

**分组与归属**：61 条按归因分三组——`arbitration`（静默误判 9 + 关键词压制 2 + advisory 代表 10，共 21 条）、`contract`（词表 5 + 合并 2 + 口径 2，共 9 条）、`true_gap`（真缺口 13 条，预期全是"正确拦截"，作负向金标准）、`clean_pass`（干净通过 18 条，防回归）。

### 4.4 新增单元测试清单（`backend/tests/agents/data_fetcher/`）

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `test_arbitration.py` | 8 | LLM 显式否决移除 locked（改动点 1）；未否决时 locked 正常补回（改动点 2 回归）；否决必须带 analysis_only/reject_reason 才生效；空 skills 但无否决标记仍走澄清（防 LLM 偷懒）；advisory 放行（改动点 3）；advisory 取数后 P0-6 失败升级 hard；否决写 telemetry；advisory 证据不进完整性判定 |
| `test_derivative_blacklist.py` | 6 | "产能投资/爬坡/过剩/跑满"不 lock；最长匹配优先（"在建产能"赢"产能"）；否定表从 YAML 加载生效；窗口外派生词不误伤（"产能利用率"正常命中）；降级写 telemetry；否定表为空时行为不变 |
| `test_merge_relaxed.py` | 4 | entity 或 metric 重叠可合并（A02/C06 回归）；intent_type 不同不合；合并后 capability 校验失败不合；合并去重后无重复子查询 |
| `test_metric_granularity.py` | 4 | 有效/在建/规划产能独立命中（A06/B06 回归）；三者可同存于一个 plan；词表 5 项新别名命中；渗透率无数据源时走 unsupported 不硬路由 |
| `test_p0_routing_fix.py`（已有 25 例） | — | **全量回归不得变红**（每刀的兼容性底线） |

### 4.5 门禁矩阵更新（叠加进 V8 §6.2）

| 场景 | 指标 | 阈值 |
|---|---|---|
| PR 合并 | `intent_routing` + `core_calc` + `intercept` + `tool_planning` + **`arbitration` 新组** pass@1 | 100%（一票否决组） |
| 每刀修复提交 | 对应单测文件 + P0 已有 25 例 | 全绿 |
| replay 回归（S4） | 61 条金标准：静默误判率 / 错配率 / 过度阻塞率 / 干净通过率 | §3 全部达标 |
| 日常迭代 | 全量 pass@3 | ≥90%（沿用 V8） |
| 发版 | 全量 pass*3 + `arbitration` 组 pass*5 | ≥95% / 100% |
| 遥测周审 | LLM 否决率 | 5%-20% 健康区间 |

### 4.6 问题分流（沿用 V8 §13.1，本方案映射）

| 类别 | 本方案实例 | 节奏 |
|---|---|---|
| ① 评测器/接线 | arbitration scorer 新增、61 条 YAML 固化、快照重录 | 随手修，不碰生产代码 |
| ② 用例预期 | 61 条金标准标注的人工复核（尤其是 advisory 放行边界） | 即改用例 |
| ③ 确定性生产 bug | **四刀全部**（仲裁 3 处、否定表、合并、口径、词表） | 授权后即修，pytest + replay 验证 |
| ④ LLM 行为 | surrogate 代打暴露的拆解/否决质量问题 | 记 8 字段根因攒批，L4b 一轮验收 |

### 4.7 不重复造车（复用清单）

- transport 快照/strict replay：`eval/transport.py`（已有）；
- surrogate 四模型：`eval/surrogate_models.py`（已有，本轮 Agent 1 语义层直接复用）；
- fail-closed 自检：`eval/tests/test_fail_closed.py`（已有，新增 ARB1-ARB4 注册后须过 F0-01/F0-07）；
- 遥测：`routing_telemetry.py`（P0-5 已有，仅扩展 `llm_veto`/`advisory_passed`/`derivative_suspected` 三个事件类型）；
- I1-I8 意图判分：`eval/scorers/intent.py`（已有，ARB 判分新文件与之并列，不改它）。

---

## 5. 变更文件清单

### 生产代码（③类，需授权）

| 文件 | 改动 |
|---|---|
| `backend/app/agents/data_fetcher/intent_merger.py` | `_merge_llm_plan` 显式否决通道（:368）；`locked_skill_missing_after_merge` 条件补回（:477-485）；`_find_merge_target` 合并放宽 |
| `backend/app/agents/data_fetcher/intent_models.py` | `LLMSubRequirement` 新增 `reject_reason: str \| None` |
| `backend/app/agents/data_fetcher/semantic_router.py` | schema 同步 `reject_reason`；拆解 prompt 加"可显式否决"说明 |
| `backend/app/agents/data_fetcher/metric_registry.py` | 最长匹配优先；派生词否定表校验钩子；词表 5 项别名；有效/在建/规划产能 3 族；外置 YAML 合并加载 |
| `backend/app/agents/data_fetcher/service.py` | 澄清门 hard/advisory 两级放行；advisory 证据标 `low_confidence`、不进完整性判定；advisory+P0-6 联动升级 hard |
| `backend/app/agents/data_fetcher/routing_telemetry.py` | 新增 `llm_veto` / `advisory_passed` / `derivative_suspected` 事件 |
| `backend/config/metric_aliases.yaml` | 新增：长尾别名外置 |
| `backend/config/metric_derivative_blacklist.yaml` | 新增：派生词否定表外置 |

### 测试与评测（①②类，随时改）

| 文件 | 改动 |
|---|---|
| `backend/tests/agents/data_fetcher/test_arbitration.py` | 新增 8 例 |
| `backend/tests/agents/data_fetcher/test_derivative_blacklist.py` | 新增 6 例 |
| `backend/tests/agents/data_fetcher/test_merge_relaxed.py` | 新增 4 例 |
| `backend/tests/agents/data_fetcher/test_metric_granularity.py` | 新增 4 例 |
| `eval/cases/intent_routing_61.yaml` | 新增：61 条金标准（四组） |
| `eval/cases/pv_original_task.yaml` | 新增：光伏原始任务端到端 |
| `eval/scorers/arbitration.py` | 新增：ARB1-ARB4 判分 |
| `eval/tests/test_fail_closed.py` | 注册 ARB1-ARB4，过 F0-01/F0-07 |
| `eval/tools/miss_report.py` | 新增：周度 miss 提取 |
| `eval/snapshots/` | `snapshot_ver: v2` 整批重录 + manifest 更新 |

---

## 6. 风险与回滚

| 风险 | 等级 | 缓解 |
|---|---|---|
| LLM 滥用否决权导致 recall 下降 | 中 | 否决必须显式（analysis_only 或 reject_reason）；否决率 telemetry 周审，>30% 触发 prompt 审查；feature flag `AGENT1_LLM_VETO_ENABLED` 可关 |
| advisory 放行让低置信数据进报告 | 中 | advisory 证据强制 `low_confidence` 层级 + 报告强制披露 + 不进完整性判定；P0-6 失败升级 hard；flag `AGENT1_ADVISORY_PASS_ENABLED` 可关 |
| 否定表误伤正常查询（"产能利用率"含"产能"） | 低 | 最长匹配优先 + 窗口 ±8 字符 + 单测覆盖（test_derivative_blacklist 第 4 例）；否定表外置可热修 |
| 合并放宽误合不同诉求 | 低 | 双护栏（intent_type 相同 + capability 校验）；T3 重复调用率指标监控 |
| 快照 v2 重录引入新静默降级样本 | 低 | 恰是所需（验证 P0-6 联动）；录制时逐条核对 `_extract_rows` 列名 |
| 回滚 | — | 每刀独立 feature flag；配置回滚 = 还原 YAML；代码回滚 = git revert，评测集 YAML 与快照版本绑定，回滚后仍可用 v2 快照验证 |

---

## 7. 实施顺序

1. **S0/S1 先行**：新增 scorer + 61 条 YAML 固化 + fail-closed 自检 + 单测骨架（红着提交，TDD）；
2. **S2 录制**：修复前基线快照（v2）落盘，含静默降级样本；
3. **第一刀**（仲裁 3 处，flag 默认开）→ 单测绿 → replay 跑 `arbitration` 组：静默误判 9 条应全部转为"否决/澄清/放行"三态之一；
4. **第二刀**（否定表 + 最长匹配）→ 单测绿 → replay：`derivative_suspected` 事件出现，ARB3 全过；
5. **第三刀**（契约 9 条）→ 单测绿 → replay：`contract` 组全过；
6. **S4 全量 replay**：§3 六项指标全部达标，修复前后 grades.jsonl diff 逐条人工确认；
7. **S5 L4a 代打全链路**：光伏原始任务端到端出完整报告，待澄清 ≤2（仅真缺口）；
8. **第四刀机制落地**：`miss_report.py` 跑第一期周报，词表外置双轨切换；
9. **S6 L4b 真实 LLM 冒烟**：置后，额度恢复后一轮跑完（沿用 V8 "集中修、一轮验"原则）。

---

## 附：与 P0 方案的关系

本方案是 [2026-08-31-agent1-routing-fix.md](2026-08-31-agent1-routing-fix.md) §4（P1 观测驱动仲裁）的**提前落子**——P0-5 埋点刚上线一天，61 条压测就用真实代码把层间仲裁的三处缺陷钉死了，不需要再等两周日志。P1 原清单中**尚未包含**的两项（词表外置、分技能阈值校准）仍按原节奏走：词表外置随第四刀落地（配置文件先行），分技能阈值校准等 `arbitration` 组积累 ≥2 周 replay 数据后立项。
