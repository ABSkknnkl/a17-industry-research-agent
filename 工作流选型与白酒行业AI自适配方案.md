# 工作流选型与「AI 自适配白酒」落地方案

> 日期：2026-11-14　范围：只做选型与流程设计，不改 `a17-industry-research-agent` 任何代码
> 事实基准：GitHub API 实时取数（star / license / 最近 push），当日 2026-11-14

---

## 0. 一句话结论

**主选 Kestra（Apache-2.0，30.2k star），备选 Dify（DSL 可版本化，161k star），第三选 Windmill。**
把它们只当「调度壳 + 门禁壳」，你现有的 `state_machine.py` + `/api/v1/runs` 继续做唯一状态真相。
真正让 AI 能自己适配白酒的，不是工作流引擎，而是**行业画像（profile）+ 查询模板 + 验收矩阵三份 YAML**——AI 只改这三份，四道闸门决定能不能合并。

---

## 1. 候选项目对比（真实数据，2026-11-14）

| 项目 | Star | 许可 | 流程定义形态 | 人工停点 | 接你现有 Python 的方式 | 判断 |
|---|---|---|---|---|---|---|
| **kestra-io/kestra** | 30,225 | Apache-2.0 | **纯 YAML**，一个 flow 一个文件 | **原生 `Pause`**（OSS）；`HumanTask` 是 EE 插件 | HTTP 任务打你的 API；Python 任务本地/容器 runner | **主选**：流程即文本，diff 可审，与你的门禁文化同构 |
| **langgenius/dify** | 161,124 | 类 Apache-2.0 + 附加限制 | **可视化画布 + DSL YAML 导出/导入**（导入时校验 schema，可回滚版本） | 无原生「等人审批」节点 | HTTP 请求节点 / 代码节点 | **备选**：DSL 可进 Git，答辩视觉最好；但状态在它自己库里 |
| windmill-labs/windmill | 18,576 | AGPL-3.0（非 OSI） | flow 为 JSON，脚本原生 Python | 有挂起/审批步 | 直接跑你的 py 脚本 | 第三选：最省事，但 AGPL + 要 Postgres |
| n8n-io/n8n | 210,424 | Sustainable Use（fair-code，非 OSI） | 可视化 + JSON 导出 | `Wait` 节点 | HTTP 节点 | **不建议**：许可限制商用/多租户，且无 Python 生态 |
| langchain-ai/langgraph | 44,931 | MIT | **代码即图**（StateGraph） | `interrupt` | 原生 Python | **不建议**：等于把状态机搬一次家，且「AI 改工作流」= 改代码，与你前提冲突 |
| temporalio/temporal | 24,390 | MIT | 代码式 workflow | signal | Python SDK | 不建议：耐久性最强但运维最重，赛题场景用不上 |
| crewAIInc/crewAI / microsoft/autogen | 60.9k / 61.8k | MIT / CC-BY-4.0 | 角色协作，不是流程编排 | 无 | — | 不建议：会在你 state_machine 之上再叠一层编排，双真相 |
| apache/airflow · PrefectHQ/prefect · dagster-io/dagster | 47.5k / 24.2k / 16.4k | Apache-2.0 | DAG（数据管道语义） | 弱 | Python | 不建议：解决的是调度，不是「AI 工作流 + 人工门禁」 |

**可直接抄设计（不抄代码）的参考实现**

| 项目 | 抄什么 |
|---|---|
| bytedance/deer-flow（85.3k，MIT） | 研究型 harness 的 planner / researcher / reporter 分工与沙箱隔离 |
| xbtlin/ai-berkshire（17.1k） | 多 Agent 并行投研的角色拆分与证据链写法 |
| FoundationAgents/AFlow（ICLR 2025 Oral）+ ShengranHu/ADAS（ICLR 2025，1.6k） | **「AI 自动改工作流」的正确方法论**：把 workflow 当可搜索的程序，用打分函数筛，而不是让 LLM 自由发挥 |

---

## 2. 诊断：你缺的不是流程，是「流程的可改写层」

先把现状说准，避免选错工具：

1. **五阶段 + 人工门禁已经在代码里跑通了。** `STAGE_ORDER = data_fetch → data_interpret → chart_generate → chapter_write → report_fusion`，`StageStatus` 含 `waiting_review/approved/rejected`，`ReviewAction` 八种（approve / accept_recommendation / accept_with_risks / customize / revise / regenerate / cancel / direct_edit），还有 `/resume`、`/cancel`、`revisions/{n}` 回滚、`feedback-history`。这套东西比大多数 GitHub 工作流项目更「金融严肃」。
2. **所以不要用工作流项目替换它。** 替换 = 迁移 4 个停点 + 8 种审核动作 + 版本快照，风险最高、收益最低。
3. **行业适配的真实差异 90% 不是拓扑差异，是配置差异。** 换白酒不用新增节点，只换：点名公司、年度窗口、必备指标（含营运资金明细）、产业链环节、图表期望、章节边界、验收矩阵。
4. **因此选型标准只有四条**：① 流程能写成 **可 diff 的文本**；② 有 **schema 校验**能挡住 AI 写坏；③ 能 **HTTP 接你现有 API**，零代码改动；④ 有 **原生等待/重试/超时**，能挂住「等人审」。

四条全过的只有 Kestra；Dify 过三条（差原生停点）；其余各有硬伤。

---

## 3. 工作流怎么搭（Kestra，不改你的代码）

### 3.1 唯一状态真相原则（这条不守，必翻车）

- **A17 的 `run_id` + 落盘产物 = 唯一真相**；`state_machine.py` 仍是阶段机。
- Kestra 的 `execution_id` **只做外键**，写进交付记录，不参与判定。
- 审核仍在**你现有前端**做（8 种 ReviewAction + revision 快照都在那儿）；Kestra 只负责「等」，不复制一套审核 UI。
- Kestra 里禁止出现任何「正式/受限/未通过」判断逻辑——三档判定必须留在服务端。

### 3.2 节点表（一个 flow = 一次行业研报）

| # | Kestra 节点 | 动作 | 对应你的接口 | 产出 / 落点 |
|---|---|---|---|---|
| 0 | `validate_input` (Python) | 校验 `industry_profile.yaml` + 问题输入：公司是否在本行业、期间是否年度、必填指标是否齐全 | 本地 schema 校验 | `precheck.json`（不合法直接 kill，不建 run） |
| 1 | `create_run` (HTTP) | 建任务 | `POST /api/v1/runs` | `run_id` 写入 flow output |
| 2 | `poll_data_fetch` (Retry + HTTP) | 轮询到 `data_fetch` 进 `waiting_review`，超时阈值 25 min | `GET /api/v1/runs/{run_id}` | `gate1_state.json` |
| 3 | `wait_gate1` (Pause 或轮询 approved) | 等人审（审核在你前端） | 审完由 `POST /reviews` 推进 | 超时 → 告警并挂起，不自动放行 |
| 4 | `poll_data_interpret` → `wait_gate2` | 同上，A2 产业链接入 + 归属待核 | 同上 | `gate2_state.json` |
| 5 | `poll_chart_generate` → `wait_gate3` | A3 图表：11 ready / 43 suppressed 类抑制必须落盘原因 | 同上 | `chart_result.json` |
| 6 | `poll_chapter_write` → `wait_gate4` | A4 章节并行；`passed=false` 不许绕过 | 同上 | `chapter_result.json` |
| 7 | `report_fusion` (HTTP + 长超时) | A5 融合 + PDF | 同上 | PDF / HTML / MD 三格式 |
| 8 | `acceptance` (Python) | 跑验收矩阵：总态、缺格率、图表数、无据数字数、页码目录一致 | 读产物，只读 | `acceptance.json` + `run_ledger.jsonl` |
| 9 | `notify` | 落 `run_id / execution_id / 版本 / 结论` | — | 交付台账 |

关键实现细节（都是配置层，不写代码）：
- 轮询用 `Retry` + 条件判断，间隔 30s，累计上限按阶段配（A1 25min / A2 15min / A3 20min / A4 40min / A5 15min），超时 **只告警 + 挂起**，绝不自动 `accept_with_risks`。
- 章节写作要并行，用并行分支调 `/resume` 分阶段推进，别在 Kestra 里自己拆章节（拆了就和 A4 的 `assignment.py` 打架）。
- 每次 flow 的输出目录带 `run_id`，禁止按 `industry` 命名（同一行业多次跑要能并列对比）。

---

## 4. 「让 AI 自己改项目」的四闸闭环（核心）

这是你要的「用工作流让 AI 适配白酒」。**AI 只允许产出三份 YAML，永远不碰 `.py`。**

```
闸0 基线冻结  →  闸1 AI 生成配置  →  闸2 静态语义校验  →  闸3 影子跑  →  闸4 回归+人审合并
```

### 闸 0：基线冻结（动手前一次性做完）

- 冻结 NEV 20 题 + 白酒 4 题当前的 `run_id`、`dataset.json`、`chart_result.json`、`chapter_result.json`、PDF 页码核对表 → `baseline/20261114/`。
- 特别要把文档里的**反例**存成「负样本集」：白酒第 1 题错用洋河/古井贡、巨力索具混入估值、第 2 题用 2026 前三季度冒充三年同比、毛利率图把水平画成同比、社零百分点算错。**这些是 AI 改配置时必须全过的断言**。

### 闸 1：AI 只产出三份文件（限 diff 范围）

| 文件 | 内容 | 允许 AI 改吗 |
|---|---|---|
| `industry_profile.yaml` | 行业边界、锁定公司、排除项、期间、必备指标及口径、产业链环节、图表期望、章节边界 | 全量生成 |
| `queries.yaml` | 每个指标一条问财查询起点 + 别名/同义词兜底（减少漏取） | 全量生成 |
| `acceptance_matrix.yaml` | 题号 → 期望样本/图表/章节 → 判定规则（20 格矩阵） | 全量生成 |
| 其余（`state_machine.py`、`agents_core/*`、渲染模板） | — | **禁止，出现即拒收** |

硬约束写进 prompt：单次改动只允许上述 3 个文件、总行数 ≤ 400、必须输出 unified diff、必须附「每条公司/指标的出处依据」。

### 闸 2：静态语义校验（挡 80% 的低级错）

注意：Dify/Kestra 的 schema 校验**只验结构不验语义**，语义必须靠你自己的规则表。逐条断言：

| # | 规则 | 判定 |
|---|---|---|
| R1 | 点名公司在 A 股且行业归属命中（白酒=申万二级「白酒Ⅱ」） | 否则拒 |
| R2 | 排除清单生效：非本行业公司不得进入估值/对比样本 | 命中即拒 |
| R3 | 期间必须为年度窗口且与问题原文一致（2023–2025） | 季度/前三季度混入即拒 |
| R4 | 每个指标必须有 `口径`（合并/分部、单位、期间类型、含税与否） | 缺口径即拒 |
| R5 | 图表期望图类型与问题类型匹配（同比→画变化，不得画水平） | 不匹配即拒 |
| R6 | 产业链跨环节公司只计一次（`count_once: true`） | 重复计即拒 |
| R7 | 每章必须有「数据局限」段；披露不足的问题必须带结论限定条款 | 缺即拒 |

### 闸 3：影子跑（旁路，绝不覆盖基线）

- 新 profile 跑白酒 4 题，写到 `shadow/{profile_version}/{run_id}/`，与 `baseline/` 并排。
- 产出对比表，固定 6 列：**终态 / 缺格率 / ready-suppressed 图数 / 无据数字数 / 页码目录是否一致 / 受限原因**。
- 判据：白酒第 1 题必须出 PDF（正式或受限都行，但受限必须写明缺什么）；4 题里至少 1 题 formal。低于此不进闸 4。

### 闸 4：回归 + 人审合并

- 黄金样本（NEV 20 题）必须全绿，且 `2190 passed` 这条旧基线不许掉。
- 负样本集（闸 0 那 5 条）必须全部「不再复现」。
- 人审三问：公司名单对不对？口径有没有被偷换？受限原因写得实不实？
- 合并方式：`git branch industry/baijiu` → profile 三件套进分支 → 人审后合主干，**每个 profile 带版本号与打分记录**（这一步就是 AFlow/ADAS 那套「工作流当程序、用打分筛」的落地）。

---

## 5. 白酒这一轮：具体改哪 9 处（照这个填 profile）

| # | 要改的配置 | 内容（来自你的试跑反馈） | 验收判定 |
|---|---|---|---|
| 1 | 锁定公司（universe） | 600519 贵州茅台 / 000858 五粮液 / 000568 泸州老窖 / 600809 山西汾酒 | 四家齐全，缺一即受限 |
| 2 | 排除清单（exclude） | 洋河、古井贡仅可作对照不得替换点名；**巨力索具等非白酒禁止进入估值样本** | 报告样本 ⊆ universe |
| 3 | 期间窗口（period） | 2023–2025 年报口径；禁止 2026 前三季度充当年度或同比 | 三年序列齐全 |
| 4 | 必备指标（metrics） | 营业收入、归母净利润、毛利率、经营活动现金流净额，四项 ×3 年 ×4 家 = 48 格 | 缺格进附录，不得用他期顶替 |
| 5 | 营运资金明细（probes） | 合同负债、应收款项（票据+账款）、存货，年度序列 | 现金流/净利润差异必须有这 3 项解释，否则该结论降级为推测 |
| 6 | 派生口径（formulas） | 现金流/净利润=比率；毛利率同比=**百分点变化**；社零增速百分点单独校验 | 水平不得当变化；比率图不得用金额 |
| 7 | 产业链（chain） | 上游：高粱/小麦/包材/玻瓶 → 中游：酿造/灌装 → 下游：经销/电商/团购；跨环节只计一次 | 产业链图无重复节点、无外部公司 |
| 8 | 渠道与产品结构（structure） | 批发代理 vs 直销；茅台酒 vs 系列酒；披露口径变更要标注 | 必须给「披露不足时结论如何限定」段 |
| 9 | 验收矩阵 | 4 题 × 20 格；含页码/目录/附录/受限标识四项 PDF 检查 | 与 `五行业调优指南` 第十二节记录项一致 |

四道「必答问题」的对应（照文档原文，别改写）：
1. 四家经营现金流与净利润差异 + 可核验解释 → 靠 #5 支撑
2. 2023–2025 营收/归母/毛利率/经营现金流 + 同比 + 横向 + 口径 → 靠 #3 #4 #6
3. 现金流/归母净利润比值变化 + 合同负债/应收/存货年报证据 → 靠 #5 #6
4. 渠道与产品结构可比/不可比 + 披露不足如何限定 → 靠 #8

---

## 6. 排期（5 个工作日，全程不改代码）

| 天 | 做什么 | 产出 |
|---|---|---|
| D1 | 闸 0：冻结基线 + 负样本集；写 `industry_profile` 三件套模板 | `baseline/`、三份 YAML 骨架 |
| D2 | 起 Kestra（单机 Docker），用**新能源**那条已跑通的行业先跑 1 条完整 flow | 一条 end-to-end flow + execution 日志 |
| D3 | 把 NEV profile 作为「示范样本」交给 AI，让它按模板生成白酒 profile | 白酒三件套 + unified diff + 依据表 |
| D4 | 闸 2 校验 + 闸 3 影子跑白酒 4 题 | `shadow/`、6 列对比表 |
| D5 | 闸 4 回归 + 人审 + 答辩材料 | 合并记录 + 合规 PDF + 台账 |

**答辩 30 秒版**：
「我们的工作流不是写在代码里的流程图，而是**一份可版本化的行业画像 + 一个阶段机**。换行业只改画像三份 YAML，AI 出 diff，四道闸门——语义校验、影子跑、黄金样本回归、人审——保证它写不坏。所以不是『我们适配了五个行业』，而是『任何人加第六个行业都只需要改配置』。」

---

## 7. 风险与坑（按严重度）

1. **双状态真相（最致命）**：Kestra execution 状态和 A17 run 状态各说各话。必须写死「A17 为准，Kestra 只做外键 + 等待」。
2. **schema 只验结构不验语义**：Dify/Kestra 导入校验放行 ≠ 业务正确。R1–R7 必须是你自己的断言，否则 AI 会把「洋河」写进 universe 而平台一声不响。
3. **LLM 顺手改别的**：prompt 里限额「3 文件 / 400 行 / 只输出 diff」，超限即拒收，不要靠它自觉。
4. **Kestra 的 `HumanTask` 是 EE 插件**，`Pause` 才是 OSS，别把方案建在 EE 上。
5. **n8n 许可**：fair-code 非 OSI，商用/多租户有约束，赛题交付给主办方前先确认。
6. **别指望工作流解决 A5 的页码/目录问题**：那是渲染层的确定性缺陷，属于 A5 模板与 PDF 后处理，工作流只能「检出」不能「修好」。
7. **A4 `passed=false` 不许用 `accept_with_risks` 绕**：你的文档里已经有绕门禁的历史（REAL-A5-001~004），工作流里把这条做成硬断言。

---

## 8. 一句话给 AI 的执行指令（可直接复制）

> 你只能修改 `industry_profile.yaml`、`queries.yaml`、`acceptance_matrix.yaml` 三个文件。行业=白酒，锁定 600519/000858/000568/600809，期间=2023–2025 年报口径，必填四项财务指标 + 合同负债/应收款项/存货三项营运资金明细。禁止修改任何 `.py`、禁止替换点名公司、禁止用季度数据充当年度、禁止把毛利率水平画成同比。输出 unified diff + 每条公司/指标的出处。单文件超 400 行视为失败。
