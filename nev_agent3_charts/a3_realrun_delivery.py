#!/usr/bin/env python3
"""基于补齐后的上游数据，生成完整图表页与适配报告。

不改任何既有业务代码与产物；仅在运行时把 chart_data 的数据源指向补齐版
A1/A2 副本，复用既有 9 个图表实现逐张出图。

产物：index_adapted.html（完整图表 + 报告正文）、ADAPTATION_REPORT.md
"""

from __future__ import annotations

import json
from pathlib import Path

import chart_data as cd
import charts
import render_preview as rp

ROOT = Path(__file__).resolve().parent
APP = ROOT.parent / "a17-industry-research-agent"
PATCHED = APP / "output/a3_upstream_adaptation/patched_run/artifacts/dataset.json"
SELECTION = ROOT / "llm_selection_result.json"
PLAN = ROOT / "chart_plan.json"
MANIFEST = APP / "output/a3_upstream_adaptation/adaptation_manifest.json"
UNIT_DECL = APP / "output/a3_upstream_adaptation/unit_declarations.json"

HTML_OUT = ROOT / "index_adapted.html"
MD_OUT = ROOT / "ADAPTATION_REPORT.md"


def inject_patched_dataset() -> dict:
    """运行时替换数据源：不改 chart_data.py 文件。"""
    data = json.loads(PATCHED.read_text(encoding="utf-8"))
    cd.DATASET_PATH = PATCHED
    cd.load_dataset = lambda: data
    cd.all_evidence_ids.cache_clear()

    # 补齐后渗透率跨年，原按「X月」命名会重名；改为「YYYY-MM」标签（运行时覆盖）
    def penetration_patched():
        rs = cd.records("industry", cd.M_PENETRATION, entity="中国")
        labels = [f"{r['period_end'][:4]}-{int(r['period_end'][5:7]):02d}" for r in rs]
        t = cd.NormalizedChartTable(
            categories=labels,
            series_data={"国内零售渗透率": [cd._value(r) for r in rs]},
            series_units={"国内零售渗透率": "%"},
            primary_series_name="国内零售渗透率",
            evidence_ids=cd._ids(rs),
            unit="%",
            footnotes=[
                cd.UNIT_NOTE_PENETRATION,
                "本轮真实重新取数补回 2021-02 起的月度零售渗透率观测；仍为月度零售口径，"
                "不得当作年度全口径渗透率序列或据此计算年度同比。",
            ],
            axis_type="category",
        )
        return t

    cd.penetration_2025 = penetration_patched
    return data


def build_options() -> tuple[list[dict], dict]:
    record = json.loads(SELECTION.read_text(encoding="utf-8"))
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    specs = {s["chart_id"]: s for s in plan["charts"]}
    chosen = record["selection"]["charts"]
    declared = record["selection"]["chart_count"]
    options = []
    for item in chosen:
        cid = item["chart_id"]
        spec = json.loads(json.dumps(specs[cid], ensure_ascii=False))
        fn, ctype = charts.CHARTS[cid]
        assert ctype == item["chart_type"] == spec["chart_type"]
        if cid == "C02":
            spec["title"] = ("国内零售渗透率月度观测序列（2021—2025）："
                             "高位平台与口径混杂说明")
        option = fn(spec)
        options.append(option)
    assert len(options) == declared == len(chosen), "数量对账失败"
    return options, record


def main() -> None:
    inject_patched_dataset()
    options, record = build_options()
    declared = record["selection"]["chart_count"]

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    shown_plan = {
        "charts": [next(s for s in plan["charts"] if s["chart_id"] == c["chart_id"])
                   for c in record["selection"]["charts"]],
        "suppressed_charts": plan.get("suppressed_charts", []),
    }
    html = rp.build_html(shown_plan, options)
    assert html.count('<article class="card">') == declared
    tag = '<script src="echarts.min.js"></script>'
    echarts_js = (ROOT / "echarts.min.js").read_text(encoding="utf-8").replace("</script>", "<\\/script>")
    html = html.replace(tag, "<script>\n" + echarts_js + "\n</script>", 1)

    banner = f"""
  <section class="panel" style="border-left:4px solid #D52B1E">
    <h3>真实运行环境适配说明（务必先读）</h3>
    <p style="font-size:13px;line-height:1.9">
      本页 {declared} 张图使用<b>本轮真实重新取数并纳入项目的补齐版上游 A1/A2 数据</b>重渲染，
      复用交接包既有图表实现，图型与清单与现有示例一致。<br>
      <b>口径红线：</b>本页属交接包独立示例工程产物，<b>不经过</b>五阶段链路的审核门／发布门禁；
      真实链路（chart-generator）本轮实跑只发布 6 张 industry_chain / combo / line 图，
      图型由既有代码 selection.py::PROFILES 决定，<b>不能</b>仅靠补上游数据改变。
      详见同目录 ADAPTATION_REPORT.md。
    </p>
  </section>
"""
    marker = '  <section class="panel">\n    <h3>交付概览</h3>'
    html = html.replace(marker, banner + marker, 1)
    HTML_OUT.write_text(html, encoding="utf-8")

    body = (ROOT / "ADAPTATION_REPORT.md").read_text(encoding="utf-8") if MD_OUT.exists() else ""
    print(f"[delivery] {len(options)} 张图 -> {HTML_OUT.name} ({HTML_OUT.stat().st_size/1024/1024:.2f} MB)")
    print(f"[delivery] 页面卡片 {html.count('<article class=\"card\">')} 张；报告正文 {len(body)} 字符")
    print(f"[delivery] 渗透率序列点数: {len(options[1]['series'][0]['data'])}")


if __name__ == "__main__":
    main()
