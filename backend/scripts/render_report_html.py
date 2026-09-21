#!/usr/bin/env python3
"""把 Agent4 生成的演示报告（markdown）渲染为带研报送风格的 HTML。

无第三方依赖（内置库实现轻量 markdown 子集：# / ## / ### / 引用 / 有序列表 / 段落 / **加粗**）。
运行：cd backend && .venv/bin/python scripts/render_report_html.py
输入：backend/output/agent4-demo-report.md
输出：backend/output/agent4-demo-report.html
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD_PATH = os.path.join(BASE_DIR, "output", "agent4-demo-report.md")
HTML_PATH = os.path.join(BASE_DIR, "output", "agent4-demo-report.html")

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_LIST_RE = re.compile(r"^(\d+)\.\s+(.*)$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")

PAGE_CSS = """
:root { --navy: #1e3a5c; --gold: #a9853f; --ink: #333; --line: #e3ddd0; --paper: #f7f4ec; }
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--paper);
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  color: var(--ink);
}
.wrap { max-width: 860px; margin: 0 auto; padding: 40px 24px 64px; }
.page {
  background: #fff; border: 1px solid var(--line);
  outline: 3px double var(--navy); outline-offset: -8px;
  border-radius: 4px; padding: 48px 56px 40px;
}
.band { height: 4px; background: var(--navy); border-bottom: 2px solid var(--gold); margin: -48px -56px 32px; }
h1 {
  font-family: Georgia, "Songti SC", serif; font-size: 26px; color: var(--navy);
  letter-spacing: 1px; margin: 0 0 6px; text-align: center;
}
h2 {
  font-family: Georgia, "Songti SC", serif; font-size: 19px; color: var(--navy);
  border-left: 4px solid var(--gold); padding-left: 10px;
  margin: 30px 0 10px;
}
h3 {
  font-family: Georgia, "Songti SC", serif; font-size: 15px; color: var(--navy);
  margin: 18px 0 6px;
}
p { font-size: 14.5px; line-height: 1.95; margin: 8px 0; text-align: justify; }
ol { padding-left: 22px; margin: 8px 0; }
li { line-height: 1.8; font-size: 14.5px; }
blockquote {
  margin: 14px 0; padding: 10px 14px;
  border-left: 3px solid var(--gold); background: var(--paper);
  color: #666; font-size: 13px; line-height: 1.7;
}
em.tag { display: block; text-align: center; color: #8a8578; font-style: normal; font-size: 12px; margin-top: 10px; }
.footer { text-align: center; color: #9a9488; font-size: 12px; margin-top: 26px; }
"""


def _inline(text: str) -> str:
    return _BOLD_RE.sub(r"<strong>\1</strong>", text)


def md_to_html(md: str) -> str:
    parts: list[str] = []
    in_list = False
    quote_lines: list[str] = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            parts.append("</ol>")
            in_list = False

    def flush_quote() -> None:
        nonlocal quote_lines
        if quote_lines:
            body = " ".join(quote_lines)
            parts.append(f"<blockquote>{_inline(body)}</blockquote>")
            quote_lines = []

    for raw in md.split("\n"):
        line = raw.strip()
        if not line:
            close_list()
            flush_quote()
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            close_list()
            flush_quote()
            level = len(heading.group(1))
            parts.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue
        if line.startswith(">"):
            close_list()
            quote_lines.append(line[1:].strip())
            continue
        item = _LIST_RE.match(line)
        if item:
            flush_quote()
            if not in_list:
                parts.append("<ol>")
                in_list = True
            parts.append(f"<li>{_inline(item.group(2))}</li>")
            continue
        flush_quote()
        close_list()
        parts.append(f"<p>{_inline(line)}</p>")

    close_list()
    flush_quote()
    return "\n".join(parts)


def build_page(body_html: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>动力电池行业研究报告（智能体4 独立演示）</title>
<style>{PAGE_CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="page">
    <div class="band"></div>
    {body_html}
    <p class="footer">本页由智能体4（章节撰写）演示报告渲染 · 内容仅供流程验证，不代表投资建议</p>
  </div>
</div>
</body>
</html>
"""


def main() -> None:
    with open(MD_PATH, encoding="utf-8") as handle:
        markdown_text = handle.read()
    body = md_to_html(markdown_text)
    html = build_page(body)
    with open(HTML_PATH, "w", encoding="utf-8") as handle:
        handle.write(html)
    print(f"[render] HTML 已输出：{os.path.abspath(HTML_PATH)}（{len(html)} 字符）")


if __name__ == "__main__":
    main()