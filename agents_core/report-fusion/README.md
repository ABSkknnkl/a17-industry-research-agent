# Report Fusion Agent

独立的行业研究报告融合、全局一致性检查和多格式导出智能体。模型只能编辑已有章节、摘要与过渡；任何新增数字或未知证据引用都会被拒绝并回退原文。

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/playwright install chromium
.venv/bin/report-fusion ../data-analysis/output/runs/<id> --chapters ../chapter-writer/output/runs/<id> --charts ../chart-generator/output/runs/<id>
```

输出包括 `report_view.json`、`report.md`、自包含 `report.html`、`report.pdf`、一致性报告和带SHA-256的产物清单。PDF失败不会丢失其他格式。

## 内置 Skills

独立目录 [`report_fusion/skills`](report_fusion/skills) 包含报告一致性审计、执行摘要融合、视觉质量和证据目录四项技能。规则融合始终执行这些方法；启用模型时仅把方法提示加入受证据与数字白名单约束的编辑阶段。实际采用项写入返回结果的 `applied_skills`。

技能由 `skills包` 收窄改写，不携带逐任务审批、外部研究、投资评级、原项目状态机或团队基础设施约束。

```bash
python -m pytest -q
python -m compileall -q report_fusion
```
