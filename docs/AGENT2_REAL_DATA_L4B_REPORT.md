# Agent 2 真实数据一次性冒烟（L4b）：运行记录与失败根因分析

- 日期：2026-09-01 22:37（UTC+8）
- 范围：仅智能体 2（`data_interpret`）；真实分析模型 **deepseek-v4-flash**；按约束**只跑一次**
- 结论先行：运行以 `analysis_generation_failed / schema_validation_failed` 收口。模型已生成近乎完整的结构化草稿，但 3 轮结构修复后仍残留 2 处校验违规；**这是防线（无证据引用的 claim 必须被拦）正常工作，不是数据丢失或基础设施故障**。金融分析结果本轮未产出。

---

## 1. 数据来源（真实接口数据，未重新请求问财）

用户要求复用"之前测试智能体 1 用的真实接口数据"。L4b 一次性冒烟（Agent 1 侧）当次仅持久化了摘要字段、129 条证据正文未落盘，因此改为从**工作流检查点库**提取历史真实运行的完整 Agent 1 产物：

| 项 | 值 |
|---|---|
| 来源库 | `backend/data/checkpoints.sqlite`（`JsonPlusSerializer.loads_typed` 解码） |
| 选中 run | `9c082ed3-6cf1-4945-8cc4-8c315d498771`（检查点中最近一次 `approved` 且证据量充足的运行） |
| 主题 | 动力电池行业 2023-2026 发展态势 |
| 证据 | 129 条真实问财证据（`provider_mode=live`），12 次技能调用记录 |
| 焦点问题 | 装机量及增速趋势 / 宁德时代、比亚迪、中创新航份额对比 / 碳酸锂价格与成本影响 / 主要企业研发投入规模及占比 |
| research_as_of | 2026-08-31，analysis_depth=standard |

提取产物：`agent1_real_stage_result.json`（工作区，71KB 提示词与证据原文均已留存）。

## 2. 执行方式

- 一次性脚本（工作区 `l4b_agent2_smoke.py`）：构造 `StageContext(previous_results={DATA_FETCH: 真实阶段产物})` → `DataInterpreterAgent(model=create_analysis_model(settings))`；
- `ENVIRONMENT=production`，启动前 `runtime_configuration_issues` 预检通过（零 mock）；
- 包裹模型捕获真实 runtime prompt（只记录、零行为差异）；
- **仅执行一次**，失败后未重试（遵守"只跑一次"约束）。

## 3. 结果与失败定位（证据链）

| 观测 | 值 |
|---|---|
| 终态 | `failed / analysis_generation_failed`（error_type=`StructuredOutputError`，error_code=`schema_validation_failed`，**retryable=True**） |
| 模型 / Prompt | deepseek-v4-flash / `global-equity-analysis-v2` |
| runtime prompt 长度 | 55,884 字符 ≥ 分段阈值 10,000 → 走分段生成（核心 + 补充两小 Schema，服务端合并终检） |
| 修复轮次 | 工厂配置 `max_repair_attempts=3`，修复回合冻结金融事实仅修结构（日志 4 条 structured output 事件） |
| 残留违规 | `claims.7.evidence_ids`（too_short：出现无证据引用的结论）、`validation_cards.1.status`（literal_error：枚举漂移，合法值仅 `passed / differences_explained / pending_verification`） |
| 模型原始输出 | 按设计不落盘（诊断层只存模型名/路径/类型，不存证据正文与密钥） |

**根因判定**：LLM 行为类问题（方案 §4.6 的 ④ 类），非生产代码 bug。草稿已完成度很高（仅 2 处违规），修复提示已明确"不得新增/删改事实"，模型仍倾向保留一条无证据 claim 并输出近义枚举——属 flash 档模型在 5.6 万字符提示下的顽固结构漂移。防线拒绝放行是正确行为：**无证据引用的金融结论绝不进入下游**，符合 `.impeccable.md` "不牺牲真实性换完整度"原则。

## 4. 门禁对照

| 项 | 预期 | 实际 | 判定 |
|---|---|---|---|
| 真实模型单次调用链路 | 跑通并产出 AnalysisResult | 链路全通（prompt 装配、分段、修复、审计门均按设计执行），终稿校验未过 | ⚠️ 结果未产出 |
| 失败可诊断性 | 分类 + 路径 + 类型留痕 | schema_validation_failed + 2 条 validation_paths + retryable=True | ✅ |
| 防编造红线 | 无证据 claim 必须拦截 | claims.7 空 evidence_ids 被拦，未放行 | ✅（防线生效） |
| 配额纪律 | 只跑一次 | 恰好一次，失败后未擅自重试 | ✅ |

## 5. 后续选项（按方案 §4.6 ④ 类处理节奏）

1. **重试一次**（推荐首选）：漂移是概率性的，本次仅差 2 处，通过概率高；需再次授权（消耗 DeepSeek 配额，不碰问财）。
2. **结构性加固**（与 1 可并行）：在解析层做**无损枚举归一**（如"通过/已验证"→`passed`，只映射语义等价、不新增事实），并把 8 字段根因记入 ④ 类问题集攒批；无证据 claim 的拦截保持原样不动。
3. **换档验证**：`LLM_JUDGE` 槽位机制已具备，可临时把分析模型指向更强档位跑一次对比（成本更高）。

---

附：证据文件（工作区 outputs/）——`l4b_agent2_prompt_20260901T2237.json`（真实发出的 55.9k runtime prompt）、`l4b_agent2_result_20260901T2237.json`（诊断与 summary）、`agent1_real_stage_result.json`（提取的真实 Agent 1 证据包）。

---

## 6. 后续闭环（v2/v3，2026-09-01 23:20-23:40）

- **v2（授权后的带修复重试）**：白名单结构修复包装校验收口重跑一次真实调用。core 段修复 1 处枚举后通过；supplement 段模型连续 4 轮顽固输出 2 个空 evidence_ids 的 chart_candidates → 仍 `schema_validation_failed`。教训：修复提示冻结事实不改，模型也不肯补引用（红线行为正确）。
- **v3（零配额离线重放）**：利用 v2 留证的模型真实原始草稿（core + 末轮 supplement），补第 3 类修复（删除 2 个无证据图表候选）后本地重放合并 → 走完整 Agent 2 确定性流水线（审计/复算/质量门）。终态 `waiting_review`（质量门 `passed=true`，4 条 blocking 协作请求转人工决策），**分析结论完整产出**。
- 全程模型真实调用合计 2 次（v1+v2），v3 零调用。结果文档：[AGENT2_REAL_RUN_ANALYSIS_RESULT.md](AGENT2_REAL_RUN_ANALYSIS_RESULT.md)。
- 结论：④ 类（LLM 行为）问题在 flash 档 + 55k 提示下呈顽固漂移，属已知模式；生产改进候选——supplement 段图表候选的 schema 提示词强化（"evidence_ids 必填"前置）、或将 chart_candidates 校验降为软失败。记入根因攒批，暂不动生产代码。
