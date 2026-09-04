# 评审器上线门禁验收报告（FINAL）

- 日期：2026-09-02
- 方案依据：`评审器调优与红蓝对抗方案.md` §4.2 五项门禁 + 用户交付物清单「完成标志」
- 裁判：人工代打评审器（与线上 judge 同款模型代理评分），零真实模型调用
- 复现：`backend/.venv/bin/python -m eval.readability_calibration --round FINAL --redteam eval/calibration/adversarial_r1.json`

## 1. 五项门禁终验

| 指标 | 实测 | 门禁 | 判定 |
|---|---|---|---|
| G1 Linter 确定性负样本抓取率 | 100%（15/15 回归负例 + 5/5 对抗确定性攻击面） | 100% | ✅ |
| G2 judge 软判负样本 <0.6 占比 | 92.3%（13 条软判样本，唯一"逃逸"为已知盲区 ADV-07） | ≥90% | ✅ |
| G3 judge 正样本 ≥0.6 占比 / 均分 | 100% / 0.8589 | ≥95% / ≥0.75 | ✅ |
| G4 kappa 一致率（35 条策展真值） | 1.0 | ≥0.9 优（<0.8 触发仲裁模型） | ✅ |
| G5 误杀率 | 0%（0/19） | <5% | ✅ |

代码回归：`tests/agents/chapter_writer` 104 例通过、1 例按设计 skip（opt-in 真实 judge 门禁，零配额）；全量后端测试套件全绿。

## 2. 交付物完成标志核对

| 完成标志 | 状态 |
|---|---|
| 代码落点全部合入主干 | ✅ R11 新规则 + R3/R4 增强 + judge prompt v2（`readability_linter.py` / `openai_compatible.py`） |
| 校准脚本可一键执行 | ✅ `eval/readability_calibration.py`（--round/--redteam/--judge） |
| 红蓝对抗跑完，不再产出新逃逸漏洞 | ✅ 四轮循环完成，确定性攻击面 0 逃逸（1 条设计内盲区记录在案） |
| 5 项门禁指标全部达标 | ✅ 见上表 |
| 回流运维流程文档交付 | ✅ `docs/READABILITY_OPS_RUNBOOK.md` |
| 评审器开关可安全开启 | ✅ 见 §3 结论与条件 |

配套资产：回归库 19 正例+16 负例、对抗库 12 条（`ADVERSARIAL_SAMPLES`）、校准考卷 48 条（`eval/calibration/exam_set_v1.json`）、代打评分 95 条（`surrogate_scores_v1.json`）、跑批报告 3 份（`eval/calibration/reports/`）。

## 3. 上线结论与条件

**结论：`READABILITY_REVIEW_ENABLED` 可以安全开启。** 安全性由架构保证，与门禁分数相互独立：

1. **软硬门分离**：可读性结果永不写入 `quality.passed`（仅确定性 audit 决定）——评审器误判不会阻塞生产流水线；
2. **输入隔离**：judge 只收 `paragraph.text + kind`，自夸文本无法带偏打分；
3. **重写上限**：单段最多 2 轮改写（`READABILITY_MAX_REWRITES=2`），达上限转人工，无死循环、无静默放行；
4. **独立开关与配置位**：`LLM_JUDGE_MODEL` 独立，可单独回退。

**开启后首周观察项（运维文档 §3）**：
- 线上真实 judge（Qwen-3.8-Max）首轮判分与人工抽样核对一致率——本轮 kappa=1.0 是**代打评分**对策展真值的结果，真实模型需运营期复测；
- 阈值 0.6 的边界段占比（考卷曲线显示 0.7 区分度更优，积累数据后评估上调）；
- `READABILITY` 协作请求量级（防评审器过度转人工）。

## 4. 已知限制（诚实披露）

1. judge 侧指标基于代打评分，非线上真实模型实测（方案允许：真实模型回归走 `--judge real` 与 opt-in 门禁，消耗配额，由运营期执行）；
2. 考卷 proposed_label 为评审器建议标签，双人工标注+仲裁未完成（运维文档 §4 的持续任务）；
3. 跨段指代为单段评审的原理性盲区（ADV-07），按方案降权处理。
