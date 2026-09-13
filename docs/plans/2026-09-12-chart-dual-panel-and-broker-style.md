# 图表能力落地规格：视觉增强 + 规则修正 + 表达补齐

日期: 2026-09-12（2026-09-13 扩范围）
状态: 设计
范围: Agent 3 `chart_generator` 表达层 + 路由规则（不改数据治理与证据链）

> **范围变更说明**：本文档由「双图并排 + 券商风」单一视觉议题，**扩展为图表能力落地的统一规格**。
> 原第 1–6 节（视觉增强）内容不变；新增第 7–10 节，纳入此前散落在多轮讨论中、
> **既未进代码也未进任何 spec** 的规则修正与表达层能力。两者的分期关系见第 9 节。

---

## 一、问题

当前 Agent 3 能画多系列折线，但**表达层与券商研报脱节**：

| 能力 | 现状 | 券商研报要求 |
|------|------|--------------|
| 多系列折线 | 有，`build_line_option` 按 `series` 分组 | 同左 |
| 数据点样式 | 默认圆点 `showSymbol:True` | 密点时序**无点**；对比图用**方点** `rect` |
| 线宽 | ECharts 默认 ~2px | 密点细线 1.2–1.6px |
| 网格线 | 默认显示 | 券商风 `splitLine: false` |
| 左右双图并排 | 无，只有单 grid | 「左：绝对量，右：相对率」是标配 |
| 主题 | `research_blue` / `colorblind_safe` | 缺 `broker_thin` 券商风 |

数据模型已能支撑「四条线 × 12 个月」，缺口在**视觉参数与布局**。

**此外，本轮核查确认还有三类缺口未落地**（见第 7、8 节）：路由规则缺陷 3 条、数量阈值不一致、表达层能力 7 项。

---

## 二、设计

### 2.1 券商风主题 `broker_thin`

在 `builders.py::THEMES` 增加第三套主题，并配套样式预设：

```python
THEMES["broker_thin"] = ["#1F3A5F", "#5B8FB9", "#9BB8D3", "#8B6914", "#6B7280"]

LINE_STYLES = {
    "research_blue": {"showSymbol": True,  "symbol": "circle", "width": 2.0},
    "colorblind_safe": {"showSymbol": True, "symbol": "circle", "width": 2.0},
    "broker_thin":   {"showSymbol": False, "symbol": "rect",   "width": 1.5},
}
```

`broker_thin` 额外覆盖 `_base_option`：

| 字段 | 值 |
|------|-----|
| `grid.splitLine` | 不输出（或 `{show: False}`） |
| `yAxis.splitLine` | `{show: False}` |
| `xAxis.axisLine` | `{show: True, lineStyle: {color: "#333"}}` |
| `legend.itemWidth` | 18（细线图例） |
| `title.textStyle.fontFamily` | `"Times New Roman","SimSun",serif` |

### 2.2 密点时序 vs 对比折线

同一 `line` 类型，按主题自动分档：

| 场景 | 主题建议 | symbol | smooth |
|------|----------|--------|--------|
| 月度/季度多期趋势（≥6 点） | `broker_thin` | 无 | false |
| 年度少量点（≤5 点） | `research_blue` | circle | false |
| 用户显式要求方块标记 | 任意 + `symbol_override=rect` | rect | false |

**不引入 `smooth: true`**。券商研报时序图几乎全是直线连接；平滑曲线属于产品仪表盘风格，与研报体例冲突。

### 2.3 双图并排 `dual_panel`

#### 2.3.1 何时使用

当同一分析问题同时需要「绝对量」和「相对率/价格」时，且两者**量纲不同、不可叠在同一 Y 轴**。

典型触发：
- 销量（万辆） + 均价（万元） / 增速（%）
- 产量（万吨） + 价格指数
- 用户量（万） + ARPU（元）

**不适用**：同量纲双序列（用单图多系列或 combo）；仅一个指标（用单 line）。

#### 2.3.2 契约扩展

`ChartDataset` 已有 `points[].series`。双图用**两个逻辑子集**，通过新字段标注：

```python
# schemas/chart.py — ChartSpec 增加
class PanelSpec(BaseModel):
    position: Literal["left", "right"]
    title: str | None = None          # 子图题，默认用主标题
    y_axis_name: str | None = None
    series_names: list[str]           # 引用 dataset.points[].series

class ChartSpec(...):
    layout: Literal["single", "dual_panel"] = "single"
    panels: list[PanelSpec] = Field(default_factory=list, max_length=2)
```

校验（`model_validator`）：
- `layout == "dual_panel"` 时 `len(panels) == 2`，且 position 必须为 left+right
- 两 panel 的 `series_names` 不得重叠，且并集 ⊆ dataset 中实际存在的 series
- 每个 panel 至少 1 条 series

#### 2.3.3 Builder

新增 `build_dual_panel_line_option(title, dataset, panels, theme)`：

ECharts 侧用**双 grid + 双 xAxis + 双 yAxis**（不是 grid 数组叠在同一坐标系）：

```python
{
  "grid": [
    {"left": 56, "right": "52%", "top": 56, "bottom": 40},
    {"left": "54%", "right": 24, "top": 56, "bottom": 40},
  ],
  "xAxis": [
    {"type": "category", "gridIndex": 0, "data": labels},
    {"type": "category", "gridIndex": 1, "data": labels},
  ],
  "yAxis": [
    {"type": "value", "gridIndex": 0, "name": left_unit},
    {"type": "value", "gridIndex": 1, "name": right_unit},
  ],
  "series": [
    # left series: xAxisIndex=0, yAxisIndex=0
    # right series: xAxisIndex=1, yAxisIndex=1
  ],
}
```

两个 panel **共享时间轴标签**（同一 `period_end` 集合），子图题分别放 `title[0]/title[1]` 或 graphic text。

#### 2.3.4 路由

`router.py` 增加分支：

```
requested_type == "line"
  且 dataset 含两个语义组（绝对量 / 相对率）
  且 series 数 ≥ 2
  且 panels 元数据齐全
→ variant = "dual_panel_line"
否则 → variant = "line"（现状）
```

`ChartVariant` 增加 `"dual_panel_line"`。

判定「绝对量 / 相对率」的确定性信号（按优先级）：
1. 候选/数据集显式 `panel_role: absolute | rate`（A2 透传，首选）
2. 单位启发式：`%` / `pp` / 无量纲指数 → rate；其余 → absolute
3. 启发式失败 → 不启用 dual_panel，回退单图多系列

---

## 三、实现改动清单

| # | 文件 | 改动 |
|---|------|------|
| 1 | `builders.py` | `THEMES` + `broker_thin`；`LINE_STYLES`；`_base_option` 按主题关网格 |
| 2 | `builders.py` | `build_line_option` 应用主题 symbol/width |
| 3 | `builders.py` | 新增 `build_dual_panel_line_option` |
| 4 | `schemas/chart.py` | `PanelSpec`；`ChartSpec.layout/panels`；`ChartVariant` + `dual_panel_line` |
| 5 | `router.py` | line 分支支持 dual_panel 路由 |
| 6 | `service.py` | `_build_option` 分发 dual_panel |
| 7 | tests | 主题切换、双 panel 布局、series 隔离、回退单图 |

---

## 四、验收

1. `theme=broker_thin` 时，line 图 `showSymbol=false`、`splitLine` 不可见、线宽 1.5
2. 同一 `ChartDataset`（4 series × 12 月，左销量右增速）产出双 grid，左右 series 互不交叉
3. 缺 panels 元数据时自动回退 `line`，不抛错
4. 证据链不变：每个 point 仍有 `evidence_id`，`evidenceMap` 覆盖双 panel 全部点
5. 现有 `tests/agents/chart_generator` 全绿

---

## 五、不在范围内

- 平滑曲线（`smooth: true`）
- 数据层新增字段（销量/价格拆成两个 dataset）
- 前端渲染库替换（仍用 ECharts option JSON）
- 导出 PDF 的 CSS 双栏排版（属 Agent 5，另案）

---

## 六、与既有方案的关系

- 对齐 `REPORT_VISUAL_DESIGN.md`：双 panel 仍绑定单一 `placement_section_id`，算 **1 张图**
- 对齐图表精简方案：不新增 ChartType，只增 `variant` 与 theme
- 对齐专业度方案：补齐「无网格细线」这一券商风缺口

---

## 七、规则修正（3 条已核实缺陷 + 1 条阈值统一）

> 核查日期 2026-09-13，分支 `agent/chart-mvp-sync`。以下每条均已定位到**具体行号**。

### 7.1 combo 量纲硬限制 —— `router.py:207`

**现状**：

```python
# router.py::route_chart 的 combo 分支
if (... or len(units) != 2 or ...):
    return ChartRouteDecision(accepted=False, reason_code="combo_requirements_not_met", ...)
```

`len(units) != 2` 要求两个序列**量纲必须不同**。后果：最常见的组合「营业收入（柱）+ 归母净利润（线）」因**两者都是"亿元"**被拒 → 降级为单线图（实测 `report_view.json` 中 4 次以上"combo 条件不满足，已确定性降级为 line"）。

**修正**：把量纲从「硬条件」改为「分支条件」。

```
len(units) == 2  → 双轴柱线组合（现状，必须标注两个轴的单位）
len(units) == 1  → 单轴柱线组合（新增；共用左轴，柱=绝对量、线=第二序列）
len(units) == 0  → 拒绝（单位不可知，风险太大）
```

**保留**：`business_linked`（业务相关性）与「时间轴一致且完整」两项校验 —— 这是"双轴陷阱"的正当防线，不放宽。

**依据**：Domo 组合图指南「单轴适用于量纲相近时」；`data-visualization-2` 亦以单轴柱线为常规形态。

**验收**：给「宁德时代近四年营业收入 + 归母净利润」的输入，产出 `chart_type=combo`、`variant=combo`、单 `yAxis`，且不再降级为 line。

---

### 7.2 单位占位符泄漏到坐标轴 —— `datasets.py:189` → `builders.py::_axis_name`

**现状（完整链路已确认）**：

1. `datasets.py:189`：`unit=dataset.unit or "未提供"` —— 单位缺失时填入字符串 `"未提供"`
2. `builders.py::_axis_name`：`" ".join(item for item in (dataset.currency, dataset.unit) if item)` —— 把 currency 与 unit 直接拼接
3. 结果：轴名变成 **`"CNY 未提供"`**，实测 **26/87（30%）** 的图表都这样

**问题性质**：**做法对、位置错**。系统确实标注了缺失（符合"不伪造"原则），但把这个内部提示写进了**面向读者的坐标轴标签**，让图变成一句故障信息。

**修正**：

| 动作 | 说明 |
|---|---|
| 占位符规范化 | `"未提供"` → **`[需核实:货币单位]`**（与技能方案的占位符语法统一） |
| **禁止进轴名** | `_axis_name` 过滤掉括号占位符：仅在有真实 unit 时拼接；否则轴名只保留 currency 或留空 |
| 缺失信息下沉到图注 | 缺失事实写进 `footnotes`/数据说明（面向读者的一句话），如「本图货币单位未知，已在数据说明中标注」 |
| 质检兜底 | 新增硬规则 `unit_missing_or_placeholder`：轴名含"未提供"或为空 → 阻断 |

**验收**：对缺 `unit` 的 dataset，轴名不再出现"未提供"字样；`footnotes` 含占位符提示；26/87 的历史缺陷归零。

---

### 7.3 去重只告警不抑制 —— `service.py:784-786`

**现状**：

```python
# service.py:752 / 784-786
is_duplicate = dedupe_key in seen_dedupe_keys
...
if is_duplicate:
    # 图表仍然生成，不抑制；仅通过 risk_notices 标记
    pass
```

**注意**：这里有一处**设计意图的遗留注释**——「不再因预算/重复/章节密度而 `continue`，只记录风险提示」。即抑制逻辑被**整体关闭**过，`is_duplicate` 沦为纯标记。

**根因分析（关键）**：抑制被关闭**很可能是被迫的**。因为去重键含**自由文本**：

```python
# router.py::build_dedupe_key
return f"{family}:{purpose}:{normalized_goal}:{data_fingerprint}"
```

其中 `insight_goal` 由 LLM 生成，措辞一变（"展示趋势" vs "展示变化"）即产生不同 key → **误判为不重复**。实测 `run-real-full-chain/r1` 单份报告出现「营收与归母净利润**趋势**」×4 +「**变化**」×2 = **6 张同类图**；该 run 生成 20 张候选、最终只采用 3 张（**85% 被丢弃**）。

**修正（两步，顺序不可颠倒）**：

1. **先去自由文本**：`build_dedupe_key` 的 `insight_goal` 参数改为**归一化语义槽位**（如 `trend` / `composition` / `comparison` / `ranking` 枚举），或对 goal 做同义归并后再入键。
2. **再恢复抑制**：key 可靠后，对**完全重复**（key 相同）恢复 `suppressed` + `continue`；对**同 family 相似**（family 相同但 key 不同）维持告警。

**为何不能只做第 2 步**：在 key 不可靠时恢复抑制，会误杀本应保留的图；只做第 1 步不做第 2 步，则重复图照旧产出。**必须两步一起做**。

**验收**：同一报告内，同一 `family` + 同一 `data_fingerprint` + 同一语义槽位的图，最多 1 张；`run-real-full-chain/r1` 的 20 张候选收敛后，重复组消失。

---

### 7.4 数量阈值统一（现状有 5 个数字 + 1 处重复定义）

**核查结果**：

| # | 位置 | 当前值 | 问题 |
|:---:|---|---|---|
| 1 | `chart_generator/service.py:84` | `RECOMMENDED_CHARTS_PER_REPORT = (5, 8)` | 推荐 5–8 张 |
| 2 | `chart_generator/planner.py:18` | `RECOMMENDED_CHARTS = (5, 8)` | ⚠️ **与 #1 重复定义** |
| 3 | `report_fusion/quality.py:97` | 「超过推荐上限 **8** 张（技术上限 30 张）」 | 硬编码 8，未引用常量 |
| 4 | `report_fusion/visual.py:108` | `<=4 low / <=10 medium / >10 high` | 与 #1 的 5–8 **不一致** |
| 5 | `chart_generator/service.py:91` | `HARD_LIMIT_MAX_CANDIDATES = 30` | 技术硬上限 |
| 6 | 精简方案文档 | 「每份报告 10–15 张」 | 与 #1、#4 均不一致 |

**问题**：同一个"报告该有几张图"的问题，有 **5 个不同的数字**，其中 `(5, 8)` 还在两处重复定义。任一处改动都可能与其他处矛盾。

**修正**：

1. **单一来源**：常量收敛到一处（建议 `chart_generator/constants.py`），其余模块 import 引用；**删除 `planner.py:18` 的重复定义**。
2. **口径对齐**（以 `(5, 8)` 为推荐基准，`visual.py` 的密度档向它对齐）：

| 档次 | 张数 | 用途 |
|---|---|---|
| **推荐区间** | **5–8** | 常规深度报告的目标区间 |
| 下限告警 | < 5 | 提示"图表偏少，可能纯文字化" |
| 上限告警 | > 8 | `chart_count_over_recommended` |
| 密度分档 | ≤4 low / 5–8 medium / 9–10 high- / >10 high | 与推荐区间对齐 |
| 技术硬上限 | 30（候选）/ 10（单章） | 不变 |

3. **方案文档口径同步**：精简方案里的「10–15 张」与 `(5, 8)` 冲突，**以 `(5, 8)` 为准**并修订该方案（10–15 是含表格与附录的宽口径，需改为"核心图表 5–8 张，含表格附录不超过 15"）。

**验收**：全仓仅一处定义推荐区间；`visual.py` 的 medium 档与推荐区间一致；无硬编码 `8`。

---

## 八、表达层能力补齐（7 项）

> 这 7 项在多轮讨论中出现过，但**既未进代码也未进任何 spec**。本节将其固定下来。

| # | 能力 | 归属 | 实现要点 | 优先级 |
|:---:|---|---|---|:---:|
| 8.1 | **标题结论化** | **A2 生成 + A3 校验**（原归属未定，现定案） | A2 出结论式 title；A3 用确定性规则校验：标题不含「数值 / 比较词（增长·下降·领先·落后·高于·低于）/ 结论词」→ 判 `title_not_conclusive`（软），并降级为中性描述 | P1 |
| 8.2 | **图表编号（已有，需调格式）+ 图表目录（缺）** | A5（报告渲染） | ⚠️ **现状修正**：编号**已实现**于 `reporting/html.py:76-83`，格式 `图3-1`（章-序，章内递增）、未归属图用 `附图-N`。**缺**的是「图表目录」章节。修订：① 增加**全文连续编号**选项（`图1/图2…`，对齐券商研报）② 新增「图表目录」章节 | **P0**（目录）／P1（格式） |
| 8.8 | **图表资料来源具名标注**（本节新增） | A5（模板 + 数据） | 现状模板**已有**「数据来源：」位，但渲染的是**引用编号**（`[1][2]` 跳转到来源表），**非研报式具名来源**。需改为「**资料来源：<具名来源>**」（如「Wind，国信证券经济研究所整理」）。来源名从 `evidence_catalog` 的 `publishers` / `source_name` 推导；无来源时按占位符规范标 `[需核实:数据来源]` | **P0** |
| 8.3 | **数值标签开关** | A3（builder） | 点数 ≤12 时默认 `label.show=true`；>12 时关闭（避免糊成一团）；可由候选显式覆盖 | P1 |
| 8.4 | **截断轴提示** | A3（builder） | 当 `yAxis.scale=true`（不从 0）时，自动注入 footnotes：「纵轴未从 0 开始，用于放大变化幅度」 | P1 |
| 8.5 | **红涨绿跌语义配色** | A3（主题层） | 新增语义色 `UP=#C0392B` / `DOWN=#1E8449`；仅用于**涨跌语义明确**的序列（涨跌幅、同比），其余序列仍用常规色板 | P2 |
| 8.6 | **combo 单轴同量纲分支** | A3（router+builder） | 与 7.1 **为同一改动**，此处不重复；7.1 已含 | P0 |
| 8.7 | **`series_meta` 放开 max=2** | `schemas/chart.py` | 由 `max_length=2` 放开到 **4**（配合 combo 多序列与 future 扩展）；同步校验逻辑与测试 | P2 |

**8.1 归属定案理由**：A2 是 LLM 层（有能力生成结论式标题），A3 是确定性层（有能力做规则校验）。若把生成也放 A3，确定性层无法凭空产生结论；若把校验放 A2，则 LLM 自评不可靠。**生成在校验之前、分属两层**，是唯一自洽的划分。

**8.7 注意**：`series_meta` 放开需同步检查 `router.py` 的 combo 校验（当前依赖 `len(series_meta) != 2`）—— 该判断在 7.1 修正后应改为「按实际 series 分组数校验」，避免放开后逻辑失配。

### 8.9 参照图形态核对（2026-09-13）

以两张真实参照图为准做的逐特征核对（驱动了 8.2 / 8.8 的修订）：

| 特征 | 参照图 A（4 线双图并排） | 参照图 B（券商研报：图3 油价 / 图4 CCPI） | 本方案覆盖 |
|---|:---:|:---:|---|
| 双图并排 | ✅ | ✅ | 第 2.3 节 `dual_panel`（**P2**） |
| **图表编号** | ❌ | ✅「图3：」「图4：」 | 8.2 —— **编号已实现**（`图3-1`），仅缺「图表目录」（**P0**） |
| **资料来源** | ❌ | ✅「资料来源：Wind，国信证券经济研究所整理」 | 8.8（**P0**，本次新增） |
| 无网格 + 细线 | ❌ 有网格 / 圆点 / 粗线 | ✅ 无网格 / 细线 / 无点 | 第 2.1 节 `broker_thin`（**P2**） |
| 标题含指标 + 单位 | ❌ 无标题 | ✅「油价走势（美元/桶）」 | 8.1（P1） |
| 图例（右上 + 线型示意） | ❌ 无图例 | ✅ | **未覆盖** → 并入 8.8 处理 |

**核对结论**：

1. **参照图 A** = `dual_panel` 的**布局** + 通用商业**风格**（有网格/圆点/粗线）。布局已规划（P2）；风格与项目现状一致，**无需改造**。
2. **参照图 B** = **券商研报标准形态**。其中「图表编号」**已实现**（此前方案描述有误，本次修正）；真正缺失的是：
   - **「图表目录」** → 提至 **P0**
   - **「资料来源」具名标注** → 新增 8.8，提至 **P0**（券商研报每张图必须标来源，属合规要件）
   - 图例样式（右上 + 线型示意）→ 并入 8.8 一并处理

---

## 九、统一实现清单与分期

### 9.1 分期

| 期 | 内容 | 理由 |
|:---:|---|---|
| **P0 · 规则修正 + 交付要件** | 7.1 combo 量纲 · 7.2 单位泄漏 · 7.3 去重键+抑制 · 7.4 阈值统一 · **8.8 资料来源具名标注** · **8.2 的图表目录部分** | 规则层改动小收益直接；**资料来源与图表目录属"能否交付"要件**——券商研报每张图必须标来源，属合规要求而非装饰；且 7.3 的 key 修正**是 8.x 表达层的前置** |
| **P1 · 表达补齐** | 8.1 标题结论化 · 8.2 编号格式调整 · 8.3 标签开关 · 8.4 截断轴提示 | 提升单图信息传递效率，不新增图表类型 |
| **P2 · 视觉增强** | 第 2 节全部（broker_thin / dual_panel / 方块标记） · 8.5 语义配色 · 8.7 series_meta 放开 | 视觉与扩展性，依赖 P0/P1 稳定后再动 |

**依赖关系**：7.3（去重键）→ 8.2（编号，需先保证不重复）→ 8.1（标题，需先保证不重复）

### 9.2 改动清单（含第 7、8 节）

| # | 文件 | 改动 | 期 |
|:---:|---|---|:---:|
| 1 | `builders.py` | `THEMES` + `broker_thin`；`LINE_STYLES`；`_base_option` 按主题关网格 | P2 |
| 2 | `builders.py` | `build_line_option` 应用主题 symbol/width | P2 |
| 3 | `builders.py` | 新增 `build_dual_panel_line_option` | P2 |
| 4 | `schemas/chart.py` | `PanelSpec`；`ChartSpec.layout/panels`；`ChartVariant` + `dual_panel_line` | P2 |
| 5 | `router.py` | line 分支支持 dual_panel 路由 | P2 |
| 6 | `service.py` | `_build_option` 分发 dual_panel | P2 |
| **7** | **`router.py:207`** | **combo 量纲改分支（单轴/双轴）** | **P0** |
| **8** | **`datasets.py:189` + `builders.py::_axis_name`** | **占位符规范化 + 禁止进轴名** | **P0** |
| **9** | **`router.py::build_dedupe_key`** | **`insight_goal` 改归一化语义槽位** | **P0** |
| **10** | **`service.py:784-786`** | **恢复重复抑制（key 修正后）** | **P0** |
| **11** | **`chart_generator/constants.py`（新增）** | **数量阈值单一来源；删 `planner.py:18` 重复定义** | **P0** |
| **12** | **`builders.py`** | **点数 ≤12 自动加 `label`** | **P1** |
| **13** | **`builders.py`** | **`scale=true` 时自动注入截断轴 footnotes** | **P1** |
| **14** | ~~`schemas/chart.py`~~ → **`reporting/html.py:76-83`（已有，需扩展）** | **编号已实现（`图3-1` 格式）；增加"全文连续编号"选项** | **P1** |
| **15** | **`reporting/html.py` + `report.html.j2`** | **新增「图表目录」章节（编号 + 标题 + 页码）** | **P0** |
| **15b** | **`report.html.j2` + `evidence_catalog` 取数** | **「数据来源」改为研报式「资料来源：<具名来源>」；无来源按占位符规范标注** | **P0** |
| **16** | **A2 侧 + `quality.py`** | **结论式标题生成 + `title_not_conclusive` 校验** | **P1** |
| **17** | **`builders.py` 主题层** | **红涨绿跌语义色** | **P2** |
| **18** | **`schemas/chart.py`** | **`series_meta` max 2 → 4** | **P2** |
| 19 | tests | 上述全部改动的单测 | 随期 |

### 9.3 与既有方案文档的口径冲突（需同步修订）

| 冲突 | 现状 | 处理 |
|---|---|---|
| 数量口径 | 精简方案写「10–15 张」；代码为 `(5, 8)` | **以 `(5, 8)` 为准**，精简方案改为「核心图表 5–8 张，含表格附录 ≤15」 |
| 颜色上限 | 外部规范有「≤5 / ≤6 / 5–7」三种 | **取 5**（最严，且现状 87/87 已是 5 色） |
| combo 双轴 | 外部规范建议「双轴 → 拆成两张图」 | **有条件保留**：默认拆图，显式声明才组合（与 7.1 的分支逻辑一致） |

---

## 十、验收总表

> 覆盖第 2 节（视觉）与第 7、8 节（规则与表达）的全部改动。

| 期 | 验收项 | 判据 |
|:---:|---|---|
| **P0** | combo 同量纲可出图 | 输入「营收 + 归母净利润」→ `chart_type=combo`、单 `yAxis`，不降级 |
| **P0** | 轴名无占位符泄漏 | 缺 `unit` 的 dataset，`yAxis.name` 不含"未提供"；`footnotes` 含占位符 |
| **P0** | 去重生效 | 同报告内同 family + 同数据指纹 + 同语义槽位 → 最多 1 张；`run-real-full-chain/r1` 的 6 张同类图归 1 |
| **P0** | 阈值单一来源 | 全仓仅一处 `RECOMMENDED_CHARTS`；`visual.py` medium 档与之一致；无硬编码 `8` |
| **P1** | 标题结论化 | 标题不含数值/比较词时产出 `title_not_conclusive` 并降级为中性描述 |
| **P0** | 图表目录 | 报告含「图表目录」章节，列出全部图表编号 + 标题 |
| **P0** | 资料来源具名 | 每张图下方为「资料来源：<具名来源>」（如「Wind」），而非引用编号；无来源时标 `[需核实:数据来源]` |
| **P1** | 编号格式 | 支持全文连续编号「图 1/图 2…」；保留现有 `图3-1` 章序制作为可选项 |
| **P1** | 标签开关 | 点数 ≤12 的图有 `label.show=true`；>12 的图无 |
| **P1** | 截断轴提示 | 任何 `scale=true` 的图，`footnotes` 含「纵轴未从 0 开始」 |
| **P2** | 主题生效 | `theme=broker_thin` 时 `showSymbol=false`、`splitLine` 不可见、线宽 1.5 |
| **P2** | 双 panel | 4 series × 12 月（左销量右增速）→ 双 grid，左右互不交叉 |
| **P2** | 回退健壮 | 缺 panels 元数据时回退 `line`，不抛错 |
| **P2** | 语义配色 | 涨跌序列用红涨绿跌；非涨跌序列不受影响 |
| 全程 | 证据链不变 | 每个 point 仍有 `evidence_id`，`evidenceMap` 覆盖全部点 |
| 全程 | 回归 | `tests/agents/chart_generator` 全绿 |

---

## 十一、不在范围内

- 平滑曲线（`smooth: true`）—— 与研报体例冲突
- 数据层新增字段（销量/价格拆成两个 dataset）
- 前端渲染库替换（仍用 ECharts option JSON）
- 导出 PDF 的 CSS 双栏排版（属 Agent 5，另案）
- **任何实际代码改动** —— 本文档为设计规格，落地需另行评审

---

## 十二、修订记录

| 日期 | 修订 |
|---|---|
| 2026-09-12 | 初版：双图并排 + 券商风密点时序 |
| 2026-09-13 | **扩范围为图表能力落地规格**：新增第 7 节（3 条已核实代码缺陷 + 阈值统一，含具体行号）、第 8 节（7 项表达层能力，含标题结论化归属定案）、第 9 节（分期与统一清单）、第 10 节（验收总表）、第 11 节（范围外） |
