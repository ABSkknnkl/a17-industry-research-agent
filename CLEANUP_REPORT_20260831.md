# 项目清理执行报告

- 执行时间：2026-08-31 10:36 ~ 11:15
- 执行方式：**仅 `rm` 删除明确路径**，未执行任何 `git checkout` / `git clean` / `git stash` / `git reset`
- 备份位置：`/tmp/cleanup_backup_20260831/`（840 文件 / 90 MB）
- 总释放：约 **1.2 GB / 23084 个文件**

---

## 一、已删除清单（按类别分组）

### A 类：已完成阶段的方案 / 过程文档 — 7 个

判据：文档验收清单**全部 `[x]` 且无 `[ ]` 残留**

| 文件 | 完成证据 |
|---|---|
| `docs/plans/2026-08-01-backend-security-baseline.md` | 25 项 `[x]` |
| `docs/plans/2026-08-03-sqlite-checkpointer.md` | 18 项 `[x]` |
| `docs/plans/2026-08-04-pi-runtime-guard.md` | 16 项 `[x]` |
| `docs/plans/2026-08-09-three-plugin-p0-p1-upgrade.md` | 33 项 `[x]` |
| `docs/plans/week-0-framework.md` | 7 项 `[x]` + 验收日期 2026-07-22 |
| `docs/agent3-current-stage-completion.md` | 完成日期 2026-08-06（结项记录） |
| `docs/agent5-p0-implementation.md` | P0 完成态交接（结项记录） |

### B 类：测试报告类产物 — 8 个文件 + 1 个空目录

| 文件 |
|---|
| `docs/test-reports/deepseek-simulation-agent2-analysis.md` |
| `docs/test-reports/deepseek-simulation-agent4-chapter-result.md` |
| `test_output/real_estate_no_llm/TEST_REPORT.md` |
| `test_output/agent1_real_estate_live/AGENT1_TEST_REPORT.md` |
| `test_output/eval_full_pipeline/BUG_REPORT.md` |
| `test_output/eval_full_pipeline/BUG_REPORT_V2_REAL_LLM.md` |
| `test_output/agent1_intent_routing/AGENT1_INTENT_ROUTING_CHANGES.md` |
| `eval/transcript/FINDINGS_INTERIM.md` |
| `docs/test-reports/`（空目录，一并移除） |

### C 类：全部测试产物 — 5 个目录 / 3474 文件 / 约 909 MB

| 目录 | 文件数 | 体积 |
|---|---:|---:|
| `test_output/` | 295 | 39 MB |
| `output/` | 119 | 12 MB |
| `eval/transcript/` | 2247 | 780 MB |
| `eval/traces/` | 118 | 816 KB |
| `backend/artifacts/` | 695 | 78 MB |

`test_output/` 内部构成（21 个临时脚本已逐个 grep 验证引用数均为 0）：
19 个 `.log`、7 个 0 字节 `.out`、6 个 `.jsonl`、2 张 `.png` 截图、1 个 `checkpoint.sqlite`、
18 个一次性诊断 `.py`、3 个 `.sh`、2 个 0 字节文件（`_tmp_inspect_cases.py`、`diag_run2.py`）。

### D 类：额外指定删除 — 1 项

| 目录 | 文件数 | 体积 | 说明 |
|---|---:|---:|---|
| `frontend_legacy_20260830/` | 19610 | 289 MB | 用户指定。未跟踪，但旧前端内容在 git HEAD 中存在，可恢复 |

---

## 二、被跳过的文件及原因（11 项）

| # | 路径 | 体积 | 跳过原因 |
|---|---|---:|---|
| S2 | `eval/cache/` | 46 MB | `eval/transport.py` 的 **replay 模式依赖**其内容寻址缓存，删除后 replay 会 `strict miss=fail`。且 777 个文件**已 git 跟踪**，非临时数据 |
| S3 | `data/checkpoints.sqlite` | 20 MB | SQLite checkpointer 运行时库，属**生产运行时状态**，非测试产物；已 git 跟踪 |
| S4 | `artifacts/` | 11 MB | `backend/app/core/config.py:35` 的 `ARTIFACT_ROOT = Path("./artifacts")`，是**生产运行产物目录**（仅被 gitignore），删了会清掉历史报告 |
| S5 | `docs/plans/2026-08-07-quality-gate-upgrade.md` | 92 KB | 全文**无勾选清单**，Task 1–8 无完成标记，无法判定是否完结 |
| S6 | `docs/17.md` | 131 KB | 缺陷修复工作日志，虽属过程记录但含完整根因分析，无完成标记 |
| S7 | `docs/18.md` | 8 KB | 承接 17.md 的续篇，含 5 处修复记录与回归结论 |
| S8 | `docs/HISTORY_COMPRESSION.md` | 29 KB | 历史对话压缩提炼，含项目规则与结论 |
| S9 | `docs/REAL_CHAIN_BUG_REPORT.md` | 16 KB | Bug 根因分析报告，性质同 B 类但位于 `docs/` 根，需你确认 |
| S10 | `eval/agent1_real_e50.py` | 12 KB | 介于「专门测试代码」与「临时脚本」之间，按"专门测试的代码不删"保留 |
| S11 | `eval/run_ic01_full_surrogate.py` | 8 KB | 同上 |
| S12 | `production/session-logs/` | 188 KB | 框架方案硬约束："不改动 `production/session-logs/` 中用户已有内容" |
| S13 | 26 个 `.DS_Store` | — | macOS 系统文件，非项目内容，不在四类删除范围 |
| S14 | `frontend/dist/`、`node_modules/`、`backend/.venv/` | — | 构建/依赖产物，非测试产物 |

### 明确保留的测试文档与测试代码

| 路径 | 类别 |
|---|---|
| `docs/EVALUATION_PLAN.md` | 测试计划 |
| `eval/CHECKLIST.md` | 测试用例清单 |
| `eval/cases/{cases_v1,cases_v7,intent_golden,baselines}.json` | 用例数据 |
| `backend/tests/`（83 个文件）、`eval/tests/`（3 个文件） | 测试代码 |
| `backend/tests/**/conftest.py`（4 个） | pytest fixture，仍被引用 |
| `backend/tests/agents/chapter_writer/redteam_readability_samples.py` | 被 `test_readability_redteam.py` import |
| `eval/{harness,runner,transport,triage,metrics,mutators,isolator,surrogate_models,…}.py` | 评测基础设施 |

---

## 三、生产代码未受影响的验证证据

### 验证 1：修改项（M）执行前后逐行比对 —— 完全一致

```
diff <(执行前 M 项) <(执行后 M 项)   →  无差异
```

15 项 `M`（13 项生产代码 + 2 项测试）在执行前后**完全相同**，说明本次清理**没有造成任何生产代码的新增修改、也没有丢失任何已有修改**。

### 验证 2：新增删除项的红线目录校验 —— 全部 0 命中

本次新增 2649 个 git 删除条目（执行前 24 个 → 执行后 2673 个）。对 21 条红线路径逐一 grep：

```
backend/app/      0    backend/tests/    0    frontend/src/     0    frontend/dist/ 0
contracts/        0    config/           0    scripts/          0    skills/        0
eval/tests/       0    eval/cases/       0    eval/CHECKLIST.md 0    eval/cache/    0
docs/EVALUATION_PLAN.md 0  data/         0    production/       0    README.md      0
THIRD_PARTY_NOTICES.md 0  docs/architecture/ 0  docs/development/ 0  docs/README.md 0
docs/ownership.md 0
```

新增删除项的实际分布**全部落在** `eval/transcript`、`test_output/`、`eval/traces/`、`docs/plans/`、`docs/test-reports/`、`docs/` 之下。

### 验证 3：冒烟测试

```
✓ backend/app 导入成功
✓ 新落地的 readability_linter.py / readability.py 导入成功
✓ ARTIFACT_ROOT = artifacts
```

---

## 四、遗留问题：`tests/core/test_readiness.py` 有 1 条失败

**该失败与本次清理无关**，根因链如下（均已读码确认）：

1. `backend/tests/core/test_readiness.py:35` 构造 `Settings(API_BEARER_TOKENS={})`，期望报告 `backend_bearer_token_missing`
2. `backend/app/core/readiness.py:45` 判据是 `if not settings.API_BEARER_TOKENS`
3. `backend/app/core/config.py:15` 配置了 `env_file=".env"`，而 `backend/.env:16` 里有
   `API_BEARER_TOKENS={"frontend_dev":"0d385085…"}`
4. pydantic-settings 对 dict 这类复合字段用 `deep_update` **合并**而非覆盖 →
   显式传入的 `{}` 无法清空 `.env` 中的值 → 字段非空 → 不报告该 issue

**排除理由**：失败只取决于 `backend/.env` 与 pydantic-settings 的合并语义。本次清理
未改动 `config.py`、`readiness.py`、`test_readiness.py` 中任何一个，也未删除 `backend/.env`；
且验证 1 已证明所有 `M` 项在清理前后逐行一致。

> 说明：执行过程中 shell 环境失效（exit 127），未能取得"清理前"的 pytest 基线做直接对照。
> 上述结论基于代码因果链推导，建议在 shell 恢复后自查一次。

---

## 五、回滚方式

- **git 已跟踪的删除项**（2649 个，含全部 A/B 类文档、`eval/transcript`、`eval/traces`、`test_output` 主体）：
  `git checkout -- <路径>` 即可恢复
- **未跟踪的删除项**（`output/`、`backend/artifacts/`、`test_output` 中 26 个日志）：
  从 `/tmp/cleanup_backup_20260831/` 恢复
- **`frontend_legacy_20260830/`**：旧前端文件在 git HEAD 中仍存在，
  `git show HEAD:frontend/src/...` 可取回
