# 真实全链路评测 — 最终报告（触限停止归档）

> 纯真实环境（真实 DeepSeek LLM + 真实同花顺 SkillHub），内容寻址去重缓存，全程 transport 录制。
> 生图模型按用户要求不纳入本轮测试（`image_generation=disabled_by_evaluation_scope`）。
> **停止原因：LLM 账户余额耗尽（HTTP 402），触发铁律自动停止规则，立即归档。**

## 一、停止事件
- 触发点：S 类批次第 4 条（S-C04）执行中，LLM 返回 HTTP 402。
- 停止码：`llm_quota_or_access_exhausted`（StopController 正确生效，后续请求零发出）。
- 402 错误响应未被写入缓存（停止码阻止错误响应落盘，缓存只含 provenance=live 的成功响应）。
- 归档目录：`eval/transcript/real_run_*`（14 轮）+ `eval/cache/live_content_addressed/`（SkillHub 283 条 + LLM 87 条）。

## 二、接手时 GPT 已完成
- L0 评测器自检 10/10（fail-closed 终态判定、Provider 真实性校验、101 条用例运行时 schema）。
- 内容寻址缓存层：SkillHub 按 `skill+endpoint+canonical_query+page`，LLM 按完整请求体；仅接受 `provenance=live`。
- `real_runner.py` 五阶段 live runner（但从未真正运行过，接手时 `eval/cache` 与 `real_run_*` 均不存在）。

## 三、本轮修复的评测器/接线缺陷（13 处，均不改业务规则）
| # | 位置 | 缺陷 | 修复 |
|---|------|------|------|
| R1 | `real_runner.build_live_registry` | 漏接 `AGENT1_SEMANTIC_ROUTER_ENABLED=true` 的语义路由器 | 复用共享缓存 chat 实例接入 `OpenAICompatibleSemanticRouter` |
| R2 | `transport.classify_provider_stop` | HTTP 200 数据响应全文关键词扫描，金融公告含「额度/余额/计费」→ 假停测 | 200 且含数据行/LLM choices 不判停；仅错误信封扫描；+回归测试 |
| R3 | `transport._extract_rows` | 不识别嵌套 dict 与 `result` 键 | 对齐 SkillHub 客户端递归提取 |
| R4 | `real_runner._drive` | intercept 用例在第一个无错误审核门即停 | 仅真实 error 停止；正常审核门 resume |
| R5 | `real_runner._drive` | 不识别软拦截（blocking collaboration request） | intercept 用例对 blocking collab 停止 |
| R6 | `harness` | 不识别软拦截为合法拦截 | blocking collab 判为合法 intercept |
| R7 | `harness` | 缺部分链终态判定；runner 对 I/T/S 用例跑满五阶段烧额度 | 部分链终态 + `target_stage_for` 提前停止 |
| R8 | `harness` | 部分链用例把合法停止（澄清/缺数）误判 fail | `LEGITIMATE_STOP_ERRORS` + 计划已产出即合法 |
| R9 | `real_runner._check_rows` | `plans` 是 dict 却按 list 取值 → KeyError | dict→values |
| R10 | `scorers.rules.run_l1_checks` | `checks=[]` 回退跑全部检查 → 注入未声明检查项误报 | 区分 `None` 与 `[]` |
| R11 | `real_runner.extract_artifacts` | 评分器读 stage status 但只传了 `.data` → C3/P1 恒误报 | 注入 StageResult status |
| R12 | `real_runner._stage_status` | status 小写 vs 评分器大写比较 | 统一大写 |
| R13 | `scorers.rules.check_r2` | 用户输入纳入禁词扫描 → 注入类用例必然误报 | 只扫描系统产物 |

## 四、执行结果汇总（41/101 用例，去重后最新结果）
**通过 30 / 未过 11；真实外部请求 354 次，缓存命中复用 1004 次。**

### 分层通过率
| 类别 | 已执行 | 通过 | 结果 |
|------|--------|------|------|
| I 类意图金标准（15） | 15 | 13 | I-C02 陈旧用例期望、I-C11 需故障注入（均非系统缺陷） |
| T 类工具规划（非合成 7） | 7 | 4 | T-02/T-03/T-11 已按方案 A 修正用例（T-02 计划级 T2/T4 已验证通过，终态 verdict 待充值重跑） |
| 拦截类 E（15） | 15 | 12 | E-35/E-37/E-40：拦截正确但阶段/错误码与用例预期路径不同 |
| S 类专项（24） | 4 | 1 | S-C02/C03 未达 A2；S-C04 触限 blocked |
| core_calc（E-13~16） | 0 | — | 未执行（额度耗尽） |
| full E2E 正向（~36） | 0 | — | 未执行（额度耗尽） |

### 未过用例定性
- **非系统缺陷（2）**：I-C02（期望澄清与 BUG-006 相对时间规则冲突）、I-C11（合成 LLM-failure 用例，live 不可达）。
- **设计-缺陷已裁决（3）**：T-02/T-03/T-11。产品裁决（2026-08-22）：采纳方案 A——standard 深度固定 P0+P1 全量 11 技能扫描为既定语义，不收窄 planner。已改用例：T-02/T-03 forbidden 由 P0 成员（hithink_finance_query/hithink_macro_query，全量必发）改为条件技能 hithink_futures_query（全量扫描不调用，T2 保留判别力）；T-11 expected_task_range 由 [2,6] 放宽至 [11,20]（全量 11 + 双公司独立财务任务 + 指标任务，实测 15）。cases_v1.json（runner 实际加载）与 cases_v7.json（展开快照）已同步修改，101 条 schema 校验通过。重跑验证（real_run_20260822T080652Z）：T-02 计划级 T2「无错调」/T4 均 PASS；因 LLM 402 触限（首个 LLM 请求 cache_hits=0），三例终态 verdict 待充值后重跑确认。
- **拦截路径偏差（3）**：E-35（data_interpret 软拦截 vs 预期 data_fetch 硬拦截）、E-37/E-40（主体歧义提前澄清拦截 vs 预期缺数拦截）。系统拦截行为诚实正确，用例预期拦截路径与实际实现不一致。
- **触限未完成（3）**：S-C02/S-C03（未达 A2 即止）、S-C04（402 blocked）。

## 五、门禁核算
- must_pass 金标准 100% 要求：**未达到**（70 条 must_pass 中已执行 41 条、通过 30 条；未执行 29 条）。
- 一票否决项：本轮未发现命中（无伪造、无未知 evidence_id、无带 error 的 completed、产物链完整）。
- **结论：BLOCK（额度耗尽 + must_pass 未全绿）。**

## 六、剩余未执行用例（60 条）与恢复优先级
1. **T-02/T-03/T-11 重跑终态确认**（用例已按方案 A 修正，T-02 计划级 T2/T4 已验证通过）——成本低，充值后优先执行。
2. **S 类剩余 20 条**（S-C05~C10、S-G01~G08、S-E01~E06）——多数停在 A2/A3，成本中等。
3. **core_calc 4 条**（E-13~E-16）——C1 确定性计算基准，发版门禁核心（pass*5=100% 要求）。
4. **full E2E 正向 ~36 条**——成本最高（每条跑满五阶段 + L2 judge），额度充足后再跑。
5. **合成 T-05~T-08、T-12**——需 synthetic override/轨迹注入支持，live 直跑无意义。

恢复方式：LLM 账户充值后直接重跑 `python -m eval.real_runner`（注意：SkillHub 响应缓存键稳定、复用以它为主；LLM 请求体疑含时间变化成分，跨 run 不命中——20260822T080652Z 重跑 T-02 时 cache_hits=0、首个 LLM 请求即 402，重跑仍会消耗真实 LLM 额度）。

## 七、续测：Agent 链路确定性验证与生产缺陷修复（2026-08-22 晚）

范围切换为「只测 Agent 链路、不测任何大模型能力」：Agent 1 规划、Agent 3 图表数据/路由、Agent 5 视觉决策与跨阶段引用闭合共 65 项确定性检查全部通过（零外部调用）；Agent 1 真实 SkillHub 基础资料查询 1 次命中内容寻址缓存复用。期间发现并（经用户授权）修复 1 处生产缺陷。

### 缺陷：Agent 5 导出失败把正式报告错误降级为草稿
- **症状**：非规范章节顺序场景（用户指定 chapter_order 与 7 章标准顺序不一致）应仅给出交付提示，实际报告被降级为 `draft_with_warnings`，对应确定性测试失败。
- **复现**：`ReportFusionOptions.output_formats` 默认为空 → 服务端补全为全格式（markdown/html/pdf）→ PDF 渲染依赖 Playwright Chromium，失败时 `export_issues` 非空 → `service.py` 强制 `actual_release_mode = "draft_with_warnings"`。实验证据：monkeypatch `render_pdf` 抛错后，同场景 `release_mode` 由 formal 变为 draft_with_warnings。
- **根因**：导出失败（交付层限制）与内容质量降级共用同一决策分支，违背代码内既定设计「presentation advisories remain visible without relabelling a complete report as a draft」。章节顺序提示本身早已属于 `DELIVERY_ONLY_ADVISORY_PREFIXES`（不降级），症状在测试名语境下被误归因到章节顺序。
- **修复**：`backend/app/agents/report_fusion/service.py` 导出失败分支不再改写 `release_mode` 与 `formal_eligible`，仅置 `delivery_status = ready_with_limits`，风险条目保留在 `unresolved_risks`。
- **验证**：report_fusion 15/15 通过（新增回归测试 `test_agent_keeps_formal_release_when_single_format_export_fails`；`test_agent_keeps_markdown_and_html_when_pdf_export_fails` 断言更新为 formal + formal_eligible）；workflow 18/18、reporting 2/2、playwright_pdf 1/1 无回归。
- **遗留观察（产品决策项，非缺陷）**：正式版报告的「未解决问题清单」仅在 draft 模式渲染，交付类提示（章节顺序、PDF 失败原因等）只进入数据层 `unresolved_risks` 与头部交付状态标签；是否在正式版渲染交付提示清单待产品裁决。
