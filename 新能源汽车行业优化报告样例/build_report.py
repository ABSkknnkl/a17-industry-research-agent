#!/usr/bin/env python3
"""Assemble the NEV A5 report from the white-liquor A5 CSS and section fragments."""
from pathlib import Path

BASE = Path(__file__).resolve().parent
style = (BASE / "a5_style.html").read_text(encoding="utf-8")
parts = []
for name in ["part1.html", "part2.html", "part3.html", "part4.html"]:
    parts.append((BASE / "sections" / name).read_text(encoding="utf-8"))

extra_css = """
<style>
code{font-family:'Times New Roman',serif;font-size:8.2pt;color:#595959;letter-spacing:0;}
ul.q-list{margin:2mm 0 3mm 5mm;padding:0;}
ul.q-list li{margin:1.4mm 0;line-height:1.42;}
.hf-value.compact{font-size:18pt;}
.new-page{break-before:page;}
.chapter-head h2{max-width:none;}
figure.chart img{max-height:100mm;}
</style>
"""

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>新能源汽车行业研究报告｜2021—2025</title>
{style}
{extra_css}
</head>
<body class="visual-deep-research density-detailed profile-modern_analysis table-header-solid report-mode-comprehensive archetype-data-led" data-chart-mode="auto" data-template-source="ths-broker-report">
<div class="report">
{''.join(parts)}
</body>
</html>
"""
(BASE / "report.html").write_text(html, encoding="utf-8")
print("report.html chars:", len(html))
