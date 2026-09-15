# Agent 3 图表能力同步变更报告

日期：2026-09-15  
分支：`agent/chart-mvp-sync`  
基线：`e50af6b`  
最终代码复审提交：`3c940d7`

## 交付结论

《图表改动.md》对应的 16 项能力已全部落到 Agent 3 的确定性图表契约，并同步到前端 ECharts、后端 SVG、HTML/PDF 和公共 JSON Schema。既有 12 种基础图表类型全部保留；`dual_panel` 是 `combo` 的布局变体，不是第 13 种基础图表。

最终回归结果：后端 `867 passed, 2 skipped`；前端 `8 passed`，type-check、lint、Prettier 和 production build 均通过；本分支改动文件通过 Black、Flake8 和严格 Mypy。真实 Chromium 已将 12 类 SVG 图表导出为 6 页 A4 PDF，文件为 126,640 字节，可提取各图标题和关键数值。

## 16 项需求与可执行证据

| # | 已交付行为 | 主要实现 | 自动化证据 |
| --- | --- | --- | --- |
| 1 | `未提供`、`文本`、`不适用`、空串不进入轴名，转为 `[需核实:货币单位]` | `constants.py`、`builders.py`、`data_fetcher/fusion.py` | `test_fusion_normalizes_all_chart_unit_placeholders`、`test_dual_panel_sanitizes_placeholder_axis_names_and_discloses_them` |
| 2 | 完全重复、语义重复和展示冲突只交付最佳图，并输出稳定抑制原因 | `router.py`、`planner.py`、`service.py` | `test_agent_truly_suppresses_duplicate_view_and_audits_outcomes`、`test_trend_synonyms_share_one_dedupe_slot_without_merging_different_data`、`test_real_time_series_fingerprint_prevents_false_merge` |
| 3 | 组合图同单位单轴、异单位双轴、全空/未对齐/超过规则范围拒绝 | `router.py`、`builders.py` | `test_combo_same_unit_is_single_axis_and_different_unit_is_dual_axis`、`test_combo_axis_count_and_series_binding_follow_normalized_units` |
| 4 | 每条可见序列 12 点显示标签，13 点关闭；空缺不计数 | `constants.py`、`builders.py` | `test_null_gaps_do_not_count_toward_line_area_or_bar_label_limit`、`test_combo_and_dual_panel_use_per_series_visible_label_limit` |
| 5 | 非零起点/截断轴必须带脚注，雷达轴同样检查 | `builders.py`、`quality.py`、`svg.py` | `test_radar_axis_checklist_requires_truncation_disclosure`、`test_axis_scale_and_explicit_bounds_are_respected` |
| 6 | `reference_line`、`shaded_region`、`callout` 在 ECharts 与 SVG 中同步 | `schemas/chart.py`、`builders.py`、`svg.py` | `test_line_applies_labels_units_theme_colors_and_annotations`、`test_svg_labels_marks_colors_and_escaped_footnotes` |
| 7 | A 股红涨绿跌；无涨跌语义的普通序列不误着色 | `constants.py`、`builders.py` | `test_area_applies_a_share_directional_colors_to_visible_points`、`test_shared_rules_apply_to_area_bar_and_boxplot` |
| 8 | `broker_thin` 无网格、1.5px 细线、无点圆圈、深海军蓝主色 | `builders.py` | `test_line_applies_labels_units_theme_colors_and_annotations`、`test_builder_broker_thin_labels_threshold_and_null_gaps` |
| 9 | `dual_panel` 左右面板共享时间轴、独立单位、系列不交叉；重叠/漏配被拒绝 | `schemas/chart.py`、`router.py`、`builders.py`、`svg.py` | `test_dual_panel_builder_output_keeps_series_and_marks_in_own_panel`、`test_combo_dual_panels_reject_overlap_and_incomplete_coverage` |
| 10 | 标签、缺失率、图表预算、主题色等阈值集中管理 | `chart_generator/constants.py` | `test_chart_contract_supports_four_series_panels_and_annotations`、`test_report_chart_density_uses_shared_budget_bands` |
| 11 | 报告按最终出现顺序生成图表目录，全篇连续编号，附录不丢图 | `reporting/html.py`、`report.html.j2` | `test_chart_directory_follows_final_body_order_and_numbers`、`test_chart_directory_numbers_unplaced_and_unknown_sections_in_appendix` |
| 12 | 来源优先使用材料标题、机构名或 URL 主机名；无具名来源产生质量提示 | `report_fusion/evidence.py`、`quality.py` | `test_chart_sources_use_named_title_publisher_or_domain`、`test_ready_charts_without_named_sources_raise_advisory` |
| 13 | ECharts、SVG 与 PDF 保持标题、轴、单位、系列、颜色、注释、脚注语义一致 | `builders.py`、`reporting/svg.py`、`reporting/pdf.py` | `test_combo_shares_scale_by_axis_index_and_displays_both_units`、`test_specialized_axes_preserve_annotations`、真实 12 类 Chromium PDF 验收 |
| 14 | 非结论式标题产生 `title_not_conclusive`，不编造数字或结论 | `quality.py` | `test_data_health_boundaries_and_title_rule`、`test_quality_checklist_reports_machine_checks_without_changing_passed` |
| 15 | JSONL 记录 7 个业务字段及运行信封，覆盖生成、抑制、降级、失败 | `audit.py`、`service.py` | `test_audit_writes_seven_business_fields`、`test_audit_run_context_is_isolated_between_concurrent_tasks`、`test_agent_audits_p1_downgrade_instead_of_silently_dropping_candidate` |
| 16 | `<5` 行给出诊断；字段不足、缺失率 `>20%`、类型不一致阻止就绪 | `quality.py`、`service.py` | `test_data_health_boundaries_and_title_rule`、`test_agent_keeps_short_complete_dataset_as_min_rows_advisory`、`test_agent_suppresses_incomplete_data_before_routing` |

## 12 种基础图表支持矩阵

| 图表类型 | 路由/构建 | SVG | PDF 抽查 | 主要用途 |
| --- | --- | --- | --- | --- |
| `line` | 是 | 是 | 是 | 时间趋势 |
| `bar` | 是；含纵向、横向、分组、堆叠变体 | 是 | 是 | 分类比较 |
| `pie` | 是 | 是 | 是 | 少量互斥构成 |
| `radar` | 是 | 是 | 是 | 同尺度多指标评分 |
| `industry_chain` | 是；ECharts/可选生图 | 是 | 是 | 产业链关系 |
| `combo` | 是；单轴、双轴、`dual_panel` | 是 | 是 | 业务联动指标 |
| `area` | 是 | 是 | 是 | 历史与预测 |
| `scatter` | 是 | 是 | 是 | 双变量定位 |
| `bubble` | 是 | 是 | 是 | 三变量定位 |
| `heatmap` | 是 | 是 | 是 | 完整二维矩阵 |
| `boxplot` | 是 | 是 | 是 | 分布与异常值 |
| `treemap` | 是 | 是 | 是 | 层级构成 |

## 前后端契约

- 运行时源：`backend/app/schemas/chart.py`。
- 公共契约：`contracts/schemas/chart-generation-result.schema.json`。
- 前端镜像：`frontend/src/api/types.ts`。
- 消费端：`frontend/src/components/ChartGallery.vue` 直接把完整 `option` 交给 ECharts，并展示脚注，不在前端重新推断面板、轴或注释。
- 生成图片模式、ready 引用的 `artifact_id`、反馈解释和已应用修改均有条件契约测试；旧版无面板/注释结果仍兼容。

## 问财参考边界

问财公开页面仅用于研究柱折图、双轴、图例、单位、时间维度和结论摘要等可观察行为。本项目没有复制、反编译或提交问财的私有源码、压缩 bundle、缓存或抓取产物，也没有引入 K 线、分时、盘口、3D、地图或动态播放控件。

## 最终验证记录

在 2026-09-15 的 `agent/chart-mvp-sync` 分支执行：

```bash
cd backend
.venv/bin/python -m pytest -q -o addopts='--strict-markers --import-mode=importlib'
# 867 passed, 2 skipped, 24 warnings in 10.63s

cd ../frontend
npm run verify
# vue-tsc、eslint、prettier：通过；vitest：8 passed
npm run build
# Vite production build：通过

cd ..
git diff --name-only e50af6b -- backend | rg '\.py$' \
  | xargs backend/.venv/bin/python -m black --check
# 25 files would be left unchanged

cd backend
git diff --name-only e50af6b -- . | rg '^backend/.*\.py$' | sed 's#^backend/##' \
  | xargs .venv/bin/python -m flake8
# 通过，无输出

cd ..
git diff --name-only e50af6b -- backend/app | rg '\.py$' \
  | xargs backend/.venv/bin/python -m mypy --follow-imports=silent
# Success: no issues found in 14 source files
```

真实 PDF 验收使用 12 种图表各一张的 SVG，交给项目 `render_pdf` 和本机 Chromium m151 导出：PDF 1.4、A4、6 页、126,640 字节、无 JavaScript、文本抽取可识别 12 个图表标题与关键数值。仓库自带的真实浏览器冒烟测试 `tests/test_playwright_pdf.py` 另行通过：`1 passed`。

## 已知非阻塞警告与基线

- 后端全量有 24 条警告：1 条 Starlette/AnyIO `BlockingPortal` 弃用警告，以及 23 条既存 pytest asyncio 标记警告；不影响退出码。
- Vite 对 VueUse 的两个 PURE 注释位置发出警告，并报告两个构建 chunk 大于 500 kB；构建成功。
- 全仓严格 Mypy 仍有 32 个既存错误，分布于 11 个本任务范围外文件；本分支触达的 14 个生产文件已单独严格检查并为 0 errors。
- 全仓 Black 会命中 16 个本任务范围外的既存格式文件；本分支触达的 25 个 Python 文件全部通过 Black。
- 仓库基线已跟踪若干 `eval/transcript/**/artifacts/` 历史评测文件；本分支没有新增、修改或删除这些文件，`e50af6b..HEAD` 的禁止路径检查无新增结果。

## 提交记录

从 `e50af6b` 起的交付提交：

```text
45ab16b docs: define Agent 3 chart sync design
1faea77 docs: plan Agent 3 chart capability implementation
447a373 feat(chart): add panel annotation and limit contracts
45a9fce feat(chart): enforce health quality and audit gates
d70b1e0 fix(chart): preserve health and audit context
db67a99 feat(chart): route combo units and suppress semantic duplicates
a337e5f chore(chart): untrack task report artifact
de6351e feat(chart): add research-grade option rendering
382b1a0 fix(chart): honor visible labels and bar axes
c655645 feat(report): synchronize SVG chart semantics
4377cc5 fix(report): respect horizontal category axis direction
4f21894 feat(report): add chart index numbering and named sources
5b356fa feat(chart): synchronize public and frontend contracts
4202a19 fix(chart): enforce conditional contracts and radar review
3c940d7 test(chart): harden final chart acceptance
HEAD docs: report Agent 3 chart capability delivery
```

分支只等待仓库协议要求的显式 push 确认；未修改 `main`，未 force push，未创建 PR。
