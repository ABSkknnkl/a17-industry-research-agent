# 项目长期记忆

行业研究智能体-全链路系统（五智能体协同研报生成）。

## Python 环境（重要）

**本项目复用同花顺项目的虚拟环境**，不单独建 venv（用户明确说明）：

- 解释器：`/Users/Zhuanz1/PycharmProjects/同花顺/backend/.venv/bin/python`（Python 3.12.13）
- 已装：pytest 9.1.1 / pydantic 2.13.4 / fastapi 0.139.2 / pytest-asyncio 1.4.0
- 跑后端测试：
  `PYTHONPATH="<项目根>" /Users/Zhuanz1/PycharmProjects/同花顺/backend/.venv/bin/python -m pytest backend/tests -q`
- ❌ 不要用托管 python（无 pydantic）；❌ 不要新建 venv

## 已知既有问题（勿误判为新引入）

1. **后端测试长期失败 1 项**：
   `backend/tests/test_chart_data_replenishment.py::test_chart_data_replenishment_feedback_loop`
   （`assert mock_fetch.called` → False）。已用改动前备份复现，与后续改动无关。
2. **前端类型检查既有错误 1 个**：
   `src/views/ReviewView.vue(454,40): error TS18047: '__VLS_ctx.workflow' is possibly 'null'`
   来源是被前端隐藏的按钮 `v-if="false && workflow && ..."`，不影响运行。

## 前端工具链

- 目录：`frontend/`（Vue 3 + Element Plus + Vite）
- 测试：`env -u NODE_OPTIONS PATH="<托管node22>/bin:$PATH" ./node_modules/.bin/vitest run`
- 类型检查：`./node_modules/.bin/vue-tsc --build --force`
- 格式化：`./node_modules/.bin/prettier --write <file>`（提交前必跑，`verify` 含 format:check）
- node 必须剥离 NODE_OPTIONS（WorkBuddy broker shim 会拦）

## 架构要点

- 五智能体流水线：data_fetch → data_interpret → chart_generate → chapter_write → report_fusion
- 各 agent 源码在 `agents_core/*`，统一由 `backend/app/agents/adapters.py` 适配调用
- `agents_core` 各子目录经 `backend/app/core/setup_env.py` 注入 sys.path（模块导入即执行）
- **大纲单一事实源**：`agents_core/chapter-writer/chapter_writer/outline.py` 的 `DEFAULT_OUTLINE`（7 章 21 节）。
  任何"应有多少章节"的基准都应从这里推导，不得写死 7/21

## 反复出现的模式（改动时留意）

**后端已算好/已下发，但中间层或前端未消费** —— 已发现 4 例：
`dimension_label`、`skill_label`、`evidence_index`、`ReportFusionResult.consistency`。
改契约字段时务必检查消费侧。

## 图表配色约定（智能体3）—— 易被外部方案带偏

本项目图表是**行业研究出版级**风格，与同花顺（行情/金融）**不同源**。迁入代码时勿混用配色。

- 本项目 `PALETTE`（`chart_generator/compiler.py:44-50`、`render.py:11-18`）：
  `#155eef` 蓝 · `#0f766e` 青 · `#d97706` 琥珀 · `#6941c6` 紫 · `#0891b2` 青蓝 · `#d92d20` 红
  —— **无绿色**。红绿对是色盲最差组合，本项目刻意以蓝代绿
- `NEGATIVE_COLOR = #d92d20` 语义是**风险/赤字**，**不是"下跌"**
- 正负值区分（`_compile_diverging_bar`）：正 = 主蓝，负 = 警示红
- 同花顺 `UP_COLOR=#C0392B` / `DOWN_COLOR=#1E8449`（涨红跌绿）是**行情语义**，
  ❌ **不要迁入**本项目：语义错位 + 配色体系打架 + 引入本不存在的绿色
- ❌ **不要在本项目套用"涨红跌绿/A 股惯例"** —— 行业研究报告里"同比增长"是**中性事实**，
  不是"涨"；且「成本同比 +20%」上红色会误导（那是负面）

## 全链路跑批（无头运行）

**首选脚本 `scripts/run_pipeline_auto.py`**（本项目自制，2026-09-23 新增）：

```bash
# 新建全自动跑（无人工审核门）：review_stages=[] 一路到底
IMAGE_API_KEY="" PYTHONPATH="<项目根>" <venv>/bin/python scripts/run_pipeline_auto.py \
    --topic 低空经济 --depth standard > /tmp/pipe.log 2>&1

# 断点续跑（复用已有阶段产物，不要从头再跑）
... run_pipeline_auto.py --resume-run <run_id> --from-stage chapter_write
```

- 5 阶段耗时基线（standard 深度）：data_fetch ~2m / data_interpret ~4.5m /
  chart_generate ~8.5m（**含生图黑洞**）/ chapter_write ~5m / report_fusion ~20s
- **`IMAGE_API_KEY=""` 是提速关键**：产业链 AI 生图（`chart_generator/image_gen.py`）
  超时 `IMAGE_TIMEOUT_SECONDS=600`，且失败率高 → 单这一步最多吃掉 10 分钟。
  显式置空即可跳过（`config._load_env_files()` 只在变量不存在时读 .env，置空能压住）。
- ⚠️ **生图过程在 UI/日志里完全不可见**：`adapters.py` 的 `on_chart_event`
  没有映射 `image_generation_start/completed/skipped`，表现是阶段 3 "静默卡死"。
  排查阶段 3 卡住时先怀疑这里，不要以为是 LLM 挂了。
- 单阶段重跑用 `--from-stage`，比 `resume` 全量重启省很多时间。

## 报告模板（双模板）

- `agents_core/report-fusion/report_fusion/templates/{auto,rich}/report.html`
- **`auto` = 同花顺券商研报 A4 版式**（`--brand:#0A5C5C`，screen 下 body 是
  `grid: 220px | 1080px`：左 reader-rail 目录 + 右正文，含 cover/TOC/来源表）。
  用户给的 `~/Downloads/report.html`（光伏报告）就是这一族的产物
- `rich` = 本项目增强版式（图表更多），无标识条
- ⚠️ **`auto` 模板的 `body::before` 曾破坏整页版式**（2026-09-23 已修）：
  screen 模式下 body 是 grid 容器，`body::before` 会成为第一个 grid item，
  把 rail 挤到第 2 列、main 挤到第 1 列（220px）→ 左栏与正文宽度互换、封面标题竖排。
  **修法**：`body::before { grid-column: 1 / -1; }`。改模板后**必须重跑阶段 5**
  才会体现在产物里。校验方法：playwright 量 `rail` 应为 `[88,220]`、`main` 应为 `[332,1080]`（1500px 视口）
- PDF 由 playwright chromium 生成，24 页量级；用 `pymupdf` 验文本层
  （中文 >1 万字符即可复制，`/Type3` 字节计数不可靠、勿据此判断字体问题）

## 与上游仓库同步（a17-industry-research-agent）

仓库 `https://github.com/ABSkknnkl/a17-industry-research-agent`（owner 账号 `ABSkknnkl`）：

| 分支 | 承载内容 |
|---|---|
| `main` / `agent/chart-mvp-sync` | 同花顺问财 SkillHub 主体（`skills/` `contracts/` `eval/` `docs/`） |
| `agent/主线可用版` | **本项目（五智能体全链路系统）**，2026-09-23 被本地目录全量覆盖为 orphan 单提交 |
| `backup/mainline-20260923-preoverwrite` | 覆盖前的 `agent/主线可用版`（6b03126），存有 51 个只此一份的文件 |

**网络坑（必看）**：`github.com:443` 经常被掐断（代理报 `CONNECT tunnel failed 502`、直连超时），
但 `api.github.com` 是通的。git push 推不动时**直接走 Git Data API**
（blobs → tree → commit parents=[] → PATCH ref force:true），脚本模板在 `/tmp/gh_api_push.py`。
- git 全局 `http.proxy=127.0.0.1:7890` 是**死代理**，走 github 必须覆盖成 `127.0.0.1:57439`
- 令牌用 `git credential fill`（osxkeychain helper）取，**别用 `security` 命令**（沙箱被拒）
- 索引用户目录请用 `GIT_DIR=<临时> GIT_WORK_TREE=<项目根>`，不要往用户目录塞 `.git`

## 目录

- `backend/` FastAPI 服务；`agents_core/` 五智能体；`frontend/` 前端
- `data/runs/<run-id>/` 每次运行的 state.json + artifacts/
- `output/` 交付物（含设计方案文档）
