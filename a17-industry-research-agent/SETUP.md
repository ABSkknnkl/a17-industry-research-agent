# 环境配置与启动

本文适用于 2026-10-31 合并后的项目。先在终端进入本文件所在的项目目录。

## 环境和安装

需要 Python 3.11+、Node.js 22–26、npm 10+；需要实际调用时还需能够访问配置的大模型、问财及所选搜索服务。

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
cd frontend && npm ci && cd ..
```

已有 `.venv` 和 `frontend/node_modules` 且依赖可用时，可直接使用。浏览器依赖用于 PDF 渲染；前端浏览器测试使用系统 Chrome。

## 配置

首次配置时将 `.env.example` 复制为 `.env`，填写对应服务的 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL` 和 `IWENCAI_API_KEY`。**不要覆盖已有 `.env`。**具体配置见模板；可选产业链搜索和生图还需对应开关与服务配置。

也可以在前端设置页面保存模型与问财配置，设置写入 `data/user_settings.json` 并应用到当前进程。环境变量、`.env` 与界面设置可能同时存在；修改 `.env` 后需重启后端，已保存的界面设置也可能影响最终值。请勿将凭证、`user_settings.json` 和运行产物提交到代码仓库。

`CHAIN_ENGINE=evidence_v2` 使新建任务选择产业链 v2；未设置时走 legacy。主图采用确定性 SVG；可选 HTML 截图或 AI 位图受配置、模型和环境影响。当前后端默认模型超时为 180 秒；长任务可根据服务情况调整，交接记录建议考虑 600 秒。

## 启动

```bash
./start_system.sh
```

脚本会**强制释放 8000 和 5173 端口**，并启动前后端；请先确认端口用途。退出时按 `Ctrl+C`。若不希望脚本释放端口，可分别启动：

```bash
# 终端 1：项目目录
.venv/bin/python backend/run_server.py

# 终端 2：项目目录
cd frontend
npm run dev
```

默认入口：前端 <http://localhost:5173>；API <http://localhost:8000/api/v1>；交互式接口文档 <http://localhost:8000/docs>。健康检查可用 `curl --noproxy '*' http://localhost:8000/health`。

前端开发代理默认转发到 `http://localhost:8000`。需要改变代理目标时，在 `frontend/.env.local` 中设置 `VITE_PROXY_TARGET`；前端同源 API 基址默认 `/api/v1`。直接连接其他后端时设置完整的 `VITE_API_BASE_URL`，并确认后端 CORS 配置。

**网络边界：**当前后端未配置统一身份认证，设置接口会返回配置中的密钥，默认主机监听和 CORS 配置也较宽；请不要直接暴露到公网或不受信任网络。

## 验证与常见问题

```bash
.venv/bin/python -m pytest
cd frontend && npm run verify && npm run build
npm run test:e2e
```

默认 Python 测试排除 `live`；真实服务测试需单独选择并准备凭证。测试结果及上次离线验证范围见 [当前版本说明](docs/当前版本说明.md)。

- 模型 401 或 404：核对密钥、接口地址与模型名是否匹配。
- 数据获取失败：核对问财凭证、接口可用性和返回的数据覆盖。
- 前端无法连接：检查后端端口、代理地址与浏览器网络请求。
- PDF 失败：确认 Playwright Chromium 已安装，并查看融合阶段的实际告警；其他格式可能仍可用。
- 人工编辑融合报告后：旧 PDF 和旧质检会失效，需重新融合和质检；重新生成后要核对直接编辑的内容。
