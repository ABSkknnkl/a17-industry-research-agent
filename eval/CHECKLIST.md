# EVALUATION_PLAN V6 实现核对清单

本文逐条核对 [docs/EVALUATION_PLAN.md](../docs/EVALUATION_PLAN.md) 全部条目，确认评测代码实现无遗漏。
状态：`done`=已实现；`stub`=已实现框架、需运行时数据回填；`note`=设计约定（非代码）。

## 0. 交付物清单（对应 §11 工程落地清单）

| 方案条目 | 落地位置 | 状态 |
|---------|---------|:---:|
| cases/cases_v1.yaml | `eval/cases/cases_v1.json`（86 条：50 E2E + 12 T + 24 专项） | done |
| cases/intent_golden.yaml | `eval/cases/intent_golden.json`（15 条 I 类） | done |
| cases/baselines.json | `eval/cases/baselines.json`（10 组确定性计算基准） | stub（expected 待快照回填） |
| conftest.py | `eval/conftest.py`（JSON 加载 + fixture + group 门禁） | done |
| metrics.py | `eval/metrics.py`（g_pass_at_k + pass_star_k） | done |
| transport.py | `eval/transport.py`（SnapshotTransport record/replay） | done |
| mutators.py | `eval/mutators.py`（6 种变异） | done |
| isolator.py | `eval/isolator.py`（用例级隔离桩） | done |
| triage.py | `eval/triage.py`（根因 A-E + Bug 汇总） | done |
| runner.py | `eval/runner.py`（CLI --mode/--k/--case/--group） | done |
| scorers/intent.py | `eval/scorers/intent.py`（I1–I8） | done |
| scorers/rules.py | `eval/scorers/rules.py`（D/C/G/R/P/T 27 项） | done |
| scorers/judge.py | `eval/scorers/judge.py`（双法官 + κ） | stub（真实 LLM judge 运行时注入） |
| snapshots/manifest.json | 由 `transport.py::write_manifest` 落盘 | stub（首次 record 后生成） |
| transcript/{run_id} | 由 `runner.py::_write_grades` 落盘 grades.jsonl | done（traces.jsonl 待接 runtime） |
| reports/{commit}.md | 由 `triage.py::BugSummary.render` 生成 | done |

## 1. 格式替代说明（重要）

- 方案用 `.yaml`，项目 **未引入 pyyaml**（方案 §5 原则「除 GPassK 外不引入外部重依赖」）。
  故用例数据用 `.json` 承载与 §5.1 YAML schema **完全等价**的字段（id/level/group/input/runs/threshold/must_pass/veto/checks/required_skills/forbidden_skills/required_metrics/required_methodologies/expected_task_range/subgoals 均保留）。
- `cases_v1.yaml` 的 24 条专项（§5.3）正文仅给出「10 组确定性计算 + 8 图表规则 + 6 证据溯源」概数、未列逐条；实现按 §4 判定项补齐为 S-C01~S-C10、S-G01~S-G08、S-E01~S-E06，共 24 条，条目语义与 §4 判定项一一对应。

## 2. 逐章核对

### §0 开源选型
| 开源项目 | 落地 | 备注 |
|---------|:---:|------|
| GPassK → g_pass_at_k | metrics.py | 采用 pass@k 超几何无偏估计（开源公式，Apache-2.0 参考） |
| pytest-agent-eval → YAML schema | conftest.py + cases/*.json | threshold/runs/must_pass/group 字段齐备 |
| agentrr → transport | transport.py | canonical match key + 内容寻址 + strict miss=fail |
| claw-eval → pass*k | metrics.py::pass_star_k | k 次全过 |
| llm-rewind → mutators | mutators.py | 429/timeout/truncate/field_drop/field_shift/row_shuffle |
| SAP → subgoal 归因 | isolator.py::FaultState.last_reached_subgoal | 三层归因标记位 |
| big-finance-benchmark → judge | judge.py | 双法官 + Cohen's κ + grades.jsonl |
| strands-evals → 评分器分类 | rules.py | output/trajectory/tool/planning 四类 |
| pytest-agentcontract → runner CLI | runner.py | --mode record\|replay\|mutate |

### §2 可复现性基础设施
- 2.1 快照 match key / canonical_json / strict / record / manifest → transport.py `done`
- 2.2 模型与参数锁死（VerificationModel + run_manifest）→ runner 装配点，模型参数入 run_manifest `note`（真实 LLM 注入时落地）
- 2.3 run_manifest / traces.jsonl / grades.jsonl → grades.jsonl 已落盘；traces/run_manifest `stub`
- 2.4 隔离（独立进程，不共端口）→ `note`（评测默认独立进程运行）
- 2.5 变异 6 种 + 存活率≥95% + bisect → mutators.py `done`
- 2.6 故障隔离桩 7 条规则 → isolator.py `done`

### §3 22-Skill 覆盖
- 3.0 真实 Skill 白名单（15 数据 + 7 方法论）→ 见 scorer 常量与用例 required_skills `done`
- 3.1/3.2 覆盖矩阵 → cases_v1.json 50 E2E 覆盖 15 数据 Skill（含 5 缺口 E-41~E-45）`done`
- 3.3 补齐策略 10 条 → E-41~E-50 `done`
- 3.4 M1/M2/M3 方法论校验 → judge.py::METHODOLOGY_RUBRIC_DIMENSIONS + E-46~E-50 `done`

### §4 原子判定项库（L1）—— 27 项全覆盖核对
| 判定项 | 检查点关键词 | 实现函数 | 状态 |
|-------|------------|---------|:---:|
| D1 | 标的主体匹配 | check_d1 | done |
| D2 | raw_sha256 一致 | check_d2 | done |
| D3 | 时间范围 | check_d3 | done |
| D4 | 单位完整 | check_d4 | done |
| C1 | 公式误差≤0.01% | check_c1 | done |
| C2 | 单位统一 | check_c2 | done |
| C3 | 异常正确拦截 | check_c3 | done |
| G1 | 同数据集单图 | check_g1 | done |
| G2 | 用户多图豁免 | check_g2 | done |
| G3 | 产业链图≤1 | check_g3 | done |
| G4 | 图表数值与计算一致 | check_g4 | done |
| G5 | 无数据不绘图 | check_g5 | done |
| R1 | 7章21节结构 | check_r1 | done |
| R2 | 无违规表述 | check_r2 | done |
| R3 | 数据有溯源 | check_r3 | done |
| P1 | 数据不足停 WAITING_REVIEW | check_p1 | done |
| P2 | 不伪造不补数 | check_p2 | done |
| P3 | 异常提示清晰 | check_p3 | done |
| P4 | 前视偏差合理 | check_p4 | done |
| T1 | 应调尽调 | check_t1 | done |
| T2 | 无错调 | check_t2 | done |
| T3 | 无重复无效调用 | check_t3 | done |
| T4 | 参数完整正确 | check_t4 | done |
| T5 | 工具能力复用 | check_t5 | done |
| T6 | 失败降级正确 | check_t6 | done |
| T7 | 调用路径最优 | check_t7 | done |
| T8 | 新 skill 路由 | check_t8 | done |

一票否决集合 `VETO_CHECKS={D2,P2,R2,C1,T1,T2,T6}` 已与方案对齐。

### §5 用例集
- 5.0 I 类 15 条（I1–I8 金标准）→ intent_golden.json + scorers/intent.py + runner.py `done`
- 5.1 schema → conftest.py 加载字段齐备 `done`
- 5.2 E2E 50 条 → cases_v1.json E-01~E-50，全部含「Agent 1 路由」required_skills 断言 `done`
- 5.3 专项 24 条 → cases_v1.json S-* `done`（见格式替代说明）
- 5.4 T 类 12 条 → cases_v1.json T-01~T-12 `done`

### §6 分层通过率 pass@k / pass*k
- 6.1 三层 + subgoal 归因 → isolator last_reached_subgoal `done`
- 6.2 g_pass_at_k + pass_star_k + 门禁矩阵 → metrics.py + conftest.GROUP_GATES `done`

### §7 L2 语义打分
- 双法官 panel / Cohen's κ / judge schema / 权重 70/30 → judge.py `done`（真实 LLM judge 注入）
- M1/M2/M3 维度 → judge.METHODOLOGY_RUBRIC_DIMENSIONS `done`

### §8 辅助过程指标
- V1 过程指标、变异存活率、κ、must_pass 数、T 类 6 指标、I 类 8 指标 → 由 runner 汇总；intent 聚合在 summarize_intent_results `done`（聚合报告待 runner 落地）

### §9 运行节奏与精读 → `note`（流程约定，非代码）
### §10 饱和识别 → `note`（演进约定）

### §12 故障隔离
- 12.1 四态枚举 → isolator.CaseStatus `done`
- 12.2 根因 A-E → triage.RootCause + classify_by_signal `done`
- 12.3 模型换底 A/B → triage.classify_b_with_model_swap `done`
- 12.4 Bug 汇总 8 字段 → triage.BugRecord `done`
- 12.5 缺陷统计 → triage.BugSummary `done`
- 12.6 系统提示词 → 方案原文保留（运行时文案）

## 3. I 类 15 条金标准用例核对

I-C01 市占率+海外政策拆分 / I-C02 多指标+主营结构 / I-C03 双实体对比 / I-C04 业绩预告+增发 / I-C05 单指标 hybrid / I-C06 周转率 LLM 识别 / I-C07 CR3/CR5 路由 / I-C08 归母净利润+时间 / I-C09 简单零冗余 / I-C10 模糊澄清 / I-C11 回退 / I-C12 锁定不删 / I-C13 非法拒绝 / I-C14 注入防御 / I-C15 稳定性 —— 15 条全部有对应条目。

## 4. 已知待运行时回填项（非代码遗漏，属可复现性数据）

1. `baselines.json` 的 expected 基准值（10 组）——需首跑 record 后从同花顺真实快照回填，禁止凭空编造。
2. `snapshots/` 快照与 `manifest.json`——首次 record 生成。
3. `traces.jsonl` 逐事件轨迹——需接入 runtime 执行器后落盘。
4. judge.py 真实双法官模型——需运行时注入锁定模型（temp=0）。
5. `run_manifest.json`（git commit/依赖 hash/模型参数）——运行时采集。

## 5. 结论

- 判定规则（D/C/G/R/P/T/I/M 共 38 项）**逐项实现，无删减/合并**。
- 用例集 101 条（15 I + 50 E2E + 12 T + 24 专项）**逐条声明，无删减/合并**。
- 开源项目借鉴维度（GPassK/pytest-agent-eval/agentrr/claw-eval/llm-rewind/SAP/big-finance-benchmark/strands-evals/pytest-agentcontract）**全部落地**。
- 生产代码零改动；评测脚本独立于 `backend/` 存放于 `eval/`。