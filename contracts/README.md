# 公共契约

本目录是前端、后端和五个 Pipeline 节点之间的唯一跨端契约源。

## 规则

1. JSON Schema 字段使用 `snake_case`，时间使用带时区的 ISO 8601。
2. 枚举值一经使用不得直接改名；破坏性变更创建新版本。
3. 后端 Pydantic 模型、前端 TypeScript 类型和 Mock 数据必须与这里保持一致。
4. 修改契约必须由后端 C/架构负责人 Review，并同时更新契约测试。
5. `data` 只承载结构化小数据；图片、PDF 等使用 `ArtifactRef`。

## 文件

- `schemas/workflow-state.schema.json`：Pipeline 运行状态、阶段结果和产物引用。
- `schemas/review-action.schema.json`：人工审核命令。
- `schemas/chapter-writing-result.schema.json`：Agent 4的7章21节结构化结果，供Agent 5、前端和持久化层使用。

后续 API 开始实现后，以 FastAPI 生成的 OpenAPI 描述 HTTP 端点；本目录继续定义跨 Agent 和持久化状态。
