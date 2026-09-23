# Chapter Writer Agent

从 `data-analysis` 的解读报告和 `chart-generator` 的图表结果生成行业研究报告标准7章21节。每章执行有界的生成、证据审计与修复；模型不可用时仍交付完整的确定性兜底稿。

```bash
python3.11 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/chapter-writer ../data-analysis/output/runs/<id> --charts ../chart-generator/output/runs/<id>
```

模型配置使用 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。项目不读取或导入原五阶段工程。

## 内置 Skills

独立目录 [`chapter_writer/skills`](chapter_writer/skills) 包含七项收窄后的写作技能：证据约束、章节质检、行业概览、产业链、竞争格局、财务分析和风险情景。前两项应用于全部章节，其余按7章目标路由；模型提示只接收当前章需要的方法，运行结果在 `chapter_result.json.applied_skills` 记录技能及适用章节。

技能只提供结构和校验方法，事实仍只能来自上游报告。原技能中的外部研究、提纲审批、投资建议、交易风控和幻灯片流程均未迁入。

```bash
python -m pytest -q
python -m compileall -q chapter_writer
```
