# 图表能力边界与选型规范（P2-7 / P3-4 / P3-6 / P3-7）

- 日期：2026-09-13
- 配套：`docs/plans/2026-09-13-chart-capability-executable-plan.md`（28 项可执行改造）
- 本文档落地方案中 4 个"文档/抽查"类项，**零代码改动**，是 Agent3 选型与质检的规范基线。
- 证据基准：`backend/app/agents/chart_generator/router.py:10-38`（CHART_FAMILY 12 类型→7 家族、TYPE_PREFERENCE）。

---

## P3-4 能力边界表（能做什么 / 明确不做什么）

### 能做（12 种 ChartType，归 7 大家族，与 router.py:10-23 一致）

| 家族 | ChartType | 适用数据结构 | 路由偏好(TYPE_PREFERENCE) |
|---|---|---|---|
| trend 趋势 | line / area / combo | 时间序列（period_end 多值） | combo 30 > area 20 > line 10 |
| comparison 对比 | bar / heatmap | 分类对比 / 矩阵 | heatmap 20 > bar 10 |
| composition 构成 | pie / treemap | 占比（is_composition） | treemap 20 > pie 15 |
| scoring 评分 | radar | 多维评分 | 20 |
| positioning 定位 | scatter / bubble | 二维/三维分布 | bubble 20 > scatter 10 |
| distribution 分布 | boxplot | 样本分布 | 20 |
| relationship 关系 | industry_chain | 产业链节点（≥2 节点） | 20 |

### 明确不做（避免范围蔓延，与方案§六一致）

| 不做项 | 理由 |
|---|---|
| 新增 ChartType（KPI 卡 / 多面板独立类型 / Funnel / Gauge） | 当前 12 种只用 2 种（bar/line），先提利用率再谈扩类型；多面板用 P2-2 dual_panel（同类型双 grid）实现，不新增类型 |
| 3D 图表 | 研报体例不用 3D，且 3D 扭曲数值感知（误导） |
| 地图类图表 | 中国地图有合规要求（审图号/边界），默认关闭 |
| 自动补值/插值 | 红线：缺数据不补造；空值如实披露而非平滑填补 |
| Dark Mode 主题 | 报告为浅色印刷体，无场景 |
| 平滑曲线 smooth:true | 与研报体例冲突，且掩盖真实波动 |
| 期刊尺寸规范（Nature 89mm 等） | 研报无固定栏宽 |
| matplotlib / seaborn / Chart.js | 项目统一 ECharts option JSON |
| 替换前端渲染库 | 仍用 ECharts option（前端直传）+ SVG 重绘（报告） |

---

## P3-6 禁用清单（Never Use）——每种数据结构的推荐 vs 禁用

| 数据结构 | ✅ 推荐 | ❌ 禁用（Never Use） | 禁用理由 |
|---|---|---|---|
| 时间序列（单指标） | line / area | pie、radar | 饼图无法表达时间顺序；雷达轴无序 |
| 时间序列（双指标同量纲） | combo 单轴（柱+线） | 双轴 combo | 同量纲用双轴制造视觉误导（P0-1 已修） |
| 时间序列（双指标异量纲） | combo 双轴（标注两轴单位）/ dual_panel | 单轴混画 | 量纲不同单轴会压扁一个序列 |
| 分类对比（≤12 类） | bar（垂直/水平/分组/堆叠） | pie（>5 类）、line | 类别多时饼图难辨；折线暗示连续时间 |
| 分类对比（>12 类） | bar 水平 + 排序 / treemap | 垂直 bar（标签重叠） | 标签拥挤不可读 |
| 占比构成（≤5 部分，和=100%） | pie / treemap | bar、line | 占比用条形丢失"整体"语义 |
| 占比构成（>5 部分） | treemap | pie | 饼图切片过多难辨 |
| 多维评分（3-8 维） | radar | bar、pie | 雷达表达多维轮廓 |
| 二维分布/相关性 | scatter | line、pie | 折线暗示有序连接 |
| 三维分布（含规模） | bubble | scatter（丢第三维） | 气泡编码第三维 |
| 样本分布/离散度 | boxplot | bar（只显均值） | 条形掩盖分布 |
| 矩阵（两维交叉） | heatmap | bar、line | 热力表达矩阵密度 |
| 产业链/关系 | industry_chain | pie、bar | 关系图表达节点链路 |

> 落地：本清单作为 router.py 选型评审与 quality.py 质检的人工对照基准；P1-7 自查清单第 4 问"类型匹配？"即查此表。

---

## P3-7 选型决策树对照（核对 router.py 路由覆盖度）

用 5 大类决策树核对 `router.py` 的 `route_chart`（:61-267）+ `CHART_FAMILY`（:10-23）覆盖度：

```
数据有时间维度（period_end 多值）？
├─ 是 → 单指标？ → line / area
│        双指标同量纲？ → combo 单轴（P0-1）
│        双指标异量纲？ → combo 双轴 / dual_panel（P2-2）
│        【router 覆盖：trend 家族 line/area/combo ✓】
└─ 否 → 看数据意图：
    ├─ 比较类别 → bar（choose_bar_variant 选垂直/水平/分组/堆叠，router.py:50-59）/ heatmap（矩阵）
    │   【comparison 家族 ✓】
    ├─ 看占比 → pie（≤5）/ treemap（>5）【composition 家族 ✓】
    ├─ 多维评分 → radar 【scoring 家族 ✓】
    ├─ 看分布/相关 → scatter / bubble（positioning）/ boxplot（distribution）【✓】
    └─ 看关系/链路 → industry_chain（relationship）【✓】
```

**覆盖度结论**：router.py 的 7 家族（trend/comparison/composition/scoring/positioning/distribution/relationship）完整覆盖 5 大类决策树的全部叶子；12 种 ChartType 均有 CHART_FAMILY 归类与 TYPE_PREFERENCE 偏好值。**无路由盲区**。

**已知约束（非盲区，是护栏）**：
- combo 要求 `business_linked` + 时间轴一致（router.py:205 附近），防双轴陷阱——P0-1 改为按量纲分支后保留此校验。
- industry_chain 需 ≥2 节点（fusion.py:144-191），节点不足则不出图。
- 路由仅当 candidate 的 chart family 与 dataset kind 匹配才接受（router.py:70），否则 suppress。

---

## P2-7 灰度测试（抽查流程）

**目的**：黑白打印/灰度阅读下图表仍可辨（不依赖颜色区分序列）。

**抽查流程**（人工/脚本，每批图表交付前抽 ≥3 张）：
1. 取 chart_specs 的 option，渲染为图（前端 ECharts 截图或 SVG）。
2. 转灰度（去饱和）：`灰度 = 0.299R + 0.587G + 0.114B`。
3. 判据：
   - 相邻序列灰度差 ≥ 可辨（目测/脚本算 Δluminance）；
   - 关键序列即使去色仍可通过 **数据标签（P1-3）/ 标注（P1-5）/ 图例位置 / 线型** 区分；
   - 涨跌语义（P2-3 红涨绿跌）在灰度下辅以 **正负号/箭头/标签**，不单靠色相。
4. 不达标 → 调整配色明度差（Okabe-Ito P2-5 已保证色盲安全，灰度下明度差需另核）或加线型区分。

**落地建议**：可写一个抽查脚本 `scripts/chart_grayscale_check.py`（读 chart_specs option 的 color 数组 → 转灰度 → 算相邻序列 Δluminance → 低于阈值告警），但本轮按方案归为"抽查流程"，先以人工对照 + 本规范执行，脚本化留作后续。

---

## 与可执行文档的对应

| 项 | 本文档章节 | 可执行文档任务卡 | 状态 |
|---|---|---|---|
| P3-4 能力边界表 | §P3-4 | P3-4（文档） | ✅ 本文档落地 |
| P3-6 禁用清单 | §P3-6 | P3-6（文档） | ✅ 本文档落地 |
| P3-7 决策树对照 | §P3-7 | P3-7（核对 router.py） | ✅ 本文档落地（已核对无盲区） |
| P2-7 灰度测试 | §P2-7 | P2-7（抽查流程） | ✅ 规范落地；脚本化留后续 |
