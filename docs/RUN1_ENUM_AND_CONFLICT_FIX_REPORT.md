# RUN‑1 故障修复报告：Agent2 枚举混淆 / 结构化日志 / 冲突误报 / 宏观噪声

- 关联运行：RUN‑1 `run 5e73b49f-17fc-42fb-8b48-883024d352ac`（`data_interpret` FAILED `analysis_generation_failed`）
- 修复日期：2026-09-02
- 修复范围：BUG‑1（阻断）、BUG‑2（可观测性）、BUG‑4（冲突误报）、BUG‑3（宏观噪声）
- 供应商：火山方舟 `ark-code-latest`（DeepSeek 系兼容端点，json_mode 结构化输出）

---

## 总览

| Bug | 级别 | 根因一句话 | 修复 | 验证 |
|-----|------|-----------|------|------|
| BUG‑1 | 阻断 | 两组相似枚举互相抄写 + 后端无兜底 | prompt 枚举清单 + `_normalize` 别名归一 | Mock RED→GREEN + 真实单次冒烟 PASS |
| BUG‑2 | 可观测性 | 校验细节只写 `logging extra`，默认 formatter 不渲染 | 细节直接拼进日志消息体 + 补抓非法值/允许枚举 | Mock 断言日志消息含字段路径+非法值 |
| BUG‑4 | 展示噪音 | 文本标题/摘要被当数值参与冲突对比 | 冲突检测仅纳入数值型证据 | Mock：文本不报冲突、真实数值冲突仍保留 |
| BUG‑3 | 数据质量 | 宏观行无相关性门，`_is_low_relevance` 恒放行 | 宏观行按“任务查询∪意图∪主题”相关性隔离 | Mock 5 用例：无关隔离/相关保留/防误杀 |

生产代码改动四个文件：

```
backend/app/integrations/llm/openai_compatible.py   | BUG-1/BUG-2
backend/app/agents/data_fetcher/fusion.py           | BUG-4
backend/app/agents/data_fetcher/normalizer.py       | BUG-3
backend/app/schemas/acquisition.py                  | BUG-3（reason_code 增枚举）
```

测试：BUG‑1/2/4 为既有 TDD 红测（修复前失败，修复后通过）；BUG‑3 新增 `test_macro_relevance_filter.py`（5 用例）。未改动既有断言语义。

---

## BUG‑1【阻断】Agent2 结构化输出枚举混淆

### 根因

`ValidationCard.status`（三张校验卡共用）与 `AnalysisDraft.financial_quality`（顶层）两组枚举高度相似：

| 字段 | 合法枚举 |
|------|---------|
| `validation_cards[].status` | `passed` / `differences_explained` / `pending_verification` |
| `financial_quality` | `consistent` / `differences_explained` / `differences_pending_verification` |

两组共享 `differences_explained`，其余取值形近。分析系统提示（`global_equity_analysis_v2.md`）零处提及三张校验卡的 `status` 取值，flash 级模型把 `financial_quality` 的 `consistent` 抄进同名卡片的 `status`，RUN‑1 连续 4 次（1 初始 + 3 修复）都错在同一处 → `schema_validation_failed` → 阶段失败。

代码侧还有一处隐患：`openai_compatible.py` 早已定义别名映射 `_VALIDATION_STATUS_ALIASES` / `_FINANCIAL_QUALITY_ALIASES`，但 `_normalize_analysis_aliases` 从未调用——**兜底是死代码**。

### 修复（a + b 组合）

- **(a) Prompt 补枚举清单**：新增 `_VALIDATION_ENUM_DISAMBIGUATION` 常量，显式列出两组枚举各自合法取值并声明“互不通用”，注入两处系统提示——全量路径（`generate_analysis` 的 DeepSeek 契约块）与分段路径（`_segmented_system_prompt`）。生产无论长短提示都覆盖。
- **(b) 后端别名归一兜底**：在 `_normalize_analysis_aliases` 接线两个别名表，做确定性单向映射（仅字符串、已合法取值经 `.get` 原样保留）：
  - 卡片 `status`：`consistent → passed`、`differences_pending_verification → pending_verification`
  - `financial_quality`：`passed → consistent`、`pending_verification → differences_pending_verification`

即便模型再次抄错，校验前已被纠正，不再抛结构化校验失败；无法映射的非法值仍按原逻辑进入修复环并留痕。

### 证据与门禁对照

| 验收标准 | 结果 |
|---------|------|
| `validation_cards.status` 只输出 passed/differences_explained/pending_verification | ✅ Mock：`test_analysis_normalizes_financial_quality_enum_copied_into_card_status` |
| `financial_quality` 用自己枚举，两处不再互抄 | ✅ Mock：`test_analysis_normalizes_card_status_enum_copied_into_financial_quality` |
| 模型偶发写 `consistent` 给 status，后端自动拦截修正、不抛错 | ✅ Mock 同上（别名归一后校验通过） |
| “4 次重试全失败”现象消失 | ✅ 真实冒烟单次成功（见下），无 `schema_validation_failed` |
| A2 跑完并向后流转 | ✅ 真实冒烟产出合法 `AnalysisDraft`（枚举门禁全过） |

**真实单次冒烟（用户授权，1 次调用）**：`ark-code-latest`、`runtime_prompt` 3490 字符（未分段）、单次返回合法草稿：
`financial_quality=differences_pending_verification`；卡片 `scope_comparability=differences_explained`、`financial_quality=pending_verification`、`valuation_expectation=pending_verification`；全部落在各自合法枚举，`[PASS] no schema_validation_failed`。

---

## BUG‑2【可观测性】结构化校验失败日志缺细节

### 根因

`_log_structured_output_event` 把 `error_code`/校验路径等放进 `logging extra`，默认 formatter 不渲染 `extra`，日志只剩一句 `LLM structured output event`；且 `_validate_payload` 只回传 `validation_paths`/`validation_types`，未带非法值与允许枚举。排障只能回读 `checkpoints.sqlite`。

### 修复

- `_validate_payload` 诊断补齐：`validation_inputs`（模型返回的非法值）、`validation_expected`（pydantic `ctx.expected` 的允许枚举）、`raw_content_summary`（模型输出 JSON 截断摘要，≤600 字符）。`raw_content_summary` 已加入 `_SAFE_DIAGNOSTIC_KEYS`。
- `_log_structured_output_event` 新增 `_format_structured_event_message`，把 `error_code / validation_paths / validation_types / validation_inputs / validation_expected / finish_reason / raw_content_summary` 直接拼进**消息体**；`extra` 保留以兼容既有结构化断言。

### 证据与门禁对照

| 验收标准 | 结果 |
|---------|------|
| 故意制造枚举错误，日志可见错误字段名和非法取值 | ✅ `test_analysis_literal_error_diagnostics_carry_invalid_value_and_expected`：消息体含 `validation_cards.0.status` 与 `完全非法的枚举值` |
| 诊断含允许枚举列表 | ✅ `validation_expected` 含 `passed` |
| 不再依赖读 checkpoint 定位 | ✅ 失败细节随 `StructuredOutputError.diagnostics` 与日志消息体一并可见 |

---

## BUG‑4【展示噪音】新闻标题/摘要被误判为数据冲突

### 根因

`fusion.fuse_evidence` 的冲突检测按 `(指标, 单位, 报告期, 口径, 准则, 币种)` 分组，组内 ≥2 条且取值不同即判“冲突”。新闻类证据的 `value` 是标题/摘要文本（`metric_name` 常为“标题/summary”），多条不同文本被当成“同一指标不同取值” → 前端弹出无意义冲突告警。

### 修复

新增 `_is_numeric_value`（归一化后为 `int/float` 且非 `bool` 才算数值），冲突分组仅纳入数值型证据，文本证据不再参与取值对比。**去重与 `uniqueness` 计算不受影响**（走独立的 `_dedupe_groups` 通路）。

### 证据与门禁对照

| 验收标准 | 结果 |
|---------|------|
| 冲突检测过滤文本标题/摘要 | ✅ `test_fusion_does_not_flag_text_title_or_summary_as_conflict`：4 条文本证据 `conflicts == []` |
| 只有真实数值指标参与冲突对比 | ✅ `test_fusion_text_noise_does_not_mask_a_real_numeric_conflict`：数值冲突 `{E-001,E-002}` 仍保留 |
| 既有数值冲突语义不回归 | ✅ 既有 `test_fusion_deduplicates_exact_values_and_preserves_conflicts` 等全绿 |

---

## BUG‑3【数据质量】宏观无关证据范围过宽

### 根因

`normalizer.normalize_tasks` 的清洗环用 `_is_low_relevance` 判定是否隔离，但宏观技能（`SkillName.MACRO`）的行：

- 不含 `_RELEVANCE_FIELDS`（所属同花顺行业/所属概念/主营业务…）——这些是行业类字段，宏观行只有“指标名称/指标值/单位”；
- 不属于 `_TEXT_SEARCH_SKILLS`（公告/事件/研报/新闻/报告）。

于是命中 `_is_low_relevance` 的 `if not declared: if not require_text_match: return False` 分支——**宏观行被无条件放行**。RUN‑1 的 Q‑03 宏观任务因此 7 行全收，混入 12+ 条制造业 PMI / CPI 序列（与“宁德时代营收毛利率、行业出货量”两个焦点问题相关性低）。

### 修复

在清洗环为宏观行单独加一道相关性门 `_macro_row_off_topic`：

- 相关性 token 集 = **任务查询 tokens ∪ 任务意图 tokens ∪ 研究主题 tokens**；
- 宏观行的“指标名 + 行内文本”与任一 token 有包含关系 → 保留；否则隔离 `reason_code=macro_off_topic`。

选择“任务查询 ∪ 主题”而非仅主题，是为避免误杀：任务明确点名的指标即使与研究主题无字面重合也必须保留（如查“中国房地产行业 商品房销售面积”，“商品房销售面积”与主题 token“房地产”无字面交集，但它是任务直接索取对象）。被隔离的是“问财按宏观任务过宽返回、既不匹配任务查询也不匹配主题”的行（问出货量却回 PMI/CPI）。

- `reason_code` 新增枚举成员 `macro_off_topic`（`acquisition.py`，additive，默认仍 `topic_mismatch`）；contracts/前端的 `reason_code` 均为自由字符串，不受影响。
- 过滤只发生在清洗阶段，**仅对新建任务生效，不回溯历史证据**（符合验收约定）。

### 证据与门禁对照

| 验收标准 | 结果 |
|---------|------|
| 无关宏观指标不大批量进证据库 | ✅ `test_unrelated_macro_indicators_are_quarantined_not_evidence`：PMI/CPI 被隔离、出货量保留 |
| 相关宏观指标照常入库 | ✅ `test_matching_macro_indicator_still_becomes_evidence` |
| 不误杀任务点名的指标 | ✅ `test_explicitly_queried_indicator_without_topic_overlap_is_kept`（商品房/房地产场景） |
| 只作用于 MACRO 技能 | ✅ `test_macro_filter_does_not_touch_non_macro_skills` |
| 仅新任务生效、历史不清理 | ✅ 过滤在清洗环，不涉及既有证据存储 |

---

## 验证汇总

- **Mock（零配额）**：全后端 `pytest tests/ --ignore=tests/integration` → **658 passed**；BUG‑1/2/4 既有红测全由 RED 转 GREEN，BUG‑3 新增 5 用例全绿，`test_normalizer.py::test_macro_indicator_value_uses_provider_indicator_name`（商品房）保持通过。
- **真实（用户授权，单次）**：`ark-code-latest` 分析冒烟 1 次调用成功，枚举全合法，无 `schema_validation_failed`。
- **2 个失败为环境性问题（与本次改动无关）**：`test_playwright_pdf.py::test_chromium_can_render_pdf` 与 `test_pipeline.py::test_default_registry_runs_real_interpreter_and_chart_generator`，均因本机未安装 Playwright Chromium（`NO ms-playwright cache`）无法产出 `report_pdf`；原代码同样会失败。
- 未触碰：SkillHub、章节/图表/融合生成逻辑。

## 回归说明 / 风险

- 别名归一为**确定性单向映射**，只处理两组枚举的互相抄写；未映射的非法值仍走既有修复环与 fail-closed，不放宽契约。
- 日志消息体变长（含截断摘要），若日志采集端对行长敏感可后续裁剪；`extra` 结构未变，既有采集不受影响。
- 冲突过滤只影响 `ConflictRecord` 生成，不改变证据保留与图表数据集装配。
- 宏观过滤为**包含式匹配**：若某 baseline 宏观任务查询词本身就宽泛地点名了 PMI/CPI（如“GDP CPI PPI PMI…”），这些行会因命中查询词而保留——这是“按任务所查保留”的既定语义；RUN‑1 的噪声来自意图任务过宽返回，已被隔离。若需进一步收紧，可后续引入宏观指标白名单/与研究主题的语义映射。
- 完整端到端验收（RUN‑1 从 `WAITING_REVIEW` 走完整条 `data_interpret` 并流转到图表/撰写）仍需一次真实全链路重放，成本高于本次单次冒烟，建议由你在前端按既定协议触发。
