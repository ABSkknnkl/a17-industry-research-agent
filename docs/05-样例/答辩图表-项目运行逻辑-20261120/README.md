# A17 项目运行逻辑 · 答辩图册（单文件 HTML 版）

生成日期：2026-11-20

## 这套文件是什么

把同花顺 A17「五阶段多智能体行业研报系统」的运行逻辑，拆成 **1 张总图 + 5 张智能体分图 + 1 张框架答案页**，用于答辩讲解、PPT 插图和技术交接。

所有图统一按 **16:9 / 1600×900** 设计，PNG 导出为 **3200×1800（2x）**，投影和打印都够清晰。

## 文件清单

| 文件 | 用途 |
|---|---|
| `A17项目运行逻辑-答辩讲解.html` | 单文件讲解页：7 张图已内嵌，含大白话解释、30–60 秒讲解词、答辩追问 |
| `png/00-总览与框架.png` | 先回答“用了什么框架”，再给五段总览 |
| `png/01-总体框架.png` | 总体框架：前端 / FastAPI / 状态机 / 适配器 / 五智能体 / 底座 |
| `png/02-A1-数据获取.png` | A1 输入 → 7 步 → 输出 → 协作关系 |
| `png/03-A2-数据解读.png` | A2 输入 → 7 步 → 输出 → 协作关系 |
| `png/04-A3-图表生成.png` | A3 输入 → 7 步 → 输出 → 缺数回补闭环 |
| `png/05-A4-章节撰写.png` | A4 输入 → 7 步 → 输出 → 协作关系 |
| `png/06-A5-报告融合.png` | A5 输入 → 7 步 → 输出 → 交付门禁 |
| `svg/` | 同名矢量版，放大不糊，可改字改色 |
| `make_diagrams.py` | 生成全部 SVG 的源码 |
| `render_png.py` | 把 SVG 渲染成 2x PNG 的脚本 |
| `答辩串讲词-4分钟.md` | 打印用串讲词，含 3 分钟压缩版和追问速答 |

## 怎么用

1. **答辩现场**：双击 `A17项目运行逻辑-答辩讲解.html`，点任意一张图可全屏放大；按 `Esc` 关闭。图片已内嵌，单文件即可查看；下载 PNG / 打开 SVG 仍指向同目录原文件。
2. **做 PPT**：直接把 `png/` 里的图拖进幻灯片，每张占一页，16:9 不用裁。
3. **要改图**：改 `make_diagrams.py` 里的文字/坐标，重新运行：
   ```bash
   /path/to/a17-industry-research-agent/.venv/bin/python make_diagrams.py
   /path/to/a17-industry-research-agent/.venv/bin/python render_png.py
   ```
   也可以直接改 `svg/` 里的矢量文件。

## 图序与讲解重点

- **00 总览与框架**：回答“用了什么框架”——没有用 LangGraph / CrewAI / AutoGen，用的是 FastAPI + 自研状态机 + 五个独立 Python 包。
- **01 总体框架**：谁调用谁、按什么顺序、数据怎么流、人在哪里插手。
- **02 A1 数据获取**：先列验收清单，再按清单去问财取数；缺的补，补不到留缺口。
- **03 A2 数据解读**：先把数算死（CAGR / 杜邦 / 三表勾稽 / 对标 / 异常 / 敏感性），再让模型解释；结论逐条挂证据。
- **04 A3 图表生成**：先验数据点有没有证据，再决定画什么图；缺数发 `data_demands`，回 A1 补采、A2 重算。
- **05 A4 章节撰写**：7 章 21 节并发写，逐段过数字与引用审计；不自算新数、不引池外证据、不自编图号。
- **06 A5 报告融合**：合稿 + 四维一致性审计 + 三格式导出；全通过才正式下载 200，有硬伤只给受限草稿 409。

## 一句话框架结论

> 这个项目没有用现成的 Agent 框架。前端 Vue 3，后端 FastAPI，核心是自研的 StateMachine + FiveAgentsAdapter；五个智能体是五个独立 Python 包，只通过 `data/runs` 里的产物文件交接。这样做的原因是金融研报要求：阶段能停、版本能回、失败能重跑、每个数字能对账。

## 对应代码位置

- 总图 / 编排：`backend/app/engine/state_machine.py`、`backend/app/agents/adapters.py`、`backend/app/core/event_hub.py`
- A1：`agents_core/data-fetcher/data_fetcher/agent.py`、`fusion.py`、`dynamic_probe.py`、`agents_core/chain-research/`
- A2：`agents_core/data-analysis/data_interpreter/engine.py`、`sensitivity.py`、`agent.py`
- A3：`agents_core/chart-generator/chart_generator/agent.py`、`selection.py`、`metric_guard.py`、`render.py`
- A4：`agents_core/chapter-writer/chapter_writer/agent.py`、`outline.py`、`retriever.py`
- A5：`agents_core/report-fusion/report_fusion/agent.py`、`appendix.py`、`pdf.py`、`render.py`
