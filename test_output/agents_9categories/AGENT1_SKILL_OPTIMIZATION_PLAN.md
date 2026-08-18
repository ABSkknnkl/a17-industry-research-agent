# 智能体 Skill 扩展优化方案（V2，含全部图片skill评估）

日期: 2026-08-17
依据: 9类场景链路测试报告（TEST_REPORT.md）与 Bug 根因分析（BUG_ANALYSIS.md）

---

## 一、背景与目标

9类测试暴露的智能体1数据缺口：

| 测试案例 | 数据缺口 | 缺口性质 |
|---------|---------|---------|
| C3 锂电池CR3/CR5 | 142条证据中0条市占率，也无"行业内公司营收排名"横截面数据 | 缺横截面筛选能力 |
| C4 锂钴镍/动力煤/纯碱价格 | 价格靠 MACRO"宏观@值"间接命中，无期货口径价格、库存、产销、持仓 | 缺大宗商品/期货数据源 |
| C5 新能源车板块PE/PB及历史分位 | 估值数据来自个股 finance 查询，无指数级PE/PB与历史分位 | 缺指数估值数据源 |
| C6 动力电池回收政策 | news/report 已返回定性文本，数据源不缺 | 缺定性分析方法论（Agent 2层） |
| C9 风险导向 | 有定性数据但无风险分析框架 | 缺风险分析方法论（Agent 2层） |
| C1 宁德时代毛利率 | 数据已取到，问题在单位换算 | 不需要新skill |

目标：新增**项目当前没有、且与现有skill不冲突**的skill，分两层补齐：
- **第一层（Agent 1 数据层）**：官方数据查询skill，补 C3/C4/C5 数据缺口；
- **第二层（Agent 2 方法论层）**：ClawHub 分析框架skill，补 C1/C2/C5/C6/C9 分析方法缺口。

---

## 二、现有 Skill 清单（11个，不得重复引入）

INDUSTRY(hithink-industry-query)、FINANCE(hithink-finance-query)、MACRO(hithink-macro-query)、INDUSTRY_CHAIN(产业链解读)、REPORT(report-search)、NEWS(news-search)、ANNOUNCEMENT(announcement-search)、EVENT(hithink-event-query)、BUSINESS(hithink-business-query)、SECTOR(hithink-sector-selector)、INSTITUTIONAL_RESEARCH(hithink-insresearch-query)。

---

## 三、第一层：新增官方数据查询 Skill（3个）→ Agent 1

均为同花顺官方出品、走 `openapi.iwencai.com` 的 `query2data` 端点，与现有 [client.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/integrations/skillhub/client.py) 执行模型完全兼容，**客户端零改动**。

### 1. 指数数据查询（INDEX）— 解决 C5

- 建议 skill_id: `hithink-index-query`（实施前以 SkillHub 注册表实际ID为准）；tier: P1 条件触发
- 能力: 上证指数、沪深300、创业板指等指数行情与估值数据
- expected_fields: `["指数代码", "指数名称", "市盈率", "市净率", "市盈率分位点", "数据日期"]`
- 示例 query: `新能源车板块指数 市盈率 市净率 历史分位 2024-01-01至2026-08-12`
- 冲突核查: 与 MACRO（宏观经济指标）不重叠；与 SECTOR（返回成分股/涨跌幅）不重叠；现有清单无指数级估值源 ✔

### 2. 期货期权数据查询（FUTURES）— 解决 C4

- 建议 skill_id: `hithink-futures-query`；tier: P1 条件触发
- 能力: 期货期权的行情、波动率、产销、会员持仓、会员榜单、行权等数据
- expected_fields: `["品种名称", "合约/指标名称", "指标值", "单位", "数据日期"]`
- 示例 query: `碳酸锂期货 结算价 库存 2025-08-01至2026-08-12`
- 冲突核查: 与 MACRO 存在潜在重叠（锂价两边都可能返回）→ 需路由互斥规则（第五节）；与 FINANCE 不重叠 ✔

### 3. 问财选A股（STOCK_SELECTOR）— 解决 C3

- 建议 skill_id: `hithink-stock-selector`；tier: P1 条件触发
- 能力: 自然语言跨市场个股筛选/排序（行情、财务、行业概念组合条件）
- expected_fields: `["股票代码", "股票简称", "营业收入", "净利润", "排名", "报告期"]`
- 示例 query: `锂电池行业 A股 营业收入 排名前10 2025年报`
- 作用: 返回行业横截面榜单，配合 INDUSTRY 行业总量，Agent 2 即可计算 CR3/CR5
- 冲突核查: 与 SECTOR（筛板块）对象不同；与 FINANCE（查指定公司）语义不同（筛选/排序 vs 定点查询）✔

---

## 四、第二层：新增 ClawHub 分析框架 Skill（7个）→ Agent 2 方法论层

ClawHub skill 是**分析框架/方法论**（非数据查询API），不进入 Agent 1 的 RetrievalPlan，而是作为 Agent 2 的结构化分析方法注入：每个框架提供"分析维度 + 输出模板"，Agent 2 的 LLM 在生成 analysis draft 时按对应框架组织维度与结论。项目当前无任何方法论层，**零冲突**。

| # | 框架 | 映射测试场景 | 提供的核心方法论 |
|---|------|------------|----------------|
| 1 | 大宗商品分析 | C4/C15-17 | 原油供需平衡、黄金定价、铜经济先行指标、库存周期 → 价格周期判断框架 |
| 2 | 行业轮动分析 | C2/C8/C11 | 申万行业景气度评分、行业动量排名、产业链传导、估值比较 → 景气度判断框架 |
| 3 | 估值模型方法论 | C5/C18-20 | DCF/DDM/SOTP、PE-Band、PB-ROE、EV/EBITDA → 估值分位判断框架 |
| 4 | 地缘政治风险分析 | C6/C22/C24 | 战争、制裁、供应链中断量化危机信号 → 海外关税/出口管制定性分析框架 |
| 5 | 金融监管知识库 | C6/C21/C31 | A股涨跌停/ST退市新规/融券机制等监管规则 → 国内产业政策解读框架 |
| 6 | 财务报表深度解读 | C1 | 三表勾稽关系、盈利质量（应计与现金流）、杜邦分解 → 单家公司深度调研框架 |
| 7 | 风险分析与压力测试 | C9/C32-33 | VaR/CVaR、最大回撤、蒙特卡洛、极端情景 → 风险导向分析框架 |

**集成方式（二选一，推荐A）**:
- **A. 方法论模板注入（推荐，零API依赖）**: 新建 `backend/app/agents/data_interpreter/methodologies.py`，将7个框架编码为 `MethodologySpec`（触发关键词 + 分析维度 + 输出模板 + 图表建议），Agent 2 按用户问题关键词匹配后注入 runtime_prompt。不改动 Agent 1 任何契约。
- **B. Claw网关调用（可选升级）**: 若 Claw 平台以同一 `X-Claw-Skill-Id` 协议暴露这些框架，可作为 P1 条件任务调用，返回分析文本；normalizer 需将其输出标记为定性证据（grade B/C，source_locator 保留 trace_id）。实施前需冒烟验证网关可达性。

---

## 五、路由互斥规则（防冲突核心，planner.py）

新增任务均为**关键词条件触发**，不增加无条件基线调用（守住30任务上限）：

| 触发关键词 | 路由到 | 互斥/优先级说明 |
|-----------|--------|----------------|
| 估值分位、PE、PB、市盈率、市净率、沪深300、创业板指、上证指数、指数估值 | INDEX | 宏观指标词（GDP/CPI/PMI/利率/社融）仍走 MACRO |
| 期货、碳酸锂、动力煤、焦煤、纯碱、工业硅、多晶硅、铜、铝、镍、钴、大宗商品、现货价格、库存周期 | FUTURES | 与 MACRO 并存但 query 不混写：商品词→FUTURES，宏观词→MACRO 基线 |
| 市占率、CR3、CR5、集中度、市场份额、排名、前十大、龙头、筛选 | STOCK_SELECTOR | 与 FINANCE 互补：定点公司查询仍走 FINANCE，横截面榜单走 STOCK_SELECTOR |

`_metric_skill()` 扩展：`市盈率/市净率/PE/PB/分位/指数`→INDEX；`碳酸锂/动力煤/纯碱/工业硅/期货/大宗`→FUTURES；`市占率/市场份额/排名`→STOCK_SELECTOR。
`_build_requirements()` 中"市占率"类问题 target_skills 改为 `[INDUSTRY, STOCK_SELECTOR]`。

---

## 六、全量排除清单及理由

### 6.1 官方skill — 与现有重复（不引入）

公告搜索、研报搜索、新闻搜索、宏观数据查询、行业数据查询、财务数据查询、事件数据查询、公司经营数据查询、机构研究与评级查询、问财选板块 —— 均已存在（ANNOUNCEMENT/REPORT/NEWS/MACRO/INDUSTRY/FINANCE/EVENT/BUSINESS/INSTITUTIONAL_RESEARCH/SECTOR）。

### 6.2 官方skill — 冲突或场景无关（不引入）

| skill | 排除理由 |
|-------|---------|
| 行情数据查询 | 与 INDEX + FINANCE 输出重叠（最新价/涨跌幅/个股市盈率当前已能取到），引入会放大单位不一致面（BUG-005） |
| 公司股东股本查询 | 9类场景无股东结构/股本需求 |
| 基本资料查询 | 实体解析需求可由 STOCK_SELECTOR/FINANCE 覆盖；候选池备选 |
| 模拟炒股 | 交易服务，非投研数据 |
| 问财选基金/基金经理/基金公司、基金理财查询、问财选ETF | 资产类别不符（项目为A股行业研究） |
| 问财选可转债、问财选美股、问财选港股 | 资产/市场不符 |
| 问财选期货期权 | 筛选器，与已选的期货期权数据查询功能重叠，保留数据查询版 |

### 6.3 ClawHub — 定位不符：量化交易/技术信号（不引入）

波动率策略、基础技术指标信号引擎、策略生成与优化、聪明钱概念信号引擎、季节性与日历效应策略、配对交易策略、期权盈亏分析、多因子选股策略、机器学习策略、分钟级数据分析、一目均衡表信号引擎、谐波形态信号引擎、K线形态识别、艾略特波浪信号引擎、执行模型、期权策略框架、高级期权策略、对冲策略设计、爆仓热力图分析、Pine Script转换与生成 —— 均为交易信号/回测框架，项目产出是投研报告而非交易指令。

### 6.4 ClawHub — 市场/资产不符（不引入）

DeFi收益分析、加密衍生品策略、链上数据分析、稳定币流向分析、永续资金费率与基差分析、市场微观结构分析（加密/微观交易）；SEC文件分析、美国ETF资金流分析、ADR/H股/A股比价分析（美股/跨市场）；基金分析与筛选、ETF分析、可转债分析、信用与固收分析、因子研究框架、业绩归因分析、基本面因子筛选、相关性与协整分析、量化统计方法（基金/债券/量化研究）。

### 6.5 ClawHub — 数据源不符（不引入）

社交媒体情报分析（Twitter/Telegram/Reddit，非中文财经媒体源）。

### 6.6 候选池（本次不引入，列为三期备选）

宏观周期分析（C20利率环境影响）、市场情绪分析（C33担忧观点的情绪信号）、盈利预测与一致预期分析、盈利预期修正分析（一致预期跟踪）、公司事件驱动分析（并购/增减持）、沪深港通资金流分析（北向资金）、全球宏观分析框架、基本资料查询。理由：与7个已选框架相比，对当前9类失败场景的边际改善较小，待一二期验证后再评估。

---

## 七、代码改动清单（实施阶段，测试期不动生产代码）

### 一期（Agent 1 数据层，修 C3/C4/C5）

| 文件 | 改动 |
|------|------|
| [acquisition.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/schemas/acquisition.py) | `SkillName` 增加 INDEX/FUTURES/STOCK_SELECTOR；`CORE_DATA_SKILLS` 增加 INDEX、FUTURES（使 C4/C5 取数成功即过质量门） |
| [catalog.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/integrations/skillhub/catalog.py) | 增加3条 `SkillSpec`，tier=P1，endpoint="query2data" |
| [planner.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_fetcher/planner.py) | 条件触发任务块（priority 92-96，max_pages=1）；`_metric_skill()`/`_requirement_task_profile()`/`_fallback_queries()` 扩展（见第五节） |
| [normalizer.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_fetcher/normalizer.py) | 配套：单位归一（元/万元/亿元自动换算，修BUG-002）；`_METRIC_ALIASES` 增加"市盈率(pe)→市盈率"等 |
| [service.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_interpreter/service.py) | 配套：前视偏差改警告不阻断（修BUG-001），否则新skill数据仍被Agent 2拦截 |

client.py、executor.py 无需改动（新skill均为标准 query2data）。

### 二期（Agent 2 方法论层，修 C1/C2/C5/C6/C9 分析质量）

| 文件 | 改动 |
|------|------|
| 新建 `app/agents/data_interpreter/methodologies.py` | 7个 `MethodologySpec`（触发词、分析维度、输出模板、图表建议） |
| [data_interpreter/service.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_interpreter/service.py) | runtime_prompt 注入匹配到的方法论模板；不改动 preflight/calculation 逻辑 |

---

## 八、验证计划

重跑 `test_agents_9categories.py`，验收标准：

| 案例 | 预期改善 |
|------|---------|
| C3 | STOCK_SELECTOR 公司营收榜单 + INDUSTRY 行业总量 → Agent 2 可算 CR3/CR5，chart_candidates ≥1 |
| C4 | FUTURES 碳酸锂/钴/镍期货价格序列 → 期货口径价格趋势图，unit 完整 |
| C5 | INDEX 板块PE/PB及分位点 → 估值分位图直接生成 |
| C1/C6/C9 | 二期方法论注入后，analysis draft 维度与图表建议贴合需求（财务报表深度解读/地缘政治+监管知识库/风险压力测试框架） |
| 回归 | C1=7图、C2=8图等基线不劣化；单案例任务数 ≤30；无路由冲突 |

---

## 九、风险与约束

1. skill_id 以 SkillHub 注册表为准，实施前冒烟调用确认。
2. 新增任务均条件触发（P1），最坏单案例 +3 次调用，在现有重试/退避预算内。
3. 只加不改：现有11个 skill 的枚举值、query 模板、优先级不动，保证回归基线可比。
4. ClawHub 框架不得复用 Agent 1 的 RetrievalPlan 契约；若走网关调用（方式B），输出必须标记为定性证据并保留 trace_id 审计链。