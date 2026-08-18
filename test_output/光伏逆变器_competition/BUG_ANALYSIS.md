# 光伏逆变器竞争格局测试 — Bug 根因分析

测试时间: 2026-08-17
测试用例: 光伏逆变器行业竞争格局，分析龙头优势与差异化
测试链路: Agent 1(真实iFinD) → Agent 2(Assistant充当大模型) → Agent 3(图表)

---

## 一、现象

| 阶段 | 状态 | 关键数据 |
|------|------|---------|
| Agent 1 | `waiting_review` | 证据=51条，质量合格(passed=True, core_data=True, completeness=1.0) |
| Agent 2 | `waiting_review` | 候选=0，拦截=1 (`DATA-FETCH-NOT-COMPLETED`) |
| Agent 3 | N/A | 被跳过 |

---

## 二、根因链路

```
用户输入: "光伏逆变器行业竞争格局，分析龙头优势与差异化"
  │
  ▼
QueryPlanner → 生成11条需求（requirement_coverage）
  │
  ├─ supported: 9条（行业竞争格局、龙头企业优势、海外政策影响...）
  ├─ missing: 2条
  │   ├─ "国内外厂商市占率对比" → 无skill可提供市占率数据
  │   └─ "指定指标：营业收入" → 指标提取与实际证据不匹配
  │
  ▼
DataFetcherAgent.run() → 质量合格，但 requirement_coverage 有 missing
  │
  ▼
service.py:188-216 → 检测到 unavailable_requirements 非空
  │
  ▼
return StageResult(status=WAITING_REVIEW, error="required_data_unavailable")
  │
  ▼
Agent 2 (DataInterpreterAgent) → 检查前序阶段状态
  │
  ▼
service.py:137-140 → Agent 1 状态 != COMPLETED → 生成拦截
  │
  ▼
return StageResult(status=WAITING_REVIEW, error="data_fetch_not_completed",
                   collaboration_requests=[DATA-FETCH-NOT-COMPLETED])
```

---

## 三、命中的Bug

### BUG-001: 需求覆盖中的 missing 要求导致全链路阻断

**触发代码**: [service.py#L188-L216](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_fetcher/service.py#L188-L216)

```python
unavailable_requirements = [
    item for item in requirement_coverage if item.status in {"partial", "missing"}
]
if unavailable_requirements:
    data["blocking_issues"] = ["required_data_unavailable"]
    return StageResult(status=StageStatus.WAITING_REVIEW, ...)
```

**根因**: 只要存在任意一条 `missing` 需求，整批51条证据全部被拦截。即使质量评估通过（`passed=True`, `core_data=True`, `completeness=1.0`），也不放行。

**具体缺失的需求**:
1. `"国内外厂商市占率对比"` — 市占率/CR指标需要专用skill（STOCK_SELECTOR），当前planner无法路由到合适skill → 这是 BUG-004 的变体
2. `"指定指标：营业收入"` — 虽然FINANCE skill确实返回了营收数据，但planner生成的 requirement 与 evidence 的 metric_name 匹配逻辑有偏差

**影响**: 全链路阻断，Agent 2 和 Agent 3 无法执行。

**修法建议**: 
- 短期：将 `missing` 需求降级为协作请求（collaboration_request），不阻断已获取的数据进入下游
- 长期：将 requirement 的 `missing` 状态按 `priority` 分级：P0缺失→阻断，P1缺失→collaboration_request+继续

---

### BUG-002: Agent 2 对 Agent 1 状态的硬依赖

**触发代码**: [service.py#L137-L148](file:///Users/Zhuanz1/PycharmProjects/同花顺/backend/app/agents/data_interpreter/service.py#L137-L148)

```python
if fetch_result.status not in {StageStatus.COMPLETED, StageStatus.APPROVED}:
    return StageResult(
        status=StageStatus.WAITING_REVIEW,
        error="data_fetch_not_completed",
        collaboration_requests=[{"request_id": "DATA-FETCH-NOT-COMPLETED"}]
    )
```

**根因**: Agent 2 硬性要求 Agent 1 必须是 `COMPLETED` 或 `APPROVED` 状态。即使 Agent 1 有51条证据、质量合格，只要状态是 `WAITING_REVIEW`，Agent 2 就拒绝处理。

**影响**: 与 BUG-001 叠加，形成"双重阻断"——即便 Agent 1 的缺失需求不被视为阻断，Agent 2 的状态检查仍会拦截。

**修法建议**:
- 可将 `WAITING_REVIEW` 状态细分为 `WAITING_REVIEW_PARTIAL`（部分缺失但核心数据可用）和 `WAITING_REVIEW_BLOCKED`（核心数据缺失）
- Agent 2 允许 `WAITING_REVIEW_PARTIAL` 进入分析，但保留 collaboration_request 记录

---

### BUG-index: 市占率数据获取能力缺失（已知 BUG-004 的变体）

Planner 无法将"市占率对比"路由到任何可用的 skill。当前可用的 11 个默认 skill 中没有一个能直接提供市占率/CRn 数据。需要 STOCK_SELECTOR（一期优化后上线）配合 INDUSTRY 的行业总量来反推。

---

## 四、Agent 1 质量评估（正常部分）

即使被阻断，Agent 1 的实际表现良好：

| 指标 | 值 | 说明 |
|------|-----|------|
| 证据数量 | 51条 | 行业+财务+宏观+产业链，覆盖良好 |
| 完整性 | 1.0 | 满分 |
| 有效性 | 1.0 | 满分 |
| 一致性 | 0.96 | 基本一致 |
| 唯一性 | 0.82 | 略有重复 |
| 核心数据可用 | True | 核心数据已获取 |
| 核心skill成功 | hithink_finance_query, hithink_industry_query, hithink_macro_query, industry_chain_analysis | 4个核心skill均成功 |
| 需求覆盖 | 9/11 supported, 2/11 missing | 市占率+营收指标缺失 |

---

## 五、结论

本次测试中，Agent 1 在数据采集层面的表现优秀（51条证据、质量满分、4个核心skill全部成功），但两个设计问题导致全链路被阻断：

1. **需求覆盖的 missing 状态被当作硬阻断**（BUG-001），即使只有 2/11 条缺失
2. **Agent 2 对前序阶段状态的硬性依赖**（BUG-002），不允许部分缺失的数据进入下游

这两个问题的叠加使得"竞争格局分析"这类需要市占率专项数据的场景无法通过现有链路完成。建议优先级：修 BUG-001（降级缺失需求为协作请求）> 修 BUG-002（细分 WAITING_REVIEW 状态）> 上线 STOCK_SELECTOR skill。