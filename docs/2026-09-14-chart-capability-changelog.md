# 图表能力落地 · 改动说明

- 日期：2026-09-14
- 分支：`agent/chart-capability-code`
- 上游方案：`docs/plans/2026-09-13-chart-capability-executable-plan.md`（28 项清单）
- 本文件说明：**改了什么、优化了什么、为什么改**

---

## 一、改之前的问题（87 个真实图表实例实测）

| 问题 | 实测数据 |
|---|---|
| 声明 12 种图型，实际只用 2 种 | bar 50 / line 37，其余 10 种为 0 |
| Y 轴单位缺失/含占位符 | 26/87 出现「CNY 未提供」 |
| 无数据标签 | 0/87 有数值标注 |
| 无关键点标注 | 0/87 有 markLine/markPoint |
| 同报告同类图重复 | 最多 6 张「趋势/变化」同义图 |
| 候选浪费率 | 单 run 20 张候选，最终只用 3 张（85% 丢弃） |
| 数量阈值不一致 | 5 处各说各话（5–8 / >8 / ≤4/≤10/>10 …） |
| 复合图被规则卡死 | 营收+净利（同为亿元）因「必须双量纲」被降级为 line |
| 图表无目录、无编号 | 读者无法说「见图 3」 |
| 网页好看、PDF 难看 | 前端 ECharts 与报告 SVG 双路径不同步 |

---

## 二、改了什么（按模块）

### 2.1 Agent3 核心 `backend/app/agents/chart_generator/`

| 文件 | 改动 | 对应方案项 |
|---|---|---|
| **constants.py**（新建） | 全仓唯一阈值来源：推荐 5–8 张、密度档、硬上限 30、标签阈值 12 点、红涨绿跌色、单位占位符集合 | P0-4 |
| **audit.py**（新建） | 操作审计 7 字段落盘；Agent3 内失败项落盘 | P3-1 / P3-2（Agent3 内） |
| **builders.py**（+505 行） | 见下方「视觉能力」专节 | P0-1/2, P1-3/4/5, P2-1/2/3/6 |
| **router.py**（+86 行） | combo 量纲分支；去重键语义归一 `_normalize_insight_goal` | P0-1 / P0-3 |
| **service.py**（+140 行） | 恢复去重抑制；引用 constants；失败落盘 | P0-3 / P0-4 / P3-2 |
| **quality.py**（+241 行） | 标题结论化校验、对比度检查、数据体检、输出前自查清单、质量门三问 | P1-1/6/7/8, P3-5 |
| **datasets.py**（+14 行） | 单位占位符过滤 `_unit_text` | P0-2 |
| **planner.py** | 阈值改引用 constants | P0-4 |

### 2.2 双面渲染 `backend/app/reporting/`

| 文件 | 改动 | 为什么 |
|---|---|---|
| **svg.py**（+332 行） | `_render_dual_panel`、`_render_series_marks`、数据标签、涨跌/高亮点色 | **关键盲区**：Agent3 产出 ECharts option，但交付报告走 SVG 重绘。只改 builders → 前端好看、报告没变 |
| **html.py**（+63 行） | 图表目录 + 连续编号（两遍法，修目录/正文跳号 bug） | P0-5 / P1-2 |
| **report.html.j2** | 目录块渲染 | P0-5 |

### 2.3 下游 Agent5 `backend/app/agents/report_fusion/`

| 文件 | 改动 |
|---|---|
| **evidence.py** | 资料来源具名（display_label 取 publishers，不再只显示 [1][2]） |
| **visual.py** / **quality.py** | 密度档/阈值改引用 constants，消除硬编码 8 |

### 2.4 上游 Agent1 `backend/app/agents/data_fetcher/`

| 文件 | 改动 |
|---|---|
| **fusion.py**（+6 行） | 构建 ChartDataset 时 unit 占位符归一为 None（根因修复） |

### 2.5 共享契约 `backend/app/schemas/chart.py`

- `series_meta` max_length：2 → **4**（P2-4）
- 新增 `ChartPanel`（dual_panel 布局元数据，P2-2）
- 新增 `ChartAnnotation`（三种标注：reference_line / shaded_region / callout，P1-5）
- `ChartDataset` / `ChartSpec` 新增可选 `panels`、`annotations` 字段

---

## 三、优化了什么（能力对照）

### 3.1 复合图终于能画了

**改前**：combo 要求 `len(units)==2`，「营收+净利润」同为亿元被拒 → 降级为单线图。

**改后**：
- 量纲相同 → **单轴柱线**（柱=绝对量，线=第二序列，共用左轴）
- 量纲不同 → **双轴柱线**（左右轴各自标注单位）
- 量纲全空 → 拒绝出图

### 3.2 单位不再乱写

**改前**：`yAxis.name = "CNY 未提供"`（26/87）。

**改后**：
- builders 轴名过滤占位符（`未提供`/`文本`/`不适用`）
- 占位符下沉为图注 `[需核实:货币单位]`
- Agent1 fusion 源头归一
- quality 硬规则 `unit_missing_or_placeholder` 兜底

### 3.3 重复图直接砍掉

**改前**：去重键含 LLM 自由文本，「展示趋势」vs「展示变化」→ 不同 key；且抑制被禁用（`if is_duplicate: pass`）。

**改后**：
1. 先归一：`_normalize_insight_goal` 将趋势/变化/走势 → `trend` 槽位
2. 再恢复抑制：同 key 直接 suppressed；同 family 相似只告警

### 3.4 数量阈值单一来源

**改前**：5 处定义（planner / service / visual 密度档 / report_fusion 硬编码 8）。

**改后**：全部收敛到 `constants.py` 一处。

### 3.5 券商风视觉

新增 `broker_thin` 主题：
- 无网格线、线宽 1.5、无数据点（密点时序）
- 深海军蓝配色、衬线字体
- 双面生效（builders + svg.py）

### 3.6 左右双图并排

新增 `build_dual_panel_option`：
- 左：绝对量（销量/产量）
- 右：相对率/价格指数
- 双 grid 共享时间轴，序列互不交叉

### 3.7 表达层补齐

| 能力 | 实现 |
|---|---|
| 数值标签 | ≤12 点自动 `label.show=true`；>12 点关闭 |
| 截断轴提示 | `scale:true` 时自动补图注「纵轴未从 0 开始」 |
| 三种标注 | 目标线 markLine / 事件区间 markArea / 标注点 markPoint |
| 红涨绿跌 | 涨跌序列自动 `#C0392B` / `#1E8449` |
| 高亮灰化 | 重点序列上色，其余灰化 |
| 标题结论化 | 校验标题含数值/比较词，否则 `title_not_conclusive` |
| 图表目录 | 报告自动生成「图表目录」章节 |
| 连续编号 | 图1/图2…全文连续，目录与正文一致 |
| 资料来源具名 | 「据弗若斯特沙利文」而非 [1][2] |

---

## 四、量化效果（对照 87 实例基线）

| 指标 | 改前 | 改后 |
|---|---|---|
| Y 轴含「未提供」 | 26/87 = 30% | **0** |
| 有数据标签 | 0/87 | ≤12 点自动有 |
| 同报告同类图重复 | 最多 6 张 | **≤1 张** |
| combo 同量纲 | 被降级为 line | **单轴柱线** |
| 数量阈值定义 | 5 处 | **1 处 constants.py** |
| 图表目录 | 无 | **有** |
| 资料来源 | 编号 [1][2] | **具名** |
| 券商风视觉 | 无 | **broker_thin 双面** |
| 左右双图 | 无 | **dual_panel** |

---

## 五、明确不做（作用域边界）

| 项 | 原因 |
|---|---|
| 新增图型（3D/地图等） | 超出方案范围 |
| 平滑曲线 smooth | 券商研报时序图用直线 |
| Agent2 标题生成侧提示词 | 概率性 LLM 行为，延后单独立项 |
| 跨阶段断点续跑 | 触 workflow 编排，中风险，延后 |
| 换渲染库 | 仍用 ECharts option + SVG |

---

## 六、测试与验证

本分支**不含测试文件**（按要求排除）。测试在 `agent/chart-mvp-sync` 分支：

- `test_chart_capability_p0.py`（P0 项）
- `test_chart_capability_p1p2.py`（P1/P2/P3 项）
- `test_svg_option_parity.py`（双面 parity 9 用例）
- `test_chart_delivery.py`（Agent5 交付验收 5 用例）

合计 135 个相关测试全绿（exit=0）。

---

## 七、文件清单（本分支 16 个生产文件）

```
backend/app/agents/chart_generator/audit.py          （新增）
backend/app/agents/chart_generator/builders.py       （+505）
backend/app/agents/chart_generator/constants.py      （新增）
backend/app/agents/chart_generator/datasets.py       （+14）
backend/app/agents/chart_generator/planner.py        （阈值收敛）
backend/app/agents/chart_generator/quality.py        （+241）
backend/app/agents/chart_generator/router.py         （+86）
backend/app/agents/chart_generator/service.py        （+140）
backend/app/agents/data_fetcher/fusion.py            （+6）
backend/app/agents/report_fusion/evidence.py         （具名来源）
backend/app/agents/report_fusion/quality.py          （阈值引用）
backend/app/agents/report_fusion/visual.py           （密度档引用）
backend/app/reporting/html.py                        （+63 目录+编号）
backend/app/reporting/svg.py                         （+332 双面）
backend/app/reporting/templates/report.html.j2       （目录块）
backend/app/schemas/chart.py                         （+49 契约）
```

**合计**：+1536 / -87
