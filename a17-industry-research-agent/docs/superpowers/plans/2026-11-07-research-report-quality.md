# 行业研报体验与五行业实测实施计划

> **执行约定**　使用 Superpowers 的 `subagent-driven-development` 或 `executing-plans` 逐任务实施。在本文件里随做随更新。

## 进度记录

**交接点**　按当前安排在 T3 完成后停止。T0–T3 已验证并勾选，接手人从 T4 开始。当前阶段使用离线数据，未调用外部 API。

- 开始任务时，将任务状态改为“进行中”。每一步完成并核对结果后，立即把该步骤由 `[ ]` 改为 `[x]`，在进入下一步前记下测试结果、运行编号或产物链接。
- 遇到阻塞时保留未完成的复选框，并在该步骤下记录阻塞原因和下一步。按需执行的真实源用例如未执行，记为“未执行”并保留未勾选状态。
- 本任务的必做步骤全部验证后，将任务状态改为“已完成”。阶段交接时核对计划中的状态与实际测试和产物。

**目标**　让网页研究问题中的公司、期间、指标和证据要求贯穿取数、分析、图表、章节及交付，产出可读、可追溯的研报。

**架构**　沿现有五阶段流程复用研究需求矩阵、行业参考库、证据索引和审核版本。先修样本与口径，再用同一批证据驱动图表、写作与核验，最后通过网页实测确认人工审核、报告状态和 PDF 交付。

**技术栈**　Python 3.11+、FastAPI、Pydantic、pytest、Vue 3、TypeScript、Vitest、Node.js 22–26、npm 10+、Playwright/Chromium、PyMuPDF。

**依据**　[用户视角实测缺陷.md](<../../../../用户视角实测缺陷.md>) 提供缺陷与改造候选，[五行业选题与网页研究问题.docx](<../../../../五行业选题与网页研究问题.docx>) 提供网页问题、已有试跑反馈与 PDF 页码反馈。文档内的建议作为规划输入，本文中的优先级、抽样策略和验收规则为拟定方案。

## 范围与基线

- 具身智能留档 `run-20261106221050-ec4d63cc962f` 是跨阶段回归样本。缺陷文档记录 664.3 秒、383 项待核验定量断言、10 张单日截面对比图。已在该留档的 Markdown 中核对到 107 行含“资料缺口”，PDF 为 35 页且 35 页均可提取页脚页码。分别记录文档观测与本次核对结果。 [留档 Markdown](../../../data/runs/run-20261106221050-ec4d63cc962f/artifacts/report.md) · [留档 PDF](../../../data/runs/run-20261106221050-ec4d63cc962f/artifacts/report.pdf)
- 现有实现已有年度财务需求、定向取数、写作修复、产业链图、正式导出门禁和 PDF 目录分页。以网页入口复现及缺失断言驱动增量修改。白酒缺页码反馈需对应到具体产物或复现路径。
- 离线主验收覆盖具身智能 1 条基线和五行业各 1 条问题。白酒另测第 1 题的现金流成因与标的约束，其余 14 条作为扩展回归题。真实源验收按下方调用预算分批执行，单独记录覆盖范围和受限交付原因。
- 实施顺序为 **T0 → T1 → T2 → T3/T4 → T5 → T6**。T3 和 T4 共用 T2 的证据契约。T5 的审核复测需要 T3、T4 的产物。任务命令从 `a17-industry-research-agent/` 运行。当前目录没有 Git 元数据，以任务级测试结果记录检查点。

## 全局约束

- 复用 FastAPI 接口、现有阶段状态和 `record_id`。存量任务缺少新字段时按已有契约读取。新增证据和修订都走现有版本、失效与重建机制。
- 用户点名的有效证券优先。行业参考库用于未点名时的候选排序和研究方向，入选及产业链归属仍需证据。研究样本、产业链节点和背景参照分开，支持经核实的跨环节成员。
- 对比必须匹配主体、指标、观测期间、期间类型、合并或分部口径、币种和单位。数据的披露日与观测期分别校验。补采、重述和衍生计算保留原始证据关联。
- 正文、摘要、表格和图表均受最终核验约束。数字、趋势方向和因果关系分别验证。审计详情集中呈现，保留正式与受限交付的真实区别及下载权限。
- 默认使用留档、固定夹具、模拟外部响应及本地 Chromium。常规测试、PDF 检查和审核交互回归使用零次外部 API 调用。产业链图使用本地 ECharts，保持 AI 配图关闭。
- Python 按仓库约定使用四空格、类型注解和 `snake_case`。Vue/TypeScript 使用两空格、单引号、100 列宽。真实数据用例标为 `live`，测试夹具不含凭据或完整供应商响应。

## 审查重点

| 易漏场景 | 对应回归 |
| --- | --- |
| 同一问题同时指定行业宏观 2021–2025 和公司财务 2023–2025 | T2 的双窗口测试 |
| 点名证券缺数据或解析有歧义，同时召回热门概念股 | T1 的样本约束测试 |
| 结论删去数字后仍声称行业上升或某项因素导致变化 | T4 的语义复审测试 |
| 更新产业链归属后，旧章节或 PDF 仍可正式下载 | T5 的修订失效测试 |
| 相同章节标题、长目录或不同导出模板导致页码错位 | T6 的 PDF 两模板测试 |

## 文件与责任

| 位置 | 责任 |
| --- | --- |
| `backend/app/agents/adapters.py`、`agents_core/data-fetcher/data_fetcher/agent.py`、`agents_core/industry_reference/registry.py` | 从网页输入保全公司、指标及期间约束，使用现有候选与取数策略 |
| `agents_core/data-analysis/data_interpreter/engine.py`、`agents_core/financial_semantics.py` | 可比性、衍生指标和可引用证据 |
| `agents_core/chart-generator/chart_generator/agent.py`、`agents_core/chain-research/chain_research/graph_spec.py` | 图表选型、已审产业链和证据绑定 |
| `agents_core/chapter-writer/chapter_writer/agent.py`、`agents_core/report-fusion/report_fusion/agent.py` | 生成、补写、事实审计与最终交付判定 |
| `agents_core/report-fusion/report_fusion/render.py`、`templates/{auto,rich}/`、`styles/print.css`、`pdf.py`（后三项位于同包） | 阅读视图、术语、审计附录和 PDF 页码 |
| `backend/app/engine/state_machine.py`、`backend/app/api/routes.py`、`frontend/src/views/{ReviewView,ReportPreviewView,ReportDownloadView}.vue` | 审核流转、版本化发布、预览与下载 |

表中列出排查入口。仅修改失败用例定位到的责任层。

## T0　固定基准和网页验收数据

**状态**　已完成

- [x] 把本计划“五行业验收矩阵”的主测和追加问题连同具身智能原始输入登记为回归用例。固定研究截止日、原始问题、明确公司、指标、每项观测期和期望图表。具身智能使用留档 `input_data.json` 的研究输入。白酒第 3 题的“四家”在独立运行时补齐公司全称。
  - 验证记录　[回归输入](../../../eval/cases/research_report_quality.json) 已登记 7 条用例，请求均通过后端校验。具身智能研究输入与留档逐项一致，其他题统一使用 2026-11-06 截止日。
- [x] 从原有产物保存可比的聚合指标。至少记下核心样本、期间缺口、图表类型、事实审计分项、占位符行数、阶段终态和实际产物。未找到原 PDF 的试跑记录保留为“反馈待复现”。审计计数以运行产物的分项为准。
  - 验证记录　具身智能留档有 1237 条结构化记录，财务样本为中兴通讯、优刻得、深圳华强、深桑达A。财务年度为 2021、2025，中间三年缺失，预期四家核心样本均未进入财务记录。
  - 图表 10 张（bar 3、comparison_bar 4、diverging_bar 1、horizontal_bar 2），另有 95 个候选被压制。审计 441 项（定量 383、因果 12、附录 45、交付规则 1），正文 107 行含“资料缺口”。
  - 留档状态为等待融合审核、受限可交付。状态首尾时间差 665.8 秒，缺陷文档记录生成耗时 664.3 秒，两种口径分列。已核对产物大小（md 65,145 B、html 246,809 B、pdf 3,853,674 B）和 PDF 页脚 35/35。白酒缺页码及三个章节审核试跑反馈待定向复现。
- [x] 准备小型可重复夹具，覆盖正确记录、非同行记录、较新季度、缺年、迟披露、审校失败与两个同标题章节。夹具包含原始指标值和引用关系，优先复用留档中可安全使用的记录。真实源只用于 T6 的最小实测。
  - 验证记录　[离线夹具](../../../backend/tests/fixtures/research_report_quality.json) 的 8 条合成财务记录均通过生产记录模型校验，核对了缺年、季度、迟披露、审计引用与同标题不同锚点。
- [x] 运行基准测试，记录环境与结果。

```bash
python -m pytest backend/tests/test_pdf_continuation.py backend/tests/test_chart_comparability_continuation.py agents_core/report-fusion/tests/test_final_delivery_contract_v8.py -q
```

基准记录（2026-11-07，项目虚拟环境 Python 3.11.17）为 **20 passed，7 条 PyMuPDF SWIG 弃用警告**。

## T1　锁定研究样本与候选证据（P0）

**状态**　已完成

**文件**　`backend/app/agents/adapters.py` 的 `FiveAgentsAdapter.run_data_fetcher`、`data_fetcher/agent.py` 的 `DataFetcherAgent._understand` 与 `data_fetcher/fusion.py` 的 `DataFusion.fuse`。后两项位于 `agents_core/data-fetcher/`。复用 `IndustryRegistry.resolve_security` 和 `IndustryRegistry.candidates_for`。

**接口**　网页问题传入既有 `ResearchRequest`。使用 `ResearchObjective.requirements` 携带确认的主体约束。阶段产物延续 `StructuredResearchDataset` 和 `quality_summary.requirement_evidence_matrix`。

- [x] 在 `agents_core/data-fetcher/tests/test_financial_eligibility_v8.py` 加 `test_named_cohort_survives_concept_recall`。以白酒四家为输入，模拟巨力索具、其余白酒公司及缺数证券。断言财务横向比较和估值样本只含四家有效指定证券，缺数项仍有明确缺口，歧义名称待确认，补采不会替换指定样本。
  - 验证记录　离线测试已收集并运行，覆盖固定样本和指定公司缺数。
- [x] 运行 `python -m pytest agents_core/data-fetcher/tests/test_financial_eligibility_v8.py -q`。若新增断言已通过，保留测试并继续核对网页输入到图表与报告的路径。
  - 验证记录　复现结果为 11 通过、1 失败。意图阶段把模型返回的洋河股份和巨力索具合并进了用户明确指定的四家。
- [x] 收口主体约束的传递与消费。开放式主题沿现有行业参考库按环节提候选，用业务证据确认；仅概念关联的公司可作背景且有清晰标签。具身智能夹具用三花智控、拓普集团、绿的谐波、鸣志电器检查覆盖，优刻得、深圳华强和中兴通讯的概念召回不覆盖核心样本。参考库未覆盖主题时，沿现有检索取候选并保留待核验状态。
  - 验证记录　已接通网页结构化标的及问题中的明确名单。取数、可比公司表和财务补采复用同一范围，机器人环节候选仅供业务证据检索。
- [x] 重跑用例并附上数据、图表、正文的样本对账。断言跨环节公司以规范证券标识去重，背景记录不会混入主样本。
  - 验证记录　42 项离线测试通过。缺数的山西汾酒保留缺口，洋河股份与巨力索具未进入主样本。可比公司表按证券代码去重，生成图表及 Markdown 证据表引用与主样本对齐。

## T2　补齐年度序列与财务口径（P0）

**状态**　已完成

**文件**　`agents_core/data-fetcher/data_fetcher/agent.py` 的 `_annual_financial_requirements`、`_priority_annual_tasks`、`_evaluate_requirement`，以及 `agents_core/data-analysis/data_interpreter/engine.py` 和 `agents_core/financial_semantics.py`。

**接口**　现有 `ResearchRequirement` 及覆盖矩阵按指标、主体和观测期表达要求。输出沿用分析报告 `evidence_index`、`financial_ratios` 和 `verified_calculations`，供 T3 和 T4 消费。

- [x] 在 `agents_core/data-fetcher/tests/test_metric_requirements.py` 加 `test_focus_keeps_separate_macro_and_company_year_windows`。光伏装机只有 2021–2025，四家公司财务只有 2023–2025。加入 2026 年前三季度、一个缺失年度、一个截止日后披露项。断言三者均无法满足所需年度格。
  - 验证记录　光伏主测和 T0 夹具已接入测试，覆盖独立年度窗口和截止日。
- [x] 在 `agents_core/data-analysis/tests/test_engine_dynamic_refactor.py` 加 `test_derived_financial_metrics_require_matching_operands`。断言毛利率从 30% 到 28% 是下降 2 个百分点。研发费用 12、同口径营收 100 得到 12% 研发费用率。经营现金流 12、归母净利润 10 得 1.2 倍。零或缺失分母、错期或错口径不计算。同比仅使用相邻可比期，若用户要求 2023 年同比，2022 只作计算基期。对负利润基数单列盈亏变化，常规同比及现金转化效率结论须有适用性说明。
  - 验证记录　财务计算测试覆盖证据绑定、零值和负值分母、错期、分部口径及隔年比较。
- [x] 运行 `python -m pytest agents_core/data-fetcher/tests/test_metric_requirements.py agents_core/data-analysis/tests/test_engine_dynamic_refactor.py -q`，确认失败点属于输入切分、覆盖或计算中的哪一层。
  - 验证记录　离线复现为 14 通过、2 失败。公司财务被扩大到 2021–2025，且分析结果没有研发费用率。
- [x] 修正分指标期间绑定。定向按公司、指标、年批量补齐缺格，遵守既有请求预算和截止日。未指定年份的核心财务趋势优先收集连续 3–5 个已披露完整财年。披露缺失或预算耗尽时记录缺格与原因，供写作和交付使用。同比、百分点、比率与 CAGR 各用同口径输入，计算值保留输入记录 ID，正文和图表展示用同一口径。
  - 验证记录　取数现在按每个指标的时间窗口建立需求，行业序列按指标批量补齐。同比额外基期有独立标记。研发费用率与净现比在统一口径下绑定两条原始记录。
- [x] 重跑测试。抽查年度表、样本数、图表数据及结论引用能追溯到同一证据，白酒现金流的成因证据单独检查合同负债、应收及存货，记录支持程度。
  - 验证记录　141 项离线测试通过，覆盖历史预算、年度缺格、季度及迟披露排除、毛利率百分点、研发费用率和净现比。白酒成因在全链路验收中核对，分析层已改为提示需营运资金明细佐证。

## T3　生成与问题匹配的图表（P1）

**状态**　已完成

**文件**　`agents_core/chart-generator/chart_generator/agent.py` 的 `_deterministic_fallback`、`_candidate_semantic_key`、`_synthesize_option_from_evidence`。产业链复用 `agents_core/chain-research/chain_research/graph_spec.py` 的 `bundle_to_chain_spec`。

**接口**　消费 T2 的证据索引与已审产业链关系。保留现有 `ChartSpec`、证据引用及显式图表缺口契约。图表标题、系列、轴、单位、期间与样本使用同一规格。

- [x] 在 `agents_core/chart-generator/tests/test_audit_chart_quality_20261102.py` 加 `test_requested_chart_families_follow_evidence`。足量且同口径夹具能产出年度 `line`、营收与已验证增长率双轴 `combo`、带证据的 `industry_chain`。断言两轴单位、每个系列的来源、毛利率水平与百分点变化、研发金额与研发费用率均各自一致。
  - 验证记录　离线夹具含年度营收、已验证归母净利同比、基期及产业链证据。
- [x] 同一测试文件加 `test_missing_period_cannot_be_filled_by_snapshot`。缺年时断言组合图不使用较新季度，趋势显示缺点或标出未交付原因，明确要求的产业链图不会被重复截面图顶替。
  - 验证记录　同一夹具加入缺年和较新的季度，检查图表缺口。
- [x] 运行 `python -m pytest agents_core/chart-generator/tests/test_audit_chart_quality_20261102.py backend/tests/test_chart_comparability_continuation.py backend/tests/test_requested_chart_shortfall.py -q`。
  - 验证记录　首次离线运行 36 通过、1 失败。证据足够仍缺双轴图。
- [x] 调整既有候选排序和去重，优先保留显式要求且有证据的图表。白酒水平对比与同比变化分开，光伏装机趋势使用行业指标，新能源汽车渗透率标注分母。跨环节业务在拓扑中允许多条有证据的边，样本统计仍按同一证券计一次。
  - 验证记录　双轴候选跳过同量纲组合，按经核验的年度需求过滤基期和季度证据。明确请求的图表类型可获得离线保底。相关 62 项测试通过。
- [x] 重跑测试并对照网页图表、SVG 和 PDF。确认用例中的线图、双轴图及产业链图各回答不同问题，证据不足的图表有对应说明。
  - 验证记录　离线产出的折线、双轴和产业链均生成有效 SVG，并进入 Chromium PDF。缺年用例保留产业链并记录时序图缺口，未用季度顶替。

## T4　证据约束、写作修复与投研表达（P0）

**状态**　待开始

**文件**　`agents_core/chapter-writer/chapter_writer/agent.py` 的 `SYSTEM_PROMPT`、`_generate_audited_chapter`、`_audit_chapter`，以及 `agents_core/report-fusion/report_fusion/agent.py` 的 `_audit_numeric_components` 与最终视图核验，`report_fusion/render.py` 负责展示格式。

**接口**　章节仍使用 `ParagraphDraft` 等现有结构及局部 `evidence_ids`。量化事实复用 `quantity_issues` 和 `verified_calculations`。正文受限信息与原始审计问题分别进入现有正文和审计产物。

- [ ] 在 `agents_core/report-fusion/tests/test_final_delivery_contract_v8.py` 加 `test_unverified_forecast_is_not_republished_as_trend`。夹具包含有效历史事实和无来源的“9150 亿元”“6 万台”。断言摘要、章节及附录公开正文保留有据事实，无证据增长方向、因果和数字均被排除，审计记录可定位，正式交付权限遵循现有门禁。
- [ ] 同一测试文件加 `test_rendered_financial_language_preserves_audited_values`。断言展示为“2025 年合并财务报表”“销售毛利率 8.20%”，核验仍对应原始 8.1987%。覆盖 `annual`、`consolidated`、`gross_margin`、`rate_observation_change` 及百分点表达，引用 ID 和证券代码保持原值。
- [ ] 运行 `python -m pytest agents_core/chapter-writer/tests/test_agent.py agents_core/report-fusion/tests/test_final_delivery_contract_v8.py backend/tests/test_requirement_output_links.py -q`。
- [ ] 让写作提示及现有段落修复使用局部可核验材料，明确事实、推断和数据局限。优先保留有证据的句子，必要时在现有修复预算内重写一次并重新审计。只有证据本身支持方向、主体和范围时才能保留定性表述。未修复内容在最终阅读视图收拢为各章数据局限性，必答问题仍在覆盖矩阵标记为未完成。空摘要条目、空段及重复占位符按最终视图审计结果收口。
- [ ] 重跑测试。逐项确认 Markdown 与 HTML 正文无机械占位符，PDF 与两者口径一致。记录原始草稿问题数、修复后剩余问题和最终交付状态，便于区分真正修复与删减内容。

## T5　人工审核与双层交付（P1）

**状态**　待开始

**文件**　`backend/app/engine/state_machine.py` 的 `handle_review`、`_invalidate_downstream`、`_reexport_fusion_artifacts`，`backend/app/api/routes.py` 的审核和产物下载端点，以及文件责任表中的三个前端视图。

**接口**　沿用审核请求、阶段修订和现有 `draft_available`、`quality_notice` 等交付字段。服务端统一裁定 `formal` 与 `draft` 权限。

- [ ] 在 `backend/tests/test_delivery_invalidation_lifecycle_v8_final.py` 加 `test_chain_review_rebuild_invalidates_old_formal_artifact`。审核时剔除只具概念关联的公司，断言新版图、章节、报告及 PDF 的证据一致，旧正式下载失效，重复审核不会触发重复生成。覆盖同版多次提交和旧版请求。
- [ ] 在 `frontend/src/components/__tests__/ReviewActions.revise.spec.ts` 加 `shows the next action while chapter review is pending`，断言待审核可找到下一步操作。在 `frontend/src/views/__tests__/ReportPreviewView.spec.ts` 加 `shows the audit details for limited delivery`，断言受限版保留清晰状态和可展开的审计入口。扩展同目录的 `ReportDownloadView.spec.ts`，验证正式、受限、重建和失败四种下载状态。
- [ ] 运行 `python -m pytest backend/tests/test_review_revision_guard_v8.py backend/tests/test_delivery_invalidation_lifecycle_v8_final.py -q`，再从 `frontend/` 运行 `npm run verify`。
- [ ] 按现有审核机制确认章节审核的可操作路径，区分等待用户决定、后台处理中和处理失败。修订沿现有版本链刷新下游，导出失败明确显示产物状态。预览和 PDF 将详细问题归入数据核验附录，主视图简洁说明报告用途、当前状态、数据局限及可采取的操作。未经正式核验的 PDF 仍保留受限标识。
- [ ] 重跑测试。在低空经济网页主测中保留一次修订前后对照，记录剔除的样本、依据、版本和 PDF 下载状态。

## T6　PDF 回归与五行业验收（P1）

**状态**　待开始

**文件**　`agents_core/report-fusion/report_fusion/pdf.py`、同包的 `styles/print.css` 与 `templates/{auto,rich}/report.html`。测试扩展 `backend/tests/test_pdf_continuation.py`。

- [ ] 加 `test_pdf_prints_page_footer_and_matching_toc_for_both_templates`，参数化 `auto`、`rich`，覆盖短报告、长目录、重复章节标题和受限稿。真实 Chromium 渲染后逐页断言“第 n / N 页”位于页脚可见区域，目录页码等于链接目标物理页码，正文、图表和页码无重叠。打开 PDF 对照封面、目录、正文及附录至少各一页。
- [ ] 按白酒网页输入复现生成 PDF，核对实际导出模板和产物。运行 `python -m pytest backend/tests/test_pdf_continuation.py -q`。若复现异常，沿现有 `render_pdf` 定位页边距、模板或导出分支并修正。测试通过时保留回归。
- [ ] 跑完 `python -m pytest`，从 `frontend/` 跑 `npm run verify`、`npm run build`、`npm run test:e2e`。先用留档或固定夹具执行五行业主测与具身智能回归，模拟网页请求到导出的完整链路。真实源用例按下方调用预算独立记录。
- [ ] 按下表核验网页流程。光伏、低空经济、新能源汽车继续从章节审核推进到正式或受限交付，分别记录停留原因。技术错误、人工待审和数据覆盖不足分开记。具身智能优先用同一留档输入及证据回放。
- [ ] 保存验收记录，包含用例与 run ID、输入范围、实际样本及缺格、图表、引用抽查、各阶段用时、修订版本、正式或受限下载结果和 PDF 页码核对。每个核心问题至少核对一项正文事实及其来源，图表点和衍生计算另行抽查。

### 真实 API 调用预算

- [ ] 离线通过后，如需验证真实问财与模型的联动，首轮只用白酒第 2 题做一次网页冒烟。复用现有模型和问财配置，按既有请求预算执行，并记录模型、问财各自的调用次数。此轮结果只证明该题的实网表现。
- [ ] 查询只补验收所需且留档缺少的证据。使用已有批量查询、去重和重试上限，补采失败时记录缺格。修订后从受影响阶段恢复，避免为单项问题重跑整条链路。
- [ ] 仅当其他行业有离线无法验证的供应商行为，或明确需要五行业实网验收时，再逐条追加实测。验收记录按行业区分离线回放、实网通过和实网待测。

## 五行业验收矩阵

下表题号对应 Word 文档各行业内部编号。正文主张依据验收时取得的材料，题目中的公司、数字与市场用语只确定测试范围。

| 用例 | 主测与关键断言 | 扩展回归 |
| --- | --- | --- |
| 白酒 | **第 2 题**锁定贵州茅台、五粮液、泸州老窖、山西汾酒。2023–2025 同口径比较营收、归母净利、毛利率和经营现金流。同比或百分点图与标题一致。**追加第 1 题**检查现金流和利润差异解释；对合同负债、应收及存货证据逐项注明支持程度。验证 PDF 页脚。 | 第 3 题验现金转化比率和分母，第 4 题验渠道及产品结构披露边界。 |
| 半导体设备 | **第 1 题**锁定北方华创、中微公司、拓荆科技、盛美上海。核对 2023–2025 研发投入与费率、刻蚀/薄膜沉积/清洗的产品证据，区分已披露、推断和未知。 | 第 2–4 题检查研发指标、客户验证与量产阶段、产品收入和证据等级。 |
| 光伏 | **第 1 题**验 2021–2025 中国新增装机趋势及通威股份、隆基绿能、晶澳科技、阳光电源 2023–2025 的营收和毛利率。行业趋势、企业比较和拓扑各有可定位来源。 | 第 2–4 题验证分环节口径、装机/出货/营收区分和跨环节去重。 |
| 低空经济 | **第 1 题**按工业级无人机、eVTOL、运营服务和基础设施分类。依据公开主营业务材料区分实际经营与概念关联。人工剔除一个弱证据标的后，核对新版图、正文、PDF 和修订记录。 | 第 2–4 题验年报产品、收入及订单的证据等级，注册与飞行小时口径，试验、适航、运营的阶段证据。 |
| 新能源汽车 | **第 1 题**验 2021–2025 中国销量及渗透率和比亚迪、长安汽车、赛力斯 2023–2025 的营收、毛利率及经营现金流。渗透率分子分母同口径。整车与动力电池关系经证据验证，数据表、趋势图、拓扑及来源可对照。 | 第 2–4 题验统计分母及出口，整车分部与集团口径，动力电池企业与整车企业分组比较。 |
| 具身智能基线 | 验证已确认的核心环节公司覆盖、可比年度序列与图表结构。统计机械占位符、定量核验问题、实际交付状态和耗时，并与留档分开记录。 | 核对同一问题的低证据场景，交付范围与实际证据覆盖一致。 |

## 交付判定

- **正式通过**　问题明确要求的样本、期间、指标和图表交付齐全或有证据支持的适用性说明。最终审计通过，最新版本正式下载可用，PDF 目录和页脚均核对。
- **受限通过**　仅用于验证资料不足时的交付行为。可用事实和明确的数据局限进入可读草稿，正式下载权限正确。对应主测在正式覆盖栏标记“待补证据”，并记录缺格及可验证的补充方向。
- **未通过**　出现错主体、错期间、错口径、未验证主张、审核流转断开、旧版产物误发布或 PDF 目录与页脚错位。按责任任务修复并复跑受影响场景。
