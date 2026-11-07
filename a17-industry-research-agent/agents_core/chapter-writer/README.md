# Chapter Writer Agent

根据解读报告与图表结果生成章节草稿。默认大纲为 7 章 21 节；生成、证据审计和修复的实际结果受输入与模型服务影响，不能保证完整交付。

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/chapter-writer ../data-analysis/output/runs/<id> --charts ../chart-generator/output/runs/<id>
```

模型配置使用 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。该包由当前项目的五阶段工作流调用。

## 内置 Skills

独立目录 [`chapter_writer/skills`](chapter_writer/skills) 当前包含 10 份写作技能文档，覆盖证据约束、章节质检、行业、产业链、竞争、财务和风险等方法。实际选择和应用以运行结果 `chapter_result.json.applied_skills` 为准。

技能只提供结构和校验方法，事实仍只能来自上游报告。原技能中的外部研究、提纲审批、投资建议、交易风控和幻灯片流程均未迁入。

```bash
python -m pytest -q
python -m compileall -q chapter_writer
```
