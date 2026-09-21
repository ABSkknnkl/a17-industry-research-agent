# PageCompositionPlan 契约

下面是建议的最小 JSON 结构。实现可以使用 Pydantic 或等价强类型模型，但字段含义应保持稳定。

```json
{
  "schema_version": "1.0",
  "document_profile": "research_report",
  "page_size": "A4_portrait",
  "export_layer": "public",
  "content_inventory_ids": ["REPORT-TITLE"],
  "content_dispositions": {},
  "design_system": {
    "primary_color": "navy",
    "accent_color": "gold",
    "body_font_role": "cjk_sans",
    "heading_font_role": "cjk_sans",
    "chart_font_role": "cjk_sans",
    "body_alignment": "left",
    "publication_chrome": true
  },
  "render_contract": {
    "page_selector": ".report-page",
    "header_selector": ".pg-head",
    "footer_selector": ".pg-foot",
    "content_selector": ".content",
    "page_role_attribute": "data-role",
    "chapter_attribute": "data-chapter",
    "block_attribute": "data-bid",
    "measure_script": "scripts/measure_pages.js",
    "audit_script": "scripts/audit_render.py"
  },
  "pages": [
    {
      "page_number": 1,
      "page_role": "cover",
      "chapter_id": null,
      "grid": "cover_editorial",
      "estimated_fill": 0.78,
      "intentional_whitespace": true,
      "blocks": [
        {
          "block_id": "cover-title",
          "kind": "heading",
          "source_ids": ["REPORT-TITLE"],
          "span": 12,
          "size": "hero",
          "keep_together": true,
          "reading_level": "headline",
          "editorial_action": "original",
          "split_policy": "never"
        }
      ]
    }
  ]
}
```

## render_contract 为什么是必填

渲染后审计完全依赖 DOM 钩子：没有 `page_selector` 就无法逐页测量；没有 `footer_selector` 就推不出安全版心下沿，`FOOTER_COLLISION` 会退化成肉眼判断；没有章节属性，`UNEXPLAINED_WHITESPACE` 无法区分“章节正常结束的留白”和“分页失败”。

因此 `render_contract` 缺失或不完整时，`validate_page_plan.py` 报 `RENDER_CONTRACT_INCOMPLETE`。声明之后，渲染器必须真的输出这些属性。

## 枚举建议

- `document_profile`：`brief_note`、`research_report`、`data_dashboard`
- `page_size`：`A4_portrait`、`A4_landscape`、`wide_16_9`（必填，导出时按它校验纸张）
- `export_layer`：`public`、`internal_audit`、`combined`
- `page_role`：`cover`、`toc`、`list_of_figures`、`executive_summary`、`chapter_opener`、`narrative`、`chart_page`、`comparison_page`、`table_page`、`appendix`、`disclosure`、`closing`
- `grid`：`cover_editorial`、`single_column`、`two_column_short`、`single_hero`、`two_up`、`hero_plus_two`、`two_by_two`、`small_multiples`、`full_table`、`landscape_table`
- `kind`：`heading`、`paragraph`、`summary`、`metric`、`chart`、`table`、`callout`、`source`、`disclosure`
- `size`：`small`、`medium`、`large`、`hero`
- `reading_level`：`headline`、`lead`、`support`、`detail`、`audit`（**每个块必填**，渲染后审计靠它区分对外正文与内部审计）
- `editorial_action`：`original`、`deduplicate`、`extractive_summary`、`move_to_appendix`、`omit_from_public`
- `split_policy`：`never`、`paragraph`、`table_rows`、`between_children`

### chapter_id 的作用域

`executive_summary`、`narrative`、`chart_page`、`comparison_page`、`table_page`、`appendix` 这六类页面**必须**给出 `chapter_id`（同一章节跨页用同一值，附录各分册用 `APX-A` / `APX-B` 这类稳定标识）。封面、目录、章节过渡、声明、结束页可为 `null`。

## 可选图表字段

```json
{
  "visual_task": "ranking",
  "display_kind": "bar",
  "arrangement": "two_up",
  "orientation": "horizontal",
  "point_count": 8,
  "category_count": 8,
  "series_count": 1,
  "long_cjk_labels": true,
  "has_negative_values": true,
  "zero_baseline": true,
  "shared_scale_group": "company-profitability",
  "unit": "%",
  "missing_value_mode": "gap",
  "group_key": "company-profitability",
  "caption_mode": "title_and_source",
  "max_caption_lines": 2,
  "label_gutter": {
    "mode": "dedicated_slot",
    "width_ratio": 0.14,
    "note": "分类标签独占左栏，坐标域按最大绝对值对称，条形不侵入标签区"
  },
  "max_abs_ratio": 2.4,
  "degrade_reason": null
}
```

### 两个会被契约拦截的组合

- **`has_negative_values: true` + `orientation: "horizontal"` + `long_cjk_labels: true`，但没有 `label_gutter` / `label_slot`** → `DIVERGING_LABEL_GUTTER_MISSING`。负值条会伸进分类标签区，数据标签与分类标签必然重叠。规划期就要定好独占槽位与对称坐标域。
- **`max_abs_ratio ≥ 8` 且 `display_kind` 仍是同轴 `bar` / `line`，也没有 `degrade_reason`** → `OUTLIER_NOT_DEGRADED`。极值会把其余序列压成一条线，必须改为 `table` / `annotated_table` / `small_multiples` / `log_scale` / `split_axis`，或写明为何不降级。

## 可选表格字段

```json
{
  "table_id": "TABLE-03",
  "caption": "表 3（续）",
  "continued_from_page": 11,
  "repeat_header": true,
  "minimum_body_rows": 4,
  "header_max_lines": 2,
  "cjk_label_orientation": "horizontal",
  "column_widths": ["9%", "23%", "8%", "46%", "14%"],
  "column_width_basis": "longest_label",
  "merged_row_groups": [
    { "group_key": "same_handling", "member_count": 9, "display_id": "DQ-ANOM-01 等 9 项" }
  ],
  "allow_landscape": true
}
```

`column_widths` 建议显式给出。`column_width_basis` 说明列宽依据（`longest_label` / `numeric_precision` / `equal`），供复检时判断是否合理。内容完全相同的连续行应通过 `merged_row_groups` 成组，并在表下注明归并关系。

## 确定性校验

- 页码从 1 连续递增；块 ID 唯一，引用的源 ID 必须存在。
- `page_size` 必须在枚举内；导出后需核对实际纸张与之一致。
- 每个块必须有 `reading_level`；`public` 层不得出现 `audit` 层内容。
- `executive_summary`/`narrative`/`chart_page`/`comparison_page`/`table_page`/`appendix` 必须给出 `chapter_id`。
- `editorial_action = "deduplicate"` 的块必须给出 `merged_source_ids`；被合并的原始 ID 也要出现在 `content_dispositions`。
- 所有原始内容 ID 必须被某个块引用，或被明确记录为去重/下沉/对外省略；不允许静默丢失。
- 普通正文页只允许一个一级章节起点。
- `estimated_fill` 必须在 0–1 之间；低于 0.65 时必须标记可解释留白或进入重排。渲染后要用实测值复核并回填。
- `table_page` 的续表必须含 `continued_from_page`（且小于本页页码）、重复表头和“续”标题。
- 中文标签方向必须为 `horizontal`。
- `public` 层禁止出现机器状态、完整质量日志和调试块。
- 图表组必须在同页网格可容纳，且不能通过低于可读字号完成。
- 单指标不得使用柱/线/饼图；趋势图不得少于 3 个时间点；长中文排名不得使用纵向柱图。
- 发散条形图必须声明标签槽位；极值离群必须声明降级方式。
- 普通页连续三页使用同一网格且同一焦点位置时，必须有内容任务理由；否则进入候选页重排。
- 目录、图表目录和文内引用的页码必须从最终渲染产物回填并再次校验。

`content_dispositions` 记录没有直接显示的原始内容 ID 及其 `deduplicate`、`move_to_appendix` 或 `omit_from_public` 处理。它是内容未丢失的追溯记录，不能用一个笼统理由覆盖整章。

## 候选页评分

对同一内容段的候选编排使用结构化代价，不只依赖视觉模型的总分：

- `hard_fail`：溢出、裁切、内容丢失、页序错误、事实/引用断链。
- `high_cost`：裸续表、孤悬标题、图题与图拆散、可比图拆页、一页多个一级章节、正文中途大留白。
- `medium_cost`：连续构图重复、文字与图表密度失衡、图例/来源线不对齐、页面焦点偏移。
- `low_cost`：轻微间距和装饰差异。

在所有 `hard_fail=0` 的候选中选择综合代价最低者，并保留候选与选择原因便于复现。
