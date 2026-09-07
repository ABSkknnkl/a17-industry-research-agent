# Agent1–4 真实 LLM 评测报告（含三层级联降级 + 博查联网）

- 日期：2026-09-06
- 范围：智能体 1（data_fetch）→ 2（data_interpret）→ 3（chart_generate）→ 4（chapter_write），**不含 Agent5（report_fusion）**
- 模型：`ark-code-latest`（火山方舟 Auto 模式，实际路由到 `deepseek-v4-flash-ga-260731`）
- 数据源：真实问财 SkillHub + 真实博查 Web Search（L3）
- 方式：真实 LLM 全链路 + **录制回放**（内容寻址缓存 `eval/cache/live_content_addressed`，分 skillhub/llm/websearch 三 provider）
- 驱动器：`eval/agent14_live_driver.py`（新建，停在 chapter_write 审核门）
- 归档：`eval/transcript/agent14_live_20260906T045545Z/`

---

## 0. 执行摘要（结论先行）

3 条用例**全部** Agent1→Agent4 `COMPLETED`，各产出 7 章 21 节：

| 用例 | 研究问题 | 终态 | 章节 | 耗时 | 评级 |
|---|---|---|---|---|---|
| A14-02 | 隆基绿能公司概况与主营业务构成 | 全 COMPLETED | 7 | 513s | **最好** |
| A14-03 | 钠离子电池2026量产进展与产能规划 | 全 COMPLETED | 7 | 352s | 居中 |
| A14-01 | 新能源车板块整体PE、PB估值水平 | 全 COMPLETED | 7 | 281s | **最差** |

**但拿到这个结果之前，连续排掉 5 个阻断**（其中 4 个是基建/配置缺陷，1 个是模型行为）。这些阻断会让任何真实评测全军覆没，是本报告最重要的工程产出：

| # | 阻断 | 根因 | 性质 |
|---|---|---|---|
| B1 | 博查 L3 全部失败 | base_url 误写 `api.bocha.ai`（DNS 不解析），真实端点是 `api.bochaai.com` | 方案 §4.2 笔误 |
| B2 | LLM 全部 404 | 旧密钥无权访问 `ark-code-latest`（Auto 模型） | 密钥权限 |
| B3 | L2/L3 降级在评测里根本没开 | `real_runner` 绕过 factory，executor 用全默认值（降级关闭） | 评测接线缺陷 |
| B4 | Agent2/Agent4 全部截断失败 | `real_runner._live_chat` 漏禁 `ark-code-` 的 thinking，推理 content 吃光 max_tokens | **评测与生产不一致（真凶）** |
| B5 | Agent2 结构化漂移 | flash 系长提示产出空 evidence 的 claim（违反 min_length=1 红线） | 模型底座缺陷 |

**B4 是真凶**：生产路径（前端）对 `ark-code-latest` 按 `_is_deepseek_style` 禁用 thinking，所以前端能跑通；而评测路径 `real_runner` 传入自建 chat_model 绕过了类内禁用分支，且自身只判 `deepseek-` 漏了 `ark-code-` → thinking 开着 → reasoning_content 吃光 8192 token 预算 → content 为空 + finish_reason=length → `LengthFinishReasonError`。这解释了"前端正常、评测全挂"的矛盾。

---

## 1. 阻断根因 / 证据 / 修复 / 验证（逐条）

### B1 博查端点 DNS 不解析

- **证据**：`POST https://api.bocha.ai/v1/web-search` → `ConnectError: nodename nor servname provided`；`POST https://api.bochaai.com/v1/web-search` → `200`，返回 19 条命中，`totalEstimatedMatches:10000000`（印证方案 §4.6 警告的固定假值）。
- **修复**：`config.py` 与 `websearch/client.py` 默认 base_url 改 `https://api.bochaai.com`；`.env` 显式写 `AGENT1_WEB_BASE_URL`。
- **验证**：直连冒烟 `钠离子电池 2026 量产进展` → 5 条命中，域名白名单生效（3 条非白名单丢弃，2 条腾讯网通过），`freshness=oneYear` 已带。

### B2 旧密钥无权 ark-code-latest

- **证据**：旧密钥 `ark-6a6150c2…` 调 `/api/plan/v3` + `ark-code-latest` → `404 UnsupportedModel`（"does not support the agent plan feature"）；调 `/api/v3` → `404 InvalidEndpointOrModel.NotFound`。`GET /api/v3/models`（200）列出 130 个模型，**无任何 ark-code 项**。
- **修复**：换用户提供的新密钥 `ark-2d38149f…`。
- **验证**：新密钥 `/api/plan/v3` + `ark-code-latest` → `200`，响应 `"model":"deepseek-v4-flash-ga-260731"`（印证 Auto 路由）。

### B3 评测绕过 factory，降级链未开

- **证据**：`real_runner.build_live_registry` 构造 `RetrievalExecutor(gateway, concurrency=1, page_size=…)`，**未传** `fallback_chain_enabled` / `web_fallback_enabled` → 全默认 `False`。`.env` 的 `AGENT1_FALLBACK_CHAIN=true` / `AGENT1_WEB_FALLBACK_ENABLED=true` 被绕过 factory 而失效。
- **修复**：`real_runner` 镜像 factory——从 settings 读 L2 降级参数；新增 `_build_live_web_client(web_transport)` 建博查客户端（注入录制 transport）；`create_skillhub_gateway(web_search_client=…)` 注册 WEB_SEARCH 工具；executor `web_fallback_enabled=web_client is not None`。新增 `websearch` provider 的内容寻址缓存。
- **验证**：A14-03 出现 `levels_used {"1":10,"2":3,"3":0}`——**L2 降级在评测里真实触发了 3 次**（修复前恒为 0）。

### B4 thinking 未禁 → 截断（真凶）

- **证据**（探测对照，同一 prompt）：

  | thinking | finish_reason | content 长度 | reasoning 长度 | completion_tokens |
  |---|---|---|---|---|
  | 开（评测旧行为） | **length（截断）** | **0（空）** | 505 | 301（reasoning 占 300） |
  | 关（修复后） | **stop（完整）** | 82 | 0 | 52 |

  run3 实测：A14-02 Agent2 / A14-01 Agent4 均 `LengthFinishReasonError`；llm 缓存扫出 3 条 `finish_reason=length` 投毒响应（200+空 content 被内容寻址缓存，换密钥不改缓存键 → 回放仍失败）。
- **根因定位**：`openai_compatible.py:751` 的 thinking 禁用 `extra_body` 只在 model 类**自建** ChatOpenAI（`chat_model is None`）时生效；`real_runner._live_chat` 传入 chat_model 绕过该分支，且自身判断 `startswith("deepseek-")` 漏了 `ark-code-`。生产 8 处用 `_is_deepseek_style`（匹配 `deepseek-/ark-code-`），评测未对齐。
- **修复**：`real_runner._live_chat` 改用 `_is_deepseek_style(settings.LLM_MODEL)` 禁 thinking；`max_tokens` 从 `model_kwargs` 提到显式参数（消除 UserWarning，对齐生产 BUG-5）。清理 3 条截断投毒缓存（移废纸篓，未永久删）。
- **验证**：run4 截断事件=0，三条全 COMPLETED；最新缓存 `finish=stop / content_len 9170/8112/3914 / reasoning=0`。单条耗时从 711s（thinking 开）降到 281s（**快 2.5 倍**，reasoning token 不再生成）。

### B5 结构化漂移（空 evidence claim）

- **证据**：run2 日志 `repair_started | schema=AnalysisCoreDraft | validation_paths=['claims.5.evidence_ids'] | validation_types=['too_short'] | validation_inputs=['[]']`——模型产出空 evidence 的 claim，违反 `AnalysisClaim.evidence_ids: min_length=1`。
- **修复**（用户选定"提超时+确定性修复"）：
  1. `LLM_TIMEOUT_SECONDS` 60→240（`docs/REAL_CHAIN_BUG_REPORT.md` 记载 Agent2 成功轮次需 170–260s）。
  2. `openai_compatible.py` 新增**确定性白名单结构修复** `_deterministic_whitelist_repair`：校验前丢弃空 evidence 的 `claims` / `chart_candidates`，并清理 `dimensions[].claim_ids` 孤儿引用；`scenarios`（min_length=3+精确名校验）不可丢，留给模型 repair；全空 claims 丢弃后触发 min_length=1 仍 **fail-closed（绝不补造证据）**。
- **验证**：新增 4 个单测（`test_openai_compatible.py`）全绿，含"丢弃空 evidence claim 不触发模型 repair turn""全空 claims 仍 fail-closed""scenarios 不丢"。`tests/integrations/llm` + `data_interpreter` + `chapter_writer` 回归全绿。
- **注**：run4（thinking 关闭后）输出干净，确定性修复**未触发**（0 次）——thinking 禁用已消除主要漂移源。确定性修复作为安全网就位，应对未来 flash 系漂移。run4 仅 1 次模型 repair turn（A14-02 supplement 的 `data_quality_issues.2.metric_name` extra_forbidden 轻微漂移，既有机制一次修好）。

---

## 2. Agent2 数据分析：最好 / 最差

### 质量指标对照

| 指标 | A14-02（最好） | A14-03（居中） | A14-01（最差） |
|---|---|---|---|
| overall_confidence | **medium** | low | low |
| financial_quality | **differences_explained** | differences_pending_verification | differences_pending_verification |
| claims | 9 | 11 | **5** |
| evidence_catalog | 115 | 133 | 89 |
| data_quality_issues | 17 | 11 | **20** |
| calculated_metrics | 0 | 0 | 0 |
| chart_candidates | 4 | 3 | 3 |

### 最好：A14-02 隆基绿能

- headline 含**具体核实财务**：营收 703.47 亿、归母净亏 64.20 亿、毛利率 0.81%、经营现金流 +43.59 亿、总资产 1538.04 亿。
- 9 条 claim 每条带 **4–13 个 evidence_ids**，置信 high/medium，不确定性诚实披露（未审计、前视偏差风险、无上年同期无法算同比）。
- 唯一 `medium` 置信 + `differences_explained`（差异已解释，最佳财务质量档）。
- 17 条 data_quality_issues 如实披露（含 shift 异常检测 CRITICAL、业务分拆缺失、CPI/PPI 口径待确认）。
- **诚实缺口**：用户问"主营业务构成"，但证据只有整体财务、缺硅片/电池/组件分拆收入占比——Agent2 明确披露未编造。

### 最差：A14-01 新能源车 PE/PB 估值

- **核心问题无法回答**：headline 直言"缺乏可验证的整体 PE/PB 估值数据，无法确认板块整体估值水平"。
- 5 条 claim 里 **3 条是"无法计算/不可验证/不能代表"**（C-003/004/005）。
- **样本异质**：data_fetch 抓到江铃汽车、中国宝安、富奥股份、深科技、德赛电池、**高新发展（建筑装饰业！）**等概念股，分属整车/零部件/电池/建筑装饰，不能代表新能源车板块。
- low 置信 + differences_pending_verification + **20 条质量问题（最多）**，含 4 条"证据值不一致降级"冲突。
- 根因在 Agent1：板块级 PE/PB 聚合数据同花顺未直接提供，概念标签选股跨行业 → 上游取数缺陷传导到 Agent2/Agent4。

---

## 3. Agent4 章节写作：最好 / 最差

### 质量指标对照

| 指标 | A14-02（最好） | A14-03（居中） | A14-01（最差） |
|---|---|---|---|
| 章节 / 小节 | 7 / 21 | 7 / 21 | 7 / 21 |
| 正文段落数 | 43 | 49 | 40 |
| 正文字符数 | 4570 | **5628** | 4452 |
| 数值段落数 | **24** | 13 | 11 |
| 数值溯源率 | **1.00** | 1.00 | 0.91 |
| missing_inputs 披露 | 37 | 30 | 36 |
| uncertainties 披露 | 54 | 50 | 47 |

### 最好：A14-02

- 数值溯源率 **1.00**（24 个数值段全部带 evidence_ids），数据驱动内容最密（24 数值段，远超另两条）。
- 建立在 medium 置信 + differences_explained 的分析上，章节结论有扎实证据支撑。
- 每章 missing_inputs 诚实披露（CH-01 列 5 条缺口：主营分拆、行业供需、上年同期、集中度、产业链）。

### 最差：A14-01

- 数值溯源率 **0.91（唯一 <1.00）**：CH-07 SEC-07-02 P-07-02-01 段级 evidence_ids 为空（numeric_ref 内部虽带 evidence，但段级未挂，属结构漂移；正向用例门禁要求 numeric_traceability=1.0，此条会被 G 检查判负）。
- 正文最薄（4452 字符 / 40 段），建立在"核心问题无法回答"的分析上，大量章节是"数据缺失、结论不可验证"的条件性表达。
- 注： worst 的根因同样在 Agent1 取数（板块估值数据缺失 + 异质样本），Agent4 忠实地把上游缺陷披露出来（未编造），这是**正确的诚实行为**，但研究产出价值最低。

---

## 4. L3 联网搜索（博查）状态

| 验证层 | 结果 |
|---|---|
| 博查客户端直连活体 | ✅ 冒烟 2 条真实命中（腾讯网），白名单/freshness 生效 |
| executor L3 触发逻辑 | ✅ `test_cascade_fallback.py` 23 项全绿（C-04 L3 命中→level=3/web_unverified/web_fallback_used；C-06 熔断；C-07 护栏禁降级；C-08 零预算不调；C-12 缺 url 丢弃；C-14 freshness 必带） |
| real_runner 接线 | ✅ websearch provider 录制回放缓存 + gateway 注册 WEB_SEARCH + executor web_fallback_enabled |
| **链路内自然触发** | ⚠️ **3 条用例 web_calls=0，未触发** |

**未触发的原因是正确行为**：L3 是最后兜底（方案 §8.6 目标触发率 ≤10%）。3 条用例同花顺 L1 数据足够（A14-03 有 3 次 L2 降级且成功挽救），L1/L2 未全败 → L3 不应触发。要在链路内看到 L3，需要一条同花顺结构化 + 研报/公告/新闻**全部无数据**的研究需求（真实金融数据下较难自然构造）。

**S8 汇总块已落地**：`service.py` 注入 `acquisition_degradation`（web_fallback_used / web_evidence_count / levels_used / web_sources / requirements）+ WEB-SOURCE-UNVERIFIED 信息性风险通知（前端 §7.1 弹窗唯一读取入口）。3 条用例 levels_used 已正确统计（A14-03 的 L2:3 留痕可见）。

---

## 5. 红线 / 门禁合规对照

| 红线（方案 §9） | 落地 | 本轮证据 |
|---|---|---|
| 1 证据层级锁死不可上调 | `evidence_tier` 单向 | 3 条 web_evidence=0，无上调；L3 路径由 23 单测固化 |
| 2 只补定性不填数值 | `qualitative_only` + calculations 前置校验 | 3 条 calculated_metrics=0，无 web/document 证据进计算链 |
| 3 降级不冒充完整性 | status 封顶 partial | A14-03 L2 降级需求未判 supported |
| 4 冲突保留可追溯 | url/site/published_at 缺一不可 | C-12 单测；A14-01 4 条证据冲突如实降级留痕 |
| 5 L3 必须显式告知 | 前端弹窗 + 报告〔网〕标注 | S8 acquisition_degradation + WEB-SOURCE-UNVERIFIED 已注入 |

---

## 6. 可复现性

- **录制回放**：所有真实响应进 `eval/cache/live_content_addressed/{skillhub,llm,websearch}/`（内容寻址，provenance=live）。重放零配额、零触网。
- **重跑命令**（须 `cd backend` 以加载 `.env`）：
  ```bash
  cd backend && .venv/bin/python ../eval/agent14_live_driver.py
  ```
- **缓存投毒教训**：HTTP 200 + finish_reason=length 的空 content 响应会被缓存（stop_code=None），换密钥/改配置不改缓存键 → 回放仍失败。改 LLM 配置后须扫描清理 `finish_reason=length` 与 `status_code=404` 的 llm 缓存条目。
- **改动文件**：生产 `service.py`(S8) / `config.py`(base_url) / `websearch/client.py`(base_url) / `openai_compatible.py`(确定性修复)；评测 `real_runner.py`(降级+联网+thinking 接线) / `agent14_live_driver.py`(新建)；测试 `test_openai_compatible.py`(+4)；配置 `.env`(密钥/端点/超时/联网开关)。

---

## 7. 遗留与建议

1. **L3 链路内演示**：如需在真实链路看到联网兜底，建议构造一条同花顺确无数据的需求（或临时把某任务的 L1/L2 指向空查询）单独跑一次；当前 3 条因数据足够未触发（正确行为）。
2. **Agent1 取数缺陷（A14-01 暴露）**：板块级 PE/PB 聚合 + 概念标签跨行业选股，导致"新能源车估值"问题拿到建筑装饰股。这是上游路由/取数问题，建议另立任务排查（非本次 Agent2/Agent4 评测范围）。
3. **确定性修复未实战触发**：thinking 禁用后输出干净，修复作为安全网就位；建议保留并观察后续 flash 系漂移。
4. **max_tokens=8192**：thinking 禁用后够用；若未来启用 thinking 或更长输出，需同步上调。
5. **密钥安全**：博查密钥与方舟密钥均只存 `backend/.env`（gitignored）；博查密钥曾在对话出现，如有外泄顾虑建议轮换。
