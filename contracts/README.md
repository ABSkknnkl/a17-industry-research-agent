# 公共契约

本目录是前端、后端和五个 Pipeline 节点之间的唯一跨端契约源。

## 规则

1. JSON Schema 字段使用 `snake_case`，时间使用带时区的 ISO 8601。
2. 枚举值一经使用不得直接改名；破坏性变更创建新版本。
3. 后端 Pydantic 模型、前端 TypeScript 类型和 Mock 数据必须与这里保持一致。
4. 修改契约必须由后端 C/架构负责人 Review，并同时更新契约测试。
5. `data` 只承载结构化小数据；图片、PDF 等使用 `ArtifactRef`。

## 文件

- `display-labels.json`：**展示用中文标签映射**（2026-09-15 新增）。后端 `SkillName`、
  `DimensionName`、覆盖状态、证据来源类型等内部英文标识 → 终端用户可读的中文。
  后端通过 `app/schemas/display_labels.py` 加载。**新增技能或维度时必须在此补一行**，
  否则前端会退回显示英文标识。

  ⚠️ **下发范围有限制**，改动前务必读完：

  | 字段 | 后端下发？ | 原因 |
  | --- | --- | --- |
  | `SourceRecord.skill_label` | ✅ 是 | `computed_field`，随产物序列化下发 |
  | `DimensionCoverage.dimension_label` / `status_label` | ❌ 否 | 见下方约束 |

  **为什么维度标签不能由后端下发**：`DimensionCoverage` 嵌在 `AnalysisDraft` 里，
  而 `AnalysisDraft.model_json_schema()` 被用作 LLM 结构化输出 schema
  （`openai_compatible.py`）；加 `computed_field` 会让它变成必填只读属性，
  导致模型输出校验失败（`analysis_generation_failed`，实测 3 个 A2 测试变红）。
  改为在阶段数据里补 key 也不行——阶段数据会被 `AnalysisResult.model_validate()`
  校验回契约，而契约是 `extra="forbid"`，多一个 key 就报 `extra_forbidden`。
  因此维度与覆盖状态的中文由**前端** `src/api/labels.ts` 负责，
  取值仍然以本文件为准（前端映射与本文件保持一致）。标识。
- `schemas/workflow-state.schema.json`：Pipeline 运行状态、阶段结果和产物引用。
- `schemas/review-action.schema.json`：人工审核命令。
- `schemas/chapter-writing-result.schema.json`：Agent 4的7章21节结构化结果，供Agent 5、前端和持久化层使用。
- `schemas/chart-generation-result.schema.json`：Agent 3 的 P0/P1 图表引用、ECharts Option、去重与质量结果。
- `schemas/report-fusion-result.schema.json`：Agent 5 的报告元数据、上游版本、导出格式、质量门与带 SHA-256 的产物清单。

后续 API 开始实现后，以 FastAPI 生成的 OpenAPI 描述 HTTP 端点；本目录继续定义跨 Agent 和持久化状态。
