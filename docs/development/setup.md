# 开发环境搭建

## 运行时

- Python 3.12（方案要求 3.11+，团队统一使用 3.12）
- Node.js 22 LTS
- npm 10+

成员应使用相同主版本。禁止提交 `.venv/`、`node_modules/`、`.env` 和生成报告。

## 后端

安装 Python 环境和 Playwright 配套 Chromium：

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
python -m playwright install chromium
cp .env.example .env
python -m pytest
uvicorn app.main:app --reload --port 8000
```

Chromium 默认安装在用户缓存中，不在项目目录内，不得提交到 Git。Linux CI/容器首次配置可使用`python -m playwright install --with-deps chromium`安装浏览器及系统依赖。

`requirements.txt` 是所有业务模块的共同运行环境；`requirements-dev.txt` 只包含测试和质量工具。

## 前端

```bash
cd frontend
npm ci
cp .env.example .env
npm run verify
npm run dev
```

## 环境变量

真实密钥只写入本地 `.env`：

- `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`
- `SKILLHUB_API_KEY`
- `DATABASE_URL`
- `ARTIFACT_ROOT`
- `CORS_ORIGINS`
- `API_BEARER_TOKENS`（JSON对象，格式为`owner_id: token`）
- `MAX_REQUEST_BODY_BYTES`、`RATE_LIMIT_WINDOW_SECONDS`
- `CREATE_RUN_RATE_LIMIT`、`REVIEW_RATE_LIMIT`

成员在尚未取得密钥时应使用 Mock 适配器，不得在代码中放测试密钥。

## 后端认证

`/health`和`/api/v1/ping`保持公开，任务创建、查询和审核必须使用Bearer Token。未配置`API_BEARER_TOKENS`时，受保护接口默认拒绝所有请求。

```bash
TOKEN="$(openssl rand -hex 32)"
# 把TOKEN写入backend/.env的API_BEARER_TOKENS，重启后端后调用：
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/runs/<run_id>
```

Token不得写入Git、URL、报告、提示词或日志。当前迭代按需只完成后端安全层；前端尚未接入Token输入和`401/403/413/429`交互。

## 全仓验证

```bash
./scripts/verify.sh
```
