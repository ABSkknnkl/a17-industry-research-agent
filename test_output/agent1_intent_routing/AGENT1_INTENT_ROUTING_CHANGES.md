# Agent 1 复杂意图识别与多技能路由 — 交付说明（AI 可读）

> 本文档面向 AI/后续开发者。范围：RUNLOG 阶段二 P0（与 Skill 的 P0/P1 等级无关）。
> 状态：已实施。全部测试通过，金标准评测 Precision/Recall/F1/Exact Match = 1.0。

## 1. 改动总览

突破旧实现两个限制：
1. semantic_router 只处理未知长尾 metrics → 现在对完整 focus_questions 做复杂度检测与多子需求拆解；
2. 复杂问题最多两个定向 Skill → 现在每个子需求支持 1-3 个 Skill，子需求数上限 12。

架构：确定性优先（deterministic-first），LLM 只能补充不能删除。

```
focus_question
  → deterministic_intent_parser.parse_intent   # 实体/指标/时间/连接词/技能关键词，产出 locked_skills
  → complexity_detector.detect_complexity       # simple | compound | ambiguous；决定是否允许 LLM
  → intent_merger.build_intent_plan             # 确定性计划为基座
      ├─ simple 或无 decomposer → 直接返回 deterministic 计划
      ├─ LLM 成功 → _merge_llm_plan（枚举校验+能力校验+置信度分级+锁定不可删）
      └─ LLM 异常/超时 → parser_mode="fallback"，返回确定性计划并记录 warning
  → planner.build(intent_plans=...)             # 每个子需求生成独立查询（task_origin 标记）
  → service.run                                 # requires_clarification → WAITING_REVIEW 人工审核
```

## 2. 文件清单

### 新增（backend/app/agents/data_fetcher/）
- intent_models.py：Pydantic 模型 IntentEntity/IntentMetric/IntentTimeRange/IntentSubRequirement/ResearchIntentPlan。candidate_skills 保留原始字符串以便 merger 校验拒绝非法值，而非 Pydantic 直接报错。
- skill_capabilities.py：SKILL_CAPABILITIES 能力注册表（15 个 SkillName 全覆盖），capability_supports() 按 metric_type 交集校验候选 Skill。
- deterministic_intent_parser.py：确定性解析。连接词切分（实体枚举内的顿号/和受保护不切分）、技能关键词表（EVENT/INSRESEARCH/SECTOR/SHARE/FUTURES/MACRO/NEWS/REPORT/ANNOUNCEMENT/BUSINESS/BASIC_INFO/CHAIN/FINANCE/INDUSTRY）、指标注册表别名匹配、时间表达式、模糊主体模式（那家公司/最近怎么样等）。产出 locked_skills。
- complexity_detector.py：simple/compound/ambiguous 判定。compound 触发条件：复合连接词（以及/与/并/同时…）、多段、多主体多指标、锁定技能>2、超长输入。simple 不调用 LLM。
- intent_merger.py：build_intent_plan() 主入口。合并规则：
  - LLM 输出的 skill 必须能 SkillName(raw) 解析，否则进 rejected_skills 并记 warning llm_skill_not_in_enum；
  - 必须通过 capability_supports（metric_type 交集），否则 rejected + llm_skill_capability_mismatch；
  - confidence < 0.75（review 阈值）：不执行，进 rejected，触发人工澄清；
  - 0.75 ≤ confidence < 0.90（accept 阈值）：允许进入但记 llm_skill_pending_review；
  - locked_skills 合并后复核，缺失则强制补回并记 locked_skill_missing_after_merge；
  - decomposer 抛任何异常 → 返回确定性计划，parser_mode="fallback"，warning=intent_decomposer_failed:<异常类名>。
- intent_decomposer.py：re-export ResearchIntentDecomposer/LLMDecomposition/LLMSubRequirement。

### 修改
- semantic_router.py：新增 ResearchIntentDecomposer（结构化 JSON 拆解，asyncio.wait_for 超时、JSON 栅栏剥离、一次修复重试、prompt 注入防御：user_request 标记为不可信数据、禁止删除 locked、禁止自创 Skill）。保留原 OpenAICompatibleSemanticRouter 长尾路由。
- planner.py：build() 新增 intent_plans 参数；_build_requirements 对意图计划取子需求技能并集（上限 3）；compound/ambiguous 计划按子需求生成独立查询 _intent_skill_query（保留主体/指标/时间/限定词：海外/回收/排序/对比等），task_origin 标记 deterministic_intent/llm_intent/hybrid_intent；simple 计划复用基线任务不新增查询。
- service.py：DataFetcherAgent 新增 intent_decomposer/intent_confidence_accept/intent_confidence_review 参数；对每个 focus_question 调 build_intent_plan；requires_clarification → 直接返回 WAITING_REVIEW（error=intent_clarification_required，附 collaboration_requests），不执行数据获取；data 中输出 intent_routing 审计块。
- factory.py：AGENT1_INTENT_DECOMPOSER_ENABLED=true 时构造 ResearchIntentDecomposer（缺 LLM 配置抛 agent1_intent_decomposer_configuration_missing）。
- config.py：新增 AGENT1_INTENT_DECOMPOSER_ENABLED（默认 False）、AGENT1_INTENT_CONFIDENCE_ACCEPT=0.90、AGENT1_INTENT_CONFIDENCE_REVIEW=0.75。
- acquisition.py：SkillQueryTask 新增 task_origin/intent_requirement_id；ResearchRequirement.target_skills 上限 2→3。
- metric_registry.py：新增 iter_metric_aliases()。

## 3. 测试与评测

### 新增测试 tests/agents/data_fetcher/test_intent_routing.py（12 用例，先写失败后实现）
- E-24 市占率+海外政策 → ≥2 子需求，STOCK_SELECTOR+NEWS，查询保留"海外/政策/市占率"限定词；
- E-27 多财务指标+主营业务结构 → FINANCE/BUSINESS 分子需求，实体=宁德时代；
- E-42 业绩预告+增发 → 均含 EVENT，不误配 FINANCE；
- E-43 板块成分股+营收排序 → SECTOR+STOCK_SELECTOR；
- E-44 盈利预测+评级变化 → INSTITUTIONAL_RESEARCH，查询保留关键词；
- E-49 资金流向无能力 → candidate_skills=[]、子需求与计划级 requires_clarification=True；
- E-50 一致预期+分歧 → INSTITUTIONAL_RESEARCH+REPORT；
- T-09 碳酸锂期货+社融 → FUTURES+MACRO；
- T-11 多主体财务对比 → 双主体+双指标结构化提取，FINANCE 查询含两主体；
- 越权 LLM（删锁定+自创 Skill）→ 锁定保留、SUPER_SKILL/hithink_fake_query 进 rejected、合法 report_search 补充被接受；
- LLM TimeoutError → parser_mode=fallback，FUTURES/MACRO 路由完整；
- 简单请求 → complexity=simple、parser_mode=deterministic、LLM 调用 0 次。

### 金标准评测 tests/agents/data_fetcher/eval_intent_routing_golden.py
运行：`cd backend && PYTHONPATH=. python tests/agents/data_fetcher/eval_intent_routing_golden.py`
评测者充当 Agent 1 大模型（ScriptedDecomposer 注入预写结构化输出，不调用项目 LLM）。
结果（backend/test_output/agent1_intent_routing/golden_eval_report.json）：
- 8 条路由用例：Precision=1.0，Recall=1.0，F1=1.0，Exact Match=8/8=100%（macro 与 micro 一致）；
- 澄清用例 2/2 通过；安全用例 3/3 通过。

### 回归
- tests/agents/data_fetcher：76 通过；backend 全量：全部通过。

## 4. 关键约束（后续修改必须遵守）

1. locked_skills 不可被 LLM 删除；合并后必须复核，缺失强制补回。
2. LLM 候选必须通过 SkillName 枚举解析 + capability_supports 双重校验。
3. confidence < AGENT1_INTENT_CONFIDENCE_REVIEW 的路由禁止执行，只能转人工。
4. decomposer 任何异常必须回退确定性计划，禁止向 service 抛错。
5. simple 请求禁止调用 LLM、禁止生成额外定向查询（复用基线）。
6. 无能力子需求（如资金流向）candidate_skills 必须为空并触发澄清，禁止硬塞 Skill。
7. 路由准确率评测只统计 task_origin != "baseline" 的定向任务。
8. 每个子需求最多 3 个 Skill，计划最多 12 个子需求，总任务数仍受 30 上限约束。
