# 代码与协作规范

## 分支与提交

- 稳定分支统一为 `main`；当前仓库正式建立基线时应从 `master` 迁移。
- 使用短生命周期功能分支：`feature/<area>-<summary>`、`fix/<area>-<summary>`。
- 不使用每人一个永久分支，避免六周后集中合并。
- 提交格式：`type(scope): description`，类型包括 `feat`、`fix`、`docs`、`refactor`、`test`、`chore`。
- 所有合并至少一人 Review，并通过 `./scripts/verify.sh`。

## Python

- 包和模块使用 `snake_case`，类使用 `PascalCase`。
- API 输入输出必须使用 Pydantic 模型。
- 外部服务先定义 Protocol/接口，再实现真实与 Mock 适配器。
- 禁止在 Agent 内直接创建数据库连接、HTTP 客户端或读取全局密钥。
- Black 格式化、Flake8 静态检查、mypy 类型检查、pytest 测试。

## Vue / TypeScript

- 使用 `<script setup lang="ts">` 与组合式 API。
- 页面放 `src/views/`，稳定能力放 `src/modules/`，共享 UI 放 `src/components/shared/`。
- 跨页面 Pipeline 状态放 Pinia；服务端状态以 API 返回为准。
- 禁止手写与公共 Schema 冲突的枚举和值。
- ESLint、Prettier、Vue TSC、Vitest 必须通过。

## 公共变更

以下文件需要后端 C/架构负责人 Review：

- `contracts/**`
- `backend/app/main.py`、`backend/app/api/**`、`backend/app/core/**`
- `backend/app/workflow/**`
- `docs/architecture/**`
- 运行时依赖文件

