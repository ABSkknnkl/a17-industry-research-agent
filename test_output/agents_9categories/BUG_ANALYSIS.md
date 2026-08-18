# Bug根因分析文档

测试时间: 2026-08-17
测试范围: 9类金融投研场景，智能体1→2→3链路
测试方法: 智能体2由Assistant充当确定性验证模型，不调用真实LLM

---

## Bug概要

| # | Bug编号 | 严重程度 | 影响范围 | 类别 |
|---|---------|---------|---------|------|
| 1 | BUG-001 | **高** | 8/9案例 | evidence_metadata preflight检查过严，少量前视偏差证据阻断Agent 2 |
| 2 | BUG-002 | **高** | C1案例 | 计算模块无法处理单位不一致（元vs万元），导致毛利率计算失败 |
| 3 | BUG-003 | **中** | 全部案例 | Agent 3在Agent 2失败时生成与用户需求无关的兜底图表 |
| 4 | BUG-004 | **中** | C3/C6案例 | Agent 1 query planner无法将专项需求（CR3/CR5、政策）映射到正确skill |
| 5 | BUG-005 | **低** | 全部案例 | 大量证据项unit字段为"未提供"，影响计算可用性 |

---

## BUG-001: evidence_metadata preflight检查过严

### 现象
Agent 2在8/9案例中进入WAITING_REVIEW状态，未生成任何chart_candidates（0个候选），原因均为`EVIDENCE-METADATA`拦截。

### 根因分析

**代码位置**: `backend/app/agents/data_interpreter/service.py` 第19-43行 `_evidence_preflight_issues()` 函数

```python
def _evidence_preflight_issues(request: AnalysisRequest) -> list[str]:
    issues: list[str] = []
    for item in request.evidence_items:
        prefix = item.evidence_id
        if item.available_at is None:
            issues.append(f"{prefix}缺少公告日/可得日")
        elif item.available_at > request.research_as_of:
            issues.append(f"{prefix}公告日/可得日晚于研究时点，存在前视偏差")  # ← 触发点
        if item.source_locator is None:
            issues.append(f"{prefix}缺少证据定位")
        if item.grade.value == "E":
            issues.append(f"{prefix}为E级待核验输入，不得直接支持核心结论")
    return issues
```

然后在第151-169行，**任何**preflight issues都会导致Agent 2直接返回WAITING_REVIEW，不进入模型分析：

```python
preflight_issues = _evidence_preflight_issues(request)
if preflight_issues:
    return StageResult(
        stage=self.stage,
        status=StageStatus.WAITING_REVIEW,
        ...
    )
```

**实际数据验证**（以C6为例）:
- 总证据项: 135条
- 前视偏差证据: 仅4条（available_at=2026-08-13，比research_as_of=2026-08-12晚1天）
- 这4条是research report的title/summary，发布时间比研究时点晚1天属于正常延迟
- 但4条证据就阻断了整个135条证据包的分析

### 影响
- Agent 2完全无法产出chart_candidates，导致图表生成完全依赖Agent 3的兜底机制
- 用户无法获得基于分析的定制化图表推荐
- 对于定性类问题（政策、舆情），前视偏差的概念本身就不适用（新闻/报告发布时间晚于研究时点是正常的）

### 建议修复
1. 将`available_at > research_as_of`从阻断条件改为警告条件（记录但不阻断）
2. 或者设置容忍阈值（如允许N天内、或允许N%的证据有前视偏差）
3. 区分定性证据（title/summary来源于news/report skill）和定量证据，对定性证据豁免前视偏差检查
4. 函数docstring已写明"Missing period/unit are valid for qualitative news, reports and policy evidence"，但代码未实现该豁免逻辑

---

## BUG-002: 计算模块单位不一致导致毛利率计算失败

### 现象
C1案例（宁德时代财务分析）中，Agent 2因`requested_calculation_data_unavailable`进入WAITING_REVIEW，错误信息为：
- "已取得营业收入，但缺少同口径营业成本，毛利率不可计算"（重复出现）
- "营业收入与营业成本单位不一致，未执行自动换算，毛利率不可计算"

### 根因分析

**代码位置**: `backend/app/agents/data_interpreter/calculations.py` 的`calculate_p0_metrics()`函数

**实际数据验证**:
- 证据项中确实有宁德时代的营业收入（2769亿）和营业成本数据
- 但营业收入和营业成本使用了不同的单位（例如营业收入用"元"，营业成本用"万元"或"未提供"）
- 计算模块的`calculate_p0_metrics`在进行毛利率计算时，检测到单位不一致就拒绝计算
- 这触发了`_requested_calculation_gaps`检查（service.py第171-200行），因为用户明确要求了"毛利率"

**触发链路**:
1. 用户input包含"毛利率"关键词 → 触发`_CALCULATION_REQUEST_TERMS`中的`gross_margin`匹配
2. `calculate_p0_metrics`尝试计算毛利率，发现营业收入和营业成本单位不一致
3. 产生`CalculationIssue`，reason="营业收入与营业成本单位不一致，未执行自动换算，毛利率不可计算"
4. `_requested_calculation_gaps`检测到该issue + 用户请求了毛利率 → 阻断Agent 2

### 影响
- 用户明确要求的毛利率分析无法完成
- 即使数据本身是完整的（只是单位不同），也无法自动换算

### 建议修复
1. 在计算模块中增加单位自动换算逻辑（如检测到"元"和"万元"的差异时自动统一）
2. 或者在normalizer中统一单位，确保同一scope的财务数据使用一致单位
3. 将unit="未提供"的条目标记为数据质量问题，但不应阻断整个分析

---

## BUG-003: Agent 3在Agent 2失败时生成与需求无关的兜底图表

### 现象
所有9个案例中，Agent 3都生成了7-8张图表，但这些图表与用户的具体需求关联度很低。例如：

| 案例 | 用户需求 | 实际生成的图表 |
|------|---------|--------------|
| C1 (宁德时代财务) | 营收、归母净利润、毛利率、费用率 | 最新涨跌幅、总资产、存货、研发费用、市盈率、最新价、ROE |
| C3 (CR3/CR5) | 锂电池行业集中度 | 总股本、归母净利润、ROE、估值百分位、涨跌幅、最新价 |
| C6 (动力电池回收政策) | 产业政策梳理 | 市净率、归母净利润增速、市盈率TTM、涨跌幅、动力电池销量 |

### 根因分析

**代码位置**: `backend/app/agents/chart_generator/service.py` 第250-317行 `_backfill_dataset_candidates()` 函数

当Agent 2未产出chart_candidates时（candidates=0），Agent 3的`_backfill_dataset_candidates`会从Agent 1的chart_datasets中自动生成兜底图表候选。该函数：

```python
def _backfill_dataset_candidates(
    candidates: list[ChartCandidate],  # Agent 2传入的0个候选
    datasets: list[ChartDataset],      # Agent 1的30个数据集
    ...
) -> list[ChartCandidate]:
    # 当candidates为空时，直接从datasets生成候选
    for dataset in sorted(datasets, key=lambda item: item.dataset_id):
        if len(result) >= target_dataset_count:  # 默认8张
            break
        if dataset.dataset_id in used_dataset_ids:
            continue
        result.append(_candidate_for_dataset(dataset, _default_chart_type(dataset)))
```

**问题本质**:
- Agent 1的chart_datasets包含了所有获取到的数据，不仅限于用户需求的数据
- 举例：C6用户问的是"动力电池回收政策"，但Agent 1获取的数据包含了动力电池相关公司的财务数据（市净率、市盈率、利润率等），这些与"政策梳理"无关
- 兜底机制会优先选择数据集ID靠前的数据集（按dataset_id排序），而不是按与用户需求的相关性排序

### 影响
- 用户看到无关图表，降低报告质量
- 无法区分"Agent 2分析失败"和"Agent 2成功分析"两种情况

### 建议修复
1. 在兜底生成时，增加与用户focus_questions的相关性过滤
2. 当Agent 2返回0个candidates时，在图表中标注"未经过分析验证，基于原始数据自动生成"
3. 考虑对定性类问题（如政策研究），不生成兜底图表，而是生成"无可验证的定量图表"的提示

---

## BUG-004: Agent 1 query planner无法将专项需求映射到正确skill

### 现象
- **C3 (CR3/CR5)**: 用户要求"锂电池行业CR3、CR5市场占有率"，但Agent 1返回的142条证据中，**0条**包含"市占率"或"市场份额"相关指标。证据主要是公司级财务数据（营业收入、毛利率、最新价等）和新闻摘要。
- **C6 (动力电池回收政策)**: 用户要求"动力电池回收相关产业政策"，但Agent 1返回了动力电池销量、公司财务数据等，没有政策文件内容。

### 根因分析

**代码位置**: `backend/app/agents/data_fetcher/planner.py` 的`QueryPlanner.build()`方法

Agent 1的query planner是确定性规则引擎，它根据`industry_topic`、`focus_questions`、`data_fetch_options.metrics`来生成检索计划。

**C3分析**:
- `industry_topic="锂电池"`, `metrics=["市占率", "市场份额", "装机量"]`
- Planner可能将"锂电池"映射到行业查询(hithink_industry_query)和公司财务查询(hithink_finance_query)
- 但"市占率"/"市场份额"不是标准财务指标，无法通过hithink_finance_query获取
- 需要的是hithink_industry_query获取行业竞争格局数据，但planner没有将"CR3"、"CR5"、"集中度"等关键词映射到正确的查询参数

**C6分析**:
- `industry_topic="动力电池回收"`, `metrics=[]`（无指标，纯定性）
- Planner可能将"动力电池回收"截断为"动力电池"，然后进行常规的行业+财务查询
- 丢失了"回收"和"政策"两个关键维度
- 需要的是news_search和report_search来获取政策文件，但planner没有正确路由

### 影响
- 用户得到的证据与需求不匹配
- 即使Agent 2不被阻断，也无法基于不相关的数据生成有意义的分析

### 建议修复
1. 在planner中增加对"CR3"、"CR5"、"集中度"等关键词的识别，映射到hithink_industry_query的特殊查询参数
2. 对于纯定性问题（metrics=[]），优先使用news_search和report_search
3. 在focus_questions解析中保留完整的语义信息，不要截断或简化

---

## BUG-005: 大量证据项unit字段为"未提供"

### 现象
所有案例中，大量证据项的`unit`字段为"未提供"，例如：
- C1: 宁德时代营业收入 value=276916580000, unit="未提供"
- C1: 归母净利润 value=43284002000, unit="未提供"

### 根因分析

**代码位置**: `backend/app/agents/data_fetcher/normalizer.py` 的`normalize_tasks()`函数

iFinD SkillHub返回的原始数据中，部分字段不包含单位信息。normalizer在清洗数据时，对于无法确定单位的字段，设置为"未提供"而不是尝试推断。

### 影响
- 计算模块无法判断单位是否一致，导致计算失败（如BUG-002）
- 报告中的数值展示不清楚（2769亿还是2769万？）

### 建议修复
1. 在normalizer中增加单位推断逻辑（如根据数值量级和行业常识推断）
2. 对于常见财务指标（营业收入、归母净利润等），设定默认单位（如上市公司财报数据通常以"元"为单位）
3. 从iFinD返回的字段名中提取单位信息（如"营业收入(万元)"）

---

## 总结

| 优先级 | Bug | 建议优先级 |
|--------|-----|-----------|
| **P0** | BUG-001: preflight阻断 | 立即修复，影响8/9案例 |
| **P0** | BUG-002: 单位不一致 | 修复后可使C1的毛利率计算正常进行 |
| **P1** | BUG-004: query planner路由 | 修复后C3/C6等专项需求可获得正确数据 |
| **P1** | BUG-003: 兜底图表无关 | 配合BUG-001修复后自然改善 |
| **P2** | BUG-005: unit缺失 | 长期优化项 |