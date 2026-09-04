# 仓库瘦身报告：转为纯前端仓库

执行时间：2026-08-30
结果：**仓库从 1.8GB 降至 488MB，Git 追踪文件从 3800+ 降至 53**

## 一、最终保留

```text
.
├── .git/                   # 版本历史（含全部已删内容，可回滚）
├── .workbuddy-ai/          # 会话记忆与本报告
├── frontend/               # ★ 完整前端，一个文件未删
├── .gitignore              # 已精简为纯前端规则
├── .impeccable.md          # 前端设计规范
├── .nvmrc                  # Node 22
├── README.md               # 已重写为纯前端 + 后端对接指南
└── THIRD_PARTY_NOTICES.md  # 已精简为前端依赖声明
```

`frontend/` 内完整保留：`src/`（27 个源文件）、`node_modules/`、`package.json`、`package-lock.json`、
`vite.config.ts`、`vitest.config.ts`、`tsconfig*.json`、`eslint.config.js`、`.prettierrc.json`、`.prettierignore`、
`index.html`、`.env.example`、`dist/`、`README.md`。

## 二、已删除

| 路径 | 体积 | 文件数 | 类别 |
|---|---|---|---|
| `backend/` | 627MB | 224（含 .venv 515MB） | 后端全部（FastAPI + LangGraph Pipeline + 测试） |
| `eval/` | 828MB | 3174 | LLM 评测框架与 trace 转储 |
| `test_output/` | 39MB | 274 | 调试脚本与测试产物 |
| `skills/` | 592KB | 54 | 19 个问财技能包 |
| `docs/` | 560KB | 25 | 架构/计划/评测文档 |
| `data/` + `backend/data/` | 125MB | 4 | 运行时 SQLite |
| `backend/artifacts/` | 2.9MB | 41 | 运行产物 |
| `contracts/` | 36KB | 7 | API JSON Schema 契约副本 |
| `production/`、`config/`、`scripts/`、`4youh`、`.python-version` | ~250KB | 6 | 日志、MCP 配置、校验脚本、残留文件 |
| `__pycache__`、`.DS_Store` | ~2MB | 137 | 缓存与系统垃圾 |

**删除合计：约 1.62GB / 3930 个文件**

## 三、删除前的安全措施

1. **Git 快照**：删除前执行 `git add -A && git commit`，工作区零未跟踪文件。
2. **可恢复性已验证**：`backend/`（224 文件）、`eval/`（3173 文件）、`docs/`（25 文件）等均存在于历史提交
   `a5812d9` 与 `35da27e`，随时可用 `git checkout <commit> -- <path>` 取回。
3. 删除方式：大目录在上一会话中移除并已入 Git；本轮剩余项（`contracts/`、`.DS_Store`）移入
   `~/.Trash/a17-cleanup-20260830-212203`，未使用 `rm -rf`。

## 四、顺带修复的问题（与"对接外部后端"直接相关）

### 1. `VITE_API_BASE_URL` 形同虚设（真实坑）
`.env.example` 声明了该变量，但 `src/api/http.ts` 把 `baseURL: '/api/v1'` 写死，全项目无任何地方读取它。
→ 已改为 `import.meta.env.VITE_API_BASE_URL?.trim() || '/api/v1'`，并在 `src/env.d.ts` 补 `ImportMetaEnv` 类型。

### 2. Vite 代理目标硬编码
`vite.config.ts` 里 `target: 'http://localhost:8000'` 写死。
→ 改为从 `loadEnv` 读 `VITE_PROXY_TARGET`，默认仍是 `localhost:8000`。

### 3. `node_modules/.bin` 执行权限丢失
27 个 shim 权限为 666（应为 755），导致 `vue-tsc`、`vite` 报 `Permission denied`，`npm run build` 直接失败。
→ 已 `chmod +x` 全部修复。

### 4. `.env.example` 重写
补充两种对接模式的注释：模式 A（Vite 代理，后端无需 CORS）、模式 B（直连，后端需开 CORS + 放行 Authorization）。

## 五、验证结果

| 检查项 | 命令 | 结果 |
|---|---|---|
| 类型检查 | `npm run type-check` | 通过 |
| 生产构建 | `npm run build` | 通过，10.75s，2317 模块，产物 `dist/` |
| 代码规范 | `npm run lint` | 通过，0 warning |
| 单元测试 | `npm run test` | 通过（项目暂无测试文件） |

## 六、对接新后端的检查清单

1. `cp frontend/.env.example frontend/.env.local`，按模式 A 或 B 填后端地址。
2. 比对 `frontend/src/api/types.ts` 与新后端 schema 的字段名是否一致（7 个端点）。
3. 确认新后端 `CORS_ORIGINS` 放行前端源，或走 Vite 代理。
4. 确认新后端 `API_BEARER_TOKENS` 已配置；前端 Token 存 `localStorage['trc:token']`，401 时弹窗重录。
5. `npm run dev` 后检查 `/health/ready`。
