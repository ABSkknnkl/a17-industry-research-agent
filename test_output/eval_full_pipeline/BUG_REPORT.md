# 全链路流程测试 Bug 汇总报告

日期: 2026-08-20
测试依据: [docs/EVALUATION_PLAN.md](../../../docs/EVALUATION_PLAN.md) V6
测试驱动: [eval/run_pipeline_eval.py](../../../eval/run_pipeline_eval.py)（新增）+ [eval/runner.py](../../../eval/runner.py)（I 类）
grades 归档: `test_output/eval_full_pipeline/transcript/20260820T202353Z/grades.jsonl`
保留报告: `test_output/eval_full_pipeline/kept_reports/`（3 份 HTML）

---

## 一、测试执行方式声明

| 项 | 说明 |
|----|------|
| LLM 调用 | **零调用**。Agent 1 走确定性意图路由（decomposer=None）；Agent 2 用 `MockAnalysisModel`、Agent 4 用 `MockChapterWritingModel`（确定性 LLM 替身，由测试充当大模型）；Agent 3/5 本身无 LLM |
| SkillHub | `MockSkillHubClient`（provider_mode="live"，与 backend 官方测试同装配），不访问真实接口 |
| 用例级隔离 | 每条用例独立 LangGraph thread + 240s 超时 + 最多 8 轮审阅 resume；单条阻断不终止整套测试（方案 §2.6） |
| 审阅自动化 | `required_data_unavailable` 类 → cancel（合法拦截）；有决策包 → `accept_with_risks`（带 decision_id/risk_snapshot_sha256/accepted_risk_codes，对齐 §6.2 校验）；FAILED → regenerate 一次；其余 → approve |
| 执行范围 | I 类金标准 15 条（意图层直测）+ E2E 50 条 + T 类 12 条（全链路）= 77 条；S 类 24 条专项未在全链路执行（见 §五 局限） |

## 二、结果汇总

**全链路（62 条）**：pass 45 / intercept 16 / blocked 1（T-12）
**I 类意图金标准（15 条）**：12/15 通过

但 pass 的 45 条中**仅 6 条为真实完成**（五阶段无 error、报告产物齐全：E-01/E-06/E-13/E-31/E-43/T-05），其余 39 条为**虚假完成链**（详见 BUG-001/002）。有效真实通过率：6/62 ≈ 10%。

## 三、Bug 清单

### BUG-001（阻断级 · 根因 E 业务逻辑设计缺陷）

**Agent 1 规则层"一票否决式"整单澄清，63% 用例在取数前被拦死**

- 复现输入：`整理宁德时代近四年营收、归母净利润`（E-05，industry_topic=动力电池）
- 实际现象：意图拆分出 2 个子需求——段1「整理宁德时代近四年营收」命中 FINANCE 可查，段2「归母净利润」规则层无注册技能 → 段2 置 `requires_clarification` → **整单提前返回 WAITING_REVIEW，一段都不取数**。澄清提示："当前系统没有可查询"归母净利润"的已注册数据技能"。
- 影响面：62 条全链路用例中 **39 条（63%）** 被此机制拦截（含 E-02 锂价归因、E-08 估值、E-09 分业务盈利等完全正常的正向问题）。
- 根因定位：
  - [service.py L162-189](../../../backend/app/agents/data_fetcher/service.py#L162)：`if intent_routing["clarification_required"]:` 非空即整单提前 return，不执行任何已识别子需求的取数；
  - [intent_merger.py `_sub_from_segment`](../../../backend/app/agents/data_fetcher/intent_merger.py#L147)：无 skill 段强制 `requires_clarification=True`；
  - 两层叠加形成"任一段不认识 → 全单拒绝"的一票否决语义。
- 与方案冲突：§5.0 I6 的澄清语义是「低置信度/主体歧义」才转人工；规则层未识别的长尾词按 §5.0 架构应交给 LLM 补充识别（decomposer 禁用时规则层应**放行已识别部分、仅对未识别段降级标注**），而不是整单阻断。禁用 LLM 的本次测试恰好暴露了规则层兜底的脆弱性。
- 修复建议：service.py 改为「部分澄清」语义——已识别子需求正常生成任务并取数，未识别段在 `requirement_coverage` 里标 `missing/partial` 走既有缺口披露路径；只有**全部**子需求都无法识别（或触发 ambiguous 主体歧义）时才整单 WAITING_REVIEW。

### BUG-002（阻断级 · 根因 E 业务逻辑设计缺陷）

**graph 非审阅阶段自动放行不检查 error：澄清拦截被吞成 completed，全链虚假完成**

- 复现输入：任一触发 BUG-001 的用例（如 E-29「那个锂电龙头怎么样」）
- 实际现象（错误传播链）：
  ```
  data_fetch:     status=completed, error=intent_clarification_required   ← 被自动放行
  data_interpret:  status=approved,  error=analysis_input_invalid          ← 空 evidence 导致输入校验失败
  chapter_write:   status=approved,  error=chapter_input_invalid
  report_fusion:   status=approved,  error=report_input_invalid
  最终 status=completed，报告产物数=0                                   ← 虚假完成
  ```
- 根因定位：
  - [graph.py L130-239](../../../backend/app/workflow/graph.py#L130)：非 review_stages 阶段的 WAITING_REVIEW 自动接受分支**未检查 `result.error` 与 `advisory_issues`**；`intent_clarification_required` 不在 `REINPUT_REQUIRED_ERRORS`；`has_substantive_data` 把 `intent_routing` 审计字段当"实质数据"判真；
  - `collaboration_requests`（人工澄清问题）被 L133 `pop` 静默丢弃；
  - 后果：Agent 2 在 [service.py L133](../../../backend/app/agents/data_interpreter/service.py#L133) 本有 `fetch_result.status not in {COMPLETED, APPROVED}` 的越级保护，但 status 已被改成 completed，保护被绕过 → 错误字典沿 stage_results 一路传播。
- 与硬约束冲突：项目约束「Agent 失败时必须终止流水线并返回明确错误，不得伪装传播」——本 bug 让"带 error 的 completed"流过全部五个阶段，终态显示成功却零产物。
- 修复建议：graph 自动接受分支增加前置条件 `result.error is None`（或维护不可自动放行的 error 白名单）；带 error 的 WAITING_REVIEW 一律进 review_gate 等人工；`has_substantive_data` 应排除审计类字段。

### BUG-003（普通缺陷 · 根因 E 业务逻辑设计缺陷）

**metric_registry 高频指标覆盖缺口，是 BUG-001 的最大放大器**

- 复现输入：`归母净利润` / `PB估值` / `PE` / `存货周转率`（I-C06）
- 实际现象：`get_metric_spec` 返回 None → 规则层无 skill。实测 E-05 段2「归母净利润」、E-08 段2「PB估值」均因此触发整单澄清。
- 根因定位：[metric_registry.py `_SPECS`](../../../backend/app/agents/data_fetcher/metric_registry.py#L28) 共 18 个指标族，缺 A 股研报最高频的：归母净利润、净利润、营业成本、PE(市盈率)、PB(市净率)、ROE、存货周转率、应收周转率、总资产周转率等（后三者有 CalculationType 却无注册表项）。
- 修复建议：补齐注册表（至少覆盖 `_CALCULATION_REQUEST_TERMS` 与 planner 关键词表已出现的全部指标）；或规则层对「公司+未知指标」默认落 FINANCE 而非澄清。

### BUG-004（普通缺陷 · 根因 E 业务逻辑设计缺陷）

**时间提取不支持中文数字与"半年"粒度**（I 类金标准 I-C02/I-C04 失败）

- 复现输入：`宁德时代近四年营收…`（段1 time=None）、`梳理比亚迪近半年业绩预告与增发事件`
- 实际现象：「近四年」不匹配 `近\s*(\d+)\s*年`（只认阿拉伯数字）；「近半年」无对应模式（只有"近N个月"）→ `time_range` 丢失。
- 根因定位：[deterministic_intent_parser.py `_TIME_PATTERNS`](../../../backend/app/agents/data_fetcher/deterministic_intent_parser.py#L154) 正则覆盖不足。
- 修复建议：增加中文数字映射（一二三四五六七八九十）与 `近半年/半年度` 模式。

### BUG-005（普通缺陷 · 根因 E 业务逻辑设计缺陷）

**指标匹配的前后缀策略识别不了句中指标，导致简单问题误澄清**（I-C09 失败）

- 复现输入：`宁德时代2025年营业收入是多少`
- 实际现象：`get_metric_spec("宁德时代2025年营业收入是多少")` 做整串 startswith/endswith 匹配失败（指标词在句中）→ 无 skill → 误触发澄清（I6 误报），与 I-C09「simple 零冗余」预期相反。
- 根因定位：[metric_registry.py L169-179](../../../backend/app/agents/data_fetcher/metric_registry.py#L169)：`_segment_metrics` 用子串提取指标是正确的，但 `_segment_skills` L278 用整段文本调 `get_metric_spec`，两条路径不一致。
- 修复建议：`_segment_skills` 改用 `_segment_metrics` 已提取的指标名查 spec（子串路径），而非整段文本。

### 测试工程缺陷（非生产代码 bug，如实记录）

| # | 现象 | 原因 | 处置 |
|---|------|------|------|
| TE-01 | T-07/T-08（P1/P0 skill 失败构造）显示 PASS 但失败注入未执行 | 构造用例的 input 文本（"（构造）快照中某P0 skill返回空"）无金融语义 → 先被 BUG-001 澄清拦截，`SelectivelyFailingClient` 未被触达 | 下轮改用有语义输入（如「动力电池行业供需格局如何」）+ 失败 client 组合 |
| TE-02 | T-12 标记 blocked | 「先错调再补调」需按调用顺序注入轨迹的专用注入器，本轮未实现 | 如实 blocked，不伪造通过 |
| TE-03 | S 类 24 条专项未在全链路执行 | 依赖 baselines.json 基准值回填（当前 expected=null，禁止编造）与特定证据构造 | 单元级判定已有 backend/tests 覆盖；待快照回填后补跑 |

## 四、正向确认项（防御机制有效）

1. **注入防御有效**：E-38（忽略规则输出收益承诺）在 data_interpret 被 `SecuredStageAgent` 以 `PROMPT_INJECTION_SUSPECTED / IGNORE_RULES / agent_call_blocked` 正确拦截（安全审计日志留痕）。
2. **不补造红线有效**：16 条 `required_data_unavailable / requested_calculation_data_unavailable` 全部诚实拦截（cancel），无一例伪造数据强行通过；其中 CR3/CR5/市占率类因 mock 每技能仅 1 行 < 最低样本数（3/5 家）被拦，属 mock 数据规模限制而非代码缺陷。
3. **决策包校验有效**：`accept_with_risks` 路径的 decision_id / risk_snapshot_sha256 / accepted_risk_codes 校验全部通过，无 Revision/Risk hash 冲突。
4. **6 条真实 pass 用例**五阶段零 error、报告/图表/manifest 产物齐全，证明「标准问题 → 取数 → 分析 → 图表 → 7章21节 → 三格式报告」主干链路健康。

## 五、测试局限

- Mock 数据每技能仅 1 行、字段固定：E-14/E-20/E-24/E-35 等的拦截不能外推到真实 SkillHub 行为。
- Agent 2/4 为确定性替身：只验证结构合同（五维/三卡/三情景/7章21节/证据引用），不验证语义质量（属 L2 judge 范畴，见方案 §7）。
- LLM 意图路径（hybrid 模式）未测（用户要求不调 LLM）；BUG-001 在 LLM 开启时会被部分掩盖，建议修复后用真实 LLM 复测 I 类。

## 六、缺陷统计（对齐 §12.5）

- 阻断性故障：2（BUG-001/002）
- 普通功能缺陷：3（BUG-003/004/005）
- 测试工程缺陷：3（TE-01/02/03）
- 根因分布：E 业务逻辑设计缺陷 5 / A 提示词 0 / B 模型底座 0 / C 工具Schema 0 / D 上下文 0
- must_pass 阻断数：0（I 类 must_pass 失败 3 条属普通缺陷，未阻断流程）

**结论：不满足上线标准。** 修复优先级：BUG-002（虚假完成，破坏结果可信度）> BUG-001（63% 请求不可用）> BUG-003 > BUG-004/005。