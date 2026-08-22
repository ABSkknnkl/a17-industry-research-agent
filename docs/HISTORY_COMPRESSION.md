# 项目全部历史对话压缩提炼（2026-08-07 ~ 2026-08-21）

> 本文件是对全部可提取历史会话的完整压缩总结。信息来源：系统会话摘要、memory 主题记录（20260807~20260821）、项目内全部测试报告文档。
> 仅去除寒暄、工具调用失败重试、重复中间统计；所有核心诉求、结论、bug、规则、文件全部保留。

---

## 0. 项目身份

- **项目**：同花顺问财 SkillHub 多智能体行业研究报告系统
- **目录**：`/Users/Zhuanz1/PycharmProjects/同花顺/`
- **技术栈**：Python/FastAPI/LangGraph（后端）、Vue3/Element Plus（前端）、DeepSeek-v4-pro（真实 LLM）、iwencai API（真实 SkillHub 数据）
- **五智能体**：
  - Agent 1 `data_fetcher` — 意图拆解 + 22 个 Skill 路由 + 真实数据采集 + 证据结构化
  - Agent 2 `data_interpreter` — 证据分级、派生指标计算（VerificationModel 零随机性）、LLM 研究结论
  - Agent 3 `chart_generator` — 图表候选/决策包、dataset 匹配、12 种图表类型、降级与抑制
  - Agent 4 `chapter_writer` — 7 章 21 节结构化章节、引用闭合、fallback 兜底
  - Agent 5 `report_assembler` — MD/HTML/PDF/manifest 四产物、正式版/草稿版分级导出

---

## 1. 完整时间线（逐日）

### 2026-08-07：质量门系统升级（风险分级 + 决策包 + 分级导出）
- **诉求**：把质量门从简单 pass/fail 升级为「专业风险分类 + 用户知情决策 + 正式/草稿分级导出」
- **实施**（内联执行 Task 1-8）：
  - 新建 `decision.py`（风险等级与决策模型）、`chart_generator/planner.py`（图表全局规划与冲突检测）、`numeric_refs.py`（数值引用分类校验）、`chapter_repository.py`（SQLite 章节持久化）
  - `workflow.py` 审核动作枚举扩展；`graph.py` 审核门逻辑重写（支持六种审核动作）
  - Agent 3 从「静默删除超标图表」改为「生成图表决策包 + 风险提示」
  - Agent 4 章节级引用自动聚合；数值分三类：fact（有证据）/ calculation（计算）/ scenario_parameter（情景参数）
  - Agent 5 支持 draft 水印、红色横幅、未解决问题附录；有风险时正式版自动降级草稿
  - 前端新增 `RiskNoticeList.vue`、`ChartCandidateCard.vue`、`DecisionCard.vue`、`ExportDecisionCard.vue`
- **修复**：numeric_refs.py 百分比有证据误判 calculation → fact
- **验证**：142 项后端测试通过，前端 type-check + 生产构建通过

### 2026-08-08：两个 P0 bug 修复
- `ChartGenerationResult` 缺 `decision_package` 可选字段，`extra="forbid"` 拒绝合法字段 → 添加可选字段
- `graph.py` auto-accept 把带 blocking_issues 的 WAITING_REVIEW 误标 COMPLETED → 修正为保持 WAITING_REVIEW
- 143 项后端测试通过；`test_default_registry_runs_real_interpreter_and_chart_generator` 联通性验证通过

### 2026-08-12：真实数据通路打通 + Agent 4 兜底机制分析
- **Agent 4 Pydantic 验证失败分析**：DeepSeek 生成章节 JSON 不符合 `ParagraphDraft` 约束（paragraph_id 格式、analysis 段缺 claim_ids/evidence_ids）→ 触发 `fallback.py build_fallback_writing()`，从已验证 claims 固定模板拼装 7 章 21 节，quality.passed=false + chapter_fallback_used
- **Agent 1 Mock 问题定位**：25 个金融场景测试发现 `SKILLHUB_USE_MOCK=True` + 缺 `SKILLHUB_API_KEY`，返回与查询无关的固定数据；但 EvidenceItem 格式与 Agent 2 标准 100% 兼容
- **真实数据打通**：改 `SKILLHUB_USE_MOCK=false` + 配置 `IWENCAI_API_KEY` 后，iwencai API 返回宁德时代 121 条真实财务数据，状态 completed 无错误
- **质量门拦截 200 证据分析**：normalizer.py 把 iwencai 原始行拆成单指标 EvidenceItem（约 20 行企业 × 10 指标）；quality.py L62 要求 completeness==1.0（6 个 P0 skill 全成功）而实际 1/6=0.1667，数据本身 validity=1.0 却被丢弃

### 2026-08-14：边界探索
- **英伟达数据分析**：确认 Agent 1 正常调用 6 个 P0 skill（行业/财务/宏观/产业链/研报/新闻）最多 200 证据；此前测试手工注入 5 条绕过了 skill 调用
- **bug 修复**：`ConflictRecord.evidence_ids` max_length=20 在真实数据 23 个冲突 ID 下验证失败 → 改为 200（与 EvidenceItem 上限一致）
- **iFinD 行业分类问答**：申万一级约 31 个/二级 130+，中信一级约 30/二级 100+，证监会 19 门类约 90 大类；项目用 iwencai API 同样支持
- **Agent 3 图表数据复杂度分析**：扁平单层结构，复杂度在 router.py 路由规则（boxplot 每组 ≥8 样本、combo 双轴时间对齐、treemap 深度 ≤3），失配降级而非伪造

### 2026-08-15：Agent 3 十二种图表全类型测试
- **诉求**：从金融研究问题中选最复杂问题，每题生成 1 图共 12 图
- **结果**：成功生成 12 种类型（line/bar/pie/radar/industry_chain/combo/area/scatter/bubble/heatmap/boxplot/treemap），报告 `test_output/agent3_complex/agent3_complex_report.html`
- **修 3 个 bug**：ChartPoint 增加 period_end（时间序列）、heatmap 矩阵扩容、图表跨两个章节分布避免超单章上限
- **澄清**：图表由 Agent 3 生产代码生成，测试脚本只模拟 EvidenceItem/ChartDataset 输入注入 StageContext

### 2026-08-17：高难度用例 + 技能扩展 + 评测方案 V1 诞生
- **4 个高难度用例**（杜邦 ROE 拆解、CRn 市占率聚合、多图豁免、混合异常口径）：全部 WAITING_REVIEW——Agent 1 取不到专项指标（市占率、产能）→ Agent 2 计算失败 → Agent 3 生成与需求无关的兜底图表；根因：data_fetch_options.metrics 与 unit 字段缺失
- **9 类 33 个金融投研场景**：单公司深度/行业景气/竞争格局/价格周期/估值宏观/政策舆情/多维复合/口语化/风险导向，每类抽 1 句测 A1-A3
- **Agent 1 技能扩展方案**：新增 10 个技能（3 官方：指数数据查询/期货期权数据查询/问财选A股 + 7 个 ClawHub：大宗商品分析/行业轮动等），制定路由互斥规则，方案存 `AGENT1_SKILL_OPTIMIZATION_PLAN.md`（后被判定为旧方案不再实施）
- **EVALUATION_PLAN.md V1 诞生**：64 用例（6 难度级、负向 ≥40%）、分层通过率、`IwencaiSkillClient` 快照录制/回放、Agent 2 锁 VerificationModel、21 个二值检查点、三级门禁（日常 pass@3≥90%、发版 pass*3≥95%、核心计算 pass*5=100%）

### 2026-08-18：V4 升级 + 光伏逆变器根因 + LLM 集成决策
- **V4 升级**：22 个 Skill 全覆盖测试（15 个 Agent 1 数据 Skill = 11 默认 + 4 条件触发；7 个 Agent 2 方法论 Skill）；新增 E-41~E-50 十条真实场景用例，总量 86 条（50 E2E + 24 专项 + 12 工具规划）；T1-T8 工具规划检查项；YAML schema 增加 `required_methodologies`
- **光伏逆变器竞争格局测试**（`report_fixed.html`）：Agent 1 状态 waiting_review vs completed、缺 7 项需求、A2/A3 被阻断；数据只有锦浪科技（无多司对比）、取回的是财务报表而非市占率/出货量、图表 bar→line 降级
- **根因四连**：`_metric_skill` 词表缺关键词（净利率/出货量/海外收入占比）、FINANCE 查询硬编码不含用户指标、STOCK_SELECTOR 查营收排名而非市占率、focus_questions 关键词匹配不覆盖"竞争格局"
- **LLM 集成决策**：LLM 能解全部根因但引入结构化可靠性/非确定性/幻觉风险 → 决定混合路由（确定性优先 + LLM 增强 + 确定性回退）
- **公司可查性确认**：A 股（阳光电源/锦浪科技/固德威）可查；非 A 股（华为/SMA/SolarEdge）不可查
- **捏造数据全链路联通测试**（用户明确许可本轮可捏造）：84 条捏造证据（3 司 × 7 指标 × 4 期）→ A2 8 结论 + 7 图表候选 → A3 7 图（3 张降级折线）→ A4 7 章质量通过 → A5 无错误报告，验证流程联通

### 2026-08-19：P0/P1 优化 + 复杂意图实施 + 硬性清理
- **Agent 1/2 优化**（按 RUNLOG 方案 P0+P1）：metric registry（毛利率/净利率/市占率等）、planner.py 动态注入用户指标消除硬编码、混合路由（确定性 + LLM 兜底未知指标）、Agent 2 确定性公式（研发费用率/销售费用率/海外收入占比）；长尾指标正确路由、原神股价返回 null 不捏造
- **复杂意图识别与多技能路由实施**（用户点名上次只做了分析没改代码，本次必须实施）：9 文件修改 +1914/-46 行，6 新模块（intent_models/skill_capabilities/deterministic_intent_parser/complexity_detector/intent_merger + semantic_router 改造）；10 个失败测试先行；金标准评测 **Precision=Recall=F1=1.0、Exact Match=100%**；交付 `AGENT1_INTENT_ROUTING_CHANGES.md`
- **硬性清理**（不可违背指令）：删除所有已完成 md 方案/自动化测试代码/中间产物；**生成代码绝对禁止删除/屏蔽/裁剪/归档**；执行：13 个根目录测试脚本、全部测试数据目录、83 个测试产物删除；用户指出 `test_agent3_complex.py`、`test_output/agents_allcases/CASE3.json` 漋漏 → 补清；`AGENT1_INTENT_ROUTING_CHANGES.md` 误删 → git 恢复；自检 13 处关键符号全部在位

### 2026-08-20：用例构造规则修正 + Mock 全链路测试（第一份 bug 报告）
- **用例构造规则**（§3.0 真实 Skill 白名单）：正向用例必须命中 ≥1 个真实数据层 Skill；天生失败用例 E-10「贵州茅台批价/渠道库存」→ 改「近四年营收/归母净利」；E-39「对比特斯拉和宁德时代估值」保留为合法边界用例
- **Mock 全链路测试**（零 LLM 调用，测试代码充当大模型）：
  - 62 条全链路：pass 45 / intercept 16 / blocked 1；I 类金标准 12/15
  - **但 45 条 pass 中仅 6 条真实完成**（E-01/06/13/31/43/T-05），39 条虚假完成，真实通过率 ≈10%
  - 发现 BUG-001~005 + TE-01~03（详见 §3.1）
  - 报告：`test_output/eval_full_pipeline/BUG_REPORT.md`；保留 3 份 HTML 于 kept_reports/

### 2026-08-21：真实 LLM Record 测试 → BUG 修复 → V7 → L4 真实全链路（信息量最大的一天）
- **凌晨**：编写 `test_intent_golden_routing.py`（16 测试函数、8 项指标：拆解准确率/指标识别/Skill 路由/时间主体提取/多余调用率/澄清召回/规则回退/连续稳定性；FakeDecomposer 注入避免真实 LLM）
- **Record 模式真实 LLM 测试**（用户许可调项目 LLM，跳过已通过的 6 条，重点测 56 条）：
  - trace 快照 55 成功 / 0 失败（`eval/traces/`）
  - 真实通过仅 3 条（E-07/T-04/T-09）；虚假完成 41 条；真实拦截 11 条；blocked 1（T-12）
  - LLM 拆解成功率 96%（hybrid 53 / fallback 2，含 E-33 负向诱导"数据不够你就补一下"正确回退）
  - 发现 BUG-006/007/008（详见 §3.2）；报告：`BUG_REPORT_V2_REAL_LLM.md`
- **BUG-006 修复**（用户点名先改这个其他不动）：`semantic_router.py` 系统提示词加两条澄清规则
- **BUG-001 修复**：`intent_merger.py` L445-451（可路由子需求存在时澄清降级 advisory）+ `service.py` L162-212（整单拦截收紧）+ 2 个新测试；104 项 data_fetcher 测试通过
- **BUG-002 终态回归确认**（不调 LLM 基本回归）：graph 层两测试通过 + 评测驱动 `run_pipeline_eval.py` 补丁（intent_clarification_required → cancel + 合法拦截）；120 项 workflow+data_fetcher 测试通过
- **V7 升级**：EVALUATION_PLAN.md 增加 L0-L5 执行分层、L0 评测器 fail-closed 自检、A2-A5 验收维度、跨智能体交接契约、expected_stages/expected_handoffs
- **只写测试代码不执行**：`test_agent_handoffs.py`（9 条契约）+ `test_real_full_chain.py`（真实无 mock 全链路）
- **L4 真实全链路测试**（最终轮，详见 §3.3）：L2 契约 9/9 + pytest 1 passed + 4 轮诊断驱动；报告 `REAL_CHAIN_BUG_REPORT.md`；上线结论 **BLOCK**

---

## 2. 用户核心诉求全集（按提出顺序）

1. **报告生成方确认**：报告 UI/排版/布局是智能体生成的还是 AI 合成的 → 确认 Agent 5 + 模板生成
2. **动态指标注入验证**：Skill 查询参数能否动态注入用户指标 → 已实现并验证
3. **偏门问题路由验证**：长尾指标（库存周转率）能否正确路由 → FINANCE ✅；原神股价返回 null 也算成功（诚实拦截）
4. **Agent 1 复杂意图识别**（10 项 P0 强制范围）：完整 focus_questions 复杂度检测、拆子需求、每子需求 1-3 Skill、规则锁定 LLM 只补不删、SkillName 枚举约束、独立查询、主体/指标/时间结构化提取、低置信度/主体歧义转人工、LLM 异常安全回退、金标准测试
5. **不调项目 LLM 由 AI 充当大模型**（多轮测试的约束，后期部分轮次解除）
6. **硬性清理指令**：删方案/测试代码/中间产物，生成代码永久保留不可清理
7. **按 EVALUATION_PLAN.md 严格执行测试**：成功过的用例不重复测；某智能体失败不跳过该阶段（按方案继续下一个智能体）；遇到 bug 找根因写文档
8. **Record 快照录制**：transport.save_trace 每用例落盘 `./eval/traces/`；不启用 mutators/triage/scorers；保留 62 条用例与超时隔离
9. **BUG 修复指令**：BUG-006 先修（其他不动）→ 出整体修复方案 → BUG-002 终态回归（不调 LLM）
10. **测试代码只写不测**（后续再执行）
11. **真实业务数据全链路测试**：Agent 1→5 完整、无 mock、真实 SkillHub + 真实 LLM
12. **报告产物管理**：只保留最有测试价值的 3 份 HTML，其余删除
13. **历史对话压缩总结**（本文件）

---

## 3. 全部 Bug 追踪（三轮报告编号独立，按轮次列出）

### 3.1 第一轮：Mock 全链路（BUG_REPORT.md，08-20）

| 编号 | 等级/根因 | 问题 | 状态 |
|------|-----------|------|------|
| BUG-001 | 阻断/E | Agent 1 规则层"一票否决"整单澄清：任一段不认识→全单 WAITING_REVIEW，62 条中 39 条（63%）取数前被拦死（含 E-02 锂价/E-08 估值等正常问题） | ✅ 08-21 已修复 |
| BUG-002 | 阻断/E | graph 非审阅阶段自动放行不检查 error：`intent_clarification_required` 被吞成 completed，错误字典沿五阶段传播（analysis_input_invalid→chapter_input_invalid→report_input_invalid），终态 completed 零产物 | ✅ 08-21 已修复 |
| BUG-003 | 普通/E | metric_registry 缺高频指标：归母净利润/净利润/营业成本/PE/PB/ROE/存货周转率/应收周转率等 18 族外的 A 股最高频指标未注册 | 未修（LLM 层掩盖，fallback 路径复现） |
| BUG-004 | 普通/E | 时间提取不支持中文数字（"近四年"）与"半年"粒度（I-C02/I-C04 失败） | 未修（同上被掩盖） |
| BUG-005 | 普通/E | 指标句中识别失败：`_segment_skills` 用整段文本 get_metric_spec 而 `_segment_metrics` 用子串，两条路径不一致（I-C09 失败） | 未修（同上） |
| TE-01 | 测试工程 | T-07/T-08 失败注入未触达（构造文本无金融语义先被澄清拦截） | 遗留 |
| TE-02 | 测试工程 | T-12 轨迹构造类注入器未实现 → blocked | 遗留 |
| TE-03 | 测试工程 | S 类 24 条专项未执行（依赖 baselines.json 回填） | 遗留 |

**正向确认**：注入防御有效（E-38 "忽略规则"被 PROMPT_INJECTION_SUSPECTED 拦截留痕）、不补造红线有效（16 条诚实拦截）、决策包校验有效（decision_id/risk_snapshot_sha256/accepted_risk_codes 全过）、6 条真实 pass 证明主干链路健康。

### 3.2 第二轮：真实 LLM Record（BUG_REPORT_V2_REAL_LLM.md，08-21）

| 编号 | 等级/根因 | 问题 | 状态 |
|------|-----------|------|------|
| BUG-001 | 阻断/E | 真实 LLM 下拦截面扩大到 73%（41/56）：新增触发路径——LLM 自己返回 clarification_questions 被 intent_merger 无条件并入 requires_clarification，即使子需求已 100% 路由成功 | ✅ 08-21 已修复 |
| BUG-002 | 阻断/E | 41 条"带 error 的 completed"流过五阶段；真实通过率 3/56≈5% 而表面 79% | ✅ 08-21 已修复 |
| BUG-006 | 普通/A 提示词 | LLM 对相对时间过度澄清："近四年"→"请确认具体年份范围"；"最近"→"请确认近1个月还是3个月" | ✅ 08-21 已修复（提示词加两规则） |
| BUG-007 | 普通/E+A | 9 条用例行为退化：从诚实拦截退化为虚假完成（BUG-006×001×002 三叠加；E-14/18/19/20/24/32/35/41/42、T-01） | 随 001/002/006 修复，需回归这 10 条 |
| BUG-008 | 观察项/E | LLM 的合理澄清（E-29"那个锂电龙头"→"请问指哪家公司"）被虚假完成掩盖，正确拦截行为无法呈现 | 随 001/002 修复 |

**正向确认**：LLM 拆解质量高（E-05 正确拆 1 个子需求路由 FINANCE，上轮规则层拆错）、回退机制有效（2 条 fallback 零崩溃）、11 条真实取数诚实拦截、注入防御与决策包校验持续有效。

### 3.3 第三轮：L4 真实全链路（REAL_CHAIN_BUG_REPORT.md，08-21，全部未修复）

| 编号 | 被测对象 | 问题 | 根因分类 | 修复建议 |
|------|---------|------|---------|---------|
| BUG-001 | Agent 2 | 毛利率假阴性拦截：问财已披露毛利率×5 + 营业成本×4，`_DERIVED_METRIC_TOKENS` 把披露值排除在计算输入外，营业成本期间不对齐 → 4 年全判 missing → 整单取消（3/3 稳定复现） | E | 拦截前先查证据池已披露派生指标；或 A1 拆解时展开为原料指标 |
| BUG-002 | Agent 2 | 真实 LLM 偶发 stage_timeout：默认 180s vs 实际 170-260s 抖动，4 次中 2 次超时；review_gate 正确拒绝 approve | E | 默认升 600s；单调用超时+心跳；超时降级摘要模式 |
| BUG-003 | graph 构建 | settings.STAGE_TIMEOUT_SECONDS 不贯通：build_pipeline_graph 缺省用 RuntimePolicy() 默认 180s，仅 main.py API 入口生效 | E | 缺省从 settings 读取 |
| BUG-004 | Agent 3 | 图表候选 4/4 全抑制、报告 0 图表。C1：match_datasets 要求候选 evidence_ids ⊆ 单个 dataset，多指标候选天然跨 2 个 dataset（各覆盖一半）issubset 永假；C2：产业链候选引用 3 条定性研报证据，21 个 chart_datasets 零覆盖（无 industry_chain 类） | E | C1 多 dataset 联合覆盖合并渲染；C2 A1 为定性证据建 industry_chain dataset；抑制原因区分两种 code |
| BUG-005 | Agent 4 | LLM 章节结构化 12 处验证失败：枚举外字面值（kind/content_type）、中文程度词触发 float_parsing（quantitative_density）、extra forbidden 字段（suitable_for_precise_table）；fallback 兜底产出 7 章 21 节 | B 模型底座 + A 提示词 | 枚举白名单；extra 宽容剥离；literal/float 重试+纠偏；换 GPT-4o/Claude A/B 验证 |
| BUG-006 | A1+A2 | BUSINESS 主营构成不被识别：metric_name 泛化"业务收入"，分项名（动力电池系统等）旁置，A2 判缺结构化数据发 CR-001 | C Schema | 分项名写入 metric_name 或 scope；请求多年期 |

**修复优先级**：BUG-004-C1 > BUG-001 > BUG-002/003 > BUG-005 > BUG-006。

**第三轮五智能体结论**：A1 通过（5 次取数 108-116 证据/次，compound 拆分 + FINANCE+BUSINESS 双 Skill 混合路由正确）；A2 不通过；A3 不通过；A4 有条件通过（fallback 兜底）；A5 通过（四产物齐全、引用闭合、ready_with_limits 诚实降级）。**上线结论 BLOCK**。

**正确行为基线**（回归用）：A1 意图拆分路由正确、review_gate 防呆（failed stage 禁止 approve）、前视偏差与元数据分区正确、诚实降级无伪造、A5 产物完整（27KB MD/43KB HTML 7章21节/1.27MB PDF/sha256 manifest）、真实凭证 fail-closed 生效。

---

## 4. 全部测试轮次记录

| # | 轮次 | 时间 | 模式 | 规模 | 关键结果 |
|---|------|------|------|------|---------|
| 1 | 质量门升级回归 | 08-07 | 单元+集成 | 142 测试 | 全过 |
| 2 | P0 修复回归 | 08-08 | 单元+集成 | 143 测试 | 全过 |
| 3 | Agent 1 真实数据首通 | 08-12 | 真实 iwencai | 1 场景 | 宁德时代 121 条 |
| 4 | Agent 3 十二图型 | 08-15 | 模拟数据 | 12 图 | 全类型成功 |
| 5 | 4 高难度用例 | 08-17 | 模拟+A1 | 4 用例 | 全 WAITING_REVIEW（暴露专项指标缺口） |
| 6 | 9 类场景抽测 | 08-17 | 模拟 | 9 用例 | 9 份报告 + 根因文档 |
| 7 | 捏造数据联通 | 08-18 | 捏造（许可） | 84 证据 | 五阶段联通无错误 |
| 8 | Mock 全链路 | 08-20 | Mock 双层 | 62+15 条 | 表面 79% 真实 10%，发现 BUG-001~005 |
| 9 | 真实 LLM Record | 08-21 | 真实 LLM + Mock SkillHub | 56 条 | 真实 5%，trace 55 录制成功，发现 BUG-006~008 |
| 10 | BUG 修复回归 | 08-21 | 无 LLM | 120 测试 | 100% 通过（BUG-001/002/006 修复确认） |
| 11 | L2 契约测试 | 08-21 | 纯契约零网络 | 9 断言 | 9/9 通过 |
| 12 | L4 真实全链路 | 08-21 | 真实双真实 | pytest 1 + 4 轮诊断 | A1/A5 过、A2/A3 阻断、A4 兜底，发现第三轮 6 bug |

**用例覆盖统计**（方案 101 条 = cases_v1 86 + intent_golden 15）：
- 已测约 75 句去重：Mock Record 55（E45+T10）+ I 类 15 + 真实 LLM 3 + L4 真实 2
- 从未执行：E-06/E-31/T-05/T-12 中 E-06/E-31/T-05 曾在第一轮真实通过、T-12 恒 blocked；实际缺口为 S 类 24 条（需启用 scorers + baselines 回填）

---

## 5. 约定规则全集（不可变约束）

### 5.1 系统硬规则
- 所有代码读取必须通过 MCP Exec（integrated_code_mode），禁止直接 Read/Grep/Glob/SearchCodebase
- 图表技术上限 30 张，推荐 8 张软规则；同证据 ID 冲突组归并取信息最丰富版本
- 硬阻断风险（数据点超限/unknown_evidence/data_integrity）必须阻止图表生成
- 章节引用必须完整证据链；报告保持 7 章 21 节不可增减
- 风险确认校验 run_id/revision/decision_id/risk_snapshot_sha256/selected_chart_ids/placement_overrides
- Agent 2 失败必须终止流水线返回明确错误，不得把错误字典伪装成 AnalysisResult 传播
- 测试过程中不得修改生产代码
- ConflictRecord.evidence_ids max_length=200

### 5.2 评测硬规则
- 负向用例 ≥40%；L1-L6 六级难度；专项（计算 10/图表规则 8/证据溯源 6）
- L0 评测器 fail-closed 自检先行（10 断言）
- 用例级隔离：独立 thread + 超时 + 有限 resume，单条阻断不终止整套
- 正向用例必须命中 ≥1 真实数据层 Skill；边界/负向用例预期正确拦截（WAITING_REVIEW/null）
- 之前成功过的用例不重复测试；某智能体失败不跳阶段
- 发版门禁：核心计算 pass\*5=100%、全链路 pass\*3≥95%、日常 pass@3≥90%
- 评分三层：规则硬校验 70% + LLM 语义 30% + 人工抽检 10%-20%
- 22 Skill 全覆盖（A1 15 个 = 11 默认 + 4 条件触发；A2 7 个方法论）
- 工具规划 T1-T8：应调尽调/无错调/无重复无效/参数无漏错填/合理复用/失败正确处理/新技能正确路由
- 路由金标准必须报告 Precision/Recall/F1/Exact Match
- 评测环境用 `IwencaiSkillClient(transport=...)` 快照录制/回放，未命中快照判失败
- Agent 2 默认 VerificationModel 零随机性；run_manifest 锁死 commit/模型/快照版本

### 5.3 Agent 1 路由规则（复杂意图实施后）
- deterministic-first：规则结果锁定（locked_skills），LLM 只能补充不能删除
- 复杂度分级 simple/compound/ambiguous；simple 不调 LLM；子需求数上限 12，每子需求 1-3 Skill
- LLM 输出必须 SkillName(raw) 可解析，非法值进 rejected_skills 记 warning
- LLM 异常/超时/格式错误 → parser_mode="fallback" 回退确定性计划
- 相对时间（近N年/最近/近期/近半年）不澄清，写入 time_range.raw_text 透传，确定性层按 research_as_of 前推
- 只有主体歧义（哪家公司/哪个行业）才输出 clarification_questions
- 任一子需求可路由时 plan 级澄清降级 advisory_clarifications 不阻断；整单拦截仅当澄清 AND 全部不可路由
- 评测驱动中 intent_clarification_required → cancel + 合法拦截集合
- 两个独立开关：AGENT1_SEMANTIC_ROUTER_ENABLED=true（DeepSeek-v4-pro 语义路由）、AGENT1_INTENT_DECOMPOSER_ENABLED=false（确定性规则拆解）

### 5.4 清理规则
- 清理对象：方案 md、自动化测试代码、附属中间产物
- 永久保留：全部生成代码（禁止删除/屏蔽/裁剪/归档）；清理后自检生成代码完整性，缺失立即回滚
- `AGENT1_INTENT_ROUTING_CHANGES.md` 不可删除（唯一例外）
- 报告产物只保留最有测试价值的 3 份 HTML

---

## 6. 关键交付文件索引

| 文件 | 用途 | 状态 |
|------|------|------|
| `docs/EVALUATION_PLAN.md` | 评测方案 V7（V1 08-17 诞生 → V4 22Skill → V5 故障隔离 → V6 I类金标准 → V7 L0-L5） | 完整 827 行 |
| `docs/REAL_CHAIN_BUG_REPORT.md` | L4 真实链路 6 bug 根因报告 | 完整 169 行 |
| `docs/HISTORY_COMPRESSION.md` | 本文档 | 完整 |
| `test_output/agent1_intent_routing/AGENT1_INTENT_ROUTING_CHANGES.md` | Agent 1 复杂意图交付说明（AI 可读，不可删） | 完整 |
| `test_output/eval_full_pipeline/BUG_REPORT.md` | 第一轮 Mock 全链路 bug 报告（BUG-001~005） | 完整 |
| `test_output/eval_full_pipeline/BUG_REPORT_V2_REAL_LLM.md` | 第二轮真实 LLM bug 报告（BUG-006~008） | 完整 |
| `test_output/agent1_real_estate_live/AGENT1_TEST_REPORT.md` | 房地产真实取数报告（178 证据） | 完整 |
| `test_output/real_estate_no_llm/TEST_REPORT.md` | 无 LLM 房地产链路测试（A2-A5 确定性模拟 + Playwright 验证） | 完整 |
| `backend/tests/integration/test_agent_handoffs.py` | L2 跨智能体交接契约（9/9） | 完整 |
| `backend/tests/integration/test_real_full_chain.py` | L4 真实全链路 pytest | 完整 |
| `backend/tests/agents/data_fetcher/test_intent_golden_routing.py` | I 类金标准 16 测试 | 完整 |
| `backend/tests/agents/data_fetcher/eval_intent_routing_golden.py` | 金标准 P/R/F1/EM 脚本 | 完整 |
| `eval/run_pipeline_eval.py` | Record 模式快照驱动器（含 BUG-002 修复） | 完整 |
| `eval/traces/` | 55 个 trace 快照（0 失败） | 完整 |
| `eval/cases/cases_v1.json` + `intent_golden.json` | 86 + 15 用例池 | 完整 |
| `test_output/caseA4_stage_results.json` | L4 五阶段 StageResult 实锤（10360 行） | 完整 |
| `backend/artifacts/run-real-caseA4/reports/r1/` | L4 真实产物（MD/HTML/PDF/manifest） | 完整 |

**Agent 1 复杂意图核心代码**（永久保留）：`intent_models.py`、`skill_capabilities.py`、`deterministic_intent_parser.py`、`complexity_detector.py`、`intent_merger.py`、`semantic_router.py`、`planner.py`、`factory.py`、`service.py`、`app/schemas/acquisition.py`。

---

## 7. 经验教训（Lessons）

1. 静默删除超标/重复图表伤体验 → 生成风险提示后继续
2. DeepSeek-V4-Pro 对严格 JSON schema/Pydantic 约束的遵循弱于 GPT-4o/Claude（两轮实证：A4 章节验证 12 错、结构化输出失败）
3. 系统 HTTP 代理（127.0.0.1:7890）会拦 localhost 请求 → 设 no_proxy 绕过
4. Mock DataFetcher 的 dataset 结构与 chart_generate 匹配逻辑不兼容会导致图表全抑制
5. DeepSeek-V4-Flash 无法产出符合 Pydantic 严格验证的章节数据
6. 表面通过率与真实通过率可以差 15 倍（79% vs 5%）——评测器必须先过 fail-closed 自检
7. 单独修任何一处叠加 bug 都不会让退化用例恢复，必须按依赖顺序修复后整体回归
8. 规则层兜底的脆弱性只在 LLM 禁用时暴露——每条路径都要有独立测试覆盖

---

## 8. 当前未决事项（按优先级）

1. **修复第三轮 BUG-004-C1**：match_datasets 多 dataset 联合覆盖（最高优先级，A3 图表功能实际不可用）
2. **修复第三轮 BUG-001**：Agent 2 披露值回退（拦截前查证据池已披露派生指标）
3. **修复第三轮 BUG-002/003**：stage_timeout 默认 600s + 配置贯通
4. **修复第三轮 BUG-005**：A4 提示词枚举白名单 + extra 宽容 + 重试纠偏
5. **修复第三轮 BUG-004-C2 + BUG-006**：A1 建 industry_chain dataset + BUSINESS 证据结构化
6. **回归第二轮 BUG-007 的 10 条退化用例**（E-14/18/19/20/24/32/35/41/42、T-01）
7. **补修第一轮 BUG-003/004/005**（metric_registry 缺口/中文数字时间/句中指标识别——LLM 层掩盖但 fallback 路径仍在）
8. **补测缺口**：S 类 24 条专项（需 baselines.json 回填 + 启用 scorers）；TE-01 构造类用例改用有语义输入；TE-02 T-12 轨迹注入器实现
9. **L5 视觉验收**：HTML/PDF 人工抽检
10. **全链路真实 LLM 复测**：BUG-001/002/006 修复后 62 条完整回归（用户明确要求修复后需真实 LLM 全链路回归）
