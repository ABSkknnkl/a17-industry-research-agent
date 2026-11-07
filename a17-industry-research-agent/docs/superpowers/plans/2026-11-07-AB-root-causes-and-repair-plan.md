# A、B 档代码核查与修复实施方案

核查日期为 2026-11-07。本文件是基于当前交接目录的实施设计，范围对应用户列出的 A、B 项。任务编号 AB-* 是本文件新增的实施编号。

## 1 核查结论与原判断的差异

| 原问题 | 当前代码结论 | 对方案的调整 |
| --- | --- | --- |
| A② 资料缺口占位 | 成立。章节局部修复失败会整段替换，融合删句后为空也会造占位句 | 修复过程、降级结果、阅读呈现一起调整 |
| A③ 定量断言剔除且无自愈 | 融合阶段成立。章节阶段已经有局部重写和重审 | 复用章节修复能力，增加融合后的局部修复，避免叠加整章重写 |
| A⑤ 术语与精度泄露 | 成立。已有部分指标翻译，但解读重述主动拼接内部枚举，展示格式也未统一 | 从重述源头和两类导出模板共同修复 |
| A⑥ 大字草稿标识 | 成立。HTML 在目录前插入提示和水印，打印 CSS 明确为 52pt | 保留清楚的交付状态，用小型状态提示和审计附录呈现详情。26pt 未在本次核查到的样式中得到支持 |
| U-07 白名单未接取数 | 部分过时。参考库候选已进入意图与后续决策，明确点名样本已有硬过滤 | 剩余重点是开放主题的业务资格验证、单个点名和歧义身份，不能直接把候选库做硬白名单 |
| U-02 事件不进解读 | 原描述与代码不符。事件已注入证据池并按域派发 | 保留既有接线，补事件正文保全和事件必答需求的端到端验证 |
| U-05 无口径映射 | 部分过时。已有 metric_family、年度单元和经验证计算 | 重点修复非等价指标被当作别名，以及未知指标需求表达能力 |
| U-03 只留每实体最新一期 | 该表述不适用于全部路径。最新一期用于横截面，时序路径保留多期，缺点使用 None | 处理显式窗口与系列硬限额、两期趋势、来源冲突，保留合理横截面逻辑 |
| P-03 单位半修 | 成立，且风险可能涉及数值尺度 | 缺单位补元、按量级猜金额必须纳入取数与分析修复 |
| U-06 无数字—归因校验 | 原描述过强。已有数值语义、因果关键词及测量重述校验 | 补无数字的方向断言和因果支持边界，避免删除数字后保留无据结论 |
| D3-1/2 legacy 与两箭头 | 默认选路成立。但 V2 主图也进入同一个卡片间零连线的渲染器 | 同时覆盖选路、证据关系转换、主图渲染和前端消毒 |
| C-1 后缀遗漏 | 成立。技术、电池未在后缀列表，已验证会漏抽 | 优先识别规范实体，再使用后缀兜底，保留候选核验状态 |

“B 档共同点是不会给错数”不能作为实施前提。缺单位的尺度推断、研发投入与研发费用合并，均可能产生测量含义或尺度错误。现有防线对这些错误能否阻断，取决于进入证据池之前是否已被错误规范化。

旧留档中的 107 行占位、383 项断言、10 张图是既有计划记载的历史基线。本轮没有重新生成真实源报告，以下结论按静态路径证据与定向运行分别列示。

## 2 核查方式与运行结果

先使用 codebase-memory 的 index_status、search_graph、trace_path、get_code_snippet，再核查精确代码范围。索引 generation 为 2026-11-06T19:22:52Z，watch 已启用。本文件依赖的源码和已读测试文件经过 check_index_coverage，返回 metadata_match 和 no_recorded_issue。该信号仅表示没有记录到覆盖问题，核心判断另经源码核对。

在 Python 3.11 中直接导入生产模块并执行了以下小型验证，均未发起外部请求。

| 输入或操作 | 当前实际输出 | 支持的判断 |
| --- | --- | --- |
| 同一段内“甲公司2025年营业收入100亿元。甲公司2025年营业收入999亿元。”，证据只有100亿元 | 保留100亿元一句，删除999亿元一句 | 融合确实逐句改写最终段落 |
| 将上述句号改成分号 | 整段变为“【资料缺口】本项断言尚缺少同主体、指标、期间或数值的可核验依据。” | 分句粒度会连带删除有据内容 |
| infer_default_unit('revenue', domain=FINANCIALS) | 元 | 无来源单位也能取得金额尺度 |
| _normalize_money(12, None) | 12 | 分析层未知单位仍可进入金额规范值 |
| _format_card_value(8.1987, '%') | 8.1987% | 指标卡未统一展示精度 |
| quantity_issues('成本下降导致利润改善。', []) | unsupported_causal_claim | 已有因果护栏 |
| quantity_issues('行业未来将持续增长。', []) | 空问题列表 | 无数字的方向性预测未被该函数拦截 |
| 联网命中为“华为技术 宁德电池 联想集团” | 仅返回联想集团 | 后缀规则确实漏掉技术、电池结尾的候选。这里验证抽取行为，不证明合成名称的企业身份 |
| 相同节点，分别设置 A→B 和 A→C，调用 render_chain_svg | 两份 SVG 字符串完全相同 | 主图没有表达输入关系边 |
| metric_family('研发投入') 与 metric_family('研发费用') | 都为 rd_expense | 非等价业务指标被合并为同一指标族 |

尝试运行了下文的七文件 pytest 基线组合。当前解释器返回 `No module named pytest`，因此没有 pytest 通过数，也没有将既有计划中的 20、42、141 等通过数计作本轮结果。本轮验证属于生产函数定向运行，尚未覆盖网页、完整五阶段和真实 PDF。

## 3 调用链与数据流

### 3.1 研究样本与指标

`FiveAgentsAdapter.run_data_fetcher` 构造 ResearchRequest，将结构化公司输入写入 must_include_entities。`DataFetcherAgent._understand` 从参考库获取按活动划分的候选，将模型需求和年度指标需求合入 ResearchObjective。`_decide` 将 objective 与覆盖缺格送回决策，`_priority_annual_tasks` 对未满足的公司年度指标补采，技能响应由 `DataFusion.fuse` 转成 ResearchRecord，再由 `_evaluate_requirement` 生成覆盖结果。

明确样本约束通过 comparison_entities 传给 fusion，在 companies、financials 两域过滤。开放主题的 industry_candidate_slots 进入模型上下文，现有融合接口没有对应的开放主题业务资格参数。候选召回和业务证据准入仍是两个环节。[E4][E5][E6][E7]

### 3.2 分析、事件与写作

`DataInterpreterAgent.run` 先调用 engine.analyze，再补文本证据和 events。事件按 record_id 保留，`_filter_evidence_for_skill` 支持 event/events 别名，并以必需证据和实体轮转方式选择技能上下文。语义融合另有 80 条的可选证据预算，hard 需求关联证据优先保留。`build_analysis_facts → reconcile_text` 重述测量、覆盖与排名，结果进入洞察和写作上下文。[E8][E9][E10]

`ChapterWriterAgent.run → _generate_audited_chapter → _audit_chapter` 先产整章。仅剩段落错误时，按 paragraph_id 调一次局部修复并重审。失败分支用固定“资料缺口”替换段落，随后融合编辑器又拒绝把含“资料缺口”的原段落改成不含该词的文本，形成下游恢复障碍。[E1][E2]

### 3.3 图表与最终报告

数值图有候选生成、DataFormulator 规范化、图表编译及最终合同核验。`_deterministic_fallback` 的时序候选与横截面候选分开，横截面 latest 不能作为全部图表丢期数的依据。DataFormulator 的时间裁剪仍是固定政策，并有前10系列限制。[E11][E12]

融合链为 `ReportFusionAgent.run → _embed_charts → _audit_numeric_components(sanitize=True) → audit_appendix → _check_final_view → ReportViewModel → render_markdown/render_html → pdf_renderer`。章节、摘要、卡片、表格行、提示框均可能在融合审计中被修改。最终导出状态变化后会重新渲染，产物校验和随后刷新。[E2][E3]

链图在 run 创建时固定 chain_engine，未显式设置 evidence_v2 时进入现有默认路径。V2 图由 `bundle_to_chain_spec → render_chain_svg → _render_lane_grid` 生成主图，`render_bundle` 的关系图另作 aux_view。主图与辅助图是不同交付对象。[E13][E14][E15]

## 4 根因、触发条件和影响范围

### 4.1 A②与A③的失败降级丢失有效内容

触发条件包括局部修复关闭、修复响应不合法、paragraph_id 改变、重审失败或模型异常。章节层会清空整个段落的证据和假设说明，替换为固定占位。相邻有效段落保留，但同段内有据句也会丢失。指标卡和对比表在前置隔离时同样会被移除，并追加资料缺口提示。[E1]

融合层的 local_text 只按句号、问号、叹号切分。分号连接的好坏子句被当作一个单元，只要出现一个问题就整单元移除。key_points、metric_cards、callouts、表格行还有整项删除路径。摘要 headline、conclusions、risks、boundaries、takeaways 也受影响，修复范围必须覆盖这些容器。[E2]

章节已有局部修复，融合 sanitize 没有对应的局部重写。融合编辑器的占位词判断又阻止后续有据恢复。固定占位既成为阅读内容，也被用于识别不可编辑状态，混合了承载文本与审计状态两项职责。[E1][E2]

### 4.2 A⑤的内部字段与显示精度外溢

reconcile_text 的模板直接拼入 period_type、scope、metric、comparison_type，构成 annual、consolidated、gross_margin、rate_observation_change 等泄露入口。该重述会写入 executive_summary、insights、knowledge_facts、content_outline 和技能结果，再进入章节。[E9][E10]

render.py 已有 METRIC_DISPLAY_NAMES，但只在部分证据或附录字段使用。指标卡格式主要做字符串拼接，已验证8.1987会原样展示。不能全局正则替换所有英文和数字，证券代码、证据ID、URL、公式及原文引文需要有明确保护范围。[E3]

“方向一致率”是否在当前新跑产物中出现，本轮没有实测。应将其列作技术统计字段的展示验收项，结合字段含义决定译为附录统计或业务表达，避免盲目删词。

### 4.3 A⑥的提示进入阅读主流程

当 delivery_status 为 ready_with_limits 时，HTML 直接在 toc-page 前插入 aside 与 draft-watermark。打印 CSS 将水印定位为每页 fixed、52pt，Markdown 也在摘要前插入问题列表。影响所有受限报告的导出视图，包括后续状态变化导致的重渲染。[E3]

### 4.4 U-07的开放主题准入与身份边界

参考候选现已接入，明确样本在取数融合中也会过滤，因此不能重做一套固定白名单。剩余路径包括开放主题由模型返回的公司进入 must_include_entities，却没有 comparison_entities 的固定名单约束。当前候选政策以提示形式进入决策，不能证明财务样本经过业务关联核验。[E4][E5]

另外，问题文本推断 explicit 需要至少两个识别到的公司，并在发现“例如、比如、等企业”等词时跳过该推断。单一明确公司若只写在问题里、结构化名单为空，可能没有进入固定样本约束。这是源码触发条件，尚未在网页入口复现。[E4]

显式身份冲突会从 combined_entities 排除，但 annual 要求使用 explicit，后续补采如何处理冲突需专门测试。方案应先阻止歧义身份驱动财务补采，同时保留“待确认”的需求格。

### 4.5 U-02的现有接线与残余风险

events 已注入证据池，不能再归因为 all_records 不含 events。事件单独进入证据池也避免了被财务时序去重。[E8]

`_event_evidence` 使用 `value=ev.title or ev.body`。同时存在标题、正文时，正文不会进入该 EvidenceRef.value。若标题只有“公告”，关键催化内容只在正文，技能上下文可能缺少实际事件内容。事件未绑定 hard 必答需求时，也可能在语义融合的可选证据选择中被挤出。后者是条件风险，需要预算挤压夹具验证，不据此宣称所有事件催化都缺失。[E8][E9]

### 4.6 U-05的非等价别名与需求表达

已有同义指标映射、财务计算和逐年补采。具体缺陷是 metric_family 把“研发投入”和“研发费用”都映射到 rd_expense，年度需求解析也使用这一合并规则。更早的fusion.py第80–83行已把两类金额映射到rd_expense，把两类占营收比例映射到rd_ratio，因此仅修后续审计无法恢复已丢失的定义。研发投入可能包含资本化部分，合并后“费用率”可能使用错误分子，且后续审计会把同族数据视为匹配。[E4][E5][E16]

模型 metric_requirements 解析主要接受 metric_terms、domain、min_records、requires_period_end 等字段，无法完整表达用户点名的主体、期间、范围、单位及是否接受替代口径。应扩展当前需求契约并复用覆盖矩阵，未知定义保留待核。[E4]

### 4.7 U-03的截断政策与已修复路径

DataFormulator 的 `_filter_recent_periods` 在超过36个观察期后使用最近5年或最后48期，与显式研究窗口脱节。时序表仅取前10系列，fallback 时序也取前10实体，横截面取前30实体。若用户显式要求更长窗口或更多主体，可能静默丢失指定数据。[E11][E12]

fallback 生成线图要求至少3个时点，两个有效年点是否能通过其他路径产出图需测试。当前代码支持多期，missing 值已是 None，latest 只在横截面使用。这些行为应作为回归基线保留。重复同主体同期值还存在 date_map 直接覆盖的路径，需要对冲突数据先隔离再成图。[E11][E12]

### 4.8 P-03的无来源单位变成可信单位

fusion 按列头括号、行级单位、默认推断的顺序决定单位。经典金额指标缺少单位时 infer_default_unit 返回元，ResearchRecord 未在该分支标出“单位推断”。下游再保留 record.unit 进入 EvidenceRef，最终审计难以区分原始单位和推断单位。[E5][E8]

engine._normalize_money 对未知单位按数值量级推断，无法可靠区分12元、12万元或12亿元。图表端已有未知金额单位拒绝规则，但它无法识别上游已经默认为元的记录。因此根治层应包含融合和分析，不能只改图表轴标题。[E8][E11]

### 4.9 U-06的现有校验边界

quantity_issues 会检查数字的主体、指标、期间、单位，也检查命中因果关键词的子句。因果接受条件之一是该子句逐字包含在局部文本证据中。它属于文本支持检查，尚不足以分辨被转述的是事实、观点、假设还是否定句。reconcile_text 明确只处理测量、覆盖、排名，并未承担任意因果推理。[E10][E16]

定向验证中，无数字的“行业未来将持续增长”返回空问题列表。数字剔除后留下“持续增长”“受益于需求改善”等方向或归因，不能依赖现有数量检查自动排除。应在局部修复和最终视图上复用同一语义支持规则。[E2][E16]

### 4.10 D3-1/2的关系在主图渲染时消失

默认 chain_engine 为空，仅显式 evidence_v2 才走V2。历史任务缺快照继续按legacy解释，这属于已有兼容约定。[E13]

legacy 数值图 fallback 还存在按上下游数组下标配对造边的逻辑。generic render.py 的 industry_chain 分支读取节点，却只画列间箭头。更关键的是主图 chain_render._render_lane_grid 明确采用卡片间零连线，即便V2 bundle已经编译出受支持 edges，主图也不绘制。辅助 render_bundle 的关系测试不能证明主报告图通过。[E12][E14][E15]

因此“开启V2就会出现全部结构边”与实际代码不符。修复必须在主图真实入口验收关系，且所有边均有原始断言或经核验结构依据。

### 4.11 C-1的后缀过滤顺序

extract_company_candidates 先切词、限长、排短语，再检查后缀，最后才根据 whitelist 归类。因此即便已在白名单中，技术、电池结尾的名称仍会在后缀步骤被跳过。3到10字符限制也会拦截部分短品牌及完整长公司名，简单加两个后缀只能修复其中一部分。[E17]

looks_like_entity_name 还有类别词过滤，不能将“加后缀”与“允许任何行业类别词成为公司”混同。抽到的候选仍需身份与业务核验。

## 5 可执行修改任务

执行时先为每个任务加入最小失败测试，确认实际失败点，再修改责任层。每个任务完成后记录新增测试与原有回归结果，随后进入依赖任务。新字段应给出默认值，旧产物通过显式兼容读取，发生实质修订时走现有阶段版本和失效机制。

### AB-1 明确指标定义与来源单位

**修改对象**　financial_semantics.py 的 metric_family、verified_calculations，data_fetcher 的 models.py、agent.py、fusion.py，以及 data_interpreter 的 engine.py。先通过代码图定位模型字段、_paired_calculation 和金额规范化调用者，再作精确修改。

**改动范围与行为**

1. 从fusion字段规范化、年度需求到metric_family，将研发费用、研发投入及各自占营收比例拆成不同指标定义。研发费用率只接受费用分子。投入费用化/资本化拆分齐全时，才能由明确公式推导费用，保留全部输入record_id和公式。旧记录若只剩rd_expense而无可核对原始字段，应标记定义待核，不能根据规范名反推一定是费用。
2. 在ResearchRecord、EvidenceRef及需求覆盖产物中增加最小必要的单位来源信息，可用 source_field、source_schema、unknown、legacy_unknown 四类。列头或行字段的单位应保留出处，冲突应记录问题。
3. 仅供应商已验证schema能提供字段默认单位。通用缺单位金额保留unknown，排除于金额比较、比率计算和量化覆盖。保留原值用于审计和定向补采。
4. 去掉未知金额按绝对值猜尺度的参与路径。旧产物按原始字段或明确schema重建单位依据，无法恢复的标记待核。百分数、比例和百分点分别处理，禁止仅凭0.12的大小推断口径。
5. 扩展现有ResearchRequirement表达主体、期间、指标定义、范围与单位条件，替代口径另有字段记录。覆盖不得因为替代指标存在就把原需求标为满足。

**风险与回归**　部分历史数据会由可计算变为待核，需对应补采缺格。涉及所有比率、排名、轴单位及事实核验，必须重跑原单位与财务语义回归。风险来自规范化源头，优先于文案修复。

### AB-2 完成开放主题样本与事件材料保全

**修改对象**　adapters.py 的run_data_fetcher，data_fetcher/agent.py的_understand、任务规划与覆盖，fusion.py的样本准入，industry_reference/registry.py的既有身份和角色接口，data_interpreter/engine.py的_event_evidence、agent.py的证据选择。

**改动范围与行为**

1. 明确点名包括单公司，沿用comparison_entities，不让模型扩写名单改变研究样本。歧义名称保留待确认需求，暂停其定向补采。
2. 开放主题以参考库给有界候选，优先使用现有role_decision核验业务资格。将已核业务样本、概念背景、待核候选区分记录，只有已核业务样本进入核心财务比较。参考库外但有可靠业务证据的主体可准入。
3. 若既有dataset模型没有样本角色字段，增加有默认值的轻量角色映射，明确证据ID与判定原因。下游分析、图表、写作消费同一映射，行业汇总与背景证据保留其上下文。
4. 事件证据同时保留标题与正文，保持事件record_id、announce_date和来源。复用结构化字段或用明确分隔文本，避免丢正文及把同公司不同事件合并。
5. 用户明确要求事件催化时，在既有需求矩阵建立可验收事件需求，其证据进入优先选择集合。技能域过滤继续隔离不相关财务证据，预算超限沿现有上下文打包机制记录缺口。

**风险与回归**　开放主题样本可能减少，必须展示待核与缺样原因，不能用热门概念公司补足数量。事件正文会增加上下文长度，需预算与重复事件回归。该任务复用现有T1和U-02实现。

### AB-3 使图表窗口和样本规模服从研究需求

**修改对象**　chart_generator/agent.py的候选生成与_synthesize_option_from_evidence，data_formulation.py的formulate、_filter_recent_periods、_formulate_time_series，必要时扩展既有图表请求字段。

**改动范围与行为**

1. 优先从年度需求矩阵读取窗口和主体，将其传入规范化阶段。显式窗口覆盖默认最近期裁剪政策。
2. 指定主体超过单图容量时，按确定顺序拆图并延续相同轴单位。受图数预算限制时，输出具体未交付主体或期间，显式要求不能静默截断。
3. 两期同口径有效数据允许生成变化图并写明只有两期观察，不能据此宣称长期趋势。横截面继续使用共同可比期间，不把多期全塞入一张横截面图。
4. 缺年保持None，connectNulls关闭，必要时补入要求但缺失的年份类别。重复同期冲突值先隔离，禁止字典覆盖决定赢家。
5. 每个可见数据点绑定真实record_id。raw_evidence_ids与实际绘制点一致，未绘制但用于计算或审计的记录另留来源，避免“引用了就算画出”。

**风险与回归**　拆图影响图数、图号、章节归位及PDF分页。需覆盖缺年、双轴、共享金额轴、三格式引用一致性和显式图表缺口。先保留已有T3线图/组合图保底逻辑。

### AB-4 在同一证据语义下修复正文

**修改对象**　chapter_writer/agent.py的_generate_audited_chapter、_audit_chapter、_fallback_chapter，report_fusion/agent.py的_audit_numeric_components、_apply_editorial、run、_check_final_view，financial_semantics.py的现有断言检查，必要时扩展既有审计模型。

**改动范围与行为**

1. 先将审计检测与内容变换分开，保留原始文本、位置、问题码、证据、处理结果。旧schema读取有默认值，审计文件记录初始问题、已修复、已隔离和仍未解决问题。
2. 共享分句规则覆盖句号、分号、换行，保留表格单元和证据关系。句子内部多个事实应按可识别事实单元处理，不能仅因为某个数字错误丢掉整行有效数据。
3. 在现有max_repairs预算内对失败单元局部修复，传入同主体、期间、指标、范围、单位的证据和已验证计算。接受候选须通过结构、数字、方向、因果、引用重审。max_repairs=0时直接执行确定性保留与隔离。
4. 融合在编辑和图表归位后使用同一局部修复规则，覆盖章节摘要、段落、要点、指标卡、表格、提示框、执行摘要各字段。融合调用数需设置固定上限，保留现有上下文预算，禁止每个错误触发无界调用。
5. 局部修复失败时保留有据内容，把尚缺问题归并为章级“数据局限”。无有效内容的段落或摘要条目移出阅读容器，保留结构化缺口及原始审计位置。必答问题继续在覆盖矩阵未满足，不能因隐藏占位通过门禁。
6. 用审计状态替代_apply_editorial对“资料缺口”字符串的硬判断。允许有据候选恢复原位置，完成重审后更新结果，失败保留审计记录。
7. 将方向与因果规则用于修复后和最终视图。可比两期事实能支持方向，单期或跨口径不能。直接事件证据应保留观点/事实/假设性质。原文逐字出现不应自动把观点升级为已证实因果。
8. 交付判定使用最终未解决事实问题、必答覆盖、引用和导出结果。原始问题继续留档，不能让旧错误计数误导阅读状态，也不能因为删光正文而通过最终核验。

**风险与回归**　当前test_failed_paragraph_becomes_a_gap_without_rewriting_other_paragraphs明确期待旧占位行为，需要调整为“有据句保留、无据内容隔离、章级局限、其他段落不变”，同时保留原局部修复调用次数和异常原因测试。新增或调整审核字段应检查适配器序列化。涉及最终门禁判定的改动必须守住旧版报告失效、证据引用、图表归位、重导出撤销和hash刷新回归。

### AB-5 统一阅读语言与受限状态呈现

**修改对象**　measurement_facts.py的reconcile_text，report_fusion/render.py的显示函数及两个渲染入口，templates/auto和templates/rich的执行摘要、section、data_quality_appendix，以及styles/print.css。

**改动范围与行为**

1. 使用已审核结构字段生成中文阅读文本。年度、合并范围、指标和比较类型建立确定性映射。模型原始事实值、ID和公式分别保留，显示转换有明确字段边界。
2. 百分比水平和百分点变化默认展示两位小数，使用同一舍入规则。8.1987%展示为8.20%，小于0.01%的非零数展示为“小于0.01%”等有界表达。关键有效位或明确用户精度另有设置。
3. 卡片、表格、正文重述、摘要和证据目录使用同一显示规则，最终显示文本再过核验。代码、URL、证券代码、record_id和原文引文按字段保护，禁止对最终HTML整体替换英文或数字。
4. ready_with_limits使用小型状态文字，摘要前仅保留必要的一句限制。详细问题、修复与缺格放审计附录。移除fixed的大水印，在页眉/页脚保留清楚的受限标记。正式状态显示与实际delivery_status一致。
5. Markdown和HTML由相同阅读视图输出，PDF使用最终HTML。auto/rich均包含审计附录入口、状态与页码，不依赖模型编辑是否成功。

**风险与回归**　中文指标映射可能影响审计识别，显示层要接受舍入容差并保留原值。缩短前置提示可能改变目录分页，需用真实Chromium PDF核对。界面和下载权限沿既有状态规则读取。

### AB-6 交付真正表达证据关系的产业链主图

**修改对象**　state_machine.py的resolve_execution_snapshot与历史快照读取，adapters.py的run_chart_generator和_sync_chart_artifacts相关路径，chain_research/graph_spec.py，chart_generator/chain_render.py、agent.py和generic render.py产业链分支，必要时调整前端SVG消毒白名单。

**改动范围与行为**

1. 先完成主图关系渲染验收，再决定新建run的默认引擎。建议新run优先evidence_v2，只有满足画像/开放研究与证据契约后采用。历史run按已存快照解释，不能通过进程环境变更静默切换历史任务。
2. 复用受支持断言生成关系，edge具有稳定ID、source、target、方向、类型、assertion/evidence映射。legacy按数组索引配对的边不得冒充核实关系。没有关系证据时明确图是环节分类，保留关系缺口。
3. 在实际主图入口绘制跨列、同列、多对多和跨环节边。复用可用的辅助关系图布局和证据映射，按拥挤程度拆成有编号的关系分图，主报告必须包含该分图，不能只落aux_view文件。
4. 卡片分类图可以保留，但不能以两根列间装饰箭头满足结构关系验收。前端消毒、SVG资产同步、HTML嵌图、PDF均应保留稳定edge ID或可校对的关联映射。
5. 关系新增或审核修订沿现有版本机制使旧图和依赖章节、报告失效，重新生成后才能发布当前版本。

**风险与回归**　默认V2会影响证据覆盖、运行成本和可交付性，必须在离线画像、无画像、证据不足夹具上验收后再切默认。SVG白名单只开放实际所需元素与属性，延续既有消毒策略。旧“polyline恒为0”等版式断言需改为关系可核验断言。

### AB-7 修复联网企业候选抽取

**修改对象**　chart_generator/websearch.py的extract_company_candidates、looks_like_entity_name及其候选消费位置。

**改动范围与行为**

1. 已在规范身份库或白名单中精确命中的实体优先识别，允许其别名规范化后进入候选。后缀规则只用于未知候选兜底。
2. 补技术、电池后缀，并对短品牌、长全称使用规范身份匹配路径。未知候选继续限制词长和短语碎片，避免放行“电池技术”“新材料企业”等泛词。
3. whitelist身份匹配只证明名称身份，仍需业务证据与环节核验才能成为图中代表企业。候选排序和去重必须稳定。

**风险与回归**　放宽抽取可能增加误召回，需成对覆盖真公司和泛词。保留web_unverified层级及原有候选预算，避免把一次抽取修复变成主样本扩张。

## 6 测试设计与明确通过标准

所有新增用例默认离线。LLM使用可计数的假实现，取数使用固定SkillResult，PDF用例使用本地Chromium。每项至少先让描述的预期行为在当前有缺陷路径上失败，再修改实现。已经成立的行为作为回归用例，不要求人为制造红测。

### 6.1 正文修复与语义核验

| ID | 失败复现输入 | 修复成功与边界通过标准 |
| --- | --- | --- |
| W01 | 100亿元正确句与999亿元错误句用分号连接 | 保留100亿元及原引用，999亿元不进入最终正文。句号、分号、换行参数化结果一致 |
| W02 | 同段一个正确事实、一个无据事实，局部修复异常/响应非法/ID改变 | 有效事实保留，失败原因和原文可追踪，章内无重复机械占位，其他段落字节不变 |
| W03 | 失败段原先含“资料缺口”，后续给出同口径有效证据 | 编辑候选经完整重审可恢复该位置，coverage与审计状态同步，无旧占位字符串锁死 |
| W04 | 摘要headline、conclusions、risks、boundaries、takeaways及章摘要分别放无据9150亿元、6万台 | 所有容器均不发布无据数字，保留同容器有据事实。空条目不会变成空列表项或空卡片 |
| W05 | 一行表格有一个合法格和一个非法格，指标卡/提示框有同类问题 | 合法格保留，非法格显示经审核的缺失状态或整项转审计，缺失不填0。引用与位置对应 |
| W06 | max_repairs为0、1、2，10个失败单元，模型持续失败 | 实际调用数不超明确预算，0时无修复调用，重复执行不增加占位或重复审计项 |
| W07 | 删去数字后的“持续增长、行业领先、成本下降导致利润改善” | 无可比序列或直接支持时不作为已证实结论发布，不能靠没有数字通过审计 |
| W08 | 两期同口径30%到28%，另有跨期/跨范围数据与观点型事件引文 | 正确显示下降2个百分点。错期和范围混合不能支持方向，观点和假设有准确标签，否定因果不误报 |
| W09 | 修复前有错，最终文本全可核验且必答齐全。另一例删去必答内容 | 前者最终事实审计通过且保留历史问题。后者coverage仍失败、正式交付门禁继续生效 |

建议落入backend/tests/test_chapter_paragraph_repair.py、test_report_integrity_facts.py、test_appendix_integrity_continuation.py，以及report-fusion/tests/test_final_delivery_contract_v8.py。继承现有局部修复夹具和最终视图构造方式。

### 6.2 指标、单位、样本和事件

| ID | 失败复现输入 | 修复成功与边界通过标准 |
| --- | --- | --- |
| D01 | 用户只要求研发费用，响应只有包含资本化部分的研发投入 | 原费用需求未满足，不产伪费用率。费用与投入同时存在时分别绑定原record_id |
| D02 | 提供同口径总投入、资本化投入、营收，以及错期/缺分母/零或负分母对照 | 仅公式和适用条件成立时推导，记录输入与公式。错期、错范围、无有效分母不得计算 |
| D03 | 营收12但无单位，同一值分别带元/万元/亿元，另给来源单位冲突 | unknown不参与量化覆盖。三种显式单位换算正确，冲突记录待核。0和负数同样遵守单位规则 |
| D04 | 0.12分别带ratio、%、百分点及无单位 | 分别表达12%、0.12%和0.12个百分点，无单位不猜。9999/10000万元同轴使用一致单位 |
| D05 | 旧JSON缺新增单位/角色字段，原始字段有明确单位或完全无单位 | 前者能恢复来源，后者legacy_unknown。模型可读且没有把unknown默认为元 |
| S01 | 明确四家公司或单家公司，模型另加概念股，某指定公司缺数据 | 核心财务、可比表、图表、摘要只含指定有效身份。缺数保留需求格，不用概念股替补 |
| S02 | 开放具身智能，混入优刻得等概念记录及有业务证据的库外主体 | 只按业务证据决定核心资格，概念记录有背景标签，库外有据主体可准入，固定候选库不构成封闭名单 |
| S03 | 同名歧义证券、同代码多市场、别名和跨环节公司 | 歧义待确认并停止对应财务补采，规范证券ID去重。跨环节参与多次，样本计数一次 |
| E01 | 同公司两条事件，均有短标题和不同正文，数字财务超过80条 | 两条事件ID和正文保全。明确事件需求的证据进入技能与融合上下文，并能关联最终段落 |
| E02 | 事件晚于截止日、无日期、事件源只返回行情、无事件数据 | 不把未来或无效事件当催化事实。行情走原数字路径，无事件时显式缺口，无空壳事件 |
| E03 | 仅事件数据运行解读，另以仅财务数据运行事件技能 | 有效事件能产证据绑定结果，事件技能不接收不相关财务兜底，原域隔离行为保留 |

建议扩展data-fetcher/tests/test_metric_requirements.py、test_financial_eligibility_v8.py、test_fusion_fixes.py，data-analysis/tests/test_event_evidence.py、test_engine_dynamic_refactor.py、test_audit_regressions.py，以及backend的需求输出链路测试。

### 6.3 图表、企业抽取与产业链

| ID | 失败复现输入 | 修复成功与边界通过标准 |
| --- | --- | --- |
| C01 | 显式要求60个月，数据完整；无显式窗口对照 | 显式60期全部交付或明确拆图，无静默末48期裁剪。默认政策仍能限制非请求历史噪声 |
| C02 | 指定12家公司，财务同口径；总图数预算充足/不足 | 充足时12家全部可核对，单位一致。不足时明确未交付主体，不能伪称完整 |
| C03 | 两期年度、缺中间年、真零值、较新季度、重复同期冲突 | 两期图可解释有限变化，缺失为None，真0为0，季度不补年，冲突不因字典覆盖成为单一值 |
| C04 | 三家横截面各有多个年度且最新期不同 | 使用共同可比期或明确不可比缺口，横截面无跨期拼接；年度时序仍多期 |
| G01 | 主入口输入A→B，另次换A→C，节点保持一致 | 两份主图关系确实不同，每条关系具有source、target、稳定edge ID及证据映射，背景网格不能满足断言 |
| G02 | 同列、跨列、多对多、跨环节，含unresolved和缺证据断言 | 所有受支持关系在主报告可核对，未支持断言不成为实线事实边，重复边去重且方向正确 |
| G03 | 新run无环境设置、V2无画像/无证据、旧快照、无快照、恢复中环境改变 | 新策略按设计选路并清楚记录缺口，已有run恢复沿原快照。V2失败不能用无据legacy关系冒充完整 |
| G04 | 主图SVG经过前端消毒、_sync_chart_artifacts和两模板导出 | 关系及必要data属性保留，无脚本/事件属性。HTML和PDF可见边与规范spec一致 |
| G05 | 人工审核新增/移除关系并重导出，重导出中途失败 | 旧版本资格按现有失效机制撤销，成功文件hash与内容匹配，失败格式不冒充成功 |
| N01 | 白名单实体为华为技术、某已确认电池公司，另有短品牌和长全称 | 精确身份匹配先于后缀过滤，规范名称去重保留。抽取成功不自动成为业务已核 |
| N02 | “电池技术、新材料企业、如互联网公司”、含数字尾缀和重复候选 | 泛词碎片被拦，候选顺序稳定，limit与web_unverified状态正确 |

建议扩展chart-generator/tests/test_audit_chart_quality_20261102.py、test_shared_axis_unit_v8_final.py、test_chain_core_and_websearch_20261017.py，chain-research/tests/test_chain_relation_rendering_v8_final.py，backend/tests/test_chain_run_snapshot_v8_final.py。G01与G04必须通过实际adapters主图路径，辅助render_bundle的测试单独通过不计作主图通过。

### 6.4 阅读视图与完整交付

| ID | 失败复现输入 | 修复成功与边界通过标准 |
| --- | --- | --- |
| R01 | annual/consolidated/gross_margin/rate_observation_change，8.1987%，微小负比例 | 可见阅读文本为中文业务表达及一致精度，原值与来源ID保留，百分数/百分点区别正确 |
| R02 | 证券代码、URL、record_id、原文引文与指标名称混在报告中 | 按字段保护的内容保持原值，未知术语有明确映射或审计说明，不全局误替换 |
| R03 | ready和ready_with_limits各跑auto/rich，长目录、同标题章节、长附录 | 受限状态清楚可见，详细审计在附录，无fixed大水印。摘要有效，目录锚点和PDF页码对应 |
| R04 | 修复后完整五阶段离线运行，要求线图/双轴/链图，另有缺数据对照 | 必答证据→分析→图点→段落可追踪。齐全例可正式交付，缺数据例有准确缺口及受限状态，三个格式事实与版本一致 |

PDF通过标准包括文件可打开、预期图表和关系可见、每页页脚页码、目录项页码能定位实际章节、无内容溢出。至少人工或截图检查封面、摘要、最长正文、关系图、审计附录各一页，文本提取不能替代布局检查。

## 7 执行顺序与验收命令

建议依赖顺序为 AB-1 → AB-2 → AB-3 → AB-4 → AB-5 → AB-6 → AB-7 → 全链路离线验收。AB-6的证据契约依赖AB-2，默认引擎调整最后落入该任务。若实施时发现最小失败用例已通过，记录当前行为并缩减修改范围。

命令从应用根目录运行。先使用已配置完整项目依赖的Python环境验证pytest和pytest-asyncio可用，依赖安装按仓库说明处理。

```bash
python -m pytest \
  agents_core/data-fetcher/tests/test_financial_eligibility_v8.py \
  agents_core/data-analysis/tests/test_event_evidence.py \
  agents_core/data-fetcher/tests/test_metric_requirements.py \
  agents_core/data-analysis/tests/test_engine_dynamic_refactor.py \
  agents_core/chart-generator/tests/test_audit_chart_quality_20261102.py \
  agents_core/report-fusion/tests/test_final_delivery_contract_v8.py \
  backend/tests/test_causal_sensitivity_continuation.py -q
```

任务回归至少还应包含以下已存在文件，并加入上表新用例。

```bash
python -m pytest \
  backend/tests/test_chapter_paragraph_repair.py \
  backend/tests/test_report_integrity_facts.py \
  backend/tests/test_appendix_integrity_continuation.py \
  backend/tests/test_chart_comparability_continuation.py \
  backend/tests/test_requirement_output_links.py \
  backend/tests/test_chain_run_snapshot_v8_final.py \
  backend/tests/test_pdf_continuation.py \
  agents_core/chart-generator/tests/test_shared_axis_unit_v8_final.py \
  agents_core/chain-research/tests/test_chain_relation_rendering_v8_final.py -q

python -m pytest
```

涉及前端SVG处理或预览时，再在frontend运行 `npm run verify`、`npm run build` 和相关Playwright用例。验收记录必须分别列出离线模拟、真实浏览器PDF、真实源报告的执行状态。真实源重跑需使用既有预算，历史产物作为对照留档。

完成标准为本文件对应失败场景均被新用例捕获且修复后通过，边界与既有回归通过，五行业主用例及具身智能基线有离线端到端结果，两模板真实PDF检查通过。所有被隔离的事实、缺格及限额都有可定位原因，不能仅以占位符数量下降作为完成标准。

## 8 代码证据索引

以下行号以核查时源码为准。实施前再次检查索引与当前行号。

- E1　[章节局部修复与整段占位](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/chapter-writer/chapter_writer/agent.py:377)，关键分支为433–484，确定性兜底从736开始。
- E2　[融合数量审计与删句](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/report-fusion/report_fusion/agent.py:47)，最终调用626，编辑占位限制1101，最终视图校验248，导出重建793。
- E3　[显示规则与受限提示](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/report-fusion/report_fusion/render.py:32)，Markdown提示300，HTML注入501。[打印水印](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/report-fusion/report_fusion/styles/print.css:114)。
- E4　[候选、明确名单与需求解析](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/data-fetcher/data_fetcher/agent.py:970)，年度指标1060，模型指标1170，补采1238，决策1356，覆盖1888。
- E5　[数据融合与单位默认推断](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/data-fetcher/data_fetcher/fusion.py:237)，通用单位选择761，明确样本过滤853。
- E6　[网页输入构造](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/backend/app/agents/adapters.py:440)。
- E7　[行业参考候选接口](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/industry_reference/registry.py:118)。
- E8　[证据转换与事件正文选择](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/data-analysis/data_interpreter/engine.py:327)，金额规范化778，财务比率1367。
- E9　[事件注入与语义融合选择](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/data-analysis/data_interpreter/agent.py:355)，语义融合504，重述674，技能域和预算1123。
- E10　[测量重述与内部字段拼接](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/data-analysis/data_interpreter/measurement_facts.py:179)。
- E11　[时序裁剪与系列限额](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/chart-generator/chart_generator/data_formulation.py:56)，未知金额单位检查175，时序表810。
- E12　[多期候选与横截面latest](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/chart-generator/chart_generator/agent.py:2178)，series限额2189，latest2211，按索引造边1681与2550。
- E13　[创建时引擎快照](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/backend/app/engine/state_machine.py:234)，历史读取321。[快照默认字段](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/backend/app/schemas/workflow.py:174)。
- E14　[V2主图与辅助图交付](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/backend/app/agents/adapters.py:1287)，[受支持关系编译](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/chain-research/chain_research/graph_spec.py:180)。
- E15　[主图卡片零连线渲染](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/chart-generator/chart_generator/chain_render.py:699)，[generic产业链渲染](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/chart-generator/chart_generator/render.py:501)。
- E16　[指标别名与研发口径](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/financial_semantics.py:187)，[数量及因果校验](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/financial_semantics.py:475)。
- E17　[企业候选后缀与白名单顺序](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/agents_core/chart-generator/chart_generator/websearch.py:1193)。

原T0–T3实施状态与历史验证来自[现有研究报告质量计划](/Users/Zhuanz1/Downloads/同花顺赛题-T3交接/a17-industry-research-agent/docs/superpowers/plans/2026-11-07-research-report-quality.md)。本文件的差异核查、AB任务和测试矩阵应作为后续实施依据，执行时将实际结果追加至原任务记录并链接本文件。
