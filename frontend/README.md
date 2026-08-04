# 前端应用

Vue 3 + TypeScript 应用，包含报告展示和人机审核两类稳定能力。整体职责见 [`../docs/ownership.md`](../docs/ownership.md)。

## 目录

- `src/modules/reporting/`：前端 A，报告、图表与 PDF
- `src/modules/review/`：前端 B，Pipeline 状态与审核
- `src/stores/`：Pinia 跨页面状态
- `src/api/`：统一 Axios 客户端
- `src/types/`：公共契约的 TypeScript 镜像及一致性测试
- `src/components/shared/`：无业务依赖的共享 UI

## 命令

```bash
npm ci
npm run dev
npm run verify
npm run build
```

开发功能前先阅读根目录的架构、公共契约和 Week 1 计划。
