# Reporting

后端 C 维护渲染设施。包含 ECharts/pyecharts 配置、专用打印 HTML 模板、Playwright Chromium PDF 导出和版式测试，不承载 LLM 内容生成逻辑。导出前必须等待字体、图片、SVG、Canvas 和图表渲染完成；浏览器运行文件安装在部署环境，不进入项目仓库。
