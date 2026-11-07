# Chart Generator Agent

证据约束型图表生成智能体，读取解读报告并按数据选择图表；可生成 ECharts 配置和 SVG 等产物。模型、产业链搜索与可选补充视图是否使用取决于配置。

## 安装与使用

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/chart-generator ../data-analysis/output/runs/<analysis_id>
```

库接口：

```python
result = await ChartGeneratorAgent().run(ChartGenerationRequest(report=report))
```

产物位于 `output/runs/<run_id>/`。数据不足时允许零图表，并在结果中给出原因，不生成没有证据的数据。

## 内置 Skills

项目自带独立目录 [`chart_generator/skills`](chart_generator/skills)，运行时自动发现并把实际采用项写入 `chart_result.json.applied_skills`：

- `chart-selection`：按数据形态确定性选型。
- `chart-readability`：坐标轴、单位、脚注、零轴和图证可读性。
- `industry-chain-visualization`：有产业链证据时组织上中下游节点。
- `financial-charting`：有财务信号时处理期间、量纲和正负值。
- `sensitivity-matrix-charting`、`valuation-growth-quadrant`：相关专题图表方法。

这些技能由 `skills包` 中的相关方法收窄改写，只提供可视化方法，不携带外部取数、投资判断、人工审批或旧工作流。

## 验证

```bash
python -m pytest -q
python -m compileall -q chart_generator
```
