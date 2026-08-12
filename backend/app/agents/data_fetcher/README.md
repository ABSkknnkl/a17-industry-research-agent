# Agent 1 数据获取智能体

Agent 1已完成 P0/P1 后端实现，是五阶段流水线的事实入口。它只负责查询规划、SkillHub 调用、清洗、去重、冲突保留和证据标准化，不生成金融结论。

## 能力范围

P0 必调用能力：

- `hithink_industry_query`：行业规模、增速、景气度和估值。
- `hithink_finance_query`：代表公司财务、盈利质量和现金流。
- `hithink_macro_query`：宏观和政策指标。
- `industry_chain_analysis`：组合行业与经营数据形成可追溯的产业链研究素材；不虚构上中下游关系。
- `report_search`：研报检索。
- `news_search`：新闻与风险事件检索。

P1 增强能力（`standard`/`deep`深度自动启用）：

- `announcement_search`：上市公司公告。
- `hithink_event_query`：业绩预告、调研、监管、解禁等事件。
- `hithink_business_query`：主营业务、客户、供应商和业务构成。
- `hithink_sector_selector`：板块成分、市值、龙头和行情。
- `hithink_insresearch_query`：机构覆盖、评级和盈利预测。

`overview`模式仅执行六个 P0；`standard`/`deep`执行 P0+P1 共 11 个逻辑技能。

## 内部流程

```text
用户研究请求
  -> QueryPlanner（范围/指标/时间/来源规划）
  -> RetrievalExecutor（有界并发、分页、备选查询）
  -> ToolGateway（Schema、超时、预算、结构化错误）
  -> SkillHub Client（真实/本地 Mock）
  -> Normalizer（清洗、口径归一、相关性隔离、EvidenceItem）
  -> Fusion（原始行/事实两级去重、来源合并、真冲突保留）
  -> Quality Gate（核心数据组、有效性、一致性、唯一性）
  -> StageResult(data_fetch)
```

业务节点不允许直接调用 CLI 或 HTTP；所有外部能力都必须通过 `ToolGateway`。这样可统一参数校验、超时、调用上限、脱敏日志和可重试错误。

## 输出交接

Agent 2 消费标准 `evidence_items`；Agent 3 消费 `chart_datasets`。审计和人工审核使用：

- `retrieval_plan`：实际查询计划与已应用审核意见。
- `skill_calls`：每个技能的状态、行数、页数、耗时和错误码。
- `source_records`：来源定位、抓取时间、原始返回 SHA-256 和存储边界。
- `data_gaps`：空结果、鉴权、限流或供应商异常。
- `conflicts`：同口径不同值的全部证据 ID，不静默选值。
- `duplicate_groups`：同一事实的主证据、被合并证据和全部来源定位。
- `quarantined_records`：明确与研究主题不匹配的返回行，仅隔离供人工复核，不静默删除。
- `normalization_summary`：原始行、唯一行、清洁行、证据、重复和隔离数量。
- `acquisition_quality`：完整性、技能覆盖率、有效性、一致性和去重率。

财务返回未携带审计/追溯调整信息时，系统保留 `unknown` 并在质量结果中告知，不猜测。缺日期、缺单位、缺来源定位、未来数据和 E 级证据仍由 Agent 2 事实门阻断。

真实提供方可能返回超过 ToolGateway 文本上限的动态宽表。SkillHub 注册项会保留已经过 Pydantic 校验的结构化对象供确定性标准化器消费，但运行事件仍只记录技能名、状态与安全错误码，不记录完整载荷。证据最多保留 200 条，每个实体的同一指标最多保留 12 个最新数据点，并按已返回结果的逻辑技能公平分配；所有来源元数据不因证据限额而丢失。字段名内的动态日期（例如 `净利润[20251231]`）会被解析为报告期。

清洗器会去除 HTML/不可见字符、空白和 `--`/`N/A` 等缺失值，并对常见财务别名、货币、股数和功率/能量单位进行确定性归一。原始行跨页重复会先去重；随后再按实体+指标+期间+数值+单位+口径合并事实。浮点噪声在容差内视为同值，实质不同值仍作为冲突全部保留。

定性研报、新闻和业务描述不强制伪造财务报告期；数值证据缺少明确期间时会进入非阻断质量警告，留给人工复核。质量门依据是“四类核心数据组”：`hithink_macro_query`、`hithink_industry_query`、`hithink_finance_query`、`industry_chain_analysis` 中任意一类调用返回数据，`completeness=1.0`；其他核心技能和搜索技能缺口只警告。正式放行还需要返回数据在清洗后形成至少一条可追溯核心证据，避免“接口成功但数据全部无效”被当作合格。四类全部未返回数据时才返回 `core_data_group_unavailable` 等待人工复核。

## 人机审核

`data_fetch`已是默认审核阶段。修改采集范围时，前端通过 `edited_data.data_fetch_options` 传入：

- `keywords`：增删查询关键词。
- `industry_scope`：调整行业/地域范围。
- `time_range`：最多两个时间边界。
- `data_sources`：指定希望优先检索的来源。
- `metrics`：指定需补充的指标。

`review_feedback` 与上述结构化字段同时进入新版查询计划。修改会增加 `revision`、重跑 Agent 1，不会让后端从自然语言猜测当前阶段。

## 运行配置

应用默认且强制使用真实 SkillHub。`SKILLHUB_USE_MOCK=true` 只允许在 `ENVIRONMENT=test` 的自动化测试进程中使用；开发、演示和部署环境尝试启用 Mock 会在启动组装 Agent 1 时直接失败。真实调用配置：

```dotenv
SKILLHUB_USE_MOCK=false
IWENCAI_API_KEY=<your-authorized-key>
IWENCAI_BASE_URL=https://openapi.iwencai.com
```

密钥只能位于本地 `.env` 或部署密钥管理中，不得进入 Git。

给其他人测试时，推荐由项目负责人部署后端并在服务器密钥管理中配置 `IWENCAI_API_KEY`，测试者只获得系统自己的 Bearer Token，通过后端调用 Agent 1；不要向测试者分发 SkillHub Key。若测试者自行启动后端，则必须配置其本人获授权的 SkillHub Key。没有 Key 时 Agent 1 返回 `auth_required` 并停在数据获取阶段，绝不回退到模拟数据。
