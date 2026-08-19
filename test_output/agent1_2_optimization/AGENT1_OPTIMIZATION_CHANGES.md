# Agent 1 数据层优化 — 改动交接文档（面向 AI）

本文件记录「智能体 Skill 扩展优化方案（V2）」中**一期（Agent 1 数据层，P0/P1）**的实际落地改动。读者对象是后续接手的 AI/开发者，用于快速理解 Agent 1 当前具备什么能力、路由规则是什么、改了哪些文件。

> 范围说明：只涉及 Agent 1（`data_fetcher`）与配套 schema/集成层。二期（Agent 2 方法论层 ClawHub 框架）不在本文件范围。

---

## 一、改动总览

| 文件 | 改动 | 解决的数据缺口 / Bug |
|------|------|---------------------|
| [acquisition.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/schemas/acquisition.py) | `SkillName` 新增 4 个枚举；`CONDITIONAL_P1_SKILLS`、`CORE_DATA_SKILLS` 同步 | C3 市占率 / C4 期货 / C5 指数估值缺数据源 |
| [catalog.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/integrations/skillhub/catalog.py) | 新增 4 条 `SkillSpec`（query2data） | 新 skill 接入 SkillHub |
| [metric_registry.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_fetcher/metric_registry.py)（新增） | 15 个 `MetricSpec` 指标注册表 | **修复「选对 Skill 但查询写死营业收入」核心 bug** |
| [semantic_router.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_fetcher/semantic_router.py)（新增） | LLM 语义路由兜底 | 长尾/偏门指标正确路由 |
| [planner.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_fetcher/planner.py) | 路由 token 扩展 + 动态查询注入 + 新 skill 的 profile/fallback | 路由覆盖 + 指标真正进入查询 |
| [normalizer.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_fetcher/normalizer.py) | 单位归一 + 市盈率后缀剥离 | 单位不一致 / 指标名失配 |
| [factory.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_fetcher/factory.py) | 组装语义路由（开关控制） | 可选择性启用 LLM 兜底 |

---

## 二、新增 Skill（P1，条件触发）

| Skill | skill_id | 触发关键词 | 解决的测试场景 |
|-------|----------|-----------|---------------|
| `INDEX` | `hithink-index-query` | 估值分位 / 历史分位 / 市盈率 / 市净率 / PE/PB / 沪深300 / 创业板指 / 上证指数 / 指数估值 | C5 板块 PE/PB 历史分位 |
| `FUTURES` | `hithink-futures-query` | 期货 / 结算价 / 碳酸锂 / 动力煤 / 焦煤 / 纯碱 / 工业硅 / 多晶硅 / 大宗商品 / 现货价格 / 库存周期 | C4 大宗商品期货价格 |
| `STOCK_SELECTOR` | `hithink-stock-selector` | 市占率 / CR3 / CR5 / 集中度 / 市场份额 / 前十大 / 龙头排名 | C3 行业横截面榜单 → 算 CR |
| `BASIC_INFO` | `hithink-basicinfo-query` | 基本资料 / 基础信息 / 股票代码 / 证券代码 / 上市地点 / 上市日期 / 发行主体 | 实体基础信息补充 |

这些 skill 均为同花顺官方 `query2data` 端点，执行模型与既有 client 完全一致，**client.py / executor.py 零改动**。

---

## 三、核心机制：动态指标注入（修复核心 bug）

### 前置问题
旧逻辑 `_market_skill_query(FINANCE)` 写死字段 `营业收入 营业成本 净利润 …`，即使用户请求「毛利率」，路由对了 FINANCE，查询里也没有「毛利率」，SkillHub 自然不返回 → 需求被判 missing。

### 修复方式
1. [metric_registry.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_fetcher/metric_registry.py) 定义 `MetricSpec`，为每个规范指标声明：
   - `aliases`：归一化别名（含「净利率/销售净利率/归母净利率」等）
   - `primary_skill`：确定性路由目标
   - `query_fields`：**必须真正发给 SkillHub 的字段**（含可复算的原始字段）
   
   例如 `gross_margin` → `query_fields = ("毛利率", "营业收入", "营业成本")`。

2. [planner.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_fetcher/planner.py) 的 `_market_skill_query` 改为：
   ```python
   metric_spec = get_metric_spec(request_text)
   metric_fields = list(metric_spec.query_fields) if metric_spec else [request_text]
   requested_fields = " ".join(dict.fromkeys(field for field in metric_fields if field))
   # FINANCE / BUSINESS / STOCK_SELECTOR 分支拼入 requested_fields
   ```

   结果：用户指标 + 必要原始字段被动态注入查询，不再依赖硬编码。

---

## 四、路由规则速查（给 AI 的决策表）

路由优先级（`deterministic_metric_skill` → `_metric_skill`）：

1. **指标注册表** `get_metric_spec(value)` 命中 → 返回 `primary_skill`（最高优先）
2. **条件市场关键词** `_conditional_market_skill` 命中（见下表）
3. **兜底 token 白名单**（营业收入/毛利率/费用率→FINANCE；GDP/CPI/PMI/利率→MACRO；产业链→INDUSTRY_CHAIN；股票代码/上市地点→BASIC_INFO）
4. 若确定性全部未命中 → `deterministic_metric_skill` 返回 `None` → **交给语义路由（LLM）**
5. 语义路由也失败/低置信度(<0.9)/异常 → 回退 `INDUSTRY`

`_conditional_market_skill` 关键词 → Skill 映射：

| 关键词 | Skill |
|--------|-------|
| 基本资料/股票代码/证券代码/上市地点/上市日期/发行主体/基金费率/期货合约信息/债券资料 | BASIC_INFO |
| 财务报表/三表/杜邦/现金含量/盈利质量/资产负债表/现金流量表 | FINANCE |
| cr3/cr5/集中度/市占率/市场份额/前十大/龙头排名 | STOCK_SELECTOR |
| 期货/结算价/碳酸锂/动力煤/焦煤/纯碱/工业硅/多晶硅/大宗商品/现货价格/库存周期 | FUTURES |
| 估值分位/历史分位/市盈率/市净率/pe·pb/指数估值/沪深300/创业板指/上证指数 | INDEX |

---

## 五、语义路由（LLM 兜底）设计约束

见 [semantic_router.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_fetcher/semantic_router.py)：

- **LLM 不是主路由**，只处理确定性注册表未命中的长尾指标。
- 只能从已注册 `SkillName` 枚举中选择，**不得自创 skill、不得生成 HTTP/CLI/参数**。
- 置信度低于 `AGENT1_SEMANTIC_ROUTER_CONFIDENCE`（默认 0.9）→ 拒绝 → 回退确定性。
- 模型异常 → 兜底确定性路径，**绝不阻断数据获取**。
- 通过 `openai_compatible` 结构化输出（`SemanticRouteBatch`），DeepSeek 走 `json_mode`。

启用开关：`AGENT1_SEMANTIC_ROUTER_ENABLED`（默认关闭，示例配置默认关），见 [factory.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_fetcher/factory.py)。

---

## 六、归一化配套

[normalizer.py](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_fetcher/normalizer.py)：
- `_normalize_numeric_unit`：元/万元/亿元、股/万股/亿股、千瓦/兆瓦/吉瓦、千瓦时/兆瓦时/吉瓦时 自动换算到基准单位。
- `_provider_contract_unit`：指数 PE/PB 单位固定「倍」，比率/占比/分位 固定「%」，不再从数值量级猜单位。
- `_normalize_metric_name`：剥离 `市盈率(pe,ttm)` 等后缀，使指标名对齐。
- `_METRIC_ALIASES`：销售毛利率→毛利率、归母净利润 等别名归一。

---

## 七、不变式 / 约束（务必遵守）

1. **新增 skill 全部条件触发**，不增加无条件基线调用（守住 30 任务上限）。
2. **只加不改**：原 11 个 skill 的枚举值、query 模板、优先级不动。
3. 指标缺失分级：
   - 核心关注问题缺失 → 硬阻断（`required_data_unavailable`）。
   - 单个指定指标缺失 → `requested_data_partial` 软路径，展示风险，允许用户接受后继续，**绝不补造数据**。
4. 无法获取的数据（如非上市实体「原神股价」）→ 返回空/null，证据数为 0，不伪造。
5. 语义路由是**咨询性质**的兜底，provider 失败绝不 disable 确定性路径。

---

## 八、验证结论（历史测试）

- 标准指标（毛利率/净利率/费用率/海外收入占比/市占率）→ 全部 supported，动态注入生效。
- 长尾指标（库存周转率/净资产收益率）→ LLM 正确路由到 FINANCE。
- 无法获取指标（原神股价）→ 返回 null/gap，不补造，走软路径。
- Agent 2 六项确定性比率公式（毛利率/净利率/研发·销售·管理费用率/海外收入占比）计算全部正确。

详见 [BUG_ANALYSIS.md](file:///Users/Zhuanz1/PycharmProjects/同花顺/test_output/agent1_2_optimization/BUG_ANALYSIS.md)。