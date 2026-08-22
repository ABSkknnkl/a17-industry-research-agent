# 全链路测试 Bug 汇总报告 V2（record 模式 + 真实大模型）

日期: 2026-08-21
测试依据: [docs/EVALUATION_PLAN.md](../../../docs/EVALUATION_PLAN.md) V6（§2.6 用例级隔离 / §5 用例集 / record 快照录制）
测试驱动: [eval/run_pipeline_eval.py](../../../eval/run_pipeline_eval.py)（record 模式改造版）
grades 归档: `test_output/eval_full_pipeline/transcript/20260821T070650Z/grades.jsonl`
trace 快照: `eval/traces/`（55 条全部录制成功，0 失败）
上轮报告: [BUG_REPORT.md](BUG_REPORT.md)（mock 全链路，2026-08-20）

---

## 一、测试执行方式声明

| 项 | 说明 |
|----|------|
| 模式 | **Record 快照录制**（非 Replay 回放）：每条用例执行完成后用 `eval.transport.save_trace` 落盘完整 trace（stage 流转 + SkillHub 调用流水 + intent_routing 摘要 + verdict）到 `./eval/traces/`，目录自动创建 |
| SkillHub | MockSkillHubClient（provider_mode="live"，与 backend 官方测试同装配），经 `TraceRecordingClient` 旁路录制每次 execute（skill/query/page/rows/raw_sha256/耗时/错误） |
| 大模型 | **调用项目真实大模型**（用户本轮许可）：Agent 1 意图拆解器 = `ResearchIntentDecomposer`（DeepSeek-v4-Pro，settings.LLM_*，超时/校验失败自动回退规则层）。Agent 2/4 保持确定性 Mock 模型（用户指令第 2 点 Mock-LLM；且上一轮失败根因 100% 在意图层，Agent 2/4 换真实 LLM 会引入结构化输出失败噪声，无法归因） |
| 用例范围 | 62 条中跳过上轮已真实通过的 6 条（E-01/06/13/31/43/T-05），**重点测未通过的 56 条**（55 真实执行 + T-12 轨迹构造类维持 blocked） |
| 用例级隔离 | 每条独立 LangGraph thread + 240s 超时 + 最多 8 轮审阅 resume；单条阻断不终止整套测试 |
| 未启用 | mutators / triage / scorers（用户指令第 4 点：本轮只做真实执行 + 录制快照） |
| 耗时 | 55 条 × 平均 6s ≈ 5.5 分钟（LLM 调用为主） |

## 二、结果汇总

| 判定 | 数量 | 明细 |
|------|:---:|------|
| **真实通过** | **3** | E-07、T-04、T-09（五阶段零 error，tasks=14/skill_calls=14/evidence=14，4 件报告产物齐全） |
| 虚假完成 | 41 | 表面 pass、零报告产物（BUG-001+002，详见下） |
| 真实拦截 | 11 | E-08/15/16/21/25/44/45/50、T-02/03/10（LLM 路由成功 → 真实取数 11-17 次调用 → 数据质量合法拦截） |
| blocked | 1 | T-12（轨迹构造类，注入器未实现） |
| **trace 录制** | **55 成功 / 0 失败** | `eval/traces/{case_id}__{run_id}.json` |

**LLM 层表现**：parser_mode 分布 hybrid 53 / fallback 2——真实大模型拆解成功率 96%，且 2 条 fallback（E-33 负向诱导等）均正确回退规则层未崩溃。

## 三、Bug 清单

### BUG-001（阻断级 · 根因 E 业务逻辑设计缺陷）【上轮已报，本轮实锤加重】

**Agent 1「任一澄清 → 整单拒绝取数」语义在真实 LLM 下拦截面扩大到 73%**

- 本轮数据：56 条中 41 条（73%）被 `intent_clarification_required` 在取数前拦死（上轮 mock 规则层为 63%）。
- 触发路径两条：
  1. 规则层无技能（上轮 BUG-001 原路径，如 E-33）；
  2. **新增路径：LLM 自己返回 clarification_questions**（本轮主要触发源）。
- 根因定位：
  - [service.py L162-189](../../../backend/app/agents/data_fetcher/service.py#L162)：`if intent_routing["clarification_required"]:` 非空即整单提前 return WAITING_REVIEW，一个已成功路由的子需求都不执行；
  - [intent_merger.py L425-432](../../../backend/app/agents/data_fetcher/intent_merger.py#L425)：LLM 的 `clarification_questions` 被**无条件**并入 `requires_clarification`，即使对应子需求已 100% 成功路由（trace 实证：E-05 的 sub source=hybrid、skills=[FINANCE]、clarify=False，但 plan 级 requires_clarification=True）。
- 修复建议：service.py 改为「部分澄清」——已路由子需求正常取数，澄清问题作为 advisory 附带；仅当**全部**子需求失败或主体歧义时才整单拦截。

### BUG-002（阻断级 · 根因 E 业务逻辑设计缺陷）【上轮已报，本轮 41 条复现】

**graph 非审阅阶段自动放行不检查 error：41 条"带 error 的 completed"流过全部五阶段，终态 completed、零产物**

- 复现（E-05 真实 LLM 本轮 trace）：
  ```
  data_fetch:     approved, error=intent_clarification_required   ← 被自动放行
  data_interpret:  approved, error=analysis_input_invalid
  chapter_write:   approved, error=chapter_input_invalid
  report_fusion:   approved, error=report_input_invalid
  终态 completed，report_artifacts=[]，skill_calls=0，evidence=0
  ```
- 根因定位：[graph.py L130-239](../../../backend/app/workflow/graph.py#L130) 自动接受分支不检查 `result.error`；`has_substantive_data` 把 `intent_routing` 审计字段当实质数据。
- 危害升级：本轮 41/56（73%）用例呈现虚假成功，**真实通过率 3/56 ≈ 5%**，而表面通过率 79%。结果可信度被完全破坏。

### BUG-006（新增 · 普通缺陷 · 根因 A 提示词缺陷）

**LLM 对相对时间过度澄清：可默认的时间范围被当成必答问题**

- 复现输入与 LLM 澄清问题（真实 DeepSeek 返回）：
  - E-05 `整理宁德时代近四年营收、归母净利润` → "请确认'近四年'的具体年份范围，例如2021-2024年还是2022-2025年。"
  - E-02 `最近锂价持续下跌的核心原因是什么` → "请确认'最近'的时间范围（如近1个月、近3个月、2025年以来）……"
  - E-14 `锂电池行业CR3、CR5市场占有率变化` → "请明确需要查询的时间范围，例如近3年、近5年或具体年份区间。"
- 根因定位：[semantic_router.py `_DECOMPOSER_SYSTEM_PROMPT`](../../../backend/app/agents/data_fetcher/semantic_router.py#L246) 未告知 LLM「相对时间（近N年/最近/近期）可按 research_as_of 默认前推，无需澄清」——planner 本有该兜底（`_intent_skill_query` 的 time_part 默认 `{research_as_of.year-1}年 {research_as_of.year}年`），但提示词没把这个约定告诉模型，模型按通用金融助手习惯把时间歧义当阻断项提问。
- 归因：**A 提示词缺陷**（约束缺失），被 BUG-001 放大成整单拦截。
- 修复建议：system prompt 增加一条："相对时间表述（近N年/最近/近期/近半年）无需澄清，直接透传 raw_text 由确定性层默认处理；只有主体（哪家公司/哪个行业）歧义才输出 clarification_questions"。

### BUG-007（新增 · 普通缺陷 · 根因 E 业务逻辑设计缺陷 + A 次生）

**引入真实 LLM 后 9 条用例行为退化：从「诚实拦截」退化为「虚假完成」**

- 上轮 intercept → 本轮虚假 pass 的用例：E-14/18/19/20/24/32/35/41/42、T-01（共 10 条，含 E-14）
- 退化机理：上轮这批用例规则层能路由（无澄清）→ 真实取数 → `required_data_unavailable` 诚实拦截；本轮 LLM 对时间范围提问 → 整单澄清拦截（BUG-001）→ 虚假完成（BUG-002）。
- 例：E-14（CR3/CR5 市占率）上轮在 data_fetch 阶段合法拦截并提示重新提交；本轮 LLM 问"时间范围"后整单拦死、终态却显示 completed。
- 根因：BUG-006（过度澄清）× BUG-001（整单拦截）× BUG-002（虚假完成）三者叠加；单独修任何一处都不会退化。
- 修复建议：按 BUG-006 → BUG-001 → BUG-002 顺序修复后必须回归这 10 条用例。

### BUG-008（新增 · 观察项 · 根因 E 业务逻辑设计缺陷）

**LLM 的合理澄清（主体歧义）被虚假完成掩盖，正确拦截行为无法呈现**

- 复现：E-29 `那个锂电龙头怎么样`，LLM 正确提出 "请问您指的是哪家锂电龙头公司？"——这正是方案 §5.0 I6 期望的应澄清场景（模糊主体召回）。
- 但该正确澄清经 BUG-001 整单拦截 + BUG-002 自动放行后，最终呈现为"五阶段全部完成"零产物——正确行为被包装成虚假成功，评测与用户都无法看到"系统其实在正确地问澄清问题"。
- 修复建议：BUG-001/002 修复后，requires_clarification 的正确终态应为 WAITING_REVIEW + collaboration_requests 呈现澄清问题（service.py 本已实现该返回，是被 graph 吞掉了）。

### 上轮遗留 bug 的本轮表现

| 上轮 Bug | 本轮状态 |
|---------|---------|
| BUG-003 指标注册表缺口 | 被 LLM 层**掩盖**（LLM 能识别归母净利润/PB/周转率并路由），但根因仍在：LLM 关闭或 fallback 时复现（E-33 fallback 即规则层路径） |
| BUG-004 时间提取中文数字/半年 | 同上被掩盖；LLM raw_text 透传绕过了规则层正则，但 fallback 路径仍失败 |
| BUG-005 指标句中识别 | 同上被掩盖 |
| TE-01 T-07/T-08 构造失败注入未触达 | **已修复效果**：本轮 T-07/T-08 仍被澄清提前拦（intent 层先于失败注入），失败注入依旧未触达——构造类用例需与有语义输入组合，遗留 |

## 四、正向确认项（真实 LLM 下新增）

1. **LLM 拆解质量高**：53/55 hybrid 成功；E-05 正确拆为 1 个子需求并路由 FINANCE（上轮规则层拆成 2 段且段 2 失败）；E-07/T-04/T-09 无澄清全链真实通过，报告 4 件产物齐全。
2. **回退机制有效**：2 条 fallback（含 E-33 负向诱导"数据不够你就补一下"）正确回退规则层，零崩溃，符合 §5.0 I7 期望。
3. **11 条真实取数拦截诚实**：LLM 路由 → 11-17 次 skill 真实调用 → 证据 7-14 条 → mock 数据不满足要求时 `required_data_unavailable` 诚实拒绝，无伪造。
4. **注入防御持续有效**：E-38（忽略规则输出收益承诺）再次被 `PROMPT_INJECTION_SUSPECTED/IGNORE_RULES` 拦截（安全审计留痕）。
5. **决策包校验持续有效**：本轮所有 accept_with_risks 路径的 decision_id/risk_snapshot_sha256 校验通过。

## 五、trace 快照目录说明

- 路径：`/Users/Zhuanz1/PycharmProjects/同花顺/eval/traces/`（55 个 JSON，0 失败）
- 单文件结构：`case_id / run_id / mode=record / llm_mode / input / verdict / stages[] / intent_routing（parser_mode·locked/accepted/rejected_skills·子需求明细）/ skill_calls[]（每次调用的 query·rows·raw_sha256·duration）/ evidence_count / task_count / report_artifacts`
- 用途：BUG-001/006 的根因均直接从 trace 的 `intent_routing.plans[].requires_clarification` 与子需求明细实证；后续修复后可用同输入重跑对比（record→replay 基线）。

## 六、缺陷统计（对齐 §12.5）

- 阻断性故障：2（BUG-001/002，本轮 41 条用例受影响）
- 普通功能缺陷：3（BUG-006 过度澄清 / BUG-007 行为退化 / BUG-008 合理澄清被掩盖）
- 遗留未修：上轮 BUG-003/004/005（被 LLM 层掩盖，根因仍在）、TE-01
- 根因分布：E 业务逻辑设计缺陷 4 / A 提示词缺陷 1（BUG-006，另为 BUG-007 次因）/ B 模型底座 0 / C 工具Schema 0 / D 上下文 0
- must_pass 阻断数：0

**结论：不满足上线标准。** 真实通过率 3/56 ≈ 5%（表面 79%）。修复优先级：
**BUG-002（虚假完成，破坏一切结果可信度）> BUG-001（整单拦截，73% 请求不可用）> BUG-006（提示词补相对时间约定，改动最小收益最大）**；BUG-006 修复即可让大部分时间类澄清消失，预计能把 41 条虚假完成中的多数转为真实执行或诚实拦截。修复后需回归：本轮 41 条 + 上轮 10 条退化用例 + 3 条真实通过用例。