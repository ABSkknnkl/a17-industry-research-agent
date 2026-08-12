# Agent 5 P0 融合与导出交接

## 完成范围

Agent 5 已经从 Mock 替换为真实的确定性报告节点。它不再调用大模型，也不重写 Agent 2 和 Agent 4 的金融结论，只做输入校验、结构组装、图表静态化、多格式导出和产物溯源。

P0 现已支持：

- 校验 Agent 2、3、4 的 Pydantic 契约与质量门。
- 校验 7 章 21 节、结论 ID、证据 ID、图表 ID 和上游修订版本。
- 同一 `ReportViewModel` 生成 Markdown、自包含 HTML 和 PDF。
- 将 Agent 3 的 `line`、`bar`、`industry_chain` ECharts Option 确定性转为内联 SVG。
- Jinja2 全局自动转义，HTML 不依赖 CDN 或外部图片。
- Playwright Chromium 输出 A4 PDF，包含封面、目录、执行摘要、正文、图表、研究边界和免责声明。
- 报告与 `manifest.json` 采用原子写入，记录字节数和 SHA-256。
- 前端可使用 `GET /api/v1/runs/{run_id}/artifacts/{artifact_id}` 下载产物，后端会先校验 owner_id。

## 输入与输出

必需上游输入：

- Agent 2：`AnalysisResult`
- Agent 3：`ChartGenerationResult`
- Agent 4：`ChapterWritingResult`

默认输出目录：

```text
artifacts/{run_id}/reports/r{revision}/
├── report.md
├── report.html
├── report.pdf
└── manifest.json
```

LangGraph 状态中只保存 `ReportFusionResult` 和 `ArtifactRef`，不把整份 HTML/PDF 放进 SQLite Checkpointer。

## 人工审核边界

`report_fusion_options` 可选择 `markdown/html/pdf`、专业或通俗展示风格，并记录摘要侧重与终审备注。这些文字只作为可见的人工备注，不会被当作 Prompt 执行，也不能新增数据事实。P0 固定 7 章 21 节顺序，非标准重排会返回 `waiting_review`。

## 主要代码位置

- `backend/app/agents/report_fusion/`：组装、质量门和 Agent 入口。
- `backend/app/reporting/`：Markdown、HTML、SVG 与 Playwright PDF。
- `backend/app/schemas/report.py`：报告内部视图模型和公开结果契约。
- `contracts/schemas/report-fusion-result.schema.json`：前后端公共 JSON Schema。
- `backend/app/infrastructure/storage/local.py`：报告原子保存和哈希。
- `backend/tests/agents/report_fusion/`：融合、转义、溯源和质量门测试。

## 后续工作

- 使用赛事授权密钥运行已完成的 Agent 1 SkillHub 适配器，并用真实行业数据进行端到端验收。
- 前端接入 `ReportFusionResult`，实现 HTML 预览、格式选择、终审和下载按钮。
- P1 再增加模板管理、报告历史列表、对象存储和更丰富的图表静态化。
