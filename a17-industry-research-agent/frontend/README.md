# 前端工作台

这是 A17 项目的 Vue 3 + Vite 前端，与同一项目中的 FastAPI 后端配合，提供任务创建、阶段审核、证据与图表查看、报告预览和下载。后端使用自研状态机。

## 启动

```bash
cd frontend
npm ci
npm run dev
```

默认前端地址为 <http://localhost:5173>。同时从项目目录运行 `.venv/bin/python backend/run_server.py` 启动后端。环境要求与完整步骤见 [项目部署说明](../SETUP.md)。

开发时 Vite 默认将 `/api` 代理到 `http://localhost:8000`。可在 `frontend/.env.local` 中设置 `VITE_PROXY_TARGET` 改变代理目标；前端 API 基址默认 `/api/v1`。如直接连接其他服务，设置完整的 `VITE_API_BASE_URL`，并核对后端 CORS。

前端可以保存并发送 Bearer Token，遇到 401 时会提示；当前项目后端未设置统一身份认证，不应把此前端行为当成服务端访问控制。设置接口会返回配置中的密钥，默认服务不应直接暴露到公网或不受信任网络。

## 操作

新建任务并选择审核阶段后，在工作台检查各阶段结果和来源；可提交审核、编辑或修订。报告编辑后，旧 PDF 和质检结果会失效；完整视图可先预览 Markdown/HTML，重新融合并质检后才可定稿和生成新 PDF。重新融合后需核对直接编辑的内容。

## 验证

```bash
npm run verify       # 类型检查、lint、格式检查与单元测试
npm run build        # 生产构建
npm run test:e2e     # 使用系统 Chrome
```

前端请求封装位于 `src/api/`，路由和组件位于 `src/router.ts`、`src/views/`、`src/components/`。后端完整接口以运行中的 `http://localhost:8000/docs` 和后端源码为准。上次离线测试结果见 [当前版本说明](../docs/当前版本说明.md)。
