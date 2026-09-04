# Third-Party Notices

本项目依赖的第三方软件由各自许可证授权。完整直接与传递依赖及准确版本以 `backend/requirements*.txt`、当前 Python 环境和 `frontend/package-lock.json` 为准。

主要项目包括：FastAPI、Pydantic、SQLAlchemy、LangChain、LangGraph、LangGraph SQLite Checkpointer、pandas、pywencai、pyecharts、Playwright、Chromium、Vue、Vite、Element Plus、Pinia、ECharts、Axios、ESLint、Prettier 与 Vitest。

团队成员复制第三方源码、Prompt、模板或媒体资源时，必须在本文件补充项目名称、原始地址、许可证、使用范围和修改说明；未知许可证内容不得合入。

## Pi Agent Harness

- 来源：https://github.com/earendil-works/pi（原`badlogic/pi-mono`）
- 许可证：MIT License
- 参考范围：`packages/agent/src/agent-loop.ts`中的回合停止检查、工具参数校验、before/after Hook、超时/错误结果回灌和生命周期事件顺序。
- 使用说明：项目未引入Pi依赖，也未复制TypeScript源码；现有`app/runtime/`是在LangGraph和Python 3.12上按相同治理顺序独立实现，并增加金融项目所需的脱敏事件与持久化预算。

## 问财 SkillHub：行为金融分析

- 来源：同花顺问财 SkillHub，技能 UUID `89fe55e5-bd73-4dfd-870a-aa85110f3294`
- 官方入口：https://www.iwencai.com/skillhub
- 安装包 SHA-256：`fe3a9582f2609685fd16b00e733ef0eef7f2351775d1852f87a935d387233a8a`
- 文件 SHA-256：`be52b6e482a9e135df0c144f48abed0b4a62298258fe3884aa8e1020a0773e30`
- 使用范围：仅作为 Agent 2 数据解读阶段的受控辅助知识，不执行其中示例代码，不直接采用固定阈值、收益概率、仓位或买卖建议。
- 修改说明：技能原文件保持不变；项目在外层增加证据分级、协同确认和投资建议禁用规则。
- 许可证：安装包未附许可证文件。正式提交或公开发布前必须向技能发布方确认再分发授权；未确认前不得将该技能文件纳入公开发行包。

## Agent 5 P0 架构参考

以下来源只用于理解架构、版式和质量模式，本项目没有直接复制其业务代码或 HTML 模板：

- Kami：https://github.com/tw93/Kami — 参考金融研报的信息层级、A4 分页和风险提示区域。
- codex-seo：https://github.com/AgriciDaniel/codex-seo — 参考 Playwright 打印就绪检查和 `page.pdf()` 导出参数。
- Apache ECharts：https://github.com/apache/echarts — 参考 ECharts Option 与 SVG 服务端静态化思路。
- pyecharts：https://github.com/pyecharts/pyecharts — 参考 Python 端 ECharts Option 数据结构。
- quant-report-writer：https://github.com/severin-spagnola/quant-report-writer — 参考单一结构化报告模型驱动多格式输出。
- dataprov：https://github.com/RI-SE/dataprov — 参考产物 SHA-256、文件大小和上游版本溯源。
- Jinja：https://github.com/pallets/jinja — 项目通过已声明的 Python 依赖使用其模板渲染和自动转义功能。

未来如需复制上述仓库中的任何文件，必须先锁定提交版本、核验许可证并在此记录修改范围。
