
# 真实全链路测试 Bug 根因分析报告（五智能体 L4 层）

- 日期：2026-08-21
- 依据方案：docs/EVALUATION_PLAN.md（V7）L2/L4 执行分层 + §12 根因归因规范
- 测试环境：真实 SkillHub（问财）+ 真实 LLM（deepseek-v4-pro），LLM_USE_MOCK=false、SKILLHUB_USE_MOCK=false
- 测试方式：pytest 真实链路测试（tests/integration/test_real_full_chain.py，1 passed）+ 4 次全链路诊断驱动（含 1 次超时隔离重试）+ L2 契约测试 9/9 通过
- 证据落盘：test_output/caseA4_stage_results.json（五阶段完整 StageResult）、backend/artifacts/run-real-caseA4/（报告产物）、backend/artifacts/run-real-caseA/（首轮产物）

## 0. 测试覆盖与总体结论

| 智能体 | 是否真实测到 | 结果 | 结论 |
|--------|:---:|------|------|
| Agent 1 数据获取 | 是（5 次真实取数，108-116 条证据/次） | 全部成功 | **通过**：意图拆分（compound→2 子需求）、FINANCE+BUSINESS 双 Skill 混合路由、确定性校准均正确 |
| Agent 2 数据解读 | 是（成功 2 次 / 拦截 3 次 / 超时 2 次） | 部分失败 | **不通过**：BUG-001 假阴性拦截、BUG-002 偶发超时 |
| Agent 3 图表生成 | 是（2 次完整执行） | 流程通过、产物失败 | **不通过**：BUG-004 图表候选 4/4 全部被抑制，报告 0 图表 |
| Agent 4 章节撰写 | 是（2 次完整执行） | 兜底成功、主路径失败 | **有条件通过**：BUG-005 LLM 结构化输出 12 处验证错误，确定性 fallback 兜底产出 7 章 21 节 |
| Agent 5 报告融合 | 是（2 次完整执行） | 成功 | **通过**：MD/HTML/PDF/manifest 四产物齐全，7 章 21 节，引用闭合，诚实降级 ready_with_limits |

测试基线：L2 跨智能体交接契约测试 9/9 通过（tests/integration/test_agent_handoffs.py）。

---

## 1. BUG-001：Agent 2 毛利率「假阴性拦截」（有数据判无数据）

- **被测对象**：Agent 2（data_interpreter）
- **故障等级**：普通功能缺陷（高频触发：任何含派生指标的用户问题）
- **复现输入**：focus_questions = ["整理宁德时代近四年营业收入、归母净利润、毛利率及主营业务构成"]
- **实际现象**：Agent 1 真实取回 116 条证据，其中包含**问财直接披露的毛利率值 x5、营业成本 x4**；Agent 2 仍返回 error=requested_calculation_data_unavailable，blocking_issues 提示 2022-2025 四个年度"已取得营业收入，但缺少同口径营业成本，毛利率不可计算"，整单被取消，Agent 3/4/5 未执行。复现 3/3 次（稳定）。
- **原始快照片段**（caseA 系列诊断，calculation_issues）：

  ```json
  [{"calculation_type": "gross_margin", "entity_scope": "宁德时代", "period_end": "2022-12-31",
    "reason": "已取得营业收入，但缺少同口径营业成本，毛利率不可计算。",
    "missing_inputs": ["营业成本"], "evidence_ids": ["E-8c709e805c539f17"]},
   ... 2023/2024/2025 同构 ...]
  ```

  同一证据池 metric 直方图：`毛利率 x5、营业成本 x4、营业收入 x8、归母净利润 x8`。
- **根因分类**：E（业务逻辑缺陷）。触发链：
  1. [service.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_interpreter/service.py) `_CALCULATION_REQUEST_TERMS` 将用户问题中的"毛利率"映射为计算型指标；
  2. [calculations.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_interpreter/calculations.py) `calculate_p0_metrics` 仅按「同 period 的 revenue+cost 原始科目」重算毛利率，`_DERIVED_METRIC_TOKENS` 把已披露的"毛利率"证据排除在计算输入之外；
  3. 营业成本证据与年度 period 不对齐（真实数据源只返回了部分期间），四个年度全部判 missing_inputs；
  4. `_requested_calculation_gaps` 发现用户要求了毛利率且重算失败 → 整单拦截。
  系统从不消费已披露的毛利率值（fact 级证据），形成"数据源给了、系统不用、还判没有"的假阴性。
- **修复建议**：`_requested_calculation_gaps` 在拦截前先检查证据池是否存在「已披露的派生指标值」（按 _CALCULATION_REQUEST_TERMS 的中文词反查 metric_name）：存在则不拦截，将披露值作为 fact 输出并标注口径未验证；或 Agent 1 意图拆解时把派生指标展开为原料指标（营业收入+营业成本）的取数需求。两案取其一即可消除整单拦截。
- **测试结论**：Agent 2 不满足上线标准，直至本缺陷修复。

## 2. BUG-002：Agent 2 真实 LLM 分析偶发 stage_timeout

- **被测对象**：Agent 2（data_interpreter）+ 运行时策略
- **故障等级**：阻断性故障（4 次运行 2 次触发）
- **复现输入**：同 BUG-001 用例（去掉毛利率的用例 A 同样触发）
- **实际现象**：data_interpret 返回 error=stage_timeout（status=failed），review_gate 正确拒绝 approve（"failed stage cannot be approved"）。成功轮次 Agent 2 耗时约 170-260 秒（deepseek-v4-pro 处理 108 条证据 + 结构化输出）。
- **原始快照片段**：

  ```
  [interrupt 1] stage=data_interpret error=stage_timeout
    decision: approve
    resume ValueError: failed stage cannot be approved; regenerate, revise, or cancel
  FINAL status: waiting_review
  ```

- **根因分类**：E（业务逻辑缺陷）为主。`app/runtime/models.py` 中 `stage_timeout_seconds` 默认 180 秒，与真实 LLM 分析时长（170-260s 抖动）没有安全余量；同一用例在 180s 阈值下 4 次中 2 次超时。
- **修复建议**：将 stage_timeout_seconds 默认值提升至 600s（或按 analysis_depth 分级），并为 Agent 2 内部 LLM 调用增加进度心跳与单调用超时，避免整阶段一刀切失败；超时后应支持自动降级（证据摘要模式）而非直接 failed。
- **测试结论**：Agent 2 在真实 LLM 延迟抖动下稳定性不足。

## 3. BUG-003：settings.STAGE_TIMEOUT_SECONDS 配置不贯通（仅 API 入口生效）

- **被测对象**：workflow graph 构建路径
- **故障等级**：普通功能缺陷（影响测试/脚本/二次集成）
- **复现输入**：诊断脚本中 `settings.STAGE_TIMEOUT_SECONDS = 600` 后直接 `build_pipeline_graph(registry, checkpointer=...)`
- **实际现象**：Agent 2 仍在约 180 秒超时——settings 覆盖无效。
- **根因分类**：E（业务逻辑缺陷）。[graph.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/workflow/graph.py) `build_pipeline_graph` 不传 runtime_policy 时使用 `RuntimePolicy()` 默认值（stage_timeout=180）；settings 值仅在 `app/main.py`（API 入口）显式传入。两条构建路径配置不一致。
- **修复建议**：`build_pipeline_graph` 在 runtime_policy 缺省时从 settings 读取默认值（单一事实来源），或在文档中强制要求显式传 policy。
- **测试结论**：不阻断主流程（API 路径正常），但必须修复以保证可配置性与测试可重复性。

## 4. BUG-004：Agent 3 图表候选 4/4 全部抑制（报告 0 图表）

- **被测对象**：Agent 3（chart_generator）
- **故障等级**：阻断性故障（本轮真实环境 100% 复现，报告无任何图表）
- **复现输入**：用例 A（"整理宁德时代近四年营业收入、归母净利润及主营业务构成"）
- **实际现象**：chart_generate 阶段 status=completed 但 quality.passed=false，ready_count=0、suppressed_count=4，issues=[no_matching_dataset, no_ready_charts]；报告 manifest included_chart_count=0，HTML/PDF 中无图表。Agent 2 的 4 个图表候选（营收净利 combo、同比增速 line、归母净利率 line、产业链示意）全部被抑制。
- **原始快照片段**（suppressed_candidates）：

  ```json
  {"title": "宁德时代2022-2025年营业收入与归母净利润", "reason_code": "no_matching_dataset",
   "reason": "没有找到与证据编号匹配的数据集",
   "evidence_ids": ["E-0f3287a7c16d930c", "E-2a0e44c5646385c0", "E-22ece49e216c0e5b", "E-18ead7ddb5ab5382",
                    "E-b2803a15e8085e6b", "E-2c7bcc3ff0b98cee", "E-6b54fdfffec2d409", "E-a944f2396b3d4bcf"]}
  ```

- **根因分类**：E（业务逻辑缺陷），含两个独立子根因，均已用落盘数据实锤：
  - **C1 匹配规则与数据形态结构性失配**：[datasets.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/chart_generator/datasets.py) `match_datasets` 要求「候选的全部 evidence_ids ⊆ 某一**单个** dataset」。而多指标图表候选（营收+净利润 8 个证据）天然横跨两个按指标切分的 dataset（DS-1c5df4e92519 归母净利润 4/8 + DS-a4375a6dff02 营业收入 4/8）——每个 dataset 都只覆盖一半，issubset 永远为 False。len(matched)>1 的"多数据集择优"分支实际不可能命中这种形态（它只处理多个 dataset 各自都完整包含候选全集的罕见情形）。三个指标类候选全部因此被抑制。
  - **C2 产业链 dataset 覆盖缺口**："动力电池产业链结构示意"候选引用 3 条定性研报证据，在 Agent 1 产出的全部 21 个 chart_datasets 中**零覆盖**（无任何 industry_chain 类 dataset 引用这些证据）。Agent 1 只为结构化数值证据建 dataset，未把研报/新闻中的产业链描述转成 industry_chain dataset。
- **修复建议**：
  1. match_datasets 支持「多 dataset 联合覆盖」：候选证据可由 ≤N 个 dataset 的并集覆盖时，按 x 轴周期对齐合并 series 后渲染（combo/多序列 line 正是典型场景）；
  2. Agent 1 增加 industry_chain dataset 构建：对 REPORT/NEWS/INDUSTRY_CHAIN skill 的定性证据生成节点/边结构（可用确定性模板 + chain_template_hint）；
  3. 抑制原因应区分 C1/C2 两种 code，便于统计与回归。
- **测试结论**：Agent 3 不满足上线标准（当前真实环境下图表功能实际不可用）。

## 5. BUG-005：Agent 4 LLM 章节结构化输出验证失败（deepseek-v4-pro 严格 schema 遵循弱）

- **被测对象**：Agent 4（chapter_writer）
- **故障等级**：普通功能缺陷（主路径 2/2 失败，fallback 兜底生效）
- **复现输入**：用例 A 完整链路（两轮均复现）
- **实际现象**：chapter_write status=completed、7 章 21 节产出，但 quality.passed=false，issues=[chapter_fallback_used:StructuredOutputError:schema_validation_failed; validation_error_count=12]，章节级 evidence_coverage=0.0。报告仍完整交付（manifest 级 evidence_coverage=1.0），章节内容为确定性证据摘要（各章 summary 统一标注"本章依据 Agent 2 已通过校验的结论生成；未通过自动写作校验的内容已采用确定性证据摘要并标记复核边界"）。
- **原始快照片段**（chapter_write.quality.issues）：

  ```
  validation_paths=['sections.0.paragraphs.1.kind', 'sections.0.visual_semantics.content_type',
    'sections.0.visual_semantics.quantitative_density', 'sections.0.visual_semantics.suitable_for_precise_table', ...]
  validation_types=['literal_error', 'literal_error', 'float_parsing', 'extra_forbidden', ...]
  ```

- **根因分类**：B（模型底座缺陷）+ A（提示词/schema 约束不足）。deepseek-v4-pro 输出：paragraphs.kind 与 visual_semantics.content_type 使用了枚举外字面值；quantitative_density 输出了非数字（中文程度词）触发 float_parsing；额外输出 schema 未定义的 suitable_for_precise_table 字段触发 extra_forbidden。与既有经验一致（DeepSeek 系列对 Pydantic 严格校验的遵循弱于 GPT-4o/Claude）。
- **修复建议**：
  1. 提示词中给出每个受约束字段的枚举值白名单与正反例（尤其 kind/content_type/quantitative_density 数值范围）；
  2. 对 extra 字段做宽容剥离（前向兼容）而非整单拒绝；literal/float 错误做一次 temp=0 重试 + 字段级自动纠偏；
  3. 换底 A/B 验证：同用例换 GPT-4o/Claude 家族重跑，若错误消失则确认 B 类归因。
- **测试结论**：Agent 4 主路径（LLM 写作）当前不可用，fallback 路径质量可接受但不满足"智能体写作"的产品预期。

## 6. 观察项 BUG-006（次要）：Agent 2 未识别 BUSINESS 证据为主营构成

- **被测对象**：Agent 1 证据结构化 + Agent 2 证据消费
- **实际现象**：Agent 1 经 BUSINESS skill 取回主营构成数据（业务收入/业务成本/收入占比/成本占比/利润占比 各 x1，仅一期），但 metric_name 泛化（"业务收入"），分项名称（动力电池系统等）仅在旁置"项目名称"字段；Agent 2 判定"缺少主营业务构成的结构化数据"并发起 blocking 协作请求 CR-001，报告相应章节标注证据不足。
- **根因分类**：C（工具 Schema/证据结构化缺陷）。
- **修复建议**：Agent 1 规范化 BUSINESS 证据时把分项名称写入 metric_name 或 scope（如"主营业务收入-动力电池系统"），并尽量请求多年期数据。
- **测试结论**：不阻断流程，影响报告完整度。

---

## 7. 正确行为记录（非 bug，作为回归基线）

1. Agent 1 意图拆分与路由：compound 问题正确拆为 SUB-01（财务查询→hithink_finance_query，LLM 语义+确定性校准 hybrid）与 SUB-02（主营业务构成→hithink_business_query，确定性规则），无澄清、无误路由。
2. review_gate 防呆：failed stage（stage_timeout）禁止 approve，抛出明确指引（regenerate/revise/cancel）。
3. 前视偏差与元数据分区：`_partition_evidence` 正确隔离缺 available_at/source_locator、E 级证据。
4. 诚实降级：图表/章节质量门未过时，报告仍交付但标记 ready_with_limits，issues 透出两个质量门失败原因，无伪造图表/数据。
5. Agent 5 产物完整：report.md（27KB）/report.html（43KB，7 章 21 节+目录+证据索引）/report.pdf（1.27MB）/manifest.json（sha256 校验齐全），引用闭合（manifest evidence_coverage=1.0）。
6. 真实凭证 fail-closed：无 mock 断言与凭证检查在 pytest fixture 生效（首轮被全局 conftest 强制 mock 拦截后，经 integration 局部 conftest 解除，测试代码自身断言未放松）。

## 8. 缺陷统计与门禁结论

| 统计项 | 数值 |
|--------|------|
| 阻断性故障 | 2（BUG-002 超时、BUG-004 图表全抑制） |
| 普通功能缺陷 | 4（BUG-001、BUG-003、BUG-005、BUG-006） |
| A 提示词缺陷 | 1（BUG-005 共因） |
| B 模型底座缺陷 | 1（BUG-005 共因） |
| C 工具 Schema 缺陷 | 1（BUG-006） |
| D 记忆/上下文缺陷 | 0 |
| E 业务逻辑缺陷 | 4（BUG-001、BUG-002、BUG-003、BUG-004） |

**上线结论：BLOCK。** must_pass 维度上 Agent 2（假阴性拦截、超时）与 Agent 3（图表全抑制）不达标。修复优先级：BUG-004（C1 匹配规则）> BUG-001（披露值回退）> BUG-002/003（超时与配置贯通）> BUG-005（schema 约束/重试）> BUG-006。

## 9. 测试执行记录

| 轮次 | 入口 | 用例 | 结果 |
|------|------|------|------|
| 1 | pytest tests/integration/test_agent_handoffs.py | 7 类交接契约 | 9/9 通过 |
| 2 | pytest tests/integration/test_real_full_chain.py | 含毛利率用例 | 1 passed（诚实拦截：A2 拦截→cancelled，暴露 BUG-001） |
| 3 | 诊断脚本 diagnose_real_chain.py | 含毛利率用例 | A1 成功 116 证据→A2 拦截（BUG-001 复现） |
| 4 | 诊断脚本 diagnose_agent2_block.py | 含毛利率用例 | BUG-001 calculation_issues 全量落盘 |
| 5 | 诊断脚本 diagnose_full_chain_caseA.py | 用例 A（无毛利率） | 全链路 completed，产物齐全（暴露 BUG-004/005） |
| 6 | 诊断脚本 diagnose_full_chain_caseA2.py | 用例 A | A2 stage_timeout（BUG-002，settings 覆盖无效暴露 BUG-003） |
| 7 | 诊断脚本 diagnose_full_chain_caseA3.py | 用例 A | A2 stage_timeout 复现 |
| 8 | 诊断脚本 diagnose_full_chain_caseA4.py | 用例 A（显式 RuntimePolicy 600s） | 全链路 completed，五阶段 StageResult 落盘（BUG-004 双子根因实锤） |

附：诊断脚本与落盘快照位于 test_output/（diagnose_*.py、inspect_*.py、caseA4_stage_results.json），产物位于 backend/artifacts/run-real-caseA/ 与 run-real-caseA4/。
