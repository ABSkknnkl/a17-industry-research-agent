# Report Fusion Agent

独立的行业研究报告融合、全局一致性检查和多格式导出智能体。对章节、摘要和图表进行融合与检查；模型编辑受到数字和证据约束，但结果仍需人工核验。

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/playwright install chromium
.venv/bin/report-fusion ../data-analysis/output/runs/<id> --chapters ../chapter-writer/output/runs/<id> --charts ../chart-generator/output/runs/<id>
```

可能输出 `report_view.json`、Markdown、HTML、PDF、一致性报告和产物清单；实际格式以本次运行结果和告警为准。

## 内置 Skills

独立目录 [`report_fusion/skills`](report_fusion/skills) 包含报告一致性审计、执行摘要融合、视觉质量、证据目录和研判卡片等技能。启用模型时，编辑阶段受到证据与数字约束。实际采用项写入返回结果的 `applied_skills`。

技能由 `skills包` 收窄改写，不携带逐任务审批、外部研究、投资评级、原项目状态机或团队基础设施约束。

```bash
python -m pytest -q
python -m compileall -q report_fusion
```
