# 环境配置与启动说明

> **本文件是唯一的部署入口。** 请严格按顺序操作。
> 90% 的启动失败都出在第 3 节「环境变量配置」，若报错请直接跳到 **第 6 节 排查表**。

---

## 1. 前置要求

| 组件 | 版本要求 | 说明 |
|---|---|---|
| Python | **≥ 3.10**（推荐 3.13） | 后端 FastAPI 与五个智能体 |
| Node.js | **≥ 22 且 < 27** | 前端 `package.json` 里 `engines` 的硬要求，版本不符会装不上依赖 |
| npm | ≥ 10 | 随 Node 22 一起安装 |
| 网络 | 可访问外网 | 需连通「大模型服务」与「同花顺问财 OpenAPI」 |
| 可用端口 | **8000**（后端）、**5173**（前端） | 被占用时 `start_system.sh` 会尝试自动释放 |

检查版本：

```bash
python3 --version     # 应 >= 3.10
node --version        # 应 v22.x ~ v26.x
npm --version         # 应 >= 10
```

---

## 2. 目录结构

```
行业研究智能体-全链路系统/
├── backend/            FastAPI 服务 + 状态机调度引擎（run_server.py 为启动入口）
├── frontend/           Vue 3 + Vite + ECharts 前端工作台
├── agents_core/        五个智能体的算法核心
│   ├── data-fetcher/       ① 数据获取
│   ├── data-analysis/      ② 数据解读
│   ├── chart-generator/    ③ 图表生成
│   ├── chapter-writer/     ④ 分章节撰写
│   └── report-fusion/      ⑤ 报告融合
├── eval/               评测用例与运行脚本
├── scripts/            各类运行 / 诊断脚本
├── .env.example        后端环境变量模板  ← 复制成 .env
├── frontend/.env.example 前端环境变量模板 ← 复制成 frontend/.env
├── requirements.txt    后端 Python 依赖
└── start_system.sh     一键启动脚本
```

---

## 3. 环境变量配置（**最容易出错的一步**）

### 3.1 后端：`./.env`

```bash
cp .env.example .env
# 然后用编辑器打开 .env，把下面标「必填」的两项换成你自己的真实凭证
```

| 变量 | 必填 | 默认值 | 说明 |
|---|:-:|---|---|
| `LLM_API_KEY` | ✅ **必填** | — | 大模型密钥。支持任何 OpenAI 兼容接口（火山引擎方舟 / DeepSeek 官方 / 硅基流动 / Ollama 等） |
| `LLM_BASE_URL` | ✅ **必填** | `https://ark.cn-beijing.volces.com/api/plan/v3` | 大模型接口地址。**换服务商时必须同步改这里**，否则会报 401 / 404 |
| `LLM_MODEL` | | `deepseek-v4-flash` | 模型名。**要与所连服务商支持的模型名完全一致** |
| `LLM_REASONING_EFFORT` | | `low` | 推理强度，`low` / `medium` / `high` |
| `LLM_TIMEOUT_SECONDS` | | `180` | 单次请求超时（秒）。网络慢时可调大 |
| `LLM_MAX_TOKENS` | | `16384` | 单次最大输出 token |
| `IWENCAI_API_KEY` | ✅ **必填** | — | 同花顺问财 SkillHub 凭证。**数据获取智能体强依赖，缺失时第一阶段直接失败** |
| `IWENCAI_BASE_URL` | | `https://openapi.iwencai.com` | 问财接口地址 |
| `IWENCAI_API_KEY_BACKUP` | | 空 | 备用问财凭证，可留空 |
| `SKILL_CONCURRENCY_LIMIT` | | `7` | 技能并发数。调大更快，但可能触发上游限流 |
| `CHAPTER_CONCURRENCY` | | `7` | 章节并发数。同上 |
| `IMAGE_API_KEY` | | 空 | 产业链 **AI 配图**密钥。**留空即跳过 AI 生图**，不影响报告产出（见 3.3） |
| `IMAGE_BASE_URL` / `IMAGE_MODEL` / `IMAGE_SIZE` / `IMAGE_TIMEOUT_SECONDS` / `IMAGE_EXTRA_FIELDS` | | 空 | 仅在启用 AI 配图时需要 |
| `ENABLE_INDUSTRY_CHAIN_IMAGE` | | `0` | **产业链 AI 配图总开关，默认 0（关闭）** |

### 3.2 前端：`./frontend/.env`

```bash
cp frontend/.env.example frontend/.env
```

| 变量 | 默认值 | 说明 |
|---|---|---|
| `VITE_PROXY_TARGET` | `http://localhost:8000` | **模式 A（推荐）**：走 Vite 代理。后端换端口/换机器时只改这一行 |
| `VITE_API_BASE_URL` | `/api/v1` | 模式 A 下**不要改** |
| `VITE_APP_TITLE` | `同花顺问财SkillHub` | 页面标题 |

> 模式 B（前端直连后端）：注释掉 `VITE_PROXY_TARGET`，取消注释 `VITE_API_BASE_URL=http://<后端地址>:8000/api/v1`。
> ⚠️ 此模式下后端必须开启 CORS 并放行 `Authorization` 头，否则浏览器会拦掉所有请求。

### 3.3 关于「产业链 AI 配图」

系统有**两条**产业链图路径，默认只走第 1 条：

1. **本地确定性 ECharts 渲染**（默认，始终可用）——上中下游三栏 + 代表企业 + 证据注，零外部依赖，节点可被报告融合阶段逐点校验。
2. **AI 生图**（默认关闭）——需同时满足 `ENABLE_INDUSTRY_CHAIN_IMAGE=1` **且** `IMAGE_API_KEY` 非空才会启用。单次耗时可达数分钟，且产出的是位图，无法逐点校验。

**不配置 `IMAGE_API_KEY` 完全不影响报告产出**，报告、图表、PDF 都会正常生成。

### 3.4 两条必须知道的规则

- 📌 **`.env` 必须位于项目根目录**（即与 `requirements.txt` 同级）。配置文件是按固定相对路径查找的，放到别处会静默读不到 → 表现为"密钥明明填了却说没配置"。
- 📌 **改完 `.env` 必须重启后端**才生效。进程启动时读一次环境变量，运行中改文件不会热加载。

---

## 4. 安装依赖

### 4.1 后端

```bash
cd 行业研究智能体-全链路系统
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4.2 前端

```bash
cd frontend
npm install
```

> 💡 **国内网络建议先换镜像源**，否则极易卡住：
> ```bash
> npm config set registry https://registry.npmmirror.com
> ```
> 若 `npm install` 长时间停在 `warn deprecated` 之后不再有输出，多半是网络问题而非真的卡死，
> 可换源或改用 `npm install --registry=https://registry.npmjs.org` 重试。

---

## 5. 启动

### 方式一：一键启动（推荐）

```bash
bash start_system.sh
```

脚本会自动完成：环境检查 → 释放 8000/5173 端口 → 启动后端 → 等待 `/health` 就绪 → 启动前端。
按 `Ctrl+C` 可一键停止前后端全部服务。

| 入口 | 地址 |
|---|---|
| 前端工作台 | http://localhost:5173 |
| 后端接口 | http://localhost:8000/api/v1 |
| 接口文档（Swagger） | http://localhost:8000/docs |

### 方式二：分开启动（便于看日志）

```bash
# 终端 1 —— 后端
cd 行业研究智能体-全链路系统
export PYTHONPATH="$PWD:$PWD/agents_core/data-fetcher:$PWD/agents_core/data-analysis:$PWD/agents_core/chart-generator:$PWD/agents_core/chapter-writer:$PWD/agents_core/report-fusion"
python backend/run_server.py

# 终端 2 —— 前端
cd frontend && npm run dev
```

---

## 6. 常见配置错误排查

| 现象 | 根本原因 | 解决 |
|---|---|---|
| 后端启动即报 `KeyError` / 密钥为空 | `.env` 不存在，或放错目录 | 确认 `.env` 在**项目根目录**，且字段名与 `.env.example` 完全一致（**区分大小写**） |
| 调用大模型返回 **401** | `LLM_API_KEY` 错误，或 key 与 `LLM_BASE_URL` 不属同一家服务商 | 核对 key 与 base_url 是否配套 |
| 调用大模型返回 **404 / model not found** | `LLM_MODEL` 名字与服务商不匹配 | 换成该服务商真实支持的模型名 |
| 第一阶段（数据获取）直接失败 | `IWENCAI_API_KEY` 缺失或失效 | 补全问财凭证；确认 `IWENCAI_BASE_URL` 可访问 |
| 前端页面打开但**所有请求 404** | `frontend/.env` 缺失，或 `VITE_PROXY_TARGET` 指错后端 | `cp frontend/.env.example frontend/.env`，确认 `VITE_PROXY_TARGET` = 后端实际地址 |
| 前端请求被浏览器 **CORS** 拦截 | 用了模式 B（直连）而后端未开 CORS | 改回模式 A（走 Vite 代理），或后端放行来源与 `Authorization` 头 |
| `npm install` 报引擎不兼容 | Node 版本不在 `>=22 <27` | 升级/切换 Node 版本 |
| 端口被占用 | 上次未正常退出 | `lsof -ti:8000 \| xargs kill -9`；或直接用 `start_system.sh`（脚本会自动释放） |
| **改了 `.env` 但行为没变** | 后端进程仍在用旧环境变量 | **重启后端** |
| 报告里没有"产业链 AI 配图" | 这是**预期行为**（默认关闭） | 需要时置 `ENABLE_INDUSTRY_CHAIN_IMAGE=1` 并配置 `IMAGE_API_KEY` |

---

## 7. 验证清单

启动成功后，按顺序确认：

- [ ] `curl http://localhost:8000/health` 返回正常
- [ ] 打开 http://localhost:8000/docs 能看到接口文档
- [ ] 打开 http://localhost:5173 能看到首页
- [ ] 首页新建一个任务（如"低空经济"），能正常提交
- [ ] 工作台能看到五个阶段的执行轨迹
- [ ] 跑完后能在报告预览页看到正文、图表与来源索引

---

## 8. 可选：命令行跑完整流水线（不依赖前端）

```bash
# 全自动跑完五个阶段（不设人工审核门）
python scripts/run_pipeline_auto.py --topic "低空经济" --depth overview
```

- `--depth` 可选 `overview`（最快）/ `standard` / `deep`
- 产物落在 `data/runs/<run_id>/artifacts/`：`report.md`、`report.html`、`report.pdf`、`charts/`
- 脚本结束时会打印 `RUN_ID=` 与产物清单
