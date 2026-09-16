# Agent 3 第 13 类图表交付说明

## 交付内容

新增正式图表类型 `comparison_bar`，中文名称为“涨跌幅对比图”。该类型面向同一组公司、标的或行业的两个完整可比周期，使用分组柱展示正负变化，并成为 Agent 3 原有 12 类图表之外的第 13 类图表。

## 数据与路由

- 复用 `ChartDataset(kind="categorical")` 与 `ChartPoint`，不增加平行数据模型。
- 必须存在恰好两条非空序列，且两条序列完整覆盖同一组不重复类别。
- 不完整、含空值、只有一条序列或类别不对齐时，返回 `comparison_bar_series_not_aligned`，不补造零值。
- 后端运行时枚举、工作流/分析/报告模型、两份 JSON Schema 和前端 TypeScript 类型已同步。

## ECharts 与报告效果

- 两条序列并列显示，纵轴域同时覆盖最小值、零和最大值并保留 10% 视觉余量。
- 零轴使用独立参考线；正值向上、负值向下。
- 第一序列使用深红/深绿，第二序列使用浅红/浅绿，兼顾序列身份与红涨绿跌语义。
- 长类别名称倾斜 32 度；超过 10 类时增加横向 dataZoom。
- 前端 ECharts、HTML、SVG 与 PDF 报告共享同一标题、序列、轴、单位、颜色和证据映射。

## 自动化验收映射

| 需求 | 验收位置 |
| --- | --- |
| 公共契约接受第 13 类 | `backend/tests/test_contracts.py` |
| 两条序列完整对齐 | `backend/tests/agents/chart_generator/test_router.py` |
| 正负轴域、方向色、零轴、长标签、缩放 | `backend/tests/agents/chart_generator/test_builders.py` |
| 服务分派到专用 builder | `backend/tests/agents/chart_generator/test_chart_capability_mvp.py` |
| SVG 正负柱围绕真实零轴 | `backend/tests/reporting/test_svg.py` |
| 前端类型名称及共享 ECharts 路径 | `frontend/src/components/__tests__/ChartGallery.spec.ts` |

## 真实预览

- HTML：`/Users/hanyaohui/Documents/Codex/2026-09-15/x/outputs/Agent3-全部13类金融图表生产代码效果.html`
- 桌面截图：`/Users/hanyaohui/Documents/Codex/2026-09-15/x/outputs/Agent3-全部13类金融图表生产代码效果-最终.png`
- 窄屏截图：`/Users/hanyaohui/Documents/Codex/2026-09-15/x/outputs/Agent3-全部13类金融图表生产代码效果-窄屏.png`
- 设计验收：仓库根目录 `design-qa.md`，结果为 `passed`。

预览使用当前生产 builder 和本地 ECharts bundle 直接生成；HTML、PNG 和辅助裁图位于仓库外，不进入 Git 历史。

## 已知限制

- 该类型只接受两条序列；三条及以上指标应使用普通分组柱或双面板组合图。
- 在明显窄于已验证 720px 的容器中，十个长类别名可能需要用户使用 dataZoom 或 Tooltip 查看完整文本。
- 负值使用绿色是项目金融语义约定，与参考图按系列固定红/灰颜色的做法有意不同。
