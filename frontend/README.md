# 同花顺问财 SkillHub — 前端（Vue 3 + Vite）

行业研究报告生成系统的人机协同前端：**报告工作台、流水线进度、图表画廊、人工审核、产物下载**。

本仓库**只包含前端**。后端为独立仓库/独立项目，通过 HTTP API 对接。

## 技术栈

| 类别     | 选型                                          |
| -------- | --------------------------------------------- |
| 框架     | Vue 3.5（`<script setup>` + Composition API） |
| 构建     | Vite 6、TypeScript 5.7、vue-tsc               |
| 状态     | Pinia 3                                       |
| 路由     | Vue Router 4                                  |
| UI       | Element Plus 2.9 + `@element-plus/icons-vue`  |
| 图表     | ECharts 6                                     |
| 请求     | Axios                                         |
| Markdown | marked                                        |
| 质量     | ESLint 9、Prettier 3、Vitest 3                |

## 快速开始

```bash
cd frontend
npm ci          # 或使用已安装的 node_modules 直接启动
npm run dev     # http://localhost:5173
```

其他脚本：

```bash
npm run build        # vue-tsc -b && vite build → frontend/dist
npm run type-check   # 仅类型检查
npm run lint         # ESLint，--max-warnings 0
npm run format       # Prettier 写入
npm run test         # Vitest
npm run verify       # 以上四项串起来跑
```

Node 版本要求 `>=22 <27`（见 `.nvmrc`）。

## 对接后端

### 模式 A：Vite 代理（推荐，开发环境）

后端无需开 CORS。复制环境变量模板后只改后端地址：

```bash
cp frontend/.env.example frontend/.env.local
```

```ini
VITE_PROXY_TARGET=http://<backend-host>:8000
VITE_API_BASE_URL=/api/v1
```

### 模式 B：前端直连（生产 / 跨域部署）

后端需开启 CORS 并放行 `Authorization` 头：

```ini
VITE_API_BASE_URL=http://<backend-host>:8000/api/v1
```

### 鉴权

所有业务接口要求 `Authorization: Bearer <token>`。前端把 Token 存在 `localStorage`（key `trc:token`），
收到 401 时自动清空并弹出 `TokenDialog` 重新录入。Token 由后端 `API_BEARER_TOKENS` 配置颁发。

### 依赖的接口契约

前端只依赖 `/api/v1` 下的 7 个端点，另有 3 个健康检查/文档端点：

| 方法 | 路径                                            | 用途                                  | 返回模型               |
| ---- | ----------------------------------------------- | ------------------------------------- | ---------------------- |
| POST | `/api/v1/runs`                                  | 创建任务（同步跑首阶段，超时 5 分钟） | `WorkflowState`        |
| GET  | `/api/v1/runs?offset&limit`                     | 任务列表                              | `RunListResponse`      |
| GET  | `/api/v1/runs/{run_id}`                         | 任务详情（轮询用）                    | `WorkflowState`        |
| GET  | `/api/v1/runs/{run_id}/revisions`               | 历史版本列表                          | `RevisionListResponse` |
| GET  | `/api/v1/runs/{run_id}/revisions/{revision}`    | 指定版本快照                          | `WorkflowState`        |
| POST | `/api/v1/runs/{run_id}/reviews`                 | 提交审核并推进下一阶段（超时 5 分钟） | `WorkflowState`        |
| GET  | `/api/v1/runs/{run_id}/artifacts/{artifact_id}` | 下载产物（md/html/pdf/json）          | 文件流                 |
| GET  | `/health`、`/health/ready`                      | 健康检查                              | —                      |
| GET  | `/docs`                                         | OpenAPI 文档                          | —                      |

TypeScript 侧的字段定义集中在 **`frontend/src/api/types.ts`**，换后端时以此文件比对字段是否一致。

错误响应：`detail` 为字符串或 `{ code, message }` 对象，前端在 `frontend/src/api/http.ts` 中统一归一化成 `ApiError`。

## 目录结构

```text
frontend/
├── index.html              # Vite 入口
├── vite.config.ts          # 构建 + /api 代理
├── vitest.config.ts
├── tsconfig*.json          # TS 配置（app / node / 根引用）
├── eslint.config.js
├── .prettierrc.json
├── .env.example            # 后端对接配置项
└── src/
    ├── main.ts             # 应用入口
    ├── App.vue
    ├── router.ts
    ├── style.css
    ├── api/
    │   ├── http.ts         # Axios 实例、鉴权拦截、错误归一化
    │   ├── client.ts       # 7 个后端端点封装
    │   └── types.ts        # ★ 与后端的数据契约
    ├── stores/auth.ts      # Token 持久化
    ├── composables/usePipelineOverlay.ts
    ├── views/              # HomeView / ReviewView / RunsView
    └── components/         # 报告、图表、审核、流水线、通用组件
```

## 设计约束

见 [`.impeccable.md`](.impeccable.md)：编辑式浅色排版、深蓝标题、等宽数字、一屏一重点、缺失数据明确写"未提供"而非推断。

## 说明

后端（FastAPI + LangGraph 五阶段 Pipeline）、评测框架、技能包与文档已从本仓库移除，仅保留在 Git 历史中（见 `35da27e` 及之前的提交）。
