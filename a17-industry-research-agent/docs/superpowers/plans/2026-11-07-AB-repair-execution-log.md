# A、B 档修复执行记录（AB-1 … AB-7）

本文件按 [2026-11-07-AB-root-causes-and-repair-plan.md](./2026-11-07-AB-root-causes-and-repair-plan.md) 逐任务追加实际执行结果。
执行环境：`/Users/Zhuanz1/Downloads/行业研究智能体-全链路系统 4/.venv`（Python 3.13，pytest 9.1.1），全程离线、零配额、不调用真实 LLM/问财。
回归命令：`env -u CORS_ORIGINS -u API_BEARER_TOKENS python -m pytest -q`（应用根目录）。

**基线（修复前）**：1897 passed / 1 failed / 64 skipped。唯一既有失败 `backend/tests/test_all_defects_verification.py::test_new_02_combo_growth_rates_preserves_both_series`（"增长率" vs "增速" 命名漂移，与本方案无关，保留不动）。

---

## AB-1 明确指标定义与来源单位 —— 已完成

### 根因（已复现确认）
- `metric_family('研发投入')` 与 `metric_family('研发费用')` 都返回 `rd_expense`，非等价口径被合并；`fusion.py` 字段规范化同样把两类金额并入 `rd_expense`、两类占比并入 `rd_ratio`。研发费用率因此可能用"投入"（含资本化）当分子。
- `infer_default_unit('revenue')→元`：缺来源单位的金额被默认成"元"，`ResearchRecord` 不区分原始单位与推断单位。
- `engine._normalize_money(12, None)→12`、`abs(val)>=1e5→val/1e8`：按绝对值猜金额尺度。
- `_normalize_pct`：无单位 `0.12` 被猜成 `12%`。

### 改动
| 层 | 文件 | 改动 |
| --- | --- | --- |
| 指标语义 | `agents_core/financial_semantics.py` | `metric_family`：研发投入→`rd_investment`、研发投入占比→`rd_investment_ratio`，与 `rd_expense`/`rd_ratio` 分离 |
| 取数规范化 | `agents_core/data-fetcher/data_fetcher/fusion.py` | `METRIC_NAMES` 同步拆分；新增 `resolve_inferred_unit()` 把 `infer_default_unit` 结果拆成 (可信单位, 来源)：`%`/`倍`→`source_schema` 保留，金额"元"猜测→单位 `None`+`unknown`；三处调用点（主指标路径、长表宏观、报告挖掘）全部接入来源追踪；新增读取"指标名+单位"行级字段（如 `营业收入单位`）为 `source_field`；金额缺单位打 `unit_unknown` 议题；移除长表 `or "元"` 硬兜底 |
| 数据模型 | `data_fetcher/models.py`、`data_interpreter/models.py` | `ResearchRecord`/`EvidenceRef` 新增 `unit_provenance`（默认 `legacy_unknown`，兼容旧产物） |
| 解读引擎 | `data_interpreter/engine.py` | `_evidence` 透传 `unit_provenance`；`_normalize_money` 对未知/缺失单位返回 `None`（不再按量级猜尺度）；`_normalize_pct` 无单位不再 `*100`；`_paired_calculation` 增加 `unit_provenance=="unknown"` 守卫 |
| 覆盖判定 | `data_fetcher/agent.py` | `_evaluate_requirement`：带 `unit_unknown` 议题的记录不满足量化覆盖（需求维持未满足→触发定向补采）；研发费用/投入分别成需求（`financial` 别名表拆分），`labels` 补 `rd_investment` |
| 展示 | `chart_generator/metric_guard.py`、`chart_generator/render.py`、`report_fusion/render.py` | 新增 `rd_investment`「研发投入」、`rd_investment_ratio`「研发投入占营收比例」显示名与 MetricMeta |

### 行为变化（符合方案预期）
- 缺来源单位的金额：`unit=None`、`unit_provenance="unknown"`、议题 `unit_unknown`，**原值保留**供审计/补采；不参与金额比较、比率、量化覆盖。仅有此类金额、无可比锚点的公司会退出 peer comps（金额比较被排除）。
- 比率/倍数的定义性单位（%、倍）由指标语义确定，标 `source_schema` 并保留。
- 研发费用率只接受 `rd_expense` 分子；只有研发投入时不产伪费用率；覆盖不因替代指标（投入）存在而把费用需求标为满足。

### 测试
- 新增 `backend/tests/test_ab1_metric_unit_provenance.py`（14 例，D01–D05）：先确认 9 例在缺陷路径失败，修复后全绿。
- 调整 4 个编码旧行为的既有夹具（补显式来源单位，保留各测试原意，不削弱断言）：
  - `data-fetcher/tests/test_fusion_fixes.py::test_default_unit_inference_for_financial_metrics`（净利润无单位→unknown，ROE/PE 仍 %/倍）
  - `data-fetcher/tests/test_fusion_fixes.py::test_operating_cash_flow_unit_not_corrupted_by_pe`（现金流无单位→None 而非"倍"，反污染意图保留）
  - `backend/tests/test_report_integrity_data.py`（scope/currency、clean supplement、required cells 三处夹具补 `(元)`）
  - `backend/tests/test_official_restatement_reconciliation.py`（重述夹具补 `(元)`）
- `infer_default_unit` 函数本身语义不变（仍返回 元/%/倍），信任决策移到融合包装层，故 `test_p03_infer_default_unit_rules` 无需改动。
- 全量回归：**1911 passed / 1 failed（既有 test_new_02）/ 64 skipped**。

### 本轮缩减/延后（记录当前行为，非确认缺陷）
- AB-1.1 "投入费用化/资本化拆分齐全时由公式推导研发费用"：当前无来源提供资本化拆分字段，未实现推导；已保证的是"不合并、不产伪费用率"。
- AB-1.1 "旧记录只剩 rd_expense 无原始字段→标记定义待核"：未实现（需历史产物迁移策略）。
- AB-1.5 `ResearchRequirement` 显式 scope/unit 条件字段与"替代口径"字段：未新增（无消费方，避免投机性契约）；"替代指标不满足原需求"已由指标族拆分达成。
- 单位来源冲突（同指标多来源单位不一致）的议题记录：未新增（已有 period_conflict）。

---

## AB-2 开放主题样本与事件材料保全 —— 已完成

### 根因（已复现确认）
- S01：`_understand` 的 `len(mentioned) >= 2` 门槛使**单一公司**（只写在问题里、结构化名单为空）永远无法成为 comparison_entities → fusion 无固定名单过滤，模型扩写的概念股直接进入核心样本。
- S03：conflict 身份被剔出 combined_entities，但 `_annual_financial_requirements` 使用 `explicit or combined_entities`——explicit 非空时歧义名称继续驱动年度财务补采与更正公告检索；且模型扩写名单中的歧义名从未做 conflict 检查。
- S02：开放主题（无固定名单）由模型返回的公司直接进入 must_include_entities，无业务资格核验——概念股与真实业务样本同入核心财务比较；融合接口无开放主题资格参数，dataset 无样本角色字段。
- AB-2.5/E02：用户明确要求事件催化时，需求矩阵无可验收事件需求，事件证据可能被语义融合 80 条预算挤出（方案 §4.5）；无事件时无显式缺口。
- E01（前次会话已修）：`_event_evidence` 用 `title or body` 丢正文。

### 改动
| 层 | 文件 | 改动 |
| --- | --- | --- |
| 样本推断 | `data_fetcher/agent.py` `_understand` | `>= 2` → `>= 1`：明确点名包括单公司；conflicts 检查扩到 explicit ∪ model_entities（模型扩写的歧义名同样待确认）；年度补采改用无冲突的 combined_entities；identity_conflict 需求格覆盖两类来源且排序稳定 |
| 样本准入 | `data_fetcher/fusion.py` | `fuse()` 新增 `industry` 参数（开放主题且无 comparison_entities 时触发资格分类）；`THEME_ALIASES` 从 agent 移入并共用；新增 `_classify_open_theme_samples` + `_theme_activity_terms`：业务证据（主营业务/主营构成/主营产品/相关产品名称/经营范围/溯源分析 命中主题环节词）→ core_verified（记录证据 record_id）；参考库候选无证据 → pending_verification；仅概念标签（所属概念/纳入概念原因/概念解析）→ concept_background；quality_summary 增加 `sample_admission`（theme + 三类名单） |
| 数据模型 | `data_fetcher/models.py`、`data_interpreter/models.py` | 两份 `StructuredResearchDataset` 同步新增 `SampleRole`（entity_name/role/reason/evidence_ids）与 `sample_roles: list`（默认空，旧产物兼容） |
| 核心可比 | `data_interpreter/engine.py` `build_peer_comps_matrix` | `sample_roles` 非空时仅 core_verified 进入可比矩阵；空名单（点名样本/旧产物）不过滤，背景记录保留数据集 |
| 事件需求 | `data_interpreter/agent.py` `run` | 明确事件催化问询（事件/催化）→ 需求矩阵新增 `event_catalysts` hard 需求：有公告日期的事件进必答证据集合（技能上下文与语义融合预算挤压不丢）；缺日期事件不计入催化事实；无事件时 passed=False 且 missing 显式缺口进 `requested_requirement_coverage` 附录 |
| 事件正文 | `data_interpreter/engine.py` `_event_evidence`（前次会话） | 标题+正文用换行分隔合并，正文已含于标题不重复；各事件按 record_id 独立 |

### 行为变化（符合方案预期）
- 单公司点名（仅问题文本）→ comparison_entities=[该公司]，模型扩写概念股不得改变研究样本；指定公司缺数据时需求格保留未满足，概念股不入核心数据集。
- 歧义身份（同名多主体/模型扩写名单）→ 样本名单剔除、财务补采与更正公告检索停止，仅保留"待确认"需求格。
- 开放主题核心财务比较只含具备主题业务证据的公司（库内或库外均可准入，候选库不构成封闭名单）；概念股保留背景上下文不入核心可比；三类名单与原因在 quality_summary.sample_admission 可查。
- 明确要求事件催化时：有效事件为必答证据；无事件/仅缺日期事件 → 需求未满足、显式缺口可见，不用行情或财务记录顶替。

### 测试
- 新增（先红后绿）：
  - `data-fetcher/tests/test_financial_eligibility_v8.py`：`test_single_named_company_in_question_becomes_fixed_sample`、`test_single_named_company_missing_data_not_backfilled_by_concept_stock`（S01，2例）；`test_ambiguous_identity_keeps_confirmation_cell_and_stops_financial_backfill`（S03，stub registry 1例）；`test_open_theme_core_sample_requires_business_evidence`（S02，含库内候选/概念股/库外有据三分类与可比矩阵过滤断言）
  - `data-analysis/tests/test_event_evidence.py`：`TestEventRequirementMatrix` 4例（有日期事件绑定必答证据、无事件显式缺口、缺日期事件不满足催化需求、未要求事件不造需求）
  - 前次会话 E01 3例（标题+正文保全、同公司双事件正文独立、正文不重复）
- 既有守卫按方案 §6 作为回归用例保留：未来事件丢弃/行情型不产空壳事件/缺日期留痕不造数（`test_event_schema.py`）、事件域隔离与预算稳定（`test_event_evidence.py`）、开放主题候选不锁样本（`test_open_robotics_topic_gets_role_candidates_without_locking_samples`）。
- 夹具调整 1 处编码旧 schema：`test_fusion.py::test_all_dataset_sections_exist_even_when_empty` 补 `sample_roles` 字段。
- 全量回归：**1925 passed / 1 failed（既有 test_new_02）/ 64 skipped**。

### 本轮缩减/延后（记录当前行为，非确认缺陷）
- S03 "同代码多市场/别名去重/跨环节样本计数一次"：本任务只修歧义身份驱动补采的确认缺陷；同代码多市场的具体形态（如 A+H 双市场）依赖 registry 证券数据补充，未单独建用例。
- S02 业务资格的"可靠业务证据"以确定性字段匹配实现（业务文本命中主题环节词）；未接入语义相似度或 LLM 判定（保持离线可验）。
- AB-2.5 事件需求在解读层建立（与 sensitivity_gaps 同模式）；取数层未新增事件技能任务规划（事件由既有 announcement/event 技能召回，需求矩阵在覆盖判定处可见缺口）。

---

## AB-3 图表窗口与样本规模服从研究需求 —— 已完成

### 根因（已复现确认）
- C01：`_filter_recent_periods` 对超 36 期序列一律套"最近 5 年或末 48 期"固定政策，与需求矩阵中的显式研究窗口脱节——132 个月度期被静默裁成 60 期。
- C02：`_deterministic_fallback` 时序候选 `[:10]` 系列硬截断（12 家指定公司只画 10 家，静默丢 2 家）；且语义去重键 `(timeseries_curve, 指标)` 不含样本组，拆图后第二张会被当同指标冗余图抑制。
- C03：fallback 时序门槛 `len(periods) >= 3` 使两期同口径数据无图可出；"要求但缺失"的年份类别不补入。
- C04：fallback 横截面用**各实体最新期**拼图（甲@2025年报、乙@2025三季报、丙@2024年报），随后可比性审计直接把整图抑制——即使三家存在共同可比期 2024。
- 附带发现：`_verify_numeric_candidate` 重建脚注时整体覆盖候选既有脚注（两期观察提示、单位注一起丢失）——但模型拟议注必须被丢弃（`test_bar_notes_regenerated_after_structure_candidate_becomes_bar` 锁定该行为），两类注需要分离通道。

### 改动
| 层 | 文件 | 改动 |
| --- | --- | --- |
| 窗口裁剪 | `chart_generator/data_formulation.py` | 新增 `_required_years_from_report`（需求矩阵 hard 需求 period_ends 的年份=显式窗口）；`_filter_recent_periods(..., keep_years)`：窗口内期次不参与最近期裁剪，窗口外噪声仍受默认政策约束；`formulate` 主路径与 `_formulate_time_series` 双处接入 |
| 缺年类别 | `data_formulation.py` `_formulate_time_series` | 观测期全为年度且显式窗口要求了未观测年份时补入空类别（值 None 不填零，月度/季度不外插），quality_notes 记录补入年份 |
| 系列容量 | `data_formulation.py` `_formulate_time_series` | `[:10]` 截断保留（图例可读上限）但不再静默：quality_notes 列出未绘制系列，供拆图与缺口呈现 |
| 拆图 | `chart_generator/agent.py` `_deterministic_fallback` | 时序候选按确定顺序拆为 ≤10 系列/张（标题（一）（二）编号），每张独立证据集、同轴单位；`_Candidate` 新增 `sample_group`，语义去重键纳入拆图组别（第二张拆图不再被当冗余抑制） |
| 两期图 | `agent.py` `_deterministic_fallback` | `len(periods) >= 3` → `>= 2`：两期同口径出变化图，`audit_notes` 注明"样本仅覆盖两个观测期：只作有限变化对比，不构成持续趋势结论" |
| 横截面 | `agent.py` `_deterministic_fallback` | 换掉"各实体最新期"拼图：对齐共同可比期（覆盖主体数最多、同期最新优先）；缺共同期的主体不入图并 audit_notes 列名；无任何共同期时保留最新期+显式"披露期不一致"注 |
| 审计注 | `agent.py` `_Candidate`/`_verify_numeric_candidate` | 新增 `audit_notes`（确定性审计注）与 `footnotes`（模型拟议注，核验时整体重建——既有行为保留）分离；audit_notes 并入最终 footnotes 呈现 |

### 行为变化（符合方案预期）
- 显式研究窗口（需求矩阵 period_ends 年份）内的期次全部交付；无显式窗口时默认最近期政策不变（对照用例锁死）。
- 12 家指定公司 → 拆 2 张线图（10+2），全部主体可核对、两图同单位；单图仍 ≤10 系列保图例可读。
- 两期同口径数据出图且明确标注有限观察；缺年补空类别为 None；真零保持 0.0；季度不并入年度；同期冲突值按既有 period_conflict 隔离，不做字典覆盖赢家。
- 横截面使用共同可比期；原"跨期拼接图"要么对齐要么带显式不可比注，且不再因跨期被整图抑制（有共同期时）。

### 测试
- 新增 `chart-generator/tests/test_ab3_window_and_sample_capacity.py`（9 例，C01×3 / C02×1 / C03×4 / C04×1）：
  - 红→绿：显式 132 期不被裁（原 60）、窗口年份提取、12 家全交付（原丢 2 家）、两期出图（原无图）、缺年补 None 类别（原缺类别）、横截面对齐共同期（原图被整图抑制）。
  - 既有行为回归（绿）：默认政策限噪、季度不并入年度、冲突隔离不覆盖。
- 回归：chart-generator 全套 763 passed（含 `test_bar_notes_regenerated_after_structure_candidate_becomes_bar` 审计注分离后仍绿）；全量 **1934 passed / 1 failed（既有 test_new_02）/ 64 skipped**。

### 本轮缩减/延后（记录当前行为，非确认缺陷）
- AB-3.5 "每个可见数据点绑定真实 record_id"：既有 point_evidence_ids 机制已逐点绑定（`test_c03_missing_year` 同时校验点级证据对位），未新增断言文件。
- C02 "受图数预算限制时输出具体未交付主体"：超预算候选已有 SuppressedChart 留痕（evidence_ids 可反查主体）；未在 reason 文本中展开主体名单（拆图后单张超预算的粒度较粗）。
- C01 的"60 个月"显式窗口以需求矩阵 period_ends 年份承载（年度窗口）；问句中的"近 N 个月"自然语言窗口未新增解析（min_records 契约未扩展）。

---

## AB-4 正文证据修复与审计

- 复现分号和换行连接的合法、非法事实被一起删除，以及无数字的方向预测穿过核验。章节修复失败时保留能独立核验的子句，将整段无据内容移出正文，原文、位置、证据和处理结果进入结构化审计。
- 章节修复调用消耗现有 max_repairs 预算。融合在图表归位后对至多 8 个失败段落合并发起一次局部修复，每段只提供其引用证据，重审通过且保留原有据句后才采纳。摘要和结构化组件使用确定性隔离，表格按单元保留已核验值。
- 已有证据能恢复此前隔离的段落。仅当章节旧阻塞来自已完整恢复的段落、且最终事实与交付核验通过时，允许恢复正式状态。必答内容失去最后一个输出引用时继续阻断，空正文也继续阻断。
- 验证涵盖分句、局部恢复、旧门禁、缺必答、无据预测、双期方向和来源观点。现有章级隔离测试改为断言结构化留痕和正文保全。

## AB-5 阅读语言与受限状态

- 解读重述与导出使用中文期间和口径，Markdown、auto HTML 和 rich HTML 共享阅读转换。百分数与百分点按两位小数显示，保留证据原值及 ID。单位未知的证据目录数值保留原量级。
- 自动模板中确实还有 26pt 封面水印样式，与 52pt 打印水印一起清理。受限报告使用摘要旁的状态提示和小页眉，核验事项进入附录。真实 PDF 视觉核查发现 rich 的 CSS 页码与 Chromium 页脚重叠，已统一使用 Chromium 页码。
- 通过两种模板的真实 Chromium PDF 回归，核对摘要、目录链接、关系文字、附录和受限状态。原始未核验断言保留在事实审计附件。

## AB-6 产业链关系进入主图

- V2 主图使用已支持的工序断言，稳定边 ID 按端点生成，合并同向重复断言及证据。主 SVG 关系区保留方向、端点、断言 ID 和证据 ID。分类图仍显示上中下游层次，缺关系的报告走受限交付。
- 新建任务固定链图意图。已有明确的 CHAIN_ENGINE 配置优先，默认仅对请求了链图且有已审画像或选择开放研究的任务采用 V2。历史快照继续按原策略读取。
- 使用真实图表阶段适配器验证 V2 主 SVG 和落盘文件一致。核对辅助关系、历史快照、前端现有允许的 SVG 图元、PDF 关系文字及版本回归。关系区使用独立箭头行避免穿过分类卡片，浏览器 PDF 复核后调大文字。

## AB-7 企业名候选抽取

- 规范名单中的精确命中优先于长度和后缀筛选。未知候选补充“技术”“电池”后缀，继续过滤常见类别词、数字尾缀及重复词。候选结果仍按现有层级核验业务关系。
- 离线覆盖短名、长全称、白名单优先级、未知后缀和类别词误召回。

## 接手后的验收边界

- 磁盘执行日志与实现表明 AB-1 至 AB-3 已落盘，本轮从 AB-4 开始。AB-1 至 AB-3 的历史数据迁移、自然语言月窗及其他延后项仍以其对应小节为准。
- 七个登记用例均完成合成记录→融合取数→解读→图表→模拟章节→三格式交付的离线验证。覆盖的是交付契约和代表性财务数据，PDF 布局由单独的本机 Chromium 用例验证。真实源覆盖率及真实模型表达属于后续实测。
- 全量回归通过清除凭据的临时源副本运行，保留仓库现有官方财务重述夹具。外部网络在 Python 验证中关闭，本机 Chromium 与回环测试服务器单独启用。
- 最终全量离线回归为 **1960 passed / 1 failed / 64 skipped / 1 deselected**。唯一失败仍为接手前已有的 `test_new_02_combo_growth_rates_preserves_both_series`，断言使用“同比增长率”，实际显示名称为“同比增速”。两套真实 Chromium PDF 用例和七条合成交付用例均通过。
- 最后一处 auto 分页调整后重新运行 `backend/tests/test_pdf_continuation.py`，4 项通过。两套模板均验证附录标题与核验内容同页。
