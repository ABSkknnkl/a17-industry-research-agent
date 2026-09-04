# 评审器样本回流与运维手册

- 适用：`ReadabilityLinter`（确定性锚）+ `ReadabilityLLMReviewer`（LLM 软分）

- 开关：`READABILITY_REVIEW_ENABLED`；阈值 `READABILITY_THRESHOLD`（0.6）；重写上限 `READABILITY_MAX_REWRITES`（2）

- 前置阅读：`READABILITY_ACCEPTANCE_REPORT.md`（上线条件）、`评审器调优与红蓝对抗方案.md`（方法论）

## 1. 周度例行（每周一，≤30 分钟）

```bash
# 1) 确定性门禁 + 对抗回归（零模型调用，必跑）
cd backend && .venv/bin/python -m pytest tests/agents/chapter_writer -q

# 2) 校准跑批（默认代打评分，零调用）
cd .. && backend/.venv/bin/python -m eval.readability_calibration --round WEEKLY
```

门禁任一项不达 §4.2 标准 → 评审器开关回退关闭，走 §2 缺陷处置。

## 2. 样本回流流程（核心运维闭环）

**回流来源**（按优先级）：

1. 审核界面被人工驳回/改写的段落（最高价值，永久入库）；
2. 上线报告被外部评审打回的段落；
3. 用户反馈"读不懂"的具体段落。

**处置步骤**：

1. **采集**：段落原文 + 打回原因 + 所在章节，记为候选样本；
2. **分流**（方案 §4.1 原则——能确定性判的进 Linter，判不了的进 judge）：

   - 病句/裸标签/泄漏/自夸/数字洪水等**客观可判** → 在 `readability_linter.py` 增补规则或词表，样本入 `ADVERSARIAL_SAMPLES` 并填 `linter_expected`；

   - 语义断裂/指代混乱/文风问题等**软判** → 样本入 `ADVERSARIAL_SAMPLES`（`linter_expected=None`），同时在 judge prompt 软判指引补一条形态描述；
3. **回归**：按 §1 全量重跑；确认新样本被抓取、正样本全集零误报（按下葫芦浮起瓢检查）；
4. **固化**：合入主干，样本成为永久回归资产（只增不删——**删难样本提分是一票否决**）。

**单轮回流样本上限 30 条**（方案 §2.2 成本控制）；超过攒批下轮。

## 3. 开关与阈值运维

| 触发条件                   | 动作                                            |
| ---------------------- | --------------------------------------------- |
| 周度门禁任一项不达标             | `READABILITY_REVIEW_ENABLED=false`，修复后按验收流程重开 |
| 真实 judge 与人工抽样一致率 <0.8 | 引入仲裁模型（`LLM_JUDGE_MODEL` 第二配置位交叉评分），方案 §5 L4  |
| 一致率 0.8\~0.9           | 观察期，积累分歧样本                                    |
| 边界段（0.55\~0.75）占比持续偏高  | 评估阈值上调（考卷曲线支持 0.7），**须有真实 judge 判分数据支撑后再改**   |
| `READABILITY` 协作请求激增   | 检查是否误杀潮：抽 10 条人工复核，误杀入正样本库                    |

## 4. 校准集扩建（持续任务）

1. 考卷 48 条的 `proposed_label` 目前是评审器建议标签——**完成双人工背靠背标注 + 分歧仲裁后**，把结果写回 `exam_set_v1.json` 的 `gold_label`（仲裁前的数据不得当真值用）；
2. 新研报 PDF 入库：`eval/calibration/extract_corpus.py` 抽取 → 按 5:3:2（正:负:边界）分层标注 → 并入考卷；
3. 四个语体（宏观策略/行业深度/公司深度/事件点评）保持覆盖，缺一类补一类。

## 5. 换 judge 模型必跑清单（每次更换 `LLM_JUDGE_MODEL`）

1. `eval/readability_calibration.py --judge real --round MODEL-SWAP`（消耗配额，需审批）；
2. 五项门禁对照本报告 §1 基线；
3. 红队 opt-in 门禁：`READABILITY_REDTEAM_LLM_GATE=1 pytest tests/agents/chapter_writer/test_readability_redteam.py`；
4. 任一不达标 → 不切换，记入迭代记录。

## 6. 防作弊红线（方案 §6，违反即作废重来）

1. 校准集标注样本禁止混入 judge few-shot（few-shot 只允许合成示例）；
2. 禁止删除难样本或改 labels 提分；
3. 正样本必须含术语密集/长句/跨市场样本；
4. Linter 100% 抓取率未达标禁止启用评审器。

