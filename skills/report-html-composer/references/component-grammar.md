# 小节级组件语法

模型为每个小节只选择一个主要构图，并给出简短理由。

| 构图 | 使用条件 | 禁止条件 |
|---|---|---|
| `prose_flow` | 连续论证、复杂解释 | 无 |
| `evidence_split` | 引用密集且正文仍有足够宽度 | 移动端并排 |
| `chart_focus` | 至少 1 张关键图 | 无图 |
| `chart_sequence` | 至少 2 张有先后逻辑的图 | 单图 |
| `small_multiples` | 至少 2 张同口径可比较图 | 口径不同 |
| `metric_strip` | 多个单点指标 | 用单点伪造趋势 |
| `comparison_board` | 两组对象或情景可并行比较 | 没有比较维度 |
| `table_story` | 多维字段或结构化对照 | 用表格承载长段全文 |
| `diagram_story` | 产业链、流程、关系网络 | 普通时间序列 |
| `risk_register` | 风险、触发条件、影响、监测项 | 普通叙事章节 |

`reading_order` 可选 `insight_first`、`data_first`、`balanced`；`content_width` 可选 `prose`、`wide`、`full`。这些是构图提示，不得改变内容。

同一种构图连续出现三次时，应检查是否真的由内容决定；若只是偷懒，改用另一种语义正确的构图。安全约束不满足时回退 `prose_flow`。
