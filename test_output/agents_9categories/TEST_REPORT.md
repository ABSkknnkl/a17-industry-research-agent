# 9类金融投研场景 — 智能体1→2→3 链路测试报告

测试时间: 2026-08-17
测试方法: 智能体2由Assistant充当确定性验证模型（不调用真实LLM），智能体1使用真实iFinD数据

---

## 测试用例选择

| 类别 | 话术ID | 选取的话术 | 话题 | 指标 |
|------|--------|-----------|------|------|
| 1. 单家公司深度调研 | C1 | 整理宁德时代近四年营收、归母净利润、毛利率、各项费用率，同时梳理主营业务结构 | 动力电池 | 营业收入、归母净利润、毛利率、销售费用、管理费用、研发费用、主营业务收入 |
| 2. 行业景气度 | C2 | 动力电池行业近5年市场规模、增速、竞争格局，预判未来两年行业景气变化 | 动力电池 | 市场规模、装机量、行业增速、市场份额 |
| 3. 竞争格局/CR | C3 | 锂电池行业CR3、CR5市场占有率变化，对比国内外龙头企业差距 | 锂电池 | 市占率、市场份额、装机量 |
| 4. 价格/周期 | C4 | 锂、钴、镍近一年价格走势，分析供需基本面和价格后续驱动因素 | 有色金属 | 碳酸锂价格、钴价格、镍价格、锂价格 |
| 5. 估值/宏观 | C5 | 当前新能源车板块整体PE、PB估值以及近三年历史估值分位 | 新能源汽车 | PE、PB、市盈率、市净率、估值分位 |
| 6. 政策/舆情 | C6 | 近期动力电池回收相关产业政策梳理，评估政策落地带来的行业影响 | 动力电池回收 | (定性) |
| 7. 多维度复合 | C7 | 结合行业规模、竞争格局、原材料价格、政策四个维度，综合分析储能行业投资逻辑 | 储能 | 市场规模、市场份额、原材料价格、装机量 |
| 8. 简短口语化 | C8 | 动力电池行业现在景气度怎么样 | 动力电池 | 装机量、行业增速、产能利用率 |
| 9. 风险导向 | C9 | 梳理动力电池行业潜在风险，包括产能过剩、价格战、原材料波动风险 | 动力电池 | 产能、产能利用率、价格、原材料价格 |

---

## 汇总表

| 类别 | 话术ID | Agent1 | Agent2 | Agent3 | 图表 | 抑制 | 候选 | 拦截原因 |
|------|--------|--------|--------|--------|------|------|------|---------|
| 单家公司深度调研 | C1 | waiting_review | waiting_review | completed | 7 | 4 | 0 | CALCULATION-DATA-MISSING (单位不一致) |
| 行业景气度 | C2 | waiting_review | waiting_review | completed | 8 | 0 | 0 | EVIDENCE-METADATA (前视偏差) |
| 竞争格局/CR | C3 | waiting_review | waiting_review | completed | 8 | 0 | 0 | EVIDENCE-METADATA (前视偏差) |
| 价格/周期/原材料 | C4 | waiting_review | waiting_review | completed | 7 | 1 | 0 | EVIDENCE-METADATA (前视偏差) |
| 估值/市场/宏观 | C5 | waiting_review | waiting_review | completed | 8 | 0 | 0 | EVIDENCE-METADATA (前视偏差) |
| 政策/舆情/产业事件 | C6 | completed | waiting_review | completed | 8 | 0 | 0 | EVIDENCE-METADATA (前视偏差) |
| 多维度复合 | C7 | waiting_review | waiting_review | completed | 8 | 0 | 0 | EVIDENCE-METADATA (前视偏差) |
| 简短口语化 | C8 | waiting_review | waiting_review | completed | 8 | 0 | 0 | EVIDENCE-METADATA (前视偏差) |
| 风险导向 | C9 | waiting_review | waiting_review | completed | 8 | 0 | 0 | EVIDENCE-METADATA (前视偏差) |

---

## 各类别详细分析

### 1. 单家公司深度调研 — C1 (宁德时代)

**Agent 1**: waiting_review | 证据143条 | 数据集24个
- 成功获取了宁德时代的营业收入、归母净利润、净资产收益率、研发费用等数据
- 但部分证据的unit字段为"未提供"，营业收入和营业成本使用了不同单位
- 数据质量门因core_data_skills_usable不够而失败

**Agent 2**: waiting_review | 候选0个 | 拦截1个
- 被CALCULATION-DATA-MISSING阻断
- 原因: 计算模块检测到"营业收入与营业成本单位不一致，未执行自动换算，毛利率不可计算"
- 用户明确要求了"毛利率"，计算失败直接触发阻断

**Agent 3**: completed | 图表7张 | 抑制4张
- 生成的图表: 最新涨跌幅对比、总资产趋势、存货对比、研发费用趋势、市盈率对比、最新价对比、ROE对比
- 评价: 研发费用趋势图与用户需求相关，但缺少毛利率、营收同比等核心图表

### 2. 行业景气度 — C2 (动力电池)

**Agent 1**: waiting_review | 证据118条 | 数据集18个
- 获取了动力电池销量、装车量、营业收入等数据
- 质量门失败但核心数据可用

**Agent 2**: waiting_review | 候选0个
- EVIDENCE-METADATA阻断: 10条证据的公告日晚于研究时点

**Agent 3**: completed | 图表8张
- 动力电池销量:当月同比趋势、业务成本、收入占比、归母净利润、市盈率、营业收入趋势、营收同比增长率、装车量趋势
- 评价: 动力电池销量和装车量趋势图与需求相关

### 3. 竞争格局/CR — C3 (锂电池)

**Agent 1**: waiting_review | 证据142条 | 数据集28个
- **关键问题**: 142条证据中0条包含"市占率"或"市场份额"指标
- 获取的是公司级财务数据（营业收入、毛利率、最新价等）和新闻摘要
- Agent 1的query planner未将"CR3/CR5"映射到正确的查询

**Agent 2**: waiting_review | 候选0个
- EVIDENCE-METADATA阻断
- 即使不被阻断，也无法基于不相关的数据生成CR3/CR5分析

**Agent 3**: completed | 图表8张
- 总股本、归母净利润、ROE、估值百分位、涨跌幅、最新价等
- 评价: 与用户需求（CR3/CR5集中度）无关

### 4. 价格/周期 — C4 (锂钴镍价格)

**Agent 1**: waiting_review | 证据151条 | 数据集27个
- 获取了58条"宏观@值"数据（包含有色金属价格数据）
- 有"平均价:锂(≥99%):华通有色"等价格数据

**Agent 2**: waiting_review | 候选0个
- EVIDENCE-METADATA阻断

**Agent 3**: completed | 图表7张 | 抑制1张
- 有色金属趋势、锂镍钴铝氧化物进口均价趋势、锂均价趋势等
- 评价: 价格趋势图与需求较相关

### 5. 估值/宏观 — C5 (新能源车PE/PB)

**Agent 1**: waiting_review | 证据136条 | 数据集28个
- 成功获取了18条PE/PB相关数据（市盈率(pe)、市盈率(pe,ttm)、市净率(pb)、市盈率分位点等）
- 新能源汽车scope有28条数据
- 数据质量较好，但被Agent 2阻断

**Agent 2**: waiting_review | 候选0个
- EVIDENCE-METADATA阻断: 2条证据的公告日晚于研究时点

**Agent 3**: completed | 图表8张
- 业务成本、归母净利润趋势、总市值趋势、市净率、市盈率等
- 评价: 市净率和市盈率图与需求相关，但缺少估值分位图

### 6. 政策/舆情 — C6 (动力电池回收政策)

**Agent 1**: completed | 证据135条 | 数据集30个
- 唯一一个Agent 1返回COMPLETED的案例
- 但获取的是动力电池销量、公司财务数据，不是政策文件
- Agent 1的query planner将"动力电池回收"截断为"动力电池"，丢失了"回收"和"政策"维度

**Agent 2**: waiting_review | 候选0个
- EVIDENCE-METADATA阻断: 4条title/summary证据的发布时间晚于研究时点1天

**Agent 3**: completed | 图表8张
- 市净率、归母净利润增速、市盈率TTM、涨跌幅、动力电池销量等
- 评价: 与"政策梳理"需求完全无关

### 7. 多维度复合 — C7 (储能投资逻辑)

**Agent 1**: waiting_review | 证据160条 | 数据集30个
- 获取了储能相关公司的财务数据

**Agent 2**: waiting_review | 候选0个
- EVIDENCE-METADATA阻断

**Agent 3**: completed | 图表8张
- 市盈率、毛利率趋势、营收同比增长率、ROE、净利润增速、最低价、经营现金流、净利润
- 评价: 缺少行业规模、竞争格局、原材料价格、政策四个维度的图表

### 8. 简短口语化 — C8 (动力电池景气度)

**Agent 1**: waiting_review | 证据128条 | 数据集21个
- 获取了25条"宏观@值"数据和动力电池装车量数据

**Agent 2**: waiting_review | 候选0个
- EVIDENCE-METADATA阻断: 10条证据的公告日晚于研究时点

**Agent 3**: completed | 图表8张
- 最新价、业务成本、装车量趋势、涨跌幅、动力电池趋势、利润占比、归母净利润、ROE
- 评价: 装车量趋势与景气度相关

### 9. 风险导向 — C9 (动力电池风险)

**Agent 1**: waiting_review | 证据113条 | 数据集20个
- 获取了25条summary、17条title以及12条"宏观@值"数据
- 主要是定性数据（新闻摘要、报告标题）

**Agent 2**: waiting_review | 候选0个
- EVIDENCE-METADATA阻断: 10条证据的公告日晚于研究时点

**Agent 3**: completed | 图表8张
- 经营现金流趋势、营收同比增长率、业务成本、涨跌幅、归母净利润增速、动力电池趋势、收入占比
- 评价: 与"风险分析"需求关联度低

---

## 发现的Bug

共发现5个Bug，详见 `BUG_ANALYSIS.md`：

| Bug | 严重程度 | 描述 |
|-----|---------|------|
| BUG-001 | 高 | evidence_metadata preflight检查过严，少量前视偏差证据(1天)阻断Agent 2分析 |
| BUG-002 | 高 | 计算模块无法处理单位不一致（元vs万元），导致毛利率计算失败 |
| BUG-003 | 中 | Agent 3在Agent 2失败时生成与用户需求无关的兜底图表 |
| BUG-004 | 中 | Agent 1 query planner无法将专项需求（CR3/CR5、政策）映射到正确skill |
| BUG-005 | 低 | 大量证据项unit字段为"未提供"，影响计算可用性 |

---

## 测试产物

| 文件 | 说明 |
|------|------|
| C1.html ~ C9.html | 9份测试报告（含ECharts图表） |
| C1.json ~ C9.json | 9份原始数据（Agent 1/2/3完整输出） |
| summary.json | 汇总数据 |
| TEST_REPORT.md | 本报告 |
| BUG_ANALYSIS.md | Bug根因分析文档 |