# Report Fusion

Agent 5 是确定性组装与导出节点，不调用 LLM，不新增金融事实。它消费 Agent 2—4 的结构化结果，生成 Markdown、自包含 HTML、Playwright Chromium PDF 与 SHA-256 产物清单。专业质量问题进入“未解决问题清单”并自动使用 `draft_with_warnings`，不再阻塞导出。

三种格式独立导出：任一格式失败只记录风险并保留其他成功产物。例如 Chromium/PDF 不可用时，Markdown 与 HTML 仍可交付。只有上游契约不可解析、没有可用核心结论、所有格式均失败或存储完全不可用才终止。

## P0 借鉴边界

| 来源 | 在本项目中落地的思路 |
|---|---|
| Kami | 券商研报风格的封面、摘要、章节分隔和打印层级；CSS 为本项目原创 |
| codex-seo | Playwright 导出前等待页面、字体和图片就绪，开启背景色和 CSS 页面尺寸 |
| Apache ECharts / pyecharts | 消费 Agent 3 已校验 Option，将 P0 `line/bar/pie/radar/industry_chain` 和已启用的 P1 图表静态化为内联 SVG，不依赖 CDN |
| quant-report-writer | 同一个 `ReportViewModel` 驱动 Markdown、HTML 和 PDF，避免多格式口径漂移 |
| dataprov | 导出前一致性质量门，导出后记录上游修订版本、字节数与 SHA-256 |
| Jinja2 | `StrictUndefined + autoescape=True`，只对项目内部生成的 SVG 标记为安全 |

借鉴的是架构与质量模式，不直接复制来源项目的业务代码或模板；后续引入任何第三方文件时必须先核验许可证。

## P0/P1研究质量升级

- Markdown和单文件HTML均新增“数据质量与研究边界附录”，统一展示维度覆盖、数据缺口、财务一致性检查和未生成图表原因；PDF沿用同一HTML视图。
- 输出新增`delivery_status`：无重要告警为`ready`，存在可交付限制为`ready_with_limits`；所有格式均失败时仍由阶段状态返回`failed`。
- 输出新增`report_depth`：`brief`保留执行摘要与七章摘要，`standard`为默认7章21节，`deep`保留完整正文和详细质量附录。
- 图表的分析目的、证据和数据脚注在HTML/PDF中共同展示，不依赖外部CDN。
