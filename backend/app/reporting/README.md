# Reporting

渲染层不承载 LLM 逻辑。`svg.py` 将已校验 ECharts Option 转为离线 SVG，`markdown.py` 和 `html.py` 消费同一视图模型，`pdf.py` 使用 Playwright Chromium 打印自包含 HTML。浏览器运行文件安装在部署环境，不进入 Git。

安全约束：Jinja2 全局开启自动转义，仅项目内部 SVG 可跳过转义；HTML 不请求 CDN、字体或其他外部资源。
